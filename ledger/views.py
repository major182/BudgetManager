"""家計簿（SC-01）と明細入力（SC-02）。"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.choices import AmountInputType, TransactionKind
from core.dates import month_label
from core.models import AppSettings
from core.periods import holidays_between, month_containing, month_period
from ledger import entry, queries, services
from ledger.forms import BaseLineFormSet, LineFormSet, SearchForm, TransactionForm
from ledger.models import Transaction
from ledger.tax import LineInput, calculate
from masters.models import TaxRate

MSG_I01 = "登録しました"
MSG_I02 = "保存しました"
MSG_I03 = "削除しました"


def _ledger(request: HttpRequest, view: str, month: date, extra: dict[str, Any]) -> HttpResponse:
    """家計簿の3つの表示に共通の部分（見出し・合計・タブ。画面設計書 4.1）。"""
    settings = AppSettings.load()
    today = services.today()
    current = month_containing(today, settings).month
    if view == "monthly":
        prev_url = reverse("ledger:monthly", kwargs={"year": month.year - 1})
        next_url = reverse("ledger:monthly", kwargs={"year": month.year + 1})
        label = f"{month.year}年"
        is_current = month.year == current.year
    else:
        prev_month, next_month = queries.neighbors(month)
        prev_url = reverse(f"ledger:{view}", kwargs={"year_month": prev_month})
        next_url = reverse(f"ledger:{view}", kwargs={"year_month": next_month})
        label = month_label(month)
        is_current = month == current
    context = {
        "menu": "ledger",
        "view": view,
        "month": month,
        "label": label,
        "prev_url": prev_url,
        "next_url": next_url,
        "current_url": reverse(f"ledger:{view}", kwargs={"year": current.year})
        if view == "monthly"
        else reverse(f"ledger:{view}", kwargs={"year_month": current}),
        "is_current": is_current,
        "tabs": [
            ("daily", "日別", reverse("ledger:daily", kwargs={"year_month": month})),
            ("calendar", "カレンダー", reverse("ledger:calendar", kwargs={"year_month": month})),
            ("monthly", "月別", reverse("ledger:monthly", kwargs={"year": month.year})),
        ],
        **extra,
    }
    return render(request, f"ledger/{view}.html", context)


def daily(request: HttpRequest, year_month: date) -> HttpResponse:
    """SC-01 家計簿（日別。F-LS-01・04）。"""
    period = month_period(year_month)
    transactions = list(queries.with_details(queries.in_period(period)))
    holidays = holidays_between(period.start, period.end)
    return _ledger(
        request,
        "daily",
        year_month,
        {
            "period": period,
            "totals": queries.totals(queries.in_period(period)),
            "days": queries.group_by_day(transactions, holidays),
        },
    )


def calendar(request: HttpRequest, year_month: date) -> HttpResponse:
    """SC-01 家計簿（カレンダー。F-LS-02）。日付を選ぶと、その日の明細を下に出す。"""
    settings = AppSettings.load()
    period = month_period(year_month, settings)
    today = services.today()
    selected = _parse_date(request.GET.get("date")) or (
        today if period.start <= today <= period.end else period.start
    )
    day_transactions = list(queries.with_details(Transaction.objects.filter(date=selected)))
    return _ledger(
        request,
        "calendar",
        year_month,
        {
            "period": period,
            "totals": queries.totals(queries.in_period(period)),
            "weeks": queries.calendar_weeks(period, settings),
            "weekday_labels": queries.weekday_labels(settings),
            "selected": selected,
            "today": today,
            "day": queries.group_by_day(day_transactions, holidays_between(selected, selected)),
        },
    )


def monthly(request: HttpRequest, year: int) -> HttpResponse:
    """SC-01 家計簿（月別。F-LS-03）。"""
    rows = queries.months_of_year(year, AppSettings.load())
    return _ledger(
        request,
        "monthly",
        date(year, 1, 1),
        {"rows": rows, "totals": queries.year_totals(rows)},
    )


def jump(request: HttpRequest) -> HttpResponse:
    """年月を選んで移る（F-LS-05）。?month=2026-10"""
    try:
        year, month = (int(x) for x in request.GET.get("month", "").split("-"))
        target = date(year, month, 1)
    except ValueError:
        target = month_containing(services.today()).month
    view = request.GET.get("view", "daily")
    if view not in ("daily", "calendar"):
        view = "daily"
    return redirect(f"ledger:{view}", year_month=target)


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def search(request: HttpRequest) -> HttpResponse:
    """SC-03 検索（F-LS-06）。条件は URL に残す（戻ったときに同じ結果を出すため）。"""
    today = services.today()
    # 期間の初期値は過去1年（今日の1年前の翌日〜今日）。2/29 の1年前は 2/28 として扱う
    a_year_ago = today - timedelta(days=366 if today.month == 2 and today.day == 29 else 365)
    defaults = {"date_from": a_year_ago + timedelta(days=1), "date_until": today}
    if request.GET:
        form = SearchForm(request.GET)
    else:
        form = SearchForm({key: value.isoformat() for key, value in defaults.items()})

    page_param = request.GET.get("page", "1")
    page = int(page_param) if page_param.isdigit() and int(page_param) > 0 else 1
    results: list[Transaction] = []
    total = queries.Totals()
    count = 0
    if form.is_valid():
        found = queries.search(form.cleaned_data)
        count = found.count()
        total = queries.totals(found)
        size = queries.SEARCH_PAGE
        results = list(queries.with_details(found)[(page - 1) * size : page * size])
    dates = [tx.date for tx in results]
    holidays = holidays_between(min(dates), max(dates)) if dates else set()
    # 「さらに表示」の URL は、今の条件にページ番号だけを付け替える
    query = request.GET.copy()
    query.pop("page", None)
    context = {
        "menu": "ledger",
        "form": form,
        "days": queries.group_by_day(results, holidays),
        "count": count,
        "totals": total,
        "next_page": page + 1 if page * queries.SEARCH_PAGE < count else None,
        "query": query,
    }
    # 「さらに表示」は、次の 50 件の部分だけを返す
    if request.headers.get("HX-Request") and request.GET.get("page"):
        return render(request, "ledger/_search_results.html", context)
    return render(request, "ledger/search.html", context)


# ---------------------------------------------------------------- SC-02 明細入力


def _forms(
    data: Any,
    instance: Transaction | None,
    initial: tuple[dict[str, Any], list[dict[str, Any]]] | None = None,
) -> tuple[TransactionForm, BaseLineFormSet]:
    """見出しのフォームと内訳のフォームセットを作る。

    data があれば送られた内容で、なければ初期値（initial）で作る。
    """
    kind = (data.get("kind") if data is not None else None) or (
        initial[0]["kind"] if initial else "expense"
    )
    settings = AppSettings.load()
    line_kwargs = {
        "kind": kind,
        "keep_categories": services.categories_used(instance),
        "keep_rates": services.tax_rates_used(instance) | {settings.default_tax_rate_id or 0},
    }
    if data is not None:
        form = TransactionForm(data, keep_assets=services.assets_used(instance))
        # LineFormSet が作るのは BaseLineFormSet（forms.py）なので、その型として扱う
        lines = cast(
            BaseLineFormSet, LineFormSet(data, prefix=entry.PREFIX, form_kwargs=line_kwargs)
        )
        lines.input_type = data.get("amount_input_type") or AmountInputType.TAX_INCLUDED
        lines.rounding = settings.tax_rounding
    else:
        if initial is None:
            raise ValueError("送られた内容（data）か初期値（initial）のどちらかが必要です")
        form = TransactionForm(initial=initial[0], keep_assets=services.assets_used(instance))
        lines = cast(
            BaseLineFormSet,
            LineFormSet(initial=initial[1], prefix=entry.PREFIX, form_kwargs=line_kwargs),
        )
    return form, lines


def _render(
    request: HttpRequest,
    form: TransactionForm,
    lines: Any,
    instance: Transaction | None,
    action: str,
    in_modal: bool,
    show_errors: bool,
) -> HttpResponse:
    template = "ledger/_entry.html" if request.headers.get("HX-Request") else "ledger/entry.html"
    return render(
        request,
        template,
        {
            "menu": "ledger",
            "form": form,
            "lines": lines,
            "instance": instance,
            "action": action,
            "in_modal": in_modal,
            "show_errors": show_errors,
            # 画面設計書 4.2 のとおり、支出のタブを先にする（初期値も支出）
            "kinds": [
                (TransactionKind.EXPENSE, "支出"),
                (TransactionKind.INCOME, "収入"),
                (TransactionKind.TRANSFER, "振替"),
            ],
            "kind": form.kind_value,
            "tax": _tax_table(form.data if form.is_bound else None, form, lines),
        },
    )


def _tax_table(data: Any, form: TransactionForm, lines: Any) -> Any:
    """税額の表の中身（DB 設計書 5.6 と同じ計算）。入力の途中の値は読める行だけで計算する。"""
    if data is None:
        input_type = form.initial.get("amount_input_type")
        rows = [(f.initial.get("tax_rate"), f.initial.get("amount")) for f in lines.forms]
    else:
        input_type = data.get("amount_input_type")
        rows = [
            (data.get(f"{entry.PREFIX}-{i}-tax_rate"), data.get(f"{entry.PREFIX}-{i}-amount"))
            for i in range(len(lines.forms))
        ]
    rates = {r.pk: r.rate for r in TaxRate.objects.all()}
    inputs = []
    for rate_id, amount in rows:
        try:
            value = int(str(amount).replace(",", ""))
            rate = rates[int(rate_id)]
        except ValueError, TypeError, KeyError, InvalidOperation:
            continue
        if value:
            inputs.append(LineInput(value, Decimal(rate)))
    # プラスとマイナスが混ざっていると計算できない（MSG-E12）ため、表は出さない
    if not inputs or len({i.amount > 0 for i in inputs}) > 1:
        return None
    return calculate(
        inputs, input_type or AmountInputType.TAX_INCLUDED, AppSettings.load().tax_rounding
    )


def _done(
    request: HttpRequest, message: str, tx: Transaction | None, in_modal: bool
) -> HttpResponse:
    """保存・削除の成功（画面設計書 1.7）。

    小窓なら開いている画面を読み直し、画面全体なら家計簿のその月へ移る。
    """
    messages.success(request, message)
    response = HttpResponse(status=204)
    if in_modal:
        response["HX-Refresh"] = "true"
    else:
        month = (tx.date if tx else services.today()).replace(day=1)
        response["HX-Redirect"] = reverse("ledger:daily", kwargs={"year_month": month})
    return response


def _entry(
    request: HttpRequest, instance: Transaction | None, copy_from: Transaction | None = None
) -> HttpResponse:
    """新規・編集・コピーに共通の処理。"""
    if instance is not None:
        action = reverse("ledger:edit", kwargs={"pk": instance.pk})
    else:
        action = reverse("ledger:new")
    in_modal = request.GET.get("modal") == "1" or request.POST.get("_modal") == "1"

    if request.method != "POST":
        source = instance or copy_from
        initial = entry.initial(
            source,
            copy=copy_from is not None,
            kind=request.GET.get("kind"),
            date=request.GET.get("date"),
        )
        form, lines = _forms(None, instance, initial)
        return _render(request, form, lines, instance, action, in_modal, show_errors=False)

    command = request.POST.get("_action", "save")
    if command != "save":
        data = entry.apply_action(request.POST, command)
        form, lines = _forms(data, instance)
        return _render(request, form, lines, instance, action, in_modal, show_errors=False)

    form, lines = _forms(request.POST, instance)
    is_transfer = request.POST.get("kind") == TransactionKind.TRANSFER
    if form.is_valid() and (is_transfer or lines.is_valid()):
        line_data = (
            []
            if is_transfer
            else [
                services.LineData(
                    f.cleaned_data["category"], f.cleaned_data["tax_rate"], f.cleaned_data["amount"]
                )
                for f in lines.forms
            ]
        )
        tx = services.save(form.cleaned_data, line_data, instance=instance)
        return _done(request, MSG_I02 if instance else MSG_I01, tx, in_modal)
    if not is_transfer:
        lines.is_valid()  # 見出しに誤りがあっても、内訳の誤りも一緒に表示する
    return _render(request, form, lines, instance, action, in_modal, show_errors=True)


def new(request: HttpRequest) -> HttpResponse:
    """SC-02 明細の登録。"""
    return _entry(request, None)


def edit(request: HttpRequest, pk: int) -> HttpResponse:
    """SC-02 明細の編集。"""
    tx = get_object_or_404(Transaction, pk=pk)
    return _entry(request, tx)


def copy(request: HttpRequest, pk: int) -> HttpResponse:
    """SC-02 明細のコピー：この明細の内容で新規の入力画面を開く（F-TX-04、BR-15）。"""
    source = get_object_or_404(Transaction, pk=pk)
    return _entry(request, None, copy_from=source)


@require_POST
def delete(request: HttpRequest, pk: int) -> HttpResponse:
    """明細の削除（F-TX-03）。確認は画面のダイアログで行う（MSG-C01）。"""
    tx = get_object_or_404(Transaction, pk=pk)
    tx.delete()
    return _done(request, MSG_I03, tx, request.POST.get("_modal") == "1")


@require_POST
def tax_table(request: HttpRequest) -> HttpResponse:
    """入力中の税額の表だけを返す（F-TX-08。htmx が入力のたびに呼ぶ）。"""
    form, lines = _forms(request.POST, None)
    return render(request, "ledger/_tax_table.html", {"tax": _tax_table(request.POST, form, lines)})


def suggest(request: HttpRequest) -> HttpResponse:
    """入力の補完の候補（F-TX-05）。"""
    kind = request.GET.get("kind", TransactionKind.EXPENSE)
    candidates = services.suggestions(kind, request.GET.get("description", ""))
    return render(request, "ledger/_suggest.html", {"candidates": candidates})
