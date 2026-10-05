"""明細・内訳の制約のテスト（テスト仕様書 2.3）。"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from ledger.models import Transaction, TransactionLine
from masters.models import Asset, AssetGroup, Category, TaxRate

pytestmark = pytest.mark.django_db


@pytest.fixture
def cash() -> Asset:
    return Asset.objects.get(name="現金")


@pytest.fixture
def bank() -> Asset:
    return Asset.objects.create(asset_group=AssetGroup.objects.get(name="銀行"), name="銀行")


def _raises_integrity(create: Callable[[], object]) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        create()


def _tx(asset: Asset, **overrides: object) -> Transaction:
    values: dict[str, object] = {
        "kind": "expense",
        "date": date(2026, 10, 15),
        "asset": asset,
        "amount": 1080,
        "amount_input_type": "tax_included",
    }
    values.update(overrides)
    return Transaction.objects.create(**values)


def test_金額の範囲と0円(cash: Asset) -> None:
    _tx(cash, amount=99_999_999)
    _tx(cash, amount=-99_999_999)
    _raises_integrity(lambda: _tx(cash, amount=100_000_000))
    _raises_integrity(lambda: _tx(cash, amount=0))


def test_マイナスは支出だけ(cash: Asset) -> None:
    _tx(cash, amount=-550)
    _raises_integrity(lambda: _tx(cash, kind="income", amount=-550))


def test_振替は振替先が必要で税込税抜を持たない(cash: Asset, bank: Asset) -> None:
    _tx(bank, kind="transfer", transfer_to_asset=cash, amount_input_type=None, amount=30000)
    _raises_integrity(lambda: _tx(bank, kind="transfer", amount_input_type=None))
    _raises_integrity(lambda: _tx(bank, kind="transfer", transfer_to_asset=cash))


def test_収入支出は振替先を持たない(cash: Asset, bank: Asset) -> None:
    _raises_integrity(lambda: _tx(cash, transfer_to_asset=bank))


def test_振替の出金元と入金先は別の資産(cash: Asset) -> None:
    _raises_integrity(
        lambda: _tx(
            cash, kind="transfer", transfer_to_asset=cash, amount_input_type=None, amount=1000
        )
    )


def test_内訳の税込額は税抜額と税額の合計(cash: Asset) -> None:
    tx = _tx(cash)
    food = Category.objects.get(kind="expense", name="食費")
    rate = TaxRate.objects.get(name="軽減税率 8%")
    line = {"transaction": tx, "category": food, "tax_rate": rate, "tax_rate_value": Decimal("8.0")}
    TransactionLine.objects.create(**line, amount_excl=1000, tax_amount=80, amount_incl=1080)
    _raises_integrity(
        lambda: TransactionLine.objects.create(
            **line, amount_excl=1000, tax_amount=80, amount_incl=1081
        )
    )


def test_明細を削除すると内訳も消える(cash: Asset) -> None:
    tx = _tx(cash)
    TransactionLine.objects.create(
        transaction=tx,
        category=Category.objects.get(kind="expense", name="食費"),
        tax_rate=TaxRate.objects.get(name="軽減税率 8%"),
        tax_rate_value=Decimal("8.0"),
        amount_excl=1000,
        tax_amount=80,
        amount_incl=1080,
    )
    tx.delete()
    assert not TransactionLine.objects.exists()
