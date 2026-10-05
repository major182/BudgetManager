"""統計・推移グラフ・予算設定の画面のテスト（テスト仕様書 4.7・4.8）。"""

import json
from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

from budgets.models import Budget, MonthlyBudget
from ledger import services
from masters.models import Asset, Category, TaxRate

pytestmark = pytest.mark.django_db


def _cat(name: str, kind: str = "expense") -> Category:
    return Category.objects.get(kind=kind, name=name)


def _tx(day: date, category: Category, rate: str, amount: int, kind: str = "expense") -> None:
    header = {
        "kind": kind,
        "date": day,
        "asset": Asset.objects.get(name="現金"),
        "amount_input_type": "tax_included",
    }
    services.save(
        header, [services.LineData(category, TaxRate.objects.get(rate=Decimal(rate)), amount)]
    )


@pytest.fixture
def october() -> None:
    eat_out = Category.objects.create(kind="expense", name="外食", parent=_cat("食費"))
    _tx(date(2026, 10, 2), _cat("食費"), "8", 3000)
    _tx(date(2026, 10, 3), eat_out, "10", 1000)
    _tx(date(2026, 10, 5), _cat("光熱費"), "10", 6000)
    _tx(date(2026, 10, 14), _cat("給与", "income"), "0", 250000, kind="income")


def _pie(html: str) -> dict[str, list[object]]:
    data = html.split('<script id="pie-data" type="application/json">')[1].split("</script>")[0]
    loaded: dict[str, list[object]] = json.loads(data)
    return loaded


@pytest.mark.usefixtures("october")
def test_統計の分類別と円グラフ(client: Client) -> None:
    html = client.get("/stats/2026-10/").content.decode()
    assert _pie(html) == {"labels": ["光熱費", "食費"], "values": [6000, 4000]}
    assert html.index("光熱費") < html.index("食費")  # 金額の大きい順
    assert "60%" in html and "40%" in html
    assert "└ 外食" in html and "└ 小分類なし" in html  # 小分類を開く（F-ST-02）
    assert 'href="/stats/trends/categories/' in html  # 推移を見る


@pytest.mark.usefixtures("october")
def test_収入のタブ(client: Client) -> None:
    html = client.get("/stats/2026-10/?kind=income").content.decode()
    assert _pie(html) == {"labels": ["給与"], "values": [250000]}
    assert "<h2>予算</h2>" not in html  # 予算は支出のときだけ


def test_上位8分類まで色を分け残りはその他(client: Client) -> None:
    names = [
        "食費",
        "備品・衣類",
        "交通費",
        "レジャー・趣味",
        "交際費",
        "通信費",
        "健康・医療",
        "光熱費",
        "保険",
        "税金",
    ]
    for i, name in enumerate(names):
        _tx(date(2026, 10, 1), _cat(name), "10", 1000 * (len(names) - i))
    labels = _pie(client.get("/stats/2026-10/").content.decode())["labels"]
    assert len(labels) == 9 and labels[-1] == "その他"


@pytest.mark.usefixtures("october")
def test_予算の消化状況(client: Client) -> None:
    Budget.objects.create(category=None, base_amount=150_000)
    Budget.objects.create(category=_cat("食費"), base_amount=3_000)
    html = client.get("/stats/2026-10/").content.decode()
    assert "¥10,000 / ¥150,000" in html and "残り ¥140,000" in html
    assert "¥4,000 / ¥3,000" in html and "超過 ¥1,000" in html  # 超過は赤（budget over）
    assert 'class="budget over"' in html


def test_予算がない場合(client: Client) -> None:
    html = client.get("/stats/2026-10/").content.decode()
    assert "予算が設定されていません。" in html and "予算を設定する" in html  # MSG-N03


@pytest.mark.usefixtures("october")
def test_年の統計と消費税(client: Client) -> None:
    html = client.get("/stats/year/2026/").content.decode()
    assert "2026年" in html and "<h2>予算</h2>" not in html  # 予算は月単位
    assert _pie(html)["values"] == [6000, 4000]
    # 消費税：8% は 3,000 円（税 222）、10% は 1,000＋6,000 円
    assert "<td>8%</td><td>2,778</td><td>222</td>" in html


@pytest.mark.usefixtures("october")
def test_分類の推移(client: Client) -> None:
    html = client.get(f"/stats/trends/categories/{_cat('食費').pk}/?month=2026-10").content.decode()
    data = json.loads(
        html.split('<script id="bar-data" type="application/json">')[1].split("</script>")[0]
    )
    assert len(data["values"]) == 12 and data["values"][-1] == 4000 and data["labels"][-1] == "10月"
    assert "2025年11月〜2026年10月" in html


@pytest.mark.usefixtures("october")
def test_資産の推移(client: Client) -> None:
    html = client.get("/stats/trends/assets/?month=2026-10").content.decode()
    data = json.loads(
        html.split('<script id="line-data" type="application/json">')[1].split("</script>")[0]
    )
    assert data["assets"][-1] == 250000 - 10000 and data["liabilities"][-1] == 0
    cash = Asset.objects.get(name="現金")
    html = client.get(f"/stats/trends/assets/?month=2026-10&asset={cash.pk}").content.decode()
    assert '"balance"' in html


# ---------------------------------------------------------------- 予算設定（SC-11）


def test_予算の基本額を保存する(client: Client) -> None:
    food = _cat("食費")
    response = client.post(
        "/settings/budgets/", {"_form": "base", "base-all": "150000", f"base-{food.pk}": "30000"}
    )
    assert response.status_code == 302
    assert Budget.objects.get(category=None).base_amount == 150000
    assert Budget.objects.get(category=food).base_amount == 30000
    # 空欄にすると予算を削除する（月ごとの額も消える）
    MonthlyBudget.objects.create(
        budget=Budget.objects.get(category=food), year_month=date(2026, 12, 1), amount=1
    )
    client.post(
        "/settings/budgets/", {"_form": "base", "base-all": "150000", f"base-{food.pk}": ""}
    )
    assert not Budget.objects.filter(category=food).exists() and not MonthlyBudget.objects.exists()


def test_予算額の誤り(client: Client) -> None:
    html = client.post("/settings/budgets/", {"_form": "base", "base-all": "-1"}).content.decode()
    assert "全体は0〜99,999,999の範囲で入力してください。" in html  # MSG-E04
    assert not Budget.objects.exists()


def test_月ごとの予算と基本額に戻す(client: Client) -> None:
    whole = Budget.objects.create(category=None, base_amount=150_000)
    url = "/settings/budgets/?month=2026-12"
    client.post(url, {"_form": "month", "month-all": "200000"})
    assert MonthlyBudget.objects.get(budget=whole, year_month=date(2026, 12, 1)).amount == 200000
    html = client.get(url).content.decode()
    assert 'value="200000"' in html and "基本額に戻す" in html
    client.post(url, {"_form": "month", "month-all": "200000", "_reset": "all"})
    assert not MonthlyBudget.objects.exists()


def test_月ごとの額は基本額のある予算だけ(client: Client) -> None:
    html = client.get("/settings/budgets/").content.decode()
    assert "基本額を設定すると、月ごとの額を変えられます。" in html
