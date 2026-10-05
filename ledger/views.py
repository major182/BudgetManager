"""家計簿（SC-01）。Issue 2 では骨組みだけを作り、明細の一覧は Issue 5 で実装する。"""

from datetime import date

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from core.dates import add_months, month_label


def daily(request: HttpRequest, year_month: date) -> HttpResponse:
    """SC-01 家計簿（日別）。"""
    return render(
        request,
        "ledger/daily.html",
        {
            "menu": "ledger",
            "label": month_label(year_month),
            "prev_url": reverse("ledger:daily", kwargs={"year_month": add_months(year_month, -1)}),
            "next_url": reverse("ledger:daily", kwargs={"year_month": add_months(year_month, 1)}),
        },
    )
