"""統計・予算・推移の集計（DB 設計書 5.4・5.5、画面設計書 4.4・4.5）。

分類別の集計は、明細ではなく内訳の税込額で行う（1件の明細に複数の分類があるため。BR-80）。
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import F, QuerySet, Sum
from django.db.models.functions import Coalesce

from budgets.models import Budget, MonthlyBudget
from core.choices import TransactionKind
from core.dates import add_months
from core.models import AppSettings
from core.periods import MonthPeriod, month_period
from ledger.models import TransactionLine
from ledger.queries import in_period, totals
from masters.models import Asset, Category
from reports.balances import balances, summary


@dataclass(frozen=True)
class Range:
    """集計の期間（月なら1か月、年なら1月〜12月の期間）。"""

    start: date
    end: date


def month_range(month: date, settings: AppSettings) -> Range:
    period = month_period(month, settings)
    return Range(period.start, period.end)


def year_range(year: int, settings: AppSettings) -> Range:
    """その年の 1月〜12月の期間（月の開始日に従う）。"""
    return Range(
        month_period(date(year, 1, 1), settings).start,
        month_period(date(year, 12, 1), settings).end,
    )


def _lines(kind: str, span: Range) -> QuerySet[TransactionLine]:
    """期間内の、その種類の明細の内訳。並び順は外す（集計に混ざらないように）。"""
    return TransactionLine.objects.filter(
        transaction__kind=kind,
        transaction__date__gte=span.start,
        transaction__date__lte=span.end,
    ).order_by()


@dataclass(frozen=True)
class CategoryTotal:
    category: Category
    amount: int
    percent: int  # 割合（%）。四捨五入した整数


def by_category(kind: str, span: Range) -> list[CategoryTotal]:
    """大分類ごとの金額（小分類の金額を含む）。金額の大きい順（F-ST-01、DB 設計書 5.4）。"""
    sums = (
        _lines(kind, span)
        .annotate(top=Coalesce(F("category__parent_id"), F("category_id")))
        .values("top")
        .annotate(total=Sum("amount_incl"))
        .values_list("top", "total")
    )
    amounts = {top: total for top, total in sums if total}
    categories = Category.objects.in_bulk(list(amounts))
    grand = sum(amounts.values())
    rows = [
        CategoryTotal(categories[pk], total, round(total * 100 / grand) if grand else 0)
        for pk, total in amounts.items()
    ]
    return sorted(rows, key=lambda r: (-r.amount, r.category.sort_order))


@dataclass(frozen=True)
class SubTotal:
    name: str
    amount: int
    category_id: int | None  # None は「小分類なし」


def subcategories(top: Category, kind: str, span: Range) -> list[SubTotal]:
    """大分類の中の小分類ごとの金額と「小分類なし」（F-ST-02、DB 設計書 5.4）。"""
    sums = dict(
        _lines(kind, span)
        .filter(category__in=[top, *top.children.all()])
        .values("category_id")
        .annotate(total=Sum("amount_incl"))
        .values_list("category_id", "total")
    )
    rows = [
        SubTotal(child.name, sums[child.pk], child.pk)
        for child in top.children.order_by("sort_order")
        if sums.get(child.pk)
    ]
    rows.append(SubTotal("小分類なし", sums.get(top.pk, 0), None))
    return rows


@dataclass(frozen=True)
class TaxTotal:
    rate: Decimal
    excl: int
    tax: int


def tax_by_rate(kind: str, span: Range) -> list[TaxTotal]:
    """税率ごとの税抜額と消費税額の合計（F-ST-06）。内訳に保存した登録時点の税率の値で分ける（BR-76）。"""
    sums = (
        _lines(kind, span)
        .values("tax_rate_value")
        .annotate(excl=Sum("amount_excl"), tax=Sum("tax_amount"))
        .order_by("tax_rate_value")
        .values_list("tax_rate_value", "excl", "tax")
    )
    return [TaxTotal(rate, excl, tax) for rate, excl, tax in sums]


# ---------------------------------------------------------------- 予算（DB 設計書 5.5）


@dataclass(frozen=True)
class BudgetStatus:
    budget: Budget
    name: str
    amount: int  # その月の予算額
    used: int  # 消化額

    @property
    def remaining(self) -> int:
        return self.amount - self.used

    @property
    def percent(self) -> int | None:
        """消化率（%）。予算額が 0 のときは出さない。"""
        return round(self.used * 100 / self.amount) if self.amount else None

    @property
    def over(self) -> bool:
        return self.used > self.amount


def budget_amount(budget: Budget, month: date) -> int:
    """「month 月」の予算額：月別の額があればその額、なければ基本額（BR-51）。"""
    monthly = MonthlyBudget.objects.filter(budget=budget, year_month=month).first()
    return monthly.amount if monthly else budget.base_amount


def budget_statuses(month: date, settings: AppSettings) -> list[BudgetStatus]:
    """予算ごとの予算額・消化額（BR-52）。全体予算を先に、大分類は並び順に。"""
    span = month_range(month, settings)
    expense_total = totals(in_period(month_period(month, settings))).expense
    by_top = {row.category.pk: row.amount for row in by_category(TransactionKind.EXPENSE, span)}
    monthly = dict(
        MonthlyBudget.objects.filter(year_month=month).values_list("budget_id", "amount")
    )
    statuses = []
    for budget in Budget.objects.select_related("category").order_by(
        F("category__sort_order").asc(nulls_first=True), "id"
    ):
        amount = monthly.get(budget.pk, budget.base_amount)
        if budget.category is None:
            statuses.append(BudgetStatus(budget, "全体", amount, expense_total))
        else:
            statuses.append(
                BudgetStatus(
                    budget, budget.category.name, amount, by_top.get(budget.category.pk, 0)
                )
            )
    return statuses


# ---------------------------------------------------------------- 推移（F-ST-04・05）


def last_12_months(end_month: date, settings: AppSettings) -> list[MonthPeriod]:
    """end_month を最後とする 12 か月の期間（古い順）。"""
    return [month_period(add_months(end_month, k - 11), settings) for k in range(12)]


def category_trend(top: Category, periods: list[MonthPeriod]) -> list[int]:
    """各月の、その大分類（小分類を含む）の金額（DB 設計書 5.4）。"""
    values = []
    for period in periods:
        span = Range(period.start, period.end)
        total = (
            _lines(top.kind, span)
            .filter(category__in=[top, *top.children.all()])
            .aggregate(total=Sum("amount_incl"))["total"]
        )
        values.append(total or 0)
    return values


def asset_trend(periods: list[MonthPeriod], asset_id: int | None = None) -> dict[str, list[int]]:
    """各月の終了日の時点の、資産合計・負債合計・純資産（DB 設計書 5.3）。

    asset_id を指定したときは、その資産の残高だけを返す。
    """
    assets = list(Asset.objects.all())
    result: dict[str, list[int]] = defaultdict(list)
    for period in periods:
        amounts = balances(period.end)
        if asset_id is not None:
            result["balance"].append(amounts.get(asset_id, 0))
            continue
        total = summary(assets, amounts)
        result["assets"].append(total.assets)
        result["liabilities"].append(total.liabilities)
        result["net"].append(total.net)
    return dict(result)
