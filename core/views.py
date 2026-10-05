"""トップと設定のメニュー（画面設計書 3章・4.8）。"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone


def top(request: HttpRequest) -> HttpResponse:
    """トップは今月の家計簿（日別）へ移る。"""
    today = timezone.localdate()
    return redirect("ledger:daily", year_month=today.replace(day=1))


def settings_menu(request: HttpRequest) -> HttpResponse:
    """SC-08 設定。"""
    return render(request, "core/settings_menu.html", {"menu": "settings"})
