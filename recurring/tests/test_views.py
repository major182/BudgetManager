"""定期収支管理の画面のテスト（テスト仕様書 4.9）。"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from ledger.models import Transaction
from masters.models import Asset, AssetGroup, Category, TaxRate
from recurring.models import RecurringItem
from recurring.services import register_due

pytestmark = pytest.mark.django_db

HTMX = {"HX-Request": "true"}


def _data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": "expense",
        "asset": Asset.objects.get(name="現金").pk,
        "category": Category.objects.get(kind="expense", name="通信費").pk,
        "tax_rate": TaxRate.objects.get(rate=Decimal("10")).pk,
        "amount_input_type": "tax_included",
        "amount": "3980",
        "description": "スマホ代",
        "frequency": "monthly",
        "day_of_month": "25",
        "holiday_rule": "previous",
        "start_date": timezone.localdate().isoformat(),
    }
    data.update(overrides)
    return data


def test_定期収支を登録すると一覧に次回の予定日が出る(client: Client) -> None:
    response = client.post("/settings/recurring/new/", _data(), headers=HTMX)
    assert response.status_code == 204 and response["HX-Redirect"] == "/settings/recurring/"
    item = RecurringItem.objects.get()
    assert (item.frequency, item.day_of_month, item.weekday, item.month) == (
        "monthly",
        25,
        None,
        None,
    )
    html = client.get("/settings/recurring/").content.decode()
    assert "スマホ代" in html and "毎月25日（前営業日）" in html and "次回" in html


def test_周期に使わない項目は保存しない(client: Client) -> None:
    client.post(
        "/settings/recurring/new/", _data(frequency="weekly", weekday="0", month="3"), headers=HTMX
    )
    item = RecurringItem.objects.get()
    assert (item.weekday, item.day_of_month, item.month) == (0, None, None)


def test_振替は分類と税率を保存しない(client: Client) -> None:
    bank = Asset.objects.create(asset_group=AssetGroup.objects.get(name="銀行"), name="銀行")
    data = _data(
        kind="transfer",
        asset=bank.pk,
        transfer_to_asset=Asset.objects.get(name="現金").pk,
        amount="30000",
    )
    assert client.post("/settings/recurring/new/", data, headers=HTMX).status_code == 204
    item = RecurringItem.objects.get()
    assert (item.category, item.tax_rate, item.amount_input_type) == (None, None, None)


def test_入力の誤り(client: Client) -> None:
    html = client.post(
        "/settings/recurring/new/",
        _data(amount="-1", category="", end_date="2000-01-01", frequency="weekly", weekday=""),
        headers=HTMX,
    ).content.decode()
    assert "金額は1〜99,999,999の範囲で入力してください。" in html  # マイナスは扱わない
    assert "分類を入力してください。" in html and "曜日を入力してください。" in html
    assert "終了日は開始日以降の日付にしてください。" in html  # MSG-E08
    assert not RecurringItem.objects.exists()


def test_収入の定期収支に支出用の分類は使えない(client: Client) -> None:
    html = client.post(
        "/settings/recurring/new/", _data(kind="income"), headers=HTMX
    ).content.decode()
    assert "収入の明細には、収入用の分類を選んでください。" in html  # MSG-E14


def test_分類の既定の税率の対応表(client: Client) -> None:
    html = client.get("/settings/recurring/new/", headers=HTMX).content.decode()
    food = Category.objects.get(kind="expense", name="食費")
    eight = TaxRate.objects.get(rate=Decimal("8"))
    assert '<script id="default-rates" type="application/json">' in html
    assert f'"{food.pk}": "{eight.pk}"' in html


def test_入力中に次回の予定日を出す(client: Client) -> None:
    today = timezone.localdate()
    html = client.post(
        "/settings/recurring/preview/", _data(day_of_month=str(today.day)), headers=HTMX
    ).content.decode()
    assert "次回の登録予定日" in html


def test_削除しても登録済みの明細は消えない(client: Client) -> None:
    client.post("/settings/recurring/new/", _data(start_date="2026-01-01"), headers=HTMX)
    item = RecurringItem.objects.get()
    RecurringItem.objects.filter(pk=item.pk).update(
        created_at=timezone.make_aware(datetime(2026, 1, 1))
    )
    register_due(date(2026, 1, 26))
    html = client.get(f"/settings/recurring/{item.pk}/edit/", headers=HTMX).content.decode()
    assert "登録済みの明細は削除されません。" in html  # MSG-C03
    assert client.post(f"/settings/recurring/{item.pk}/delete/", headers=HTMX).status_code == 204
    assert not RecurringItem.objects.exists() and Transaction.objects.count() == 1


def test_開始日を過去にしたときの注意(client: Client) -> None:
    html = client.post(
        "/settings/recurring/new/", _data(start_date="2000-01-01", amount=""), headers=HTMX
    ).content.decode()
    assert "登録日より前の回は、自動では登録されません。" in html  # MSG-W01
