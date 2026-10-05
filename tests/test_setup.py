"""開発環境が意図どおりに設定されているかを確かめるテスト。"""

import pytest
from django.conf import settings
from django.db import connection
from django.test import Client


def test_日本語と日本時間で動く() -> None:
    # 要件定義書 BR-04：日付は日本時間で扱う
    assert settings.LANGUAGE_CODE == "ja"
    assert settings.TIME_ZONE == "Asia/Tokyo"


@pytest.mark.django_db
def test_mysql_84_に接続できる() -> None:
    # 技術選定書 5.6：本番の RDS と同じ MySQL 8.4 系で動かす
    with connection.cursor() as cursor:
        cursor.execute("SELECT VERSION()")
        (version,) = cursor.fetchone()
    assert connection.vendor == "mysql"
    assert version.startswith("8.4.")


# 404 の画面は設定（テーマ）を DB から読むため、DB を使う
@pytest.mark.django_db
def test_管理画面は公開しない(client: Client) -> None:
    # 技術選定書 7.2 S-06：ログインがないため /admin/ を登録しない
    response = client.get("/admin/")
    assert response.status_code == 404
