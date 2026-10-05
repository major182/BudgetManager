"""家計簿（日別・カレンダー・月別）と検索のテスト（テスト仕様書 4.4・4.5）。"""

from datetime import date

import pytest
from django.test import Client

from core.models import AppSettings
from ledger import services
from ledger.models import Transaction
from masters.models import Asset, AssetGroup, Category, TaxRate

pytestmark = pytest.mark.django_db


@pytest.fixture
def bank() -> Asset:
    return Asset.objects.create(asset_group=AssetGroup.objects.get(name="銀行"), name="〇〇銀行")


def _tx(
    day: date,
    amount: int,
    *,
    kind: str = "expense",
    category: str = "食費",
    description: str = "スーパー",
    memo: str = "",
    asset: Asset | None = None,
    extra_lines: int = 0,
    source: str = "manual",
) -> Transaction:
    """税率 0% の内訳で明細を作る（金額をそのまま合計にするため）。"""
    rate = TaxRate.objects.get(rate=0)
    cat = Category.objects.get(kind=kind, name=category)
    lines = [services.LineData(cat, rate, amount)] + [services.LineData(cat, rate, 1)] * extra_lines
    header = {
        "kind": kind,
        "date": day,
        "asset": asset or Asset.objects.get(name="現金"),
        "description": description,
        "memo": memo,
        "amount_input_type": "tax_included",
    }
    return services.save(header, lines, source=source)


def _transfer(day: date, amount: int, source: Asset, to: Asset) -> Transaction:
    header = {
        "kind": "transfer",
        "date": day,
        "asset": source,
        "transfer_to_asset": to,
        "amount": amount,
    }
    return services.save(header, [])


# ---------------------------------------------------------------- 日別


def test_日別は日ごとにまとめ新しい日付が上(client: Client) -> None:
    _tx(date(2026, 10, 14), 250000, kind="income", category="給与", description="10月分")
    _tx(date(2026, 10, 15), 1960)
    html = client.get("/ledger/daily/2026-10/").content.decode()
    assert html.index("スーパー") < html.index("10月分")
    assert "¥250,000" in html and "¥1,960" in html


def test_期間の合計に振替は含めない(client: Client, bank: Asset) -> None:
    _tx(date(2026, 10, 14), 250000, kind="income", category="給与")
    _tx(date(2026, 10, 15), 1960)
    _transfer(date(2026, 10, 5), 30000, bank, Asset.objects.get(name="現金"))
    html = client.get("/ledger/daily/2026-10/").content.decode()
    totals = html.split('class="totals"')[1].split("</div>\n  </div>")[0]
    assert "¥250,000" in totals and "¥1,960" in totals and "¥248,040" in totals
    assert "¥30,000" not in totals
    assert "〇〇銀行 → 現金" in html  # 振替の行


def test_明細の行の表示(client: Client) -> None:
    _tx(date(2026, 10, 15), 1960, extra_lines=2)
    _tx(date(2026, 10, 13), -550, category="備品・衣類", description="返品")
    _tx(date(2026, 10, 11), 3980, category="通信費", source="recurring")
    html = client.get("/ledger/daily/2026-10/").content.decode()
    assert "他2件" in html  # 内訳が複数
    assert '<span class="badge">定期</span>' in html  # 定期収支で登録された明細
    # 返品（マイナス支出）は符号なしの青（画面設計書 1.2・1.3）
    assert 'class="amt num income">¥550<' in html
    assert "−" not in html.split('id="main"')[1].split("</main>")[0].replace("−99,999,999", "")


def test_明細がない月(client: Client) -> None:
    assert "この期間の明細はありません。" in client.get("/ledger/daily/2026-10/").content.decode()


def test_開始日が25日の期間(client: Client) -> None:
    AppSettings.objects.filter(pk=1).update(month_start_day=25)
    _tx(date(2026, 9, 25), 100, description="期間の最初")
    _tx(date(2026, 10, 25), 200, description="翌月の期間")
    html = client.get("/ledger/daily/2026-10/").content.decode()
    assert "9/25〜10/24" in html  # 開始日が1日以外のときだけ期間を出す
    assert "期間の最初" in html and "翌月の期間" not in html


# ---------------------------------------------------------------- カレンダー・月別・移動


def test_カレンダー(client: Client) -> None:
    _tx(date(2026, 10, 1), 80000, category="その他", description="家賃")
    html = client.get("/ledger/calendar/2026-10/?date=2026-10-01").content.decode()
    assert "8万" in html  # 1万円以上は縮める
    assert "10/1（木）の明細" in html and "家賃" in html
    # 週の開始は日曜（初期値）。10/1（木）の週は 9/27（日）から
    assert 'href="?date=2026-09-27"' in html
    AppSettings.objects.filter(pk=1).update(week_start="monday")
    html = client.get("/ledger/calendar/2026-10/").content.decode()
    assert 'href="?date=2026-09-28"' in html and 'href="?date=2026-09-27"' not in html


def test_月別(client: Client) -> None:
    _tx(date(2026, 10, 14), 250000, kind="income", category="給与")
    _tx(date(2026, 3, 3), 5000)
    html = client.get("/ledger/monthly/2026/").content.decode()
    assert html.index("12月") < html.index("10月") < html.index("3月")  # 新しい月が上
    assert 'href="/ledger/daily/2026-10/"' in html
    assert "¥245,000" in html  # 年の合計（250,000 − 5,000）


def test_タブと前後の移動(client: Client) -> None:
    html = client.get("/ledger/daily/2026-10/").content.decode()
    for url in ["/ledger/daily/2026-10/", "/ledger/calendar/2026-10/", "/ledger/monthly/2026/"]:
        assert f'href="{url}"' in html
    assert 'href="/ledger/daily/2026-09/"' in html and 'href="/ledger/daily/2026-11/"' in html
    assert 'hx-boost="true"' in html  # URL の更新は hx-boost が行う（画面設計書 1.4）


def test_年月を選んで移る(client: Client) -> None:
    response = client.get("/ledger/jump/?month=2025-03&view=calendar")
    assert response["Location"] == "/ledger/calendar/2025-03/"


# ---------------------------------------------------------------- 検索


def _search(client: Client, **params: str) -> str:
    query = {"date_from": "2026-01-01", "date_until": "2026-12-31", **params}
    return client.get("/transactions/search/", query).content.decode()


def test_キーワードは内容とメモを部分一致で探す(client: Client) -> None:
    _tx(date(2026, 10, 1), 100, description="ドラッグストア")
    _tx(date(2026, 10, 2), 200, description="昼", memo="同僚とランチ")
    _tx(date(2026, 10, 3), 300, description="電車")
    html = _search(client, q="ラ")
    assert (
        "ドラッグストア" in html
        and "同僚とランチ" not in html
        and "昼" in html
        and "電車" not in html
    )
    assert "2件" in html


def test_分類は小分類も含めて探す(client: Client) -> None:
    food = Category.objects.get(kind="expense", name="食費")
    Category.objects.create(kind="expense", name="外食", parent=food)
    _tx(date(2026, 10, 1), 100, category="外食", description="ランチ")
    _tx(date(2026, 10, 2), 200, category="光熱費", description="電気")
    html = _search(client, category=str(food.pk))
    assert "ランチ" in html and "電気" not in html


def test_資産は振替の入金先も対象(client: Client, bank: Asset) -> None:
    _transfer(date(2026, 10, 5), 30000, bank, Asset.objects.get(name="現金"))
    _tx(date(2026, 10, 6), 100, asset=bank, description="銀行で支払い")
    html = _search(client, asset=str(Asset.objects.get(name="現金").pk))
    assert "〇〇銀行 → 現金" in html and "銀行で支払い" not in html


def test_検索の合計は見つかった明細の合計(client: Client) -> None:
    _tx(date(2026, 10, 12), 2710)
    _tx(date(2026, 10, 5), 1960)
    html = _search(client, q="スーパー")
    assert "2件" in html and "¥4,670" in html


def test_返品だけの日の支出の合計は青(client: Client) -> None:
    _tx(date(2026, 10, 13), -550, category="備品・衣類", description="返品")
    html = client.get("/ledger/daily/2026-10/").content.decode()
    assert '<span class="income">¥550</span>' in html  # 日の見出し


def test_明細の行から編集の小窓を開く(client: Client) -> None:
    tx = _tx(date(2026, 10, 15), 1960)
    html = client.get("/ledger/daily/2026-10/").content.decode()
    row = f'hx-get="/transactions/{tx.pk}/edit/?modal=1" hx-target="#modal-body"'
    assert row + ' hx-select="#entry-form"' in html


def test_種類と金額の範囲(client: Client) -> None:
    _tx(date(2026, 10, 1), 100, description="安い")
    _tx(date(2026, 10, 2), 5000, description="高い")
    _tx(date(2026, 10, 3), 250000, kind="income", category="給与", description="給料")
    html = _search(client, kind="expense", amount_min="1000")
    assert "高い" in html and "安い" not in html and "給料" not in html


def test_期間の前後の誤り(client: Client) -> None:
    html = _search(client, date_from="2026-12-31", date_until="2026-01-01")
    assert "終了日は開始日以降の日付にしてください。" in html  # MSG-E08


def test_検索の初期値は過去1年(client: Client) -> None:
    html = client.get("/transactions/search/").content.decode()
    assert 'name="date_until"' in html and "条件に合う明細はありません。" in html


def test_50件ずつ表示する(client: Client) -> None:
    for i in range(55):
        _tx(date(2026, 10, 1), i + 1, description=f"明細{i + 1}")
    html = _search(client)
    assert "55件" in html and html.count('class="row"') == 50 and "さらに表示" in html
    assert "page=2" in html
    more = client.get(
        "/transactions/search/",
        {"date_from": "2026-01-01", "date_until": "2026-12-31", "page": "2"},
        headers={"HX-Request": "true"},
    ).content.decode()
    assert more.count('class="row"') == 5 and "さらに表示" not in more
    assert "<html" not in more  # 次の 50 件の部分だけを返す
