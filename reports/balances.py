"""資産の残高とクレジットカードの請求額（DB 設計書 5.3・5.7）。

残高は保存せず、開始残高と明細から毎回計算する（DB 設計書 D-3）。
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Q, Sum

from core.choices import TransactionKind
from core.dates import add_months
from core.periods import day_in_month
from ledger.models import Transaction
from masters.models import Asset


def balances(upto: date) -> dict[int, int]:
    """すべての資産の、upto の日の時点の残高（DB 設計書 5.3）。

    残高 ＝ 開始残高 ＋ 収入 − 支出 − 振替で出金 ＋ 振替で入金（upto 以前の明細）
    マイナス支出は、支出の合計から差し引かれるため残高は増える。
    """
    result: dict[int, int] = defaultdict(int)
    for asset_id, opening in Asset.objects.values_list("id", "opening_balance"):
        result[asset_id] += opening

    until = Transaction.objects.filter(date__lte=upto).order_by()
    # 資産ごと・種類ごとの合計を、1回の集計で求める
    for asset_id, kind, total in (
        until.values_list("asset_id", "kind")
        .annotate(total=Sum("amount"))
        .values_list("asset_id", "kind", "total")
    ):
        result[asset_id] += total if kind == TransactionKind.INCOME else -total
    for asset_id, total in (
        until.filter(kind=TransactionKind.TRANSFER)
        .values_list("transfer_to_asset_id")
        .annotate(total=Sum("amount"))
        .values_list("transfer_to_asset_id", "total")
    ):
        result[asset_id] += total
    return dict(result)


def balance(asset: Asset, upto: date) -> int:
    """1つの資産の残高。"""
    return balances(upto).get(asset.pk, asset.opening_balance)


@dataclass(frozen=True)
class Summary:
    """資産合計・負債合計・純資産（BR-42）。"""

    assets: int
    liabilities: int

    @property
    def net(self) -> int:
        return self.assets - self.liabilities


def summary(asset_list: list[Asset], amounts: dict[int, int]) -> Summary:
    """カード以外の残高の合計が資産、カードの残高（マイナス）の符号を反転したものが負債。

    非表示の資産も含める（お金としては存在するため。画面設計書 4.6）。
    """
    total_assets = sum(amounts.get(a.pk, 0) for a in asset_list if not a.is_credit_card)
    total_liabilities = -sum(amounts.get(a.pk, 0) for a in asset_list if a.is_credit_card)
    return Summary(total_assets, total_liabilities)


# ---------------------------------------------------------------- クレジットカードの請求額
# DB 設計書 5.7


@dataclass(frozen=True)
class Bill:
    closing_date: date  # 締め日
    payment_date: date  # 引き落とし日
    period_start: date  # 対象の利用分の最初の日（前の締め日の翌日）
    amount: int  # 請求額
    estimate: bool  # 締め日がまだ来ていない（目安）


def _closing(card: Asset, month: date) -> date:
    return day_in_month(month.year, month.month, card.closing_day or 0)


def bill_for(card: Asset, closing_month: date, today: date) -> Bill:
    """closing_month の締め日の請求。"""
    closing = _closing(card, closing_month)
    previous = _closing(card, add_months(closing_month, -1))
    pay_month = add_months(closing_month, card.payment_month_offset or 1)
    payment = day_in_month(pay_month.year, pay_month.month, card.payment_day or 0)
    start = previous + timedelta(days=1)
    used = Transaction.objects.filter(asset=card, date__gte=start, date__lte=closing).order_by()
    # 請求額 ＝ カードで払った支出（マイナス支出は差し引く）− カードへの入金（ポイントの還元など）。
    # 振替（引き落とし口座からの支払いなど）は含めない
    sums = dict(
        used.filter(Q(kind=TransactionKind.EXPENSE) | Q(kind=TransactionKind.INCOME))
        .values_list("kind")
        .annotate(total=Sum("amount"))
        .values_list("kind", "total")
    )
    amount = (sums.get(TransactionKind.EXPENSE) or 0) - (sums.get(TransactionKind.INCOME) or 0)
    return Bill(closing, payment, start, amount, estimate=closing > today)


def upcoming_bills(card: Asset, today: date, count: int = 2) -> list[Bill]:
    """引き落とし日が今日以降の請求を、早い順に count 件（画面設計書 4.6・4.7）。"""
    month = add_months(today.replace(day=1), -3)  # 翌々月払いもあるため、少し前の締め日から見る
    bills: list[Bill] = []
    while len(bills) < count:
        bill = bill_for(card, month, today)
        if bill.payment_date >= today:
            bills.append(bill)
        month = add_months(month, 1)
    return bills
