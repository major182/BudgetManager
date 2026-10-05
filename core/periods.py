"""月の期間と営業日の計算（DB 設計書 5.1・5.2・5.8）。

「10月」の期間は、設定の月の開始日と休日の扱いで決まる。
例：開始日が25日なら「10月」は 9/25〜10/24（BR-20）。
"""

import calendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from core.choices import MONTH_END, HolidayRule
from core.dates import add_months
from core.models import AppSettings, Holiday


def day_in_month(year: int, month: int, day: int) -> date:
    """「日」の値（0＝月末、1〜31）を実際の日付にする（DB 設計書 5.1）。

    その月にない日（2月の30日など）は、その月の末日にする。
    """
    last = calendar.monthrange(year, month)[1]
    if day == MONTH_END or day > last:
        return date(year, month, last)
    return date(year, month, day)


def holidays_between(start: date, end: date) -> set[date]:
    """期間内の祝日（holidays テーブル）。"""
    return set(
        Holiday.objects.filter(date__gte=start, date__lte=end).values_list("date", flat=True)
    )


def is_weekday(day: date, holidays: set[date]) -> bool:
    """平日：土日・祝日以外の日（BR-21。月の開始日の調整に使う）。"""
    return day.weekday() < 5 and day not in holidays


def is_business_day(day: date, holidays: set[date]) -> bool:
    """営業日：土日・祝日・年末年始（12/31〜1/3）以外の日（BR-62。定期収支の調整に使う）。"""
    year_end = (day.month == 12 and day.day == 31) or (day.month == 1 and day.day <= 3)
    return is_weekday(day, holidays) and not year_end


def shift(day: date, rule: str, is_ok: Callable[[date], bool]) -> date:
    """日付が条件を満たさなければ、rule に従って前後にずらす（BR-21・BR-62）。"""
    if rule == HolidayRule.NONE:
        return day
    step = timedelta(days=-1 if rule == HolidayRule.PREVIOUS else 1)
    while not is_ok(day):
        day += step
    return day


@dataclass(frozen=True)
class MonthPeriod:
    """「◯月」の期間。month はその月の1日（見出しの年月）。"""

    month: date
    start: date
    end: date

    @property
    def is_calendar_month(self) -> bool:
        """暦どおり（1日〜末日）か。違うときだけ画面に期間を出す（画面設計書 1.3）。"""
        return self.start.day == 1 and self.end == day_in_month(
            self.end.year, self.end.month, MONTH_END
        )


def _start_of(month: date, settings: AppSettings, holidays: set[date]) -> date:
    """「month 月」の開始日（DB 設計書 5.2）。

    開始日が1日ならその月の1日、それ以外は前月の開始日。
    """
    if settings.month_start_day == 1:
        day = month
    else:
        prev = add_months(month, -1)
        day = day_in_month(prev.year, prev.month, settings.month_start_day)
    return shift(day, settings.month_start_holiday_rule, lambda d: is_weekday(d, holidays))


def month_period(month: date, settings: AppSettings | None = None) -> MonthPeriod:
    """「month 月」の期間。終了日は「翌月」の開始日の前日。"""
    settings = settings or AppSettings.load()
    month = month.replace(day=1)
    # 前後の月をまたいでずらすことがあるため、少し広めに祝日を読む
    holidays = holidays_between(add_months(month, -2), add_months(month, 2))
    start = _start_of(month, settings, holidays)
    end = _start_of(add_months(month, 1), settings, holidays) - timedelta(days=1)
    return MonthPeriod(month, start, end)


def month_containing(day: date, settings: AppSettings | None = None) -> MonthPeriod:
    """その日を含む「◯月」の期間（例：開始日 25日なら 10/26 は「11月」）。"""
    settings = settings or AppSettings.load()
    month = day.replace(day=1)
    for candidate in (add_months(month, 1), month, add_months(month, -1)):
        period = month_period(candidate, settings)
        if period.start <= day <= period.end:
            return period
    return month_period(month, settings)  # 設定上ここには来ない
