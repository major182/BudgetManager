"""月の期間と営業日のテスト（テスト仕様書 3.3）。期待値は DB 設計書 5.1・5.2 の例。"""

from datetime import date

import pytest

from core.models import AppSettings, Holiday
from core.periods import day_in_month, is_business_day, month_containing, month_period

pytestmark = pytest.mark.django_db


def _settings(day: int, rule: str = "none") -> AppSettings:
    s = AppSettings.load()
    s.month_start_day = day
    s.month_start_holiday_rule = rule
    return s


def test_日の値を日付にする() -> None:
    assert day_in_month(2026, 2, 0) == date(2026, 2, 28)  # 月末
    assert day_in_month(2026, 2, 30) == date(2026, 2, 28)  # その月にない日は末日
    assert day_in_month(2028, 2, 29) == date(2028, 2, 29)  # うるう年は29日
    assert day_in_month(2026, 10, 25) == date(2026, 10, 25)


@pytest.mark.parametrize(
    ("day", "rule", "start", "end"),
    [
        (1, "none", date(2026, 10, 1), date(2026, 10, 31)),  # 開始日 1日
        (25, "none", date(2026, 9, 25), date(2026, 10, 24)),  # 開始日 25日
        (0, "none", date(2026, 9, 30), date(2026, 10, 30)),  # 開始日 月末
        # 開始日 25日・前の平日：2026-10-25 は日曜のため「11月」の開始日が 10/23（金）にずれる
        (25, "previous", date(2026, 9, 25), date(2026, 10, 22)),
    ],
)
def test_設計書の期間の表(day: int, rule: str, start: date, end: date) -> None:
    period = month_period(date(2026, 10, 1), _settings(day, rule))
    assert (period.start, period.end) == (start, end)


def test_開始日が祝日なら次の平日へ() -> None:
    # 2026-10-12（月）はスポーツの日。開始日 12日・次の平日 →「11月」は 10/13 から
    Holiday.objects.create(date=date(2026, 10, 12), name="スポーツの日")
    period = month_period(date(2026, 11, 1), _settings(12, "next"))
    assert period.start == date(2026, 10, 13)


def test_暦どおりの月かどうか() -> None:
    assert month_period(date(2026, 10, 1), _settings(1)).is_calendar_month
    assert not month_period(date(2026, 10, 1), _settings(25)).is_calendar_month


def test_その日を含む月() -> None:
    s = _settings(25)
    assert month_containing(date(2026, 10, 24), s).month == date(2026, 10, 1)
    assert month_containing(date(2026, 10, 25), s).month == date(2026, 11, 1)


def test_営業日は年末年始を除く() -> None:
    assert not is_business_day(date(2026, 12, 31), set())  # 木曜だが年末年始
    assert not is_business_day(date(2027, 1, 3), set())
    assert is_business_day(date(2027, 1, 4), set())  # 月曜
    assert not is_business_day(date(2026, 10, 24), set())  # 土曜
