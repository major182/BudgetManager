"""SC-11 予算設定（画面設計書 4.12）。"""

from datetime import date

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from budgets import services
from budgets.forms import BudgetAmountsForm
from budgets.models import MonthlyBudget
from core.dates import add_months, month_label
from core.periods import month_containing

MSG_I02 = "保存しました"


def _month(request: HttpRequest) -> date:
    """月ごとの額を表示する月（?month=2026-12）。なければ今日を含む月。"""
    try:
        year, month = (int(x) for x in request.GET.get("month", "").split("-"))
        return date(year, month, 1)
    except ValueError:
        return month_containing(timezone.localdate()).month


def budget_settings(request: HttpRequest) -> HttpResponse:
    """基本額（全体・大分類ごと）と、月ごとの額を設定する（F-BG-01・02）。"""
    month = _month(request)
    rows = services.budget_rows()
    keys = [(key, label) for key, label, _ in rows]
    with_base = [(key, label) for key, label, budget in rows if budget is not None]
    base_initial = {key: budget.base_amount for key, _, budget in rows if budget is not None}
    monthly = dict(
        MonthlyBudget.objects.filter(year_month=month).values_list("budget_id", "amount")
    )
    month_initial = {
        key: monthly[budget.pk] for key, _, budget in rows if budget and budget.pk in monthly
    }

    base_form = BudgetAmountsForm(rows=keys, initial=base_initial, prefix="base")
    month_form = BudgetAmountsForm(rows=with_base, initial=month_initial, prefix="month")
    here = f"{reverse('budgets:settings')}?month={month:%Y-%m}"

    if request.method == "POST":
        target = request.POST.get("_form")
        if target == "base":
            base_form = BudgetAmountsForm(request.POST, rows=keys, prefix="base")
            if base_form.is_valid():
                services.save_base(base_form.cleaned_data)
                messages.success(request, MSG_I02)
                return redirect(here)
        elif target == "month":
            reset = request.POST.get("_reset")
            data = request.POST.copy()
            if reset:
                data[f"month-{reset}"] = ""  # 「基本額に戻す」：その月の額を消す
            month_form = BudgetAmountsForm(data, rows=with_base, prefix="month")
            if month_form.is_valid():
                services.save_month(month, month_form.cleaned_data)
                messages.success(request, MSG_I02)
                return redirect(here)

    # 月ごとの欄：欄・基本額（空欄のときに薄く出す）・その月の額があるか（「基本額に戻す」を出すか）
    base_by_key = {key: budget.base_amount for key, _, budget in rows if budget is not None}
    month_rows = [
        {
            "field": month_form[key],
            "base": base_by_key[key],
            "has_value": month_form[key].value() not in (None, ""),
        }
        for key, _ in with_base
    ]
    return render(
        request,
        "budgets/settings.html",
        {
            "menu": "settings",
            "base_form": base_form,
            "month_form": month_form,
            "month_rows": month_rows,
            "month": month,
            "month_label": month_label(month),
            "prev_month": add_months(month, -1),
            "next_month": add_months(month, 1),
        },
    )
