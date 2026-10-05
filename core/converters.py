"""URL の中の年月・年を、日付として受け取るための変換（画面設計書 3章）。"""

from datetime import date


class YearMonthConverter:
    """`2026-10` の形の年月を、その月の1日の date にする。"""

    regex = r"[0-9]{4}-(0[1-9]|1[0-2])"

    def to_python(self, value: str) -> date:
        year, month = value.split("-")
        return date(int(year), int(month), 1)

    def to_url(self, value: date) -> str:
        return f"{value.year:04d}-{value.month:02d}"


class YearConverter:
    """`2026` の形の年。"""

    regex = r"[0-9]{4}"

    def to_python(self, value: str) -> int:
        return int(value)

    def to_url(self, value: int) -> str:
        return f"{value:04d}"
