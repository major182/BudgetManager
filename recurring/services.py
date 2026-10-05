"""定期収支の登録日の計算と、毎日の自動登録（DB 設計書 5.8、BT-01、BR-61〜65）。"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.choices import MONTH_END, TransactionKind
from core.dates import add_months
from core.periods import day_in_month, holidays_between, is_business_day, shift
from ledger import services as ledger_services
from ledger.models import Transaction
from recurring.models import RecurringItem, RecurringRun

logger = logging.getLogger(__name__)

# 前営業日へずらす回は、本来の登録日より前に登録日が来るため、少し先まで見る。
# 年末年始（12/31〜1/3）と連休が重なっても 14 日あれば足りる（DB 設計書 5.8）
LOOK_AHEAD_DAYS = 14


def scheduled_dates(item: RecurringItem, start: date, end: date) -> Iterator[date]:
    """start〜end の間の、本来の登録日（土日祝日の調整の前）を古い順に返す（BR-61）。

    開始日より前・終了日より後の日は含めない。その月にない日（31日など）は末日にする。
    """
    start = max(start, item.start_date)
    if item.end_date is not None:
        end = min(end, item.end_date)
    if start > end:
        return
    frequency = RecurringItem.Frequency
    if item.frequency == frequency.WEEKLY:
        # 0＝月曜〜6＝日曜（Python の weekday と同じ）。start 以降で最初のその曜日から1週間ごと
        day = start + timedelta(days=((item.weekday or 0) - start.weekday()) % 7)
        while day <= end:
            yield day
            day += timedelta(weeks=1)
        return
    month = start.replace(day=1)
    while month <= end:
        if item.frequency == frequency.MONTHLY:
            day = day_in_month(month.year, month.month, item.day_of_month or 1)
        elif item.frequency == frequency.MONTH_END:
            day = day_in_month(month.year, month.month, MONTH_END)
        elif month.month == item.month:  # 毎年
            day = day_in_month(month.year, month.month, item.day_of_month or 1)
        else:
            month = add_months(month, 1)
            continue
        if start <= day <= end:
            yield day
        month = add_months(month, 1)


def adjusted(day: date, item: RecurringItem, holidays: set[date]) -> date:
    """土日祝日・年末年始なら、前営業日・後営業日にずらす（BR-62）。"""
    return shift(day, item.holiday_rule, lambda d: is_business_day(d, holidays))


def _registered_from(item: RecurringItem) -> date:
    """自動登録の対象にする最初の日：開始日と、定期収支を登録した日の遅いほう。

    定期収支を登録した日より前の回はさかのぼらない。
    開始日を過去にしても、過去の回をまとめて登録しないようにするため（DB 設計書 5.8）。
    """
    return max(item.start_date, timezone.localtime(item.created_at).date())


@dataclass(frozen=True)
class Occurrence:
    scheduled: date  # 本来の登録日
    registered: date  # 調整後の登録日


def occurrences(item: RecurringItem, today: date) -> list[Occurrence]:
    """今日＋14日までの回（登録済みかどうかは問わない）。"""
    begin = _registered_from(item)
    end = today + timedelta(days=LOOK_AHEAD_DAYS)
    holidays = holidays_between(
        begin - timedelta(days=LOOK_AHEAD_DAYS), end + timedelta(days=LOOK_AHEAD_DAYS)
    )
    return [
        Occurrence(day, adjusted(day, item, holidays)) for day in scheduled_dates(item, begin, end)
    ]


def next_date(item: RecurringItem, today: date) -> date | None:
    """次回の登録予定日（調整後）。まだ登録していない回のうち、今日以降で最も早いもの（F-RC-02）。"""
    # 保存前（入力中）の定期収支には、登録履歴がない
    done = set(item.runs.values_list("scheduled_date", flat=True)) if item.pk else set()
    search_until = today + timedelta(days=400)  # 毎年の周期でも次の回が見つかる範囲
    begin = max(_registered_from(item), today - timedelta(days=LOOK_AHEAD_DAYS))
    holidays = holidays_between(
        begin - timedelta(days=LOOK_AHEAD_DAYS), search_until + timedelta(days=LOOK_AHEAD_DAYS)
    )
    for day in scheduled_dates(item, begin, search_until):
        when = adjusted(day, item, holidays)
        if day not in done and when >= today:
            return when
    return None


def _create(item: RecurringItem, occurrence: Occurrence) -> Transaction:
    """その回の明細を作る。消費税は登録する時点の税率の値で計算する（BR-76）。"""
    header = {
        "kind": item.kind,
        "date": occurrence.registered,
        "asset": item.asset,
        "transfer_to_asset": item.transfer_to_asset,
        "amount": item.amount,
        "amount_input_type": item.amount_input_type,
        "description": item.description,
        "memo": item.memo,
    }
    lines = []
    if item.kind != TransactionKind.TRANSFER and item.category and item.tax_rate:
        lines = [ledger_services.LineData(item.category, item.tax_rate, item.amount)]
    return ledger_services.save(header, lines, source=Transaction.Source.RECURRING)


def register_due(today: date | None = None) -> int:
    """調整後の登録日が今日以前で、まだ登録していない回を明細として登録する（BT-01）。

    - 処理が止まっていた日の分も、ここでさかのぼって登録される（BR-64）
    - 1回ごとに、明細の作成と登録履歴の作成を1つの DB の更新処理で行う。
      途中で失敗したら、その回は何も登録しない
    - 登録履歴の一意制約により、処理が2回動いても同じ回は二重に登録されない（BR-64）
    - 自動登録した明細を利用者が削除しても履歴は残るため、再び登録されない（BR-65）
    戻り値は登録した件数。
    """
    today = today or timezone.localdate()
    count = 0
    items = RecurringItem.objects.select_related(
        "asset", "transfer_to_asset", "category", "tax_rate"
    )
    for item in items:
        done = set(item.runs.values_list("scheduled_date", flat=True))
        for occurrence in occurrences(item, today):
            if occurrence.registered > today or occurrence.scheduled in done:
                continue
            try:
                with transaction.atomic():
                    tx = _create(item, occurrence)
                    RecurringRun.objects.create(
                        recurring_item=item,
                        scheduled_date=occurrence.scheduled,
                        registered_date=occurrence.registered,
                        transaction=tx,
                    )
            except IntegrityError:
                # 同じ回がすでに登録されていた（処理が同時に2回動いたなど）。何も登録しない
                logger.warning(
                    "定期収支 %s の %s は登録済みのため飛ばしました", item.pk, occurrence.scheduled
                )
                continue
            count += 1
            logger.info(
                "定期収支 %s（%s）を %s に登録しました",
                item.pk,
                item.description,
                occurrence.registered,
            )
    return count
