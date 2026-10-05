"""設定画面のテスト（テスト仕様書 4.2）。htmx の通信と同じ形でリクエストを送る。"""

import pytest
from django.test import Client

from core.models import AppSettings
from masters.models import Asset, AssetGroup, Category, TaxRate

pytestmark = pytest.mark.django_db

# htmx が送るヘッダー
HTMX = {"HX-Request": "true"}


@pytest.mark.parametrize(
    "url",
    [
        "/settings/tax-rates/",
        "/settings/categories/",
        "/settings/categories/?kind=income",
        "/settings/assets/",
        "/settings/display/",
    ],
)
def test_設定の画面が開く(client: Client, url: str) -> None:
    assert client.get(url).status_code == 200


def test_分類の一覧は大分類と既定の税率を並び順に出す(client: Client) -> None:
    html = client.get("/settings/categories/").content.decode()
    assert html.index("食費") < html.index("備品・衣類") < html.index("その他")
    assert "8.0%" in html


def test_追加の小窓を開く(client: Client) -> None:
    html = client.get("/settings/tax-rates/new/", headers=HTMX).content.decode()
    assert "税率の追加" in html and "登録" in html


def test_税率を登録すると一覧の最後に並び完了を知らせる(client: Client) -> None:
    response = client.post(
        "/settings/tax-rates/new/", {"name": "旧税率 5%", "rate": "5"}, headers=HTMX
    )
    assert response.status_code == 204
    assert response["HX-Redirect"] == "/settings/tax-rates/"
    assert TaxRate.objects.order_by("sort_order").last().name == "旧税率 5%"  # type: ignore[union-attr]
    # 開き直した一覧に完了の知らせが出る（MSG-I01）
    assert 'data-toast="登録しました"' in client.get("/settings/tax-rates/").content.decode()


def test_入力の誤りは項目の下に設計書の文言で出す(client: Client) -> None:
    html = client.post(
        "/settings/tax-rates/new/", {"name": "", "rate": "120"}, headers=HTMX
    ).content.decode()
    assert "名前を入力してください。" in html  # MSG-E01
    assert "税率は 0〜100 の範囲で、小数第1位まで入力してください。" in html  # MSG-E24


def test_名前の重複(client: Client) -> None:
    html = client.post(
        "/settings/tax-rates/new/", {"name": "標準税率 10%", "rate": "10"}, headers=HTMX
    ).content.decode()
    assert "この名前はすでに使われています。" in html  # MSG-E06


def test_既定の税率は非表示にできない(client: Client) -> None:
    rate = TaxRate.objects.get(name="標準税率 10%")
    html = client.post(
        f"/settings/tax-rates/{rate.pk}/edit/",
        {"name": rate.name, "rate": "10", "is_hidden": "on"},
        headers=HTMX,
    ).content.decode()
    assert "既定の税率に設定されている税率は、非表示にできません。" in html  # MSG-E23


def test_小分類を追加する(client: Client) -> None:
    food = Category.objects.get(kind="expense", name="食費")
    response = client.post(
        f"/settings/categories/new/?kind=expense&parent={food.pk}",
        {"name": "外食", "parent": food.pk},
        headers=HTMX,
    )
    assert response["HX-Redirect"] == "/settings/categories/?kind=expense"
    assert Category.objects.get(name="外食").parent == food


def test_小分類の下には作れない(client: Client) -> None:
    food = Category.objects.get(kind="expense", name="食費")
    eat_out = Category.objects.create(kind="expense", name="外食", parent=food)
    html = client.post(
        "/settings/categories/new/?kind=expense",
        {"name": "ランチ", "parent": eat_out.pk},
        headers=HTMX,
    ).content.decode()
    # 小分類は親の選択肢に出ないため、選べない値として誤りになる
    assert "ランチ" not in Category.objects.values_list("name", flat=True)
    assert "field-error" in html


def test_同じ親の中で分類の名前は重複しない(client: Client) -> None:
    html = client.post(
        "/settings/categories/new/?kind=expense", {"name": "食費"}, headers=HTMX
    ).content.decode()
    assert "この名前はすでに使われています。" in html
    # 収入の「その他」と支出の「その他」は別の一覧なので登録できる（初期データで両方ある）
    assert Category.objects.filter(name="その他").count() == 2


def test_使用中のマスタの削除は理由を小窓に出す(client: Client) -> None:
    group = AssetGroup.objects.get(name="現金")
    html = client.post(f"/settings/asset-groups/{group.pk}/delete/", headers=HTMX).content.decode()
    assert "「現金」には1件の資産が属しているため削除できません。" in html
    assert AssetGroup.objects.filter(pk=group.pk).exists()


def test_削除の確認ダイアログの文言(client: Client) -> None:
    rate = TaxRate.objects.get(name="軽減税率 8%")
    html = client.get(f"/settings/tax-rates/{rate.pk}/edit/", headers=HTMX).content.decode()
    # MSG-C01 とボタンの文言
    assert 'hx-confirm="「軽減税率 8%」を削除しますか？この操作は取り消せません。"' in html
    assert 'data-confirm-ok="削除する"' in html


def test_使われていないマスタを削除する(client: Client) -> None:
    rate = TaxRate.objects.create(name="旧税率 5%", rate=5)
    response = client.post(f"/settings/tax-rates/{rate.pk}/delete/", headers=HTMX)
    assert response.status_code == 204
    assert not TaxRate.objects.filter(pk=rate.pk).exists()


def test_並べ替えると一覧へ戻る(client: Client) -> None:
    rate = TaxRate.objects.get(name="軽減税率 8%")
    response = client.post(f"/settings/tax-rates/{rate.pk}/move/up/", headers=HTMX)
    assert response.status_code == 302 and response["Location"] == "/settings/tax-rates/"
    assert TaxRate.objects.order_by("sort_order").first().name == "軽減税率 8%"  # type: ignore[union-attr]


def test_クレジットカードは締め日などが必要(client: Client) -> None:
    group = AssetGroup.objects.get(name="クレジットカード")
    data = {
        "name": "カード",
        "asset_group": group.pk,
        "opening_balance": "0",
        "is_credit_card": "on",
        "closing_day": "0",
        "payment_month_offset": "1",
        "payment_day": "27",
    }
    html = client.post("/settings/assets/new/", data, headers=HTMX).content.decode()
    assert "引き落とし口座を入力してください。" in html
    data["payment_account"] = str(Asset.objects.get(name="現金").pk)
    assert client.post("/settings/assets/new/", data, headers=HTMX).status_code == 204
    card = Asset.objects.get(name="カード")
    assert (card.closing_day, card.payment_day, card.get_payment_label()) == (0, 27, "翌月27日払い")


def test_カード以外はカードの項目を保存しない(client: Client) -> None:
    group = AssetGroup.objects.get(name="銀行")
    data = {"name": "銀行", "asset_group": group.pk, "opening_balance": "1000", "closing_day": "10"}
    assert client.post("/settings/assets/new/", data, headers=HTMX).status_code == 204
    assert Asset.objects.get(name="銀行").closing_day is None


def test_表示設定を保存する(client: Client) -> None:
    data = {
        "currency_symbol": "yen_text",
        "use_thousands_separator": "on",
        "month_start_day": "25",
        "month_start_holiday_rule": "previous",
        "week_start": "monday",
        "theme": "dark",
        "tax_rounding": "round_half_up",
        "default_tax_rate": TaxRate.objects.get(name="軽減税率 8%").pk,
        "default_amount_input_type": "tax_excluded",
    }
    response = client.post("/settings/display/", data)
    assert response.status_code == 302
    s = AppSettings.load()
    assert (s.currency_symbol, s.month_start_day, s.week_start, s.theme) == (
        "yen_text",
        25,
        "monday",
        "dark",
    )
    # 保存した時点で画面に反映する（テーマ）
    assert 'data-theme="dark"' in client.get("/settings/display/").content.decode()
