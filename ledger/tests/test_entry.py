"""明細入力のテスト（テスト仕様書 3.3・4.3）。htmx の通信と同じ形でリクエストを送る。"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from ledger.models import Transaction
from masters.models import Asset, AssetGroup, Category, TaxRate

pytestmark = pytest.mark.django_db

HTMX = {"HX-Request": "true"}


def _cat(name: str, kind: str = "expense") -> Category:
    return Category.objects.get(kind=kind, name=name)


def _rate(rate: str) -> TaxRate:
    return TaxRate.objects.get(rate=Decimal(rate))


def _cash() -> Asset:
    return Asset.objects.get(name="現金")


def _bank() -> Asset:
    return Asset.objects.create(asset_group=AssetGroup.objects.get(name="銀行"), name="銀行")


def _data(
    lines: list[tuple[Category | str, TaxRate | str, Any]],
    *,
    kind: str = "expense",
    asset: Asset | None = None,
    input_type: str = "tax_included",
    action: str = "save",
    **extra: Any,
) -> dict[str, Any]:
    """明細入力のフォームが送る内容を組み立てる。"""
    data: dict[str, Any] = {
        "_action": action,
        "_modal": "1",
        "kind": kind,
        "date": "2026-10-15",
        "asset": (asset or _cash()).pk,
        "description": "スーパー",
        "memo": "",
        "amount_input_type": input_type,
        "lines-TOTAL_FORMS": str(len(lines)),
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "1",
        "lines-MAX_NUM_FORMS": "20",
    }
    for i, (category, rate, amount) in enumerate(lines):
        data[f"lines-{i}-category"] = category.pk if isinstance(category, Category) else category
        data[f"lines-{i}-tax_rate"] = rate.pk if isinstance(rate, TaxRate) else rate
        data[f"lines-{i}-amount"] = amount
    data.update(extra)
    return data


def _example() -> list[tuple[Category | str, TaxRate | str, Any]]:
    """DB 設計書 5.6 の例：食費 8% 1,080、備品・衣類 10% 550、備品・衣類 10% 330。"""
    return [
        (_cat("食費"), _rate("8"), "1080"),
        (_cat("備品・衣類"), _rate("10"), "550"),
        (_cat("備品・衣類"), _rate("10"), "330"),
    ]


# ---------------------------------------------------------------- 開いたときの初期値


def test_新規の初期値(client: Client) -> None:
    html = client.get("/transactions/new/?modal=1", headers=HTMX).content.decode()
    assert "明細の登録" in html
    assert f'value="{timezone.localdate():%Y-%m-%d}"' in html  # 日付は今日
    assert 'value="tax_included"' in html and "checked" in html  # 設定の既定値は税込
    assert f'<option value="{_rate("10").pk}" selected>' in html  # 既定の税率 10%


def test_資産の初期値は前回その種類で使った資産(client: Client) -> None:
    bank = _bank()
    client.post("/transactions/new/", _data(_example(), asset=bank), headers=HTMX)
    html = client.get("/transactions/new/?modal=1", headers=HTMX).content.decode()
    assert f'<option value="{bank.pk}" selected>' in html


# ---------------------------------------------------------------- 保存


def test_設計書の例を登録する(client: Client) -> None:
    response = client.post("/transactions/new/", _data(_example()), headers=HTMX)
    assert response.status_code == 204
    assert response["HX-Refresh"] == "true"  # 小窓から開いたときは、開いている画面を読み直す
    tx = Transaction.objects.get()
    assert (tx.kind, tx.amount, tx.amount_input_type, tx.source) == (
        "expense",
        1960,
        "tax_included",
        "manual",
    )
    lines = list(tx.lines.values_list("amount_excl", "tax_amount", "amount_incl", "tax_rate_value"))
    assert lines == [
        (1000, 80, 1080, Decimal("8.0")),
        (500, 50, 550, Decimal("10.0")),
        (300, 30, 330, Decimal("10.0")),
    ]


def test_税抜で入力する(client: Client) -> None:
    client.post(
        "/transactions/new/",
        _data([(_cat("光熱費"), _rate("10"), "1000")], input_type="tax_excluded"),
        headers=HTMX,
    )
    tx = Transaction.objects.get()
    assert tx.amount == 1100
    assert tx.lines.get().amount_excl == 1000


def test_マイナス支出(client: Client) -> None:
    client.post(
        "/transactions/new/", _data([(_cat("備品・衣類"), _rate("10"), "-550")]), headers=HTMX
    )
    assert Transaction.objects.get().amount == -550


def test_振替を登録する(client: Client) -> None:
    bank = _bank()
    data = _data([], kind="transfer", asset=bank, transfer_to_asset=_cash().pk, amount="30000")
    assert client.post("/transactions/new/", data, headers=HTMX).status_code == 204
    tx = Transaction.objects.get()
    assert (tx.kind, tx.amount, tx.transfer_to_asset, tx.amount_input_type) == (
        "transfer",
        30000,
        _cash(),
        None,
    )
    assert not tx.lines.exists()


def test_画面全体で開いたときは家計簿のその月へ移る(client: Client) -> None:
    data = _data(_example(), _modal="")
    response = client.post("/transactions/new/", data, headers=HTMX)
    assert response["HX-Redirect"] == "/ledger/daily/2026-10/"


def test_税率マスタを変えても登録済みの明細は変わらない(client: Client) -> None:
    client.post("/transactions/new/", _data(_example()), headers=HTMX)
    TaxRate.objects.filter(rate=Decimal("8")).update(rate=Decimal("9.0"))
    assert Transaction.objects.get().lines.first().tax_rate_value == Decimal("8.0")  # type: ignore[union-attr]


# ---------------------------------------------------------------- 入力の誤り（画面設計書 6.4）


def _errors(client: Client, data: dict[str, Any]) -> str:
    response = client.post("/transactions/new/", data, headers=HTMX)
    assert response.status_code == 200
    assert not Transaction.objects.exists()
    return response.content.decode()


def test_分類と金額が必須(client: Client) -> None:
    html = _errors(client, _data([("", _rate("10"), "")]))
    assert "分類を入力してください。" in html and "金額を入力してください。" in html


def test_0円は登録できない(client: Client) -> None:
    assert "0円は登録できません。" in _errors(client, _data([(_cat("食費"), _rate("8"), "0")]))


def test_マイナスは支出だけ(client: Client) -> None:
    html = _errors(client, _data([(_cat("給与", "income"), _rate("0"), "-100")], kind="income"))
    assert "マイナスの金額は、支出でだけ入力できます。" in html


def test_プラスとマイナスを混ぜられない(client: Client) -> None:
    lines: list[tuple[Category | str, TaxRate | str, Any]] = [
        (_cat("食費"), _rate("8"), "100"),
        (_cat("食費"), _rate("8"), "-50"),
    ]
    assert "プラスとマイナスの金額を混ぜることはできません。" in _errors(client, _data(lines))


def test_収入の明細に支出用の分類は使えない(client: Client) -> None:
    html = _errors(client, _data([(_cat("食費"), _rate("8"), "100")], kind="income"))
    assert "field-error" in html  # 支出用の分類は選択肢にないため選べない


def test_振替の出金元と入金先は別の資産(client: Client) -> None:
    data = _data([], kind="transfer", transfer_to_asset=_cash().pk, amount="1000")
    assert "出金元と入金先には、別の資産を選んでください。" in _errors(client, data)


def test_内訳は20行まで(client: Client) -> None:
    lines: list[tuple[Category | str, TaxRate | str, Any]] = [
        (_cat("食費"), _rate("8"), "100")
    ] * 21
    data = _data(lines)
    data["lines-MAX_NUM_FORMS"] = "20"
    assert "内訳は20行までです。" in _errors(client, data)


# ---------------------------------------------------------------- 入力中の操作


def _redraw(client: Client, data: dict[str, Any]) -> str:
    before = Transaction.objects.count()
    response = client.post("/transactions/new/", data, headers=HTMX)
    assert response.status_code == 200
    assert Transaction.objects.count() == before  # 保存はしない
    return response.content.decode()


def _select(html: str, name: str) -> str:
    """name の選択欄の部分だけを取り出す。"""
    start = html.index(f'name="{name}"')
    return html[start : html.index("</select>", start)]


def test_内訳を追加と削除する(client: Client) -> None:
    html = _redraw(client, _data(_example()[:1], action="add_line"))
    assert "内訳2" in html and 'name="lines-TOTAL_FORMS" value="2"' in html
    html = _redraw(client, _data(_example(), action="remove:1"))
    # 2行目を消すと、3行目（330）が2行目に詰まる
    assert 'name="lines-TOTAL_FORMS" value="2"' in html
    assert 'name="lines-1-amount" value="330"' in html


def test_分類を選ぶと既定の税率になる(client: Client) -> None:
    html = _redraw(client, _data([(_cat("食費"), _rate("10"), "1080")], action="category:0"))
    assert f'<option value="{_rate("8").pk}" selected>' in html


def test_種類を切り替えると分類を空に戻し金額を引き継ぐ(client: Client) -> None:
    html = _redraw(client, _data(_example(), action="kind:transfer"))
    assert 'name="kind" value="transfer"' in html
    assert 'name="amount" value="1960"' in html  # 振替へ：内訳の金額の合計を引き継ぐ
    html = _redraw(client, _data(_example()[:1], action="kind:income"))
    # 収入へ：分類は空（「選んでください」）に戻る
    assert '<option value="" selected>' in _select(html, "lines-0-category")


def test_税額の表(client: Client) -> None:
    html = client.post("/transactions/tax-table/", _data(_example()), headers=HTMX).content.decode()
    assert "1,960" in html and "1,000" in html


def test_入力の補完(client: Client) -> None:
    client.post("/transactions/new/", _data([(_cat("食費"), _rate("8"), "1080")]), headers=HTMX)
    tx = Transaction.objects.get()
    html = client.get(
        "/transactions/suggest/?kind=expense&description=ス", headers=HTMX
    ).content.decode()
    assert "スーパー" in html and f'value="apply:{tx.pk}"' in html
    assert (
        client.get("/transactions/suggest/?kind=income&description=ス", headers=HTMX)
        .content.decode()
        .strip()
        == ""
    )
    # 候補を選ぶと、分類・税率・金額を入れる。入力済みの金額は上書きしない
    data = _data([("", _rate("10"), "")], action=f"apply:{tx.pk}")
    html = _redraw(client, data)
    assert f'value="{_cat("食費").pk}" selected' in _select(html, "lines-0-category")
    assert 'name="lines-0-amount" value="1080"' in html
    # 金額を入力済みなら、候補の金額で上書きしない
    html = _redraw(client, _data([("", _rate("10"), "500")], action=f"apply:{tx.pk}"))
    assert 'name="lines-0-amount" value="500"' in html


# ---------------------------------------------------------------- 編集・削除・コピー


def _saved(client: Client) -> Transaction:
    client.post("/transactions/new/", _data(_example()), headers=HTMX)
    return Transaction.objects.get()


def test_編集する(client: Client) -> None:
    tx = _saved(client)
    html = client.get(f"/transactions/{tx.pk}/edit/?modal=1", headers=HTMX).content.decode()
    assert "明細の編集" in html and 'name="lines-2-amount" value="330"' in html
    data = _data([(_cat("食費"), _rate("8"), "2160")])
    assert client.post(f"/transactions/{tx.pk}/edit/", data, headers=HTMX).status_code == 204
    tx.refresh_from_db()
    assert tx.amount == 2160 and tx.lines.count() == 1


def test_削除する(client: Client) -> None:
    tx = _saved(client)
    html = client.get(f"/transactions/{tx.pk}/edit/?modal=1", headers=HTMX).content.decode()
    assert "「10/15 スーパー ¥1,960」を削除しますか？この操作は取り消せません。" in html  # MSG-C01
    response = client.post(f"/transactions/{tx.pk}/delete/", {"_modal": "1"}, headers=HTMX)
    assert response.status_code == 204
    assert not Transaction.objects.exists()


def test_コピーは日付を今日にする(client: Client) -> None:
    tx = _saved(client)
    Transaction.objects.filter(pk=tx.pk).update(date=date(2026, 1, 1))
    html = client.get(f"/transactions/{tx.pk}/copy/?modal=1", headers=HTMX).content.decode()
    assert "明細の登録" in html
    assert f'value="{timezone.localdate():%Y-%m-%d}"' in html
    assert 'name="lines-0-amount" value="1080"' in html


def test_画面全体で開く(client: Client) -> None:
    html = client.get("/transactions/new/").content.decode()
    assert "<html" in html and "明細の登録" in html
    assert 'class="nav"' not in html  # メニューは隠す（画面設計書 1.7）
