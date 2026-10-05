"""定期収支・登録履歴の制約のテスト（テスト仕様書 2.4）。"""

from collections.abc import Callable
from datetime import date

import pytest
from django.db import IntegrityError, transaction

from ledger.models import Transaction
from masters.models import Asset, Category, TaxRate
from recurring.models import RecurringItem, RecurringRun

pytestmark = pytest.mark.django_db


def _raises_integrity(create: Callable[[], object]) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        create()


def _item(**overrides: object) -> RecurringItem:
    values: dict[str, object] = {
        "kind": "expense",
        "asset": Asset.objects.get(name="現金"),
        "category": Category.objects.get(kind="expense", name="通信費"),
        "tax_rate": TaxRate.objects.get(name="標準税率 10%"),
        "amount_input_type": "tax_included",
        "amount": 3980,
        "frequency": "monthly",
        "day_of_month": 11,
        "start_date": date(2026, 10, 1),
    }
    values.update(overrides)
    return RecurringItem.objects.create(**values)


def test_周期に応じて必要な列だけが入る() -> None:
    _item(frequency="month_end", day_of_month=None)
    _item(frequency="weekly", day_of_month=None, weekday=0)
    _item(frequency="yearly", month=12)
    _raises_integrity(lambda: _item(frequency="monthly", day_of_month=None))
    _raises_integrity(lambda: _item(frequency="weekly", weekday=0))  # 日も入っている
    _raises_integrity(lambda: _item(frequency="yearly"))  # 月がない


def test_日は1から31() -> None:
    _item(day_of_month=31)
    _raises_integrity(lambda: _item(day_of_month=32))


def test_定期収支はマイナスを扱わない() -> None:
    _raises_integrity(lambda: _item(amount=-550))


def test_終了日は開始日以降() -> None:
    _raises_integrity(lambda: _item(end_date=date(2026, 9, 30)))


def test_振替は分類と税率を持たない() -> None:
    bank = Asset.objects.create(
        asset_group_id=Asset.objects.get(name="現金").asset_group_id, name="口座"
    )
    transfer = {"kind": "transfer", "transfer_to_asset": bank, "amount_input_type": None}
    _item(**transfer, category=None, tax_rate=None)
    _raises_integrity(lambda: _item(**transfer))


def test_同じ回は二重に登録できない() -> None:
    item = _item()
    RecurringRun.objects.create(
        recurring_item=item, scheduled_date=date(2026, 10, 11), registered_date=date(2026, 10, 11)
    )
    _raises_integrity(
        lambda: RecurringRun.objects.create(
            recurring_item=item,
            scheduled_date=date(2026, 10, 11),
            registered_date=date(2026, 10, 12),
        )
    )


def test_登録した明細を消しても履歴は残る() -> None:
    item = _item()
    tx = Transaction.objects.create(
        kind="expense",
        date=date(2026, 10, 11),
        asset=item.asset,
        amount=3980,
        amount_input_type="tax_included",
        source="recurring",
    )
    run = RecurringRun.objects.create(
        recurring_item=item, scheduled_date=tx.date, registered_date=tx.date, transaction=tx
    )
    tx.delete()
    run.refresh_from_db()
    assert run.transaction is None
