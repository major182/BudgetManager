"""
URL の割り当て（画面設計書 3章）。

管理画面（/admin/）はログインがないため登録しない（技術選定書 7.2 S-06）。
"""

from django.urls import include, path, register_converter

from core.converters import YearConverter, YearMonthConverter

# URL の中の `2026-10` を、その月の1日の日付として受け取る
register_converter(YearMonthConverter, "ym")
register_converter(YearConverter, "yr")

urlpatterns = [
    path("", include("core.urls")),
    path("", include("ledger.urls")),
    path("", include("reports.urls")),
    path("", include("masters.urls")),
]
