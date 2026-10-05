"""管理コマンド（BT-01・BT-02）のテスト（テスト仕様書 5.2）。"""

from datetime import date
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from core.models import Holiday
from recurring.tests.test_services import _item

pytestmark = pytest.mark.django_db

CSV = (
    "国民の祝日・休日月日,国民の祝日・休日名称\r\n"
    "2026/1/1,元日\r\n"
    "2026/10/12,スポーツの日\r\n"
    "2026/11/23,勤労感謝の日\r\n"
)


def test_定期収支の自動登録のコマンド() -> None:
    _item()
    out = StringIO()
    call_command("register_recurring", "--date", "2026-02-26", stdout=out)
    assert "2 件を登録しました" in out.getvalue()


def test_祝日の取り込み(tmp_path: Path) -> None:
    file = tmp_path / "syukujitsu.csv"
    file.write_bytes(CSV.encode("cp932"))  # 内閣府の CSV は Shift_JIS
    Holiday.objects.create(date=date(2025, 1, 1), name="古い祝日")
    out = StringIO()
    call_command("import_holidays", "--file", str(file), stdout=out)
    assert "3 件の祝日を取り込みました" in out.getvalue()
    assert list(Holiday.objects.values_list("date", "name")) == [
        (date(2026, 1, 1), "元日"),
        (date(2026, 10, 12), "スポーツの日"),
        (date(2026, 11, 23), "勤労感謝の日"),
    ]
