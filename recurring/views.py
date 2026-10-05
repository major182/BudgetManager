"""SC-12 定期収支管理（画面設計書 4.13）。追加・編集は入力の小窓で行う。"""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import AppSettings
from masters.models import Category
from recurring.forms import RecurringItemForm
from recurring.models import RecurringItem
from recurring.services import next_date

MSG_I01 = "登録しました"
MSG_I02 = "保存しました"
MSG_I03 = "削除しました"


def items(request: HttpRequest) -> HttpResponse:
    """定期収支の一覧と、次回の登録予定日（F-RC-02）。"""
    today = timezone.localdate()
    rows = [
        {"item": item, "next": next_date(item, today)}
        for item in RecurringItem.objects.select_related(
            "asset", "transfer_to_asset", "category"
        ).order_by("id")
    ]
    return render(request, "recurring/items.html", {"menu": "settings", "rows": rows})


def _done(request: HttpRequest, message: str) -> HttpResponse:
    messages.success(request, message)
    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse("recurring:items")
    return response


def _modal(
    request: HttpRequest, form: RecurringItemForm, item: RecurringItem | None
) -> HttpResponse:
    today = timezone.localdate()
    settings = AppSettings.load()
    action = reverse("recurring:edit", kwargs={"pk": item.pk}) if item else reverse("recurring:new")
    start = form["start_date"].value()
    return render(
        request,
        "recurring/_modal.html",
        {
            "form": form,
            "item": item,
            "action": action,
            # 分類を選んだときに、その分類の既定の税率にするための対応表（BR-78・79）
            "default_rates": {
                str(c.pk): str(c.default_tax_rate_id or settings.default_tax_rate_id or "")
                for c in Category.objects.all()
            },
            # 開始日を過去にした場合の注意（MSG-W01）
            "past_start": bool(start) and str(start) < today.isoformat() and item is None,
        },
    )


def new(request: HttpRequest) -> HttpResponse:
    """定期収支の追加（F-RC-01）。"""
    settings = AppSettings.load()
    if request.method == "POST":
        form = RecurringItemForm(request.POST)
        if form.is_valid():
            form.save()
            return _done(request, MSG_I01)
    else:
        form = RecurringItemForm(
            initial={
                "kind": "expense",
                "frequency": "monthly",
                "start_date": timezone.localdate(),
                "amount_input_type": settings.default_amount_input_type,
            }
        )
    return _modal(request, form, None)


def edit(request: HttpRequest, pk: int) -> HttpResponse:
    """定期収支の編集（F-RC-01）。"""
    item = get_object_or_404(RecurringItem, pk=pk)
    form = RecurringItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        return _done(request, MSG_I02)
    return _modal(request, form, item)


@require_POST
def delete(request: HttpRequest, pk: int) -> HttpResponse:
    """定期収支の削除。登録済みの明細は消えない（MSG-C03）。"""
    get_object_or_404(RecurringItem, pk=pk).delete()
    return _done(request, MSG_I03)


@require_POST
def preview(request: HttpRequest) -> HttpResponse:
    """入力中の内容から、次回の登録予定日を表示する（画面設計書 4.13）。保存はしない。"""
    form = RecurringItemForm(request.POST)
    when = None
    if form.is_valid():
        item = form.save(commit=False)
        item.created_at = timezone.now()  # これから登録する定期収支として計算する
        when = next_date(item, timezone.localdate())
    return render(request, "recurring/_preview.html", {"when": when, "valid": form.is_valid()})
