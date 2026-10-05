"""日付の計算の部品。"""

from datetime import date


def add_months(first_day: date, months: int) -> date:
    """月の1日に、months か月を足した月の1日を返す（マイナスなら前の月）。"""
    index = first_day.year * 12 + (first_day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def month_label(first_day: date) -> str:
    """見出し用の年月（画面設計書 1.3）。例：2026年10月"""
    return f"{first_day.year}年{first_day.month}月"
