"""家計簿・検索の表示のための集計（DB 設計書 5.4、画面設計書 4.1・4.3）。

ここは読み出しと集計だけを行い、データは変えない。
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models import Prefetch, Q, QuerySet, Sum

from core.choices import TransactionKind
from core.dates import add_months
from core.models import AppSettings
from core.periods import MonthPeriod, holidays_between, month_period
from ledger.models import Transaction, TransactionLine


@dataclass(frozen=True)
class Totals:
    """収入・支出・差額（振替は含めない。BR-14）。"""

    income: int = 0
    expense: int = 0

    @property
    def diff(self) -> int:
        return self.income - self.expense


def totals(queryset: QuerySet[Transaction]) -> Totals:
    # order_by() で並び順を外す。並び順の列があると、明細ごとに別々に集計されてしまう
    sums = dict(
        queryset.order_by()
        .filter(kind__in=[TransactionKind.INCOME, TransactionKind.EXPENSE])
        .values_list("kind")
        .annotate(total=Sum("amount"))
        .values_list("kind", "total")
    )
    return Totals(sums.get(TransactionKind.INCOME) or 0, sums.get(TransactionKind.EXPENSE) or 0)


def with_details(queryset: QuerySet[Transaction]) -> QuerySet[Transaction]:
    """一覧の行に出す情報（資産・内訳の分類）をまとめて読む。"""
    lines = TransactionLine.objects.select_related("category__parent").order_by("sort_order", "id")
    return queryset.select_related("asset", "transfer_to_asset").prefetch_related(
        Prefetch("lines", queryset=lines)
    )


def in_period(period: MonthPeriod) -> QuerySet[Transaction]:
    return Transaction.objects.filter(date__gte=period.start, date__lte=period.end)


def _day_totals(transactions: Iterable[Transaction]) -> Totals:
    income = sum(t.amount for t in transactions if t.kind == TransactionKind.INCOME)
    expense = sum(t.amount for t in transactions if t.kind == TransactionKind.EXPENSE)
    return Totals(income, expense)


@dataclass
class Day:
    """日別の一覧の1日分。"""

    date: date
    holiday: bool
    transactions: list[Transaction] = field(default_factory=list)

    @property
    def totals(self) -> Totals:
        return _day_totals(self.transactions)


def group_by_day(transactions: Iterable[Transaction], holidays: set[date]) -> list[Day]:
    """明細を日ごとにまとめる（画面設計書 4.1）。

    新しい日付が上。同じ日の中では、登録が新しいものが上。
    """
    days: dict[date, Day] = {}
    for tx in sorted(transactions, key=lambda t: (t.date, t.created_at, t.pk), reverse=True):
        days.setdefault(tx.date, Day(tx.date, tx.date in holidays)).transactions.append(tx)
    return list(days.values())


@dataclass(frozen=True)
class CalendarCell:
    date: date
    in_period: bool
    holiday: bool
    totals: Totals


def calendar_weeks(period: MonthPeriod, settings: AppSettings) -> list[list[CalendarCell]]:
    """カレンダーの週ごとのマス（F-LS-02）。週の開始曜日は設定に従う（BR-22）。"""
    first_weekday = 6 if settings.week_start == AppSettings.WeekStart.SUNDAY else 0  # 6＝日曜
    start = period.start - timedelta(days=(period.start.weekday() - first_weekday) % 7)
    end = period.end + timedelta(days=(first_weekday - 1 - period.end.weekday()) % 7)
    holidays = holidays_between(start, end)
    by_day: dict[date, list[Transaction]] = defaultdict(list)
    for tx in Transaction.objects.filter(date__gte=start, date__lte=end).only(
        "date", "kind", "amount"
    ):
        by_day[tx.date].append(tx)
    weeks: list[list[CalendarCell]] = []
    day = start
    while day <= end:
        week = []
        for _ in range(7):
            week.append(
                CalendarCell(
                    day,
                    period.start <= day <= period.end,
                    day in holidays,
                    _day_totals(by_day[day]),
                )
            )
            day += timedelta(days=1)
        weeks.append(week)
    return weeks


def weekday_labels(settings: AppSettings) -> list[str]:
    labels = ["月", "火", "水", "木", "金", "土", "日"]
    return (
        labels[6:] + labels[:6] if settings.week_start == AppSettings.WeekStart.SUNDAY else labels
    )


@dataclass(frozen=True)
class MonthRow:
    period: MonthPeriod
    totals: Totals


def months_of_year(year: int, settings: AppSettings) -> list[MonthRow]:
    """月別の一覧：その年の 12 か月の期間と合計。新しい月が上（F-LS-03）。"""
    rows = []
    for month in range(12, 0, -1):
        period = month_period(date(year, month, 1), settings)
        rows.append(MonthRow(period, totals(in_period(period))))
    return rows


def year_totals(rows: list[MonthRow]) -> Totals:
    return Totals(sum(r.totals.income for r in rows), sum(r.totals.expense for r in rows))


def neighbors(month: date) -> tuple[date, date]:
    return add_months(month, -1), add_months(month, 1)


SEARCH_PAGE = 50


def search(conditions: dict[str, object]) -> QuerySet[Transaction]:
    """明細の検索（F-LS-06、画面設計書 4.3）。日付の新しい順。"""
    qs = Transaction.objects.filter(
        date__gte=conditions["date_from"], date__lte=conditions["date_until"]
    )
    if conditions.get("q"):
        # 内容・メモを部分一致で探す
        q = str(conditions["q"])
        qs = qs.filter(Q(description__contains=q) | Q(memo__contains=q))
    if conditions.get("kind"):
        qs = qs.filter(kind=conditions["kind"])
    if conditions.get("category"):
        # 大分類を選ぶと、その小分類も含めて探す
        category = conditions["category"]
        qs = qs.filter(
            Q(lines__category_id=category) | Q(lines__category__parent_id=category)
        ).distinct()
    if conditions.get("asset"):
        # 振替では、出金元・入金先のどちらかに一致すれば対象
        asset = conditions["asset"]
        qs = qs.filter(Q(asset=asset) | Q(transfer_to_asset=asset))
    if conditions.get("amount_min") is not None:
        qs = qs.filter(amount__gte=conditions["amount_min"])
    if conditions.get("amount_max") is not None:
        qs = qs.filter(amount__lte=conditions["amount_max"])
    return qs.order_by("-date", "-created_at", "-id")
