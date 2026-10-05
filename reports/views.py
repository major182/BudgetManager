"""統計（SC-04）と資産（SC-06）。Issue 2 では骨組みだけを作る。"""

from datetime import date, timedelta

from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.choices import TransactionKind
from core.dates import add_months, month_label
from core.periods import month_containing, month_period
from ledger.models import Transaction
from masters.models import Asset, AssetGroup
from reports.balances import balance, balances, summary, upcoming_bills


def stats_current(request: HttpRequest) -> HttpResponse:
    """メニューの「統計」は今月の統計へ移る。"""
    return redirect("reports:stats", year_month=month_containing(timezone.localdate()).month)


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
    """SC-06 資産（F-AS-03）。今日時点の残高を、資産グループごとに出す。"""
    today = timezone.localdate()
    show_hidden = request.GET.get("hidden") == "1"
    amounts = balances(today)
    all_assets = list(Asset.objects.select_related("asset_group").order_by("sort_order", "id"))
    groups = []
    for group in AssetGroup.objects.order_by("sort_order", "id"):
        members = [a for a in all_assets if a.asset_group_id == group.pk]
        rows = [
            {
                "asset": a,
                "balance": amounts.get(a.pk, 0),
                "bill": upcoming_bills(a, today, 1)[0] if a.is_credit_card else None,
            }
            for a in members
            if show_hidden or not a.is_hidden
        ]
        if rows:
            # 小計には非表示の資産も含める（お金としては存在するため。画面設計書 4.6）
            groups.append(
                {
                    "group": group,
                    "rows": rows,
                    "subtotal": sum(amounts.get(a.pk, 0) for a in members),
                }
            )
    return render(
        request,
        "reports/assets.html",
        {
            "menu": "assets",
            "groups": groups,
            "summary": summary(all_assets, amounts),
            "show_hidden": show_hidden,
            "has_hidden": any(a.is_hidden for a in all_assets),
        },
    )


def asset_current(request: HttpRequest, pk: int) -> HttpResponse:
    """資産詳細は、今日を含む月で開く。"""
    return redirect("reports:asset", pk=pk, year_month=month_containing(timezone.localdate()).month)


def asset(request: HttpRequest, pk: int, year_month: date) -> HttpResponse:
    """SC-07 資産詳細（F-AS-04・05）。期間内の明細と、各明細の後の残高。"""
    target = get_object_or_404(Asset, pk=pk)
    period = month_period(year_month)
    opening = balance(target, period.start - timedelta(days=1))
    transactions = (
        Transaction.objects.filter(Q(asset=target) | Q(transfer_to_asset=target))
        .filter(date__gte=period.start, date__lte=period.end)
        .select_related("asset", "transfer_to_asset")
        .prefetch_related("lines__category__parent")
        .order_by("date", "created_at", "id")
    )
    # 古い順に残高を積み上げ、画面には新しい順に出す
    rows = []
    running = opening
    money_in = money_out = 0
    for tx in transactions:
        delta = asset_delta(tx, target)
        running += delta
        if delta >= 0:
            money_in += delta
        else:
            money_out -= delta
        rows.append({"tx": tx, "delta": delta, "after": running})
    rows.reverse()
    today = timezone.localdate()
    return render(
        request,
        "reports/asset_detail.html",
        {
            "menu": "assets",
            "asset": target,
            "period": period,
            "label": month_label(year_month),
            "prev_url": reverse(
                "reports:asset", kwargs={"pk": pk, "year_month": add_months(year_month, -1)}
            ),
            "next_url": reverse(
                "reports:asset", kwargs={"pk": pk, "year_month": add_months(year_month, 1)}
            ),
            "opening": opening,
            "money_in": money_in,
            "money_out": money_out,
            "closing": running,
            "rows": rows,
            "bills": upcoming_bills(target, today) if target.is_credit_card else [],
        },
    )


def asset_delta(tx: Transaction, target: Asset) -> int:
    """その明細で、資産 target の残高がいくら増減したか（DB 設計書 5.3）。"""
    if tx.kind == TransactionKind.INCOME:
        return tx.amount
    if tx.kind == TransactionKind.EXPENSE:
        return -tx.amount
    return -tx.amount if tx.asset_id == target.pk else tx.amount
