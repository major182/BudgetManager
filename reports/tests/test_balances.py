"""残高とクレジットカードの請求額のテスト（テスト仕様書 3.4）。期待値は DB 設計書 5.3・5.7 の例。"""

from datetime import date

import pytest

from ledger import services
from masters.models import Asset, AssetGroup, Category, TaxRate
from reports.balances import balance, balances, summary, upcoming_bills

pytestmark = pytest.mark.django_db


def _asset(name: str, group: str, opening: int = 0, **card: object) -> Asset:
    return Asset.objects.create(
        asset_group=AssetGroup.objects.get(name=group), name=name, opening_balance=opening, **card
    )


def _card(opening: int = 0) -> Asset:
    bank = Asset.objects.get(name="現金")
    return _asset(
        "カード",
        "クレジットカード",
        opening,
        is_credit_card=True,
        closing_day=0,  # 月末締め
        payment_month_offset=1,  # 翌月
        payment_day=27,  # 27日払い
        payment_account=bank,
    )


def _tx(asset: Asset, day: date, amount: int, kind: str = "expense") -> None:
    category = Category.objects.get(kind=kind, name="その他")
    header = {
        "kind": kind,
        "date": day,
        "asset": asset,
        "amount_input_type": "tax_included",
    }
    services.save(header, [services.LineData(category, TaxRate.objects.get(rate=0), amount)])


def _transfer(source: Asset, to: Asset, day: date, amount: int) -> None:
    services.save(
        {
            "kind": "transfer",
            "date": day,
            "asset": source,
            "transfer_to_asset": to,
            "amount": amount,
        },
        [],
    )


def test_残高の式() -> None:
    cash = Asset.objects.get(name="現金")
    bank = _asset("銀行", "銀行", 900_000)
    _tx(bank, date(2026, 10, 14), 250_000, kind="income")  # 収入で増える
    _tx(bank, date(2026, 10, 5), 6_820)  # 支出で減る
    _transfer(bank, cash, date(2026, 10, 5), 30_000)  # 振替で出金・入金
    _tx(cash, date(2026, 10, 13), -550)  # マイナス支出で増える
    _tx(cash, date(2026, 10, 20), 1_000)  # 基準日より後は含めない
    assert balance(bank, date(2026, 10, 15)) == 900_000 + 250_000 - 6_820 - 30_000
    assert balance(cash, date(2026, 10, 15)) == 30_000 + 550


def test_資産合計と負債合計と純資産() -> None:
    # DB 設計書 5.3 の例：銀行 100,000、財布 5,000、カード −30,000
    bank = _asset("銀行", "銀行", 100_000)
    wallet = Asset.objects.get(name="現金")
    wallet.opening_balance = 5_000
    wallet.save()
    card = _card(-30_000)
    result = summary([bank, wallet, card], balances(date(2026, 10, 15)))
    assert (result.assets, result.liabilities, result.net) == (105_000, 30_000, 75_000)


def test_カードで払うと負債が増える() -> None:
    card = _card()
    _tx(card, date(2026, 9, 10), 3_000)
    assert balance(card, date(2026, 9, 30)) == -3_000


def test_次回の引き落とし_設計書の例() -> None:
    # 月末締め・翌月27日払い。今日が 10/15 なら、
    # 次回は「9/30 締め → 10/27 引き落とし」（9/1〜9/30 の利用分）
    card = _card()
    _tx(card, date(2026, 8, 31), 999)  # 8月分（9/27 に引き落とし済み）
    _tx(card, date(2026, 9, 1), 1_000)
    _tx(card, date(2026, 9, 30), 2_000)
    _tx(card, date(2026, 9, 15), -500)  # 返品は差し引く
    _tx(card, date(2026, 10, 1), 4_000)  # 10月分
    bills = upcoming_bills(card, date(2026, 10, 15))
    first, second = bills
    assert (first.closing_date, first.payment_date, first.period_start) == (
        date(2026, 9, 30),
        date(2026, 10, 27),
        date(2026, 9, 1),
    )
    assert (first.amount, first.estimate) == (2_500, False)
    # 10/31 締めの分は、締め日前なので目安
    assert (second.closing_date, second.payment_date, second.amount, second.estimate) == (
        date(2026, 10, 31),
        date(2026, 11, 27),
        4_000,
        True,
    )


def test_請求額に振替は含めずカードへの入金は差し引く() -> None:
    card = _card()
    bank = Asset.objects.get(name="現金")
    _tx(card, date(2026, 9, 10), 5_000)
    _tx(card, date(2026, 9, 11), 300, kind="income")  # ポイントの還元
    _transfer(bank, card, date(2026, 9, 27), 9_999)  # 引き落とし（振替）は含めない
    assert upcoming_bills(card, date(2026, 10, 1))[0].amount == 4_700


def test_締め日が15日で翌々月払い() -> None:
    card = _card()
    card.closing_day, card.payment_month_offset, card.payment_day = 15, 2, 10
    card.save()
    bill = upcoming_bills(card, date(2026, 10, 1))[0]
    # 8/15 締め → 10/10 引き落とし（7/16〜8/15 の利用分）
    assert (bill.closing_date, bill.payment_date, bill.period_start) == (
        date(2026, 8, 15),
        date(2026, 10, 10),
        date(2026, 7, 16),
    )
