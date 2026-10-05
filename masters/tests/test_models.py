"""税率・分類・資産の制約と初期データのテスト（テスト仕様書 2.1・2.2）。"""

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from core.models import AppSettings
from masters.models import Asset, AssetGroup, Category, TaxRate

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- 初期データ（DB 設計書 7章）


def test_初期データ_税率() -> None:
    assert list(TaxRate.objects.values_list("name", "rate")) == [
        ("標準税率 10%", Decimal("10.0")),
        ("軽減税率 8%", Decimal("8.0")),
        ("非課税・対象外 0%", Decimal("0.0")),
    ]


def test_初期データ_支出の分類と既定の税率() -> None:
    expense = Category.objects.filter(kind="expense").select_related("default_tax_rate")
    assert [(c.name, c.default_tax_rate.rate if c.default_tax_rate else None) for c in expense] == [
        ("食費", Decimal("8.0")),
        ("備品・衣類", Decimal("10.0")),
        ("交通費", Decimal("10.0")),
        ("レジャー・趣味", Decimal("10.0")),
        ("交際費", Decimal("10.0")),
        ("通信費", Decimal("10.0")),
        ("健康・医療", Decimal("0.0")),
        ("光熱費", Decimal("10.0")),
        ("保険", Decimal("0.0")),
        ("税金", Decimal("0.0")),
        ("その他", Decimal("10.0")),
    ]


def test_初期データ_収入の分類はすべて0パーセント() -> None:
    income = Category.objects.filter(kind="income").select_related("default_tax_rate")
    assert [c.name for c in income] == ["給与", "賞与", "臨時収入", "利息", "その他"]
    assert {c.default_tax_rate.rate for c in income if c.default_tax_rate} == {Decimal("0.0")}


def test_初期データ_小分類は登録しない() -> None:
    assert not Category.objects.filter(parent__isnull=False).exists()


def test_初期データ_資産グループと資産() -> None:
    assert list(AssetGroup.objects.values_list("name", flat=True)) == [
        "現金",
        "銀行",
        "クレジットカード",
        "電子マネー",
    ]
    cash = Asset.objects.get()
    assert (cash.name, cash.asset_group.name, cash.opening_balance, cash.is_credit_card) == (
        "現金",
        "現金",
        0,
        False,
    )


def test_初期データ_設定() -> None:
    s = AppSettings.load()
    assert s.default_tax_rate is not None and s.default_tax_rate.name == "標準税率 10%"
    assert (s.currency_symbol, s.month_start_day, s.tax_rounding, s.theme) == (
        "yen_sign",
        1,
        "floor",
        "system",
    )


# ---------------------------------------------------------------- 制約（DB 設計書 4.2〜4.5）


def _raises_integrity(create: object) -> None:
    """DB の制約に反して保存できないことを確かめる。"""
    with pytest.raises(IntegrityError), transaction.atomic():
        create()  # type: ignore[operator]


def test_税率は0から100まで() -> None:
    _raises_integrity(lambda: TaxRate.objects.create(name="誤り", rate=Decimal("100.1")))
    _raises_integrity(lambda: TaxRate.objects.create(name="誤り", rate=Decimal("-0.1")))


def test_税率の名前は重複しない() -> None:
    _raises_integrity(lambda: TaxRate.objects.create(name="標準税率 10%", rate=Decimal("10.0")))


def test_分類の種類は収入か支出() -> None:
    _raises_integrity(lambda: Category.objects.create(kind="transfer", name="誤り"))


def test_使用中の分類は削除できない() -> None:
    food = Category.objects.get(kind="expense", name="食費")
    Category.objects.create(kind="expense", name="外食", parent=food)
    with pytest.raises(ProtectedError):
        food.delete()


def test_設定から使われている税率は削除できない() -> None:
    with pytest.raises(ProtectedError):
        TaxRate.objects.get(name="標準税率 10%").delete()


def _card(**overrides: object) -> Asset:
    group = AssetGroup.objects.get(name="クレジットカード")
    values: dict[str, object] = {
        "asset_group": group,
        "name": "カード",
        "is_credit_card": True,
        "closing_day": 0,
        "payment_month_offset": 1,
        "payment_day": 27,
        "payment_account": Asset.objects.get(name="現金"),
    }
    values.update(overrides)
    return Asset.objects.create(**values)


def test_カードは締め日などがすべて必要() -> None:
    _card()  # すべてそろっていれば登録できる
    _raises_integrity(lambda: _card(name="カード2", payment_day=None))
    _raises_integrity(lambda: _card(name="カード3", payment_account=None))


def test_カード以外は締め日などを持たない() -> None:
    group = AssetGroup.objects.get(name="銀行")
    _raises_integrity(lambda: Asset.objects.create(asset_group=group, name="銀行", closing_day=10))


def test_日の値は0から30() -> None:
    _card(name="月末", closing_day=0, payment_day=30)
    _raises_integrity(lambda: _card(name="31日", closing_day=31))
    _raises_integrity(lambda: _card(name="翌々々月", payment_month_offset=3))


def test_引き落とし口座になっている資産は削除できない() -> None:
    _card()
    with pytest.raises(ProtectedError):
        Asset.objects.get(name="現金").delete()
