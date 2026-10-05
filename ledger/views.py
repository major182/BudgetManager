"""家計簿（SC-01）と明細入力（SC-02）。"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.choices import AmountInputType, TransactionKind
from core.dates import add_months, month_label
from core.models import AppSettings
from ledger import entry, services
from ledger.forms import BaseLineFormSet, LineFormSet, TransactionForm
from ledger.models import Transaction
from ledger.tax import LineInput, calculate
from masters.models import TaxRate

MSG_I01 = "登録しました"
MSG_I02 = "保存しました"
MSG_I03 = "削除しました"


def daily(request: HttpRequest, year_month: date) -> HttpResponse:
    """SC-01 家計簿（日別）。明細の一覧は Issue 5 で実装する。"""
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
