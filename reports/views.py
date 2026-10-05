"""統計（SC-04）と資産（SC-06）。Issue 2 では骨組みだけを作る。"""

from datetime import date

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from core.dates import add_months, month_label


def stats_current(request: HttpRequest) -> HttpResponse:
    """メニューの「統計」は今月の統計へ移る。"""
    return redirect("reports:stats", year_month=timezone.localdate().replace(day=1))


def stats(request: HttpRequest, year_month: date) -> HttpResponse:
    """SC-04 統計。"""
    return render(
        request,
        "reports/stats.html",
        {
            "menu": "stats",
            "label": month_label(year_month),
            "prev_url": reverse("reports:stats", kwargs={"year_month": add_months(year_month, -1)}),
            "next_url": reverse("reports:stats", kwargs={"year_month": add_months(year_month, 1)}),
        },
    )


def assets(request: HttpRequest) -> HttpResponse:
    """SC-06 資産。"""
    return render(request, "reports/assets.html", {"menu": "assets"})
