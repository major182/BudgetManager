"""統計（SC-04）と資産（SC-06）。Issue 2 では骨組みだけを作る。"""

from datetime import date, timedelta

from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.choices import TransactionKind
from core.dates import add_months, month_label
from core.models import AppSettings
from core.periods import month_containing, month_period
from ledger.models import Transaction
from masters.models import Asset, AssetGroup, Category

# 集計のモジュール。画面の関数 stats と名前がぶつからないよう、別の名前で読み込む
from reports import stats as aggregates
from reports.balances import balance, balances, summary, upcoming_bills


def stats_current(request: HttpRequest) -> HttpResponse:
    """メニューの「統計」は今月の統計へ移る。"""
    return redirect("reports:stats", year_month=month_containing(timezone.localdate()).month)


PIE_TOP = 8  # 円グラフで色を分ける分類の数。残りは「その他」にまとめる（画面設計書 4.4）


def _stats(request: HttpRequest, *, month: date | None, year: int) -> HttpResponse:
    """SC-04 統計（F-ST-01〜03・06、F-BG-03）。月と年で共通。"""
    settings = AppSettings.load()
    kind = request.GET.get("kind", TransactionKind.EXPENSE)
    if kind not in (TransactionKind.EXPENSE, TransactionKind.INCOME):
        kind = TransactionKind.EXPENSE
    if month is not None:
        span = aggregates.month_range(month, settings)
        prev_url = reverse("reports:stats", kwargs={"year_month": add_months(month, -1)})
        next_url = reverse("reports:stats", kwargs={"year_month": add_months(month, 1)})
        label = month_label(month)
    else:
        span = aggregates.year_range(year, settings)
        prev_url = reverse("reports:stats_year", kwargs={"year": year - 1})
        next_url = reverse("reports:stats_year", kwargs={"year": year + 1})
        label = f"{year}年"
    rows = aggregates.by_category(kind, span)
    other = sum(r.amount for r in rows[PIE_TOP:])
    pie = {
        "labels": [r.category.name for r in rows[:PIE_TOP]] + (["その他"] if other else []),
        "values": [r.amount for r in rows[:PIE_TOP]] + ([other] if other else []),
    }
    trend_month = month or month_containing(timezone.localdate(), settings).month
    return render(
        request,
        "reports/stats.html",
        {
            "menu": "stats",
            "kind": kind,
            "unit": "month" if month else "year",
            "label": label,
            "prev_url": prev_url,
            "next_url": next_url,
            "month_url": reverse("reports:stats", kwargs={"year_month": trend_month}),
            "year_url": reverse(
                "reports:stats_year", kwargs={"year": (month or date(year, 1, 1)).year}
            ),
            "span": span,
            # 月の開始日が1日以外のときだけ、見出しの下に期間を出す（画面設計書 1.3）
            "show_range": settings.month_start_day != 1,
            "income": sum(r.amount for r in aggregates.by_category(TransactionKind.INCOME, span)),
            "expense": sum(r.amount for r in aggregates.by_category(TransactionKind.EXPENSE, span)),
            "rows": [
                {
                    "row": r,
                    "color": index if index < PIE_TOP else PIE_TOP,
                    "subs": aggregates.subcategories(r.category, kind, span),
                }
                for index, r in enumerate(rows)
            ],
            "pie": pie,
            "taxes": aggregates.tax_by_rate(kind, span),
            # 予算は月単位なので、月・支出のときだけ出す（画面設計書 4.4）
            "budgets": aggregates.budget_statuses(month, settings)
            if month and kind == TransactionKind.EXPENSE
            else None,
            "trend_month": trend_month,
        },
    )


def stats(request: HttpRequest, year_month: date) -> HttpResponse:
    """SC-04 統計（月）。"""
    return _stats(request, month=year_month, year=year_month.year)


def stats_year(request: HttpRequest, year: int) -> HttpResponse:
    """SC-04 統計（年）。"""
    return _stats(request, month=None, year=year)


def _trend_month(request: HttpRequest) -> date:
    """推移の最後の月（?month=2026-10）。なければ今日を含む月。"""
    try:
        y, m = (int(x) for x in request.GET.get("month", "").split("-"))
        return date(y, m, 1)
    except ValueError:
        return month_containing(timezone.localdate()).month


def trend_category(request: HttpRequest, pk: int) -> HttpResponse:
    """SC-05 分類の推移（F-ST-04）。表示中の月を最後とする 12 か月。"""
    category = get_object_or_404(Category, pk=pk, parent__isnull=True)
    end = _trend_month(request)
    periods = aggregates.last_12_months(end, AppSettings.load())
    values = aggregates.category_trend(category, periods)
    labels = [f"{p.month.month}月" for p in periods]
    return render(
        request,
        "reports/trend_category.html",
        {
            "menu": "stats",
            "category": category,
            "periods": periods,
            "chart": {"labels": labels, "values": values},
            "table": list(zip(reversed(periods), reversed(values), strict=True)),
            "average": round(sum(values) / len(values)),
            "maximum": max(values),
            "prev_url": f"?month={add_months(end, -1):%Y-%m}",
            "next_url": f"?month={add_months(end, 1):%Y-%m}",
            "back_url": reverse("reports:stats", kwargs={"year_month": end})
            + f"?kind={category.kind}",
        },
    )


def trend_assets(request: HttpRequest) -> HttpResponse:
    """SC-05 資産の推移（F-ST-05）。各月の終了日の残高。全体か、1つの資産を選べる。"""
    end = _trend_month(request)
    periods = aggregates.last_12_months(end, AppSettings.load())
    selected = request.GET.get("asset", "")
    asset_id = (
        int(selected)
        if selected.isdigit() and Asset.objects.filter(pk=int(selected)).exists()
        else None
    )
    trend = aggregates.asset_trend(periods, asset_id)
    labels = [f"{p.month.month}月" for p in periods]
    month_param = f"{end:%Y-%m}"
    return render(
        request,
        "reports/trend_assets.html",
        {
            "menu": "assets",
            "assets": Asset.objects.order_by("asset_group__sort_order", "sort_order", "id"),
            "asset_id": asset_id,
            "chart": {"labels": labels, **trend},
            "rows": [
                {"period": p, **{key: values[i] for key, values in trend.items()}}
                for i, p in reversed(list(enumerate(periods)))
            ],
            "periods": periods,
            "month_param": month_param,
            "prev_url": f"?month={add_months(end, -1):%Y-%m}&asset={selected}",
            "next_url": f"?month={add_months(end, 1):%Y-%m}&asset={selected}",
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
