"""定期収支の登録日と自動登録のテスト（テスト仕様書 5.1）。DB 設計書 5.8 の手順を確かめる。"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import Holiday
from ledger.models import Transaction
from masters.models import Asset, AssetGroup, Category, TaxRate
from recurring.models import RecurringItem, RecurringRun
from recurring.services import adjusted, next_date, register_due, scheduled_dates

pytestmark = pytest.mark.django_db


def _item(created: date = date(2026, 1, 1), **overrides: object) -> RecurringItem:
    values: dict[str, object] = {
        "kind": "expense",
        "asset": Asset.objects.get(name="現金"),
        "category": Category.objects.get(kind="expense", name="通信費"),
        "tax_rate": TaxRate.objects.get(rate=Decimal("10")),
        "amount_input_type": "tax_included",
        "amount": 3980,
        "description": "スマホ代",
        "frequency": "monthly",
        "day_of_month": 25,
        "start_date": date(2026, 1, 1),
    }
    values.update(overrides)
    item = RecurringItem.objects.create(**values)
    # 「定期収支を登録した日」を決めるため、作成日時を書き換える
    created_at = timezone.make_aware(datetime(created.year, created.month, created.day, 9, 0))
    RecurringItem.objects.filter(pk=item.pk).update(created_at=created_at)
    item.refresh_from_db()
    return item


# ---------------------------------------------------------------- 本来の登録日（BR-61）


def test_毎月の日とその月にない日() -> None:
    item = _item(day_of_month=31)
    days = list(scheduled_dates(item, date(2026, 1, 1), date(2026, 4, 30)))
    assert days == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_毎月末と毎週と毎年() -> None:
    assert list(
        scheduled_dates(
            _item(frequency="month_end", day_of_month=None), date(2026, 2, 1), date(2026, 3, 31)
        )
    ) == [
        date(2026, 2, 28),
        date(2026, 3, 31),
    ]
    weekly = _item(frequency="weekly", day_of_month=None, weekday=0)  # 毎週月曜
    assert list(scheduled_dates(weekly, date(2026, 10, 1), date(2026, 10, 20))) == [
        date(2026, 10, 5),
        date(2026, 10, 12),
        date(2026, 10, 19),
    ]
    yearly = _item(frequency="yearly", month=2, day_of_month=29)  # うるう年でない年は 2/28
    assert list(scheduled_dates(yearly, date(2026, 1, 1), date(2028, 12, 31))) == [
        date(2026, 2, 28),
        date(2027, 2, 28),
        date(2028, 2, 29),
    ]


def test_開始日と終了日の外は含めない() -> None:
    item = _item(start_date=date(2026, 3, 1), end_date=date(2026, 5, 31))
    assert list(scheduled_dates(item, date(2026, 1, 1), date(2026, 12, 31))) == [
        date(2026, 3, 25),
        date(2026, 4, 25),
        date(2026, 5, 25),
    ]


# ---------------------------------------------------------------- 土日祝日の扱い（BR-62）


def test_3つの休日の扱い() -> None:
    sunday = date(2026, 10, 25)
    assert adjusted(sunday, _item(holiday_rule="none"), set()) == sunday
    assert adjusted(sunday, _item(holiday_rule="previous"), set()) == date(2026, 10, 23)  # 金曜
    assert adjusted(sunday, _item(holiday_rule="next"), set()) == date(2026, 10, 26)  # 月曜


def test_祝日と年末年始もずらす() -> None:
    holiday = date(2026, 11, 23)  # 勤労感謝の日（月曜）
    assert adjusted(holiday, _item(holiday_rule="next"), {holiday}) == date(2026, 11, 24)
    # 12/31（木）は年末年始。後営業日は 1/4（月）、前営業日は 12/30（水）
    assert adjusted(date(2026, 12, 31), _item(holiday_rule="next"), set()) == date(2027, 1, 4)
    assert adjusted(date(2026, 12, 31), _item(holiday_rule="previous"), set()) == date(2026, 12, 30)


# ---------------------------------------------------------------- 自動登録（BT-01）


def test_その日が来たら登録する() -> None:
    item = _item()
    assert register_due(date(2026, 1, 24)) == 0
    assert register_due(date(2026, 1, 25)) == 1
    tx = Transaction.objects.get()
    assert (tx.date, tx.amount, tx.source, tx.description) == (
        date(2026, 1, 25),
        3980,
        "recurring",
        "スマホ代",
    )
    line = tx.lines.get()
    assert (line.tax_rate_value, line.tax_amount, line.amount_incl) == (Decimal("10.0"), 361, 3980)
    run = RecurringRun.objects.get()
    assert (run.recurring_item, run.scheduled_date, run.transaction) == (
        item,
        date(2026, 1, 25),
        tx,
    )


def test_前営業日にずらす回は前の日に登録する() -> None:
    _item(created=date(2026, 10, 1), start_date=date(2026, 10, 1), holiday_rule="previous")
    # 10/25 は日曜 → 10/23（金）に登録する
    assert register_due(date(2026, 10, 22)) == 0
    assert register_due(date(2026, 10, 23)) == 1
    assert Transaction.objects.get().date == date(2026, 10, 23)


def test_二重に登録しない() -> None:
    _item()
    register_due(date(2026, 1, 25))
    assert register_due(date(2026, 1, 25)) == 0
    assert Transaction.objects.count() == 1


def test_止まっていた日の分をさかのぼって登録する() -> None:
    _item()
    assert register_due(date(2026, 4, 10)) == 3  # 1/25・2/25・3/25
    assert list(Transaction.objects.order_by("date").values_list("date", flat=True)) == [
        date(2026, 1, 25),
        date(2026, 2, 25),
        date(2026, 3, 25),
    ]


def test_登録した日より前の回はさかのぼらない() -> None:
    _item(created=date(2026, 6, 1), start_date=date(2026, 1, 1))
    assert register_due(date(2026, 7, 1)) == 1  # 6/25 だけ。1/25〜5/25 は登録しない


def test_削除した明細は再び登録しない() -> None:
    _item()
    register_due(date(2026, 1, 25))
    Transaction.objects.all().delete()
    assert register_due(date(2026, 1, 26)) == 0
    assert RecurringRun.objects.get().transaction is None  # 履歴は残る（BR-65）


def test_振替の定期収支() -> None:
    bank = Asset.objects.create(asset_group=AssetGroup.objects.get(name="銀行"), name="銀行")
    _item(
        kind="transfer",
        asset=bank,
        transfer_to_asset=Asset.objects.get(name="現金"),
        category=None,
        tax_rate=None,
        amount_input_type=None,
        amount=30000,
    )
    register_due(date(2026, 1, 25))
    tx = Transaction.objects.get()
    assert (tx.kind, tx.amount, tx.transfer_to_asset.name if tx.transfer_to_asset else None) == (
        "transfer",
        30000,
        "現金",
    )


def test_周期の説明() -> None:
    assert _item(holiday_rule="previous").schedule_label() == "毎月25日（前営業日）"
    assert _item(frequency="weekly", day_of_month=None, weekday=0).schedule_label() == "毎週月曜"
    assert (
        _item(frequency="month_end", day_of_month=None, holiday_rule="next").schedule_label()
        == "毎月末（後営業日）"
    )
    assert _item(frequency="yearly", month=12, day_of_month=10).schedule_label() == "毎年12月10日"


def test_次回の登録予定日() -> None:
    item = _item(created=date(2026, 10, 1), start_date=date(2026, 10, 1), holiday_rule="previous")
    assert next_date(item, date(2026, 10, 5)) == date(2026, 10, 23)  # 10/25（日）→ 10/23（金）
    register_due(date(2026, 10, 23))
    assert next_date(item, date(2026, 10, 24)) == date(2026, 11, 25)


def test_祝日テーブルを使って調整する() -> None:
    Holiday.objects.create(date=date(2026, 11, 23), name="勤労感謝の日")
    _item(
        created=date(2026, 11, 1),
        start_date=date(2026, 11, 1),
        day_of_month=23,
        holiday_rule="next",
    )
    register_due(date(2026, 11, 24))
    assert Transaction.objects.get().date == date(2026, 11, 24)
