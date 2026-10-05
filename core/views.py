"""トップと設定のメニュー（画面設計書 3章・4.8）。"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from core.periods import month_containing


def top(request: HttpRequest) -> HttpResponse:
    """トップは今月（今日を含む月。DB 設計書 5.2）の家計簿（日別）へ移る。"""
    return redirect("ledger:daily", year_month=month_containing(timezone.localdate()).month)


def settings_menu(request: HttpRequest) -> HttpResponse:
    """SC-08 設定。"""
    return render(request, "core/settings_menu.html", {"menu": "settings"})
