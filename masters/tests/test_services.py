"""マスタの並べ替えと削除のテスト（テスト仕様書 3.1）。"""

from datetime import date
from decimal import Decimal

import pytest

from ledger.models import Transaction, TransactionLine
from masters import services
from masters.models import Asset, AssetGroup, Category, TaxRate

pytestmark = pytest.mark.django_db


def _names(kind: str = "expense") -> list[str]:
    qs = Category.objects.filter(kind=kind, parent__isnull=True).order_by("sort_order", "id")
    return [c.name for c in qs]


def test_1つ上へ移す() -> None:
    services.move(Category.objects.get(kind="expense", name="交通費"), "up")
    assert _names()[:3] == ["食費", "交通費", "備品・衣類"]


def test_1つ下へ移す() -> None:
    services.move(Category.objects.get(kind="expense", name="食費"), "down")
    assert _names()[:2] == ["備品・衣類", "食費"]


def test_先頭は上へ移らず最後は下へ移らない() -> None:
    before = _names()
    services.move(Category.objects.get(kind="expense", name="食費"), "up")
    services.move(Category.objects.get(kind="expense", name="その他"), "down")
    assert _names() == before


def test_並べ替えは同じ親の中だけ() -> None:
    food = Category.objects.get(kind="expense", name="食費")
    Category.objects.create(kind="expense", name="外食", parent=food, sort_order=0)
    b = Category.objects.create(kind="expense", name="食料品", parent=food, sort_order=1)
    services.move(b, "up")
    kids = list(food.children.order_by("sort_order").values_list("name", flat=True))
    assert kids == ["食料品", "外食"]
    assert _names()[0] == "食費"  # 大分類の並びは変わらない


def test_新しく追加するものは一覧の最後() -> None:
    assert services.next_sort_order(TaxRate.objects.all()) == 4  # 初期データは 1〜3
    assert services.next_sort_order(Category.objects.filter(parent__isnull=False)) == 0


def test_使われていないマスタは削除できる() -> None:
    rate = TaxRate.objects.create(name="旧税率 5%", rate=Decimal("5.0"))
    services.delete(rate)
    assert not TaxRate.objects.filter(name="旧税率 5%").exists()


def test_明細で使われている分類は削除できない() -> None:
    cash = Asset.objects.get(name="現金")
    food = Category.objects.get(kind="expense", name="食費")
    tx = Transaction.objects.create(
        kind="expense",
        date=date(2026, 10, 15),
        asset=cash,
        amount=1080,
        amount_input_type="tax_included",
    )
    TransactionLine.objects.create(
        transaction=tx,
        category=food,
        tax_rate=TaxRate.objects.get(name="軽減税率 8%"),
        tax_rate_value=Decimal("8.0"),
        amount_excl=1000,
        tax_amount=80,
        amount_incl=1080,
    )
    with pytest.raises(services.InUseError) as e:
        services.delete(food)
    # MSG-E07
    assert (
        e.value.message == "「食費」は1件の明細で使われているため削除できません。非表示にできます。"
    )


def test_設定の既定の税率は削除できない() -> None:
    with pytest.raises(services.InUseError) as e:
        services.delete(TaxRate.objects.get(name="標準税率 10%"))
    assert "分類の既定の税率で使われている" in e.value.message


def test_資産が属している資産グループは削除できない() -> None:
    with pytest.raises(services.InUseError) as e:
        services.delete(AssetGroup.objects.get(name="現金"))
    assert e.value.message == "「現金」には1件の資産が属しているため削除できません。"
