"""統計・予算・推移の集計のテスト（テスト仕様書 3.5）。DB 設計書 5.4・5.5 の式を確かめる。"""

from datetime import date
from decimal import Decimal

import pytest

from budgets.models import Budget, MonthlyBudget
from core.models import AppSettings
from ledger import services
from masters.models import Asset, AssetGroup, Category, TaxRate
from reports import stats

pytestmark = pytest.mark.django_db

OCT = date(2026, 10, 1)


def _cat(name: str, kind: str = "expense") -> Category:
    return Category.objects.get(kind=kind, name=name)


def _tx(
    day: date,
    lines: list[tuple[Category, str, int]],
    kind: str = "expense",
    asset: Asset | None = None,
) -> None:
    header = {
        "kind": kind,
        "date": day,
        "asset": asset or Asset.objects.get(name="現金"),
        "amount_input_type": "tax_included",
    }
    data = [services.LineData(c, TaxRate.objects.get(rate=Decimal(r)), a) for c, r, a in lines]
    services.save(header, data)


@pytest.fixture
def settings_() -> AppSettings:
    return AppSettings.load()


@pytest.fixture
def eat_out() -> Category:
    return Category.objects.create(kind="expense", name="外食", parent=_cat("食費"))


def test_分類別は大分類ごとに小分類を含めて集計する(
    settings_: AppSettings, eat_out: Category
) -> None:
    _tx(date(2026, 10, 2), [(_cat("食費"), "8", 3000), (eat_out, "10", 1000)])
    _tx(date(2026, 10, 5), [(_cat("光熱費"), "10", 6000)])
    _tx(date(2026, 10, 14), [(_cat("給与", "income"), "0", 250000)], kind="income")
    rows = stats.by_category("expense", stats.month_range(OCT, settings_))
    assert [(r.category.name, r.amount, r.percent) for r in rows] == [
        ("光熱費", 6000, 60),
        ("食費", 4000, 40),
    ]
    income = stats.by_category("income", stats.month_range(OCT, settings_))
    assert [(r.category.name, r.amount) for r in income] == [("給与", 250000)]


def test_返品は分類の支出から差し引く(settings_: AppSettings) -> None:
    _tx(date(2026, 10, 2), [(_cat("備品・衣類"), "10", 3000)])
    _tx(date(2026, 10, 3), [(_cat("備品・衣類"), "10", -550)])
    rows = stats.by_category("expense", stats.month_range(OCT, settings_))
    assert rows[0].amount == 2450


def test_小分類と小分類なし(settings_: AppSettings, eat_out: Category) -> None:
    _tx(date(2026, 10, 2), [(_cat("食費"), "8", 3000), (eat_out, "10", 1000)])
    rows = stats.subcategories(_cat("食費"), "expense", stats.month_range(OCT, settings_))
    assert [(r.name, r.amount) for r in rows] == [("外食", 1000), ("小分類なし", 3000)]


def test_税率ごとの消費税額(settings_: AppSettings) -> None:
    # DB 設計書 5.6 の例
    _tx(
        date(2026, 10, 15),
        [
            (_cat("食費"), "8", 1080),
            (_cat("備品・衣類"), "10", 550),
            (_cat("備品・衣類"), "10", 330),
        ],
    )
    rows = stats.tax_by_rate("expense", stats.month_range(OCT, settings_))
    assert [(r.rate, r.excl, r.tax) for r in rows] == [
        (Decimal("8.0"), 1000, 80),
        (Decimal("10.0"), 800, 80),
    ]


def test_予算の消化額と残額(settings_: AppSettings, eat_out: Category) -> None:
    whole = Budget.objects.create(category=None, base_amount=150_000)
    food = Budget.objects.create(category=_cat("食費"), base_amount=3_000)
    Budget.objects.create(category=_cat("光熱費"), base_amount=0)
    MonthlyBudget.objects.create(budget=whole, year_month=OCT, amount=200_000)  # 10月だけ別の額
    _tx(date(2026, 10, 2), [(_cat("食費"), "8", 3000), (eat_out, "10", 1000)])
    _tx(date(2026, 10, 3), [(_cat("食費"), "8", -500)])  # 返品は差し引く
    statuses = {s.name: s for s in stats.budget_statuses(OCT, settings_)}
    assert list(statuses) == ["全体", "食費", "光熱費"]  # 全体が先
    assert (statuses["全体"].amount, statuses["全体"].used, statuses["全体"].remaining) == (
        200_000,
        3_500,
        196_500,
    )
    # 食費の予算は小分類（外食）も含めて消化する：3,500 / 3,000 → 117%、超過 500
    assert (statuses["食費"].used, statuses["食費"].percent, statuses["食費"].over) == (
        3_500,
        117,
        True,
    )
    assert statuses["光熱費"].percent is None  # 予算額が 0 なら消化率を出さない
    assert stats.budget_amount(food, OCT) == 3_000
    assert stats.budget_amount(whole, date(2026, 11, 1)) == 150_000  # 月別の額がない月は基本額


def test_年の期間(settings_: AppSettings) -> None:
    span = stats.year_range(2026, settings_)
    assert (span.start, span.end) == (date(2026, 1, 1), date(2026, 12, 31))
    settings_.month_start_day = 25
    span = stats.year_range(2026, settings_)
    assert (span.start, span.end) == (date(2025, 12, 25), date(2026, 12, 24))


def test_分類の推移(settings_: AppSettings, eat_out: Category) -> None:
    _tx(date(2026, 9, 10), [(_cat("食費"), "8", 1000)])
    _tx(date(2026, 10, 10), [(eat_out, "10", 2000)])
    periods = stats.last_12_months(OCT, settings_)
    assert (periods[0].month, periods[-1].month) == (date(2025, 11, 1), OCT)
    values = stats.category_trend(_cat("食費"), periods)
    assert values[-2:] == [1000, 2000] and sum(values) == 3000


def test_資産の推移(settings_: AppSettings) -> None:
    bank = Asset.objects.create(
        asset_group=AssetGroup.objects.get(name="銀行"), name="銀行", opening_balance=1000
    )
    _tx(date(2026, 10, 14), [(_cat("給与", "income"), "0", 5000)], kind="income", asset=bank)
    periods = stats.last_12_months(OCT, settings_)
    trend = stats.asset_trend(periods)
    assert trend["assets"][-2:] == [1000, 6000]
    assert trend["net"][-1] == 6000 and trend["liabilities"][-1] == 0
    assert stats.asset_trend(periods, bank.pk)["balance"][-1] == 6000
