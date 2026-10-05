"""資産・資産詳細の画面のテスト（テスト仕様書 4.6）。"""

from datetime import date

import pytest
from django.test import Client
from django.utils import timezone

from core.periods import month_containing
from ledger import services
from masters.models import Asset, AssetGroup, Category, TaxRate

pytestmark = pytest.mark.django_db


def _asset(name: str, group: str, opening: int = 0, **extra: object) -> Asset:
    return Asset.objects.create(
        asset_group=AssetGroup.objects.get(name=group), name=name, opening_balance=opening, **extra
    )


def _tx(asset: Asset, day: date, amount: int, kind: str = "expense", description: str = "") -> None:
    header = {
        "kind": kind,
        "date": day,
        "asset": asset,
        "description": description,
        "amount_input_type": "tax_included",
    }
    category = Category.objects.get(kind=kind, name="その他")
    services.save(header, [services.LineData(category, TaxRate.objects.get(rate=0), amount)])


def test_資産の一覧と合計(client: Client) -> None:
    _asset("〇〇銀行", "銀行", 100_000)
    cash = Asset.objects.get(name="現金")
    cash.opening_balance = 5_000
    cash.save()
    _asset("旧口座", "銀行", 1_000, is_hidden=True)
    _asset(
        "△△カード",
        "クレジットカード",
        -30_000,
        is_credit_card=True,
        closing_day=0,
        payment_month_offset=1,
        payment_day=27,
        payment_account=cash,
    )
    html = client.get("/assets/").content.decode()
    summary = html.split('class="summary3"')[1].split("</div>\n</div>")[0]
    # 非表示の資産（1,000）も合計に含める：資産 106,000、負債 30,000、純資産 76,000
    assert "¥106,000" in summary and "¥30,000" in summary and "¥76,000" in summary
    assert "〇〇銀行" in html and "旧口座" not in html  # 非表示の資産は一覧に出さない
    assert "次回" in html  # カードの次回の引き落とし
    assert "旧口座" in client.get("/assets/?hidden=1").content.decode()


def test_資産詳細は今日を含む月で開く(client: Client) -> None:
    cash = Asset.objects.get(name="現金")
    month = month_containing(timezone.localdate()).month
    response = client.get(f"/assets/{cash.pk}/")
    assert response["Location"] == f"/assets/{cash.pk}/{month:%Y-%m}/"


def test_資産詳細の月初と入出金と残高(client: Client) -> None:
    bank = _asset("〇〇銀行", "銀行", 1_000_000)
    cash = Asset.objects.get(name="現金")
    _tx(bank, date(2026, 9, 30), 50_000, description="前月")
    _tx(bank, date(2026, 10, 14), 250_000, kind="income", description="給与")
    services.save(
        {
            "kind": "transfer",
            "date": date(2026, 10, 15),
            "asset": bank,
            "transfer_to_asset": cash,
            "amount": 30_000,
        },
        [],
    )
    html = client.get(f"/assets/{bank.pk}/2026-10/").content.decode()
    totals = html.split('class="summary4"')[1].split("</div>\n</div>")[0]
    # 月初 950,000、入金 250,000、出金 30,000、月末 1,170,000
    for value in ["¥950,000", "¥250,000", "¥30,000", "¥1,170,000"]:
        assert value in totals
    # 新しい明細が上。各明細の後の残高
    assert html.index("残高 ¥1,170,000") < html.index("残高 ¥1,200,000")
    assert "〇〇銀行 → 現金" in html and 'class="amt num transfer"' in html  # 振替は灰色
    # 振替の入金先から見ると入金
    cash_html = client.get(f"/assets/{cash.pk}/2026-10/").content.decode()
    assert "残高 ¥30,000" in cash_html


def test_カードの資産詳細は引き落とし予定を出す(client: Client) -> None:
    cash = Asset.objects.get(name="現金")
    card = _asset(
        "△△カード",
        "クレジットカード",
        0,
        is_credit_card=True,
        closing_day=0,
        payment_month_offset=1,
        payment_day=27,
        payment_account=cash,
    )
    html = client.get(f"/assets/{card.pk}/2026-10/").content.decode()
    assert "月末締め・翌月27日払い（現金から）" in html
    assert html.count('class="bill"') == 2  # 引き落とし予定を2件
