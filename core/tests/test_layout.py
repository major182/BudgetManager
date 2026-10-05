"""画面の骨組みのテスト（テスト仕様書 4.1）。"""

from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.utils import timezone

from core.models import AppSettings
from core.money import format_yen

pytestmark = pytest.mark.django_db

MENU_PAGES = [
    ("/ledger/daily/2026-10/", "家計簿"),
    ("/stats/2026-10/", "統計"),
    ("/assets/", "資産"),
    ("/settings/", "設定"),
]


def test_トップは今月の家計簿へ移る(client: Client) -> None:
    month = timezone.localdate().strftime("%Y-%m")
    response = client.get("/")
    assert response.status_code == 302
    assert response["Location"] == f"/ledger/daily/{month}/"


def test_統計のメニューは今月の統計へ移る(client: Client) -> None:
    month = timezone.localdate().strftime("%Y-%m")
    assert client.get("/stats/")["Location"] == f"/stats/{month}/"


@pytest.mark.parametrize(("url", "label"), MENU_PAGES)
def test_メニューの4画面が開き表示中の画面が強調される(
    client: Client, url: str, label: str
) -> None:
    html = client.get(url).content.decode()
    for _, name in MENU_PAGES:
        assert f"<span>{name}</span>" in html
    # 表示中の画面のメニューにだけ aria-current が付く
    assert html.count('aria-current="page"') == 1
    current = html.split('aria-current="page"')[1].split("</a>")[0]
    assert f"<span>{label}</span>" in current


def test_htmxの通信にCSRFトークンを付ける(client: Client) -> None:
    # 技術選定書 7.2 S-01
    html = client.get("/settings/").content.decode()
    assert 'hx-headers=\'{"X-CSRFToken": "' in html


def test_テーマは設定に従う(client: Client) -> None:
    assert 'data-theme="system"' in client.get("/settings/").content.decode()
    AppSettings.objects.filter(pk=1).update(theme="light")
    assert 'data-theme="light"' in client.get("/settings/").content.decode()


def test_年月の前後へ移るリンク(client: Client) -> None:
    html = client.get("/ledger/daily/2026-01/").content.decode()
    assert "2026年1月" in html
    assert 'href="/ledger/daily/2025-12/"' in html
    assert 'href="/ledger/daily/2026-02/"' in html


def test_存在しない年月は見つからない(client: Client) -> None:
    response = client.get("/ledger/daily/2026-13/")
    assert response.status_code == 404
    assert "ページが見つかりません。" in response.content.decode()


def test_htmxとChartjsはリポジトリから配信する() -> None:
    # 技術選定書 7.2 S-03：外部の配信サービスから読み込まない
    vendor = Path(settings.BASE_DIR) / "core" / "static" / "vendor"
    assert 'version:"2.0.11"' in (vendor / "htmx.min.js").read_text(encoding="utf-8")
    assert "Chart.js v4.5.1" in (vendor / "chart.umd.min.js").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("value", "symbol", "separator", "expected"),
    [
        (1234567, "yen_sign", True, "¥1,234,567"),
        (1234567, "yen_text", True, "1,234,567円"),
        (1234567, "none", False, "1234567"),
        (-500, "yen_sign", True, "¥500"),  # マイナスでも符号は付けない（画面設計書 1.3）
        (0, "yen_sign", True, "¥0"),
    ],
)
def test_金額の表示(value: int, symbol: str, separator: bool, expected: str) -> None:
    assert format_yen(value, symbol, separator) == expected
