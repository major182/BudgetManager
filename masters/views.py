"""マスタの設定画面（SC-09 分類・SC-10 資産・SC-14 表示設定・SC-15 税率）。

4種類のマスタは、追加・編集・削除・並べ替えの操作が同じ（画面設計書 4.9）。
共通の処理を1つにまとめ、マスタごとの違いは MasterConfig で渡す。

画面の動き（htmx）：
- 「追加」や行を押すと、入力の小窓の中身（_modal.html）を取得して小窓に入れる
- 入力に誤りがあれば、小窓の中身だけを誤りを付けて返す（入力した値は残る）
- 保存・削除が成功したら、HX-Redirect で一覧を開き直す（完了の知らせは messages で出す）
- ↑↓ は一覧の画面へリダイレクトし、htmx が一覧の部分だけを差し替える（hx-select）
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from django.contrib import messages
from django.db.models import Prefetch
from django.forms import ModelForm
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.choices import CategoryKind
from core.models import AppSettings
from masters import services
from masters.forms import AppSettingsForm, AssetForm, AssetGroupForm, CategoryForm, TaxRateForm
from masters.models import Asset, AssetGroup, Category, TaxRate
from masters.services import Master

MSG_I01 = "登録しました"
MSG_I02 = "保存しました"
MSG_I03 = "削除しました"


@dataclass(frozen=True)
class MasterConfig:
    """マスタごとの違い。"""

    model: type[Master]
    form: type[ModelForm[Any]]
    title: str  # 小窓の見出し（例：「税率」→「税率の追加」「税率の編集」）
    list_url: Callable[[Master | None, HttpRequest], str]  # 保存後に戻る一覧
    form_kwargs: Callable[[Master | None, HttpRequest], dict[str, Any]] = field(
        default=lambda obj, request: {}
    )
    initial: Callable[[HttpRequest], dict[str, Any]] = field(default=lambda request: {})


def _category_kind(obj: Master | None, request: HttpRequest) -> str:
    if isinstance(obj, Category):
        return obj.kind
    kind = request.GET.get("kind", CategoryKind.EXPENSE)
    if kind not in CategoryKind.values:
        raise Http404
    return kind


MASTERS: dict[str, MasterConfig] = {
    "tax-rates": MasterConfig(
        model=TaxRate,
        form=TaxRateForm,
        title="税率",
        list_url=lambda obj, request: reverse("masters:tax_rates"),
    ),
    "categories": MasterConfig(
        model=Category,
        form=CategoryForm,
        title="分類",
        list_url=lambda obj, request: (
            f"{reverse('masters:categories')}?kind={_category_kind(obj, request)}"
        ),
        form_kwargs=lambda obj, request: {"kind": _category_kind(obj, request)},
        # 「＋ 小分類を追加」は、その大分類を親にした状態で開く（画面設計書 4.10）
        initial=lambda request: {"parent": request.GET.get("parent")},
    ),
    "asset-groups": MasterConfig(
        model=AssetGroup,
        form=AssetGroupForm,
        title="資産グループ",
        list_url=lambda obj, request: reverse("masters:assets"),
    ),
    "assets": MasterConfig(
        model=Asset,
        form=AssetForm,
        title="資産",
        list_url=lambda obj, request: reverse("masters:assets"),
        initial=lambda request: {"asset_group": request.GET.get("group")},
    ),
}


def _get(config: MasterConfig, pk: int) -> Master:
    """マスタを1件取得する。なければ 404。"""
    # config.model は4種類のマスタのどれかなので、取得したものも Master として扱える
    return cast(Master, get_object_or_404(config.model, pk=pk))


def _config(kind: str) -> MasterConfig:
    if kind not in MASTERS:
        raise Http404
    return MASTERS[kind]


def _modal(
    request: HttpRequest,
    kind: str,
    form: ModelForm[Any],
    obj: Master | None,
    error: str = "",
) -> HttpResponse:
    """入力の小窓の中身。"""
    config = _config(kind)
    if obj is None:
        action = reverse("masters:new", kwargs={"kind": kind})
        if request.GET:
            action += f"?{request.GET.urlencode()}"
    else:
        action = reverse("masters:edit", kwargs={"kind": kind, "pk": obj.pk})
    return render(
        request,
        "masters/_modal.html",
        {
            "title": f"{config.title}の{'編集' if obj else '追加'}",
            "form": form,
            "obj": obj,
            "action": action,
            "delete_url": reverse("masters:delete", kwargs={"kind": kind, "pk": obj.pk})
            if obj
            else "",
            "error": error,
        },
    )


def _done(request: HttpRequest, message: str, url: str) -> HttpResponse:
    """保存・削除の成功：一覧を開き直し、完了の知らせを出す（画面設計書 1.6）。"""
    messages.success(request, message)
    response = HttpResponse(status=204)
    response["HX-Redirect"] = url
    return response


def new(request: HttpRequest, kind: str) -> HttpResponse:
    """追加の小窓（GET）と登録（POST）。"""
    config = _config(kind)
    kwargs = config.form_kwargs(None, request)
    if request.method == "POST":
        form = config.form(request.POST, **kwargs)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.sort_order = services.next_sort_order(services.siblings(obj))
            obj.save()
            return _done(request, MSG_I01, config.list_url(obj, request))
    else:
        form = config.form(initial=config.initial(request), **kwargs)
    return _modal(request, kind, form, None)


def edit(request: HttpRequest, kind: str, pk: int) -> HttpResponse:
    """編集の小窓（GET）と保存（POST）。"""
    config = _config(kind)
    obj = _get(config, pk)
    kwargs = config.form_kwargs(obj, request)
    if request.method == "POST":
        old_group = services.list_key(obj)
        form = config.form(request.POST, instance=obj, **kwargs)
        if form.is_valid():
            saved = form.save(commit=False)
            # 親の分類・資産グループを変えたら、移動先の一覧の最後に並べる
            if services.list_key(saved) != old_group:
                others = services.siblings(saved).exclude(pk=saved.pk)
                saved.sort_order = services.next_sort_order(others)
            saved.save()
            return _done(request, MSG_I02, config.list_url(saved, request))
    else:
        form = config.form(instance=obj, **kwargs)
    return _modal(request, kind, form, obj)


@require_POST
def delete(request: HttpRequest, kind: str, pk: int) -> HttpResponse:
    """削除。使われていれば削除せず、小窓に理由（MSG-E07）を出す。"""
    config = _config(kind)
    obj = _get(config, pk)
    url = config.list_url(obj, request)
    try:
        services.delete(obj)
    except services.InUseError as e:
        form = config.form(instance=obj, **config.form_kwargs(obj, request))
        return _modal(request, kind, form, obj, error=e.message)
    return _done(request, MSG_I03, url)


@require_POST
def move(request: HttpRequest, kind: str, pk: int, direction: str) -> HttpResponse:
    """↑↓ の並べ替え。一覧へ戻し、htmx が一覧の部分だけを差し替える。"""
    if direction not in ("up", "down"):
        raise Http404
    config = _config(kind)
    obj = _get(config, pk)
    services.move(obj, direction)
    return redirect(config.list_url(obj, request))


# ---------------------------------------------------------------- 一覧の画面


def tax_rates(request: HttpRequest) -> HttpResponse:
    """SC-15 税率管理。"""
    rates = TaxRate.objects.order_by("is_hidden", "sort_order", "id")
    return render(request, "masters/tax_rates.html", {"menu": "settings", "rates": rates})


def categories(request: HttpRequest) -> HttpResponse:
    """SC-09 分類管理。非表示の分類は一覧の下にまとめる（画面設計書 4.9）。"""
    kind = _category_kind(None, request)
    children = Category.objects.select_related("default_tax_rate").order_by("sort_order", "id")
    tops = (
        Category.objects.filter(kind=kind, parent__isnull=True)
        .select_related("default_tax_rate")
        .prefetch_related(Prefetch("children", queryset=children))
        .order_by("sort_order", "id")
    )
    return render(
        request,
        "masters/categories.html",
        {
            "menu": "settings",
            "kind": kind,
            # 画面設計書 4.10 のとおり、支出のタブを先にする
            "kinds": [(CategoryKind.EXPENSE, "支出"), (CategoryKind.INCOME, "収入")],
            "tops": [c for c in tops if not c.is_hidden],
            "hidden_tops": [c for c in tops if c.is_hidden],
            "default_rate": AppSettings.load().default_tax_rate,
        },
    )


def assets(request: HttpRequest) -> HttpResponse:
    """SC-10 資産管理。"""
    groups = AssetGroup.objects.prefetch_related(
        Prefetch(
            "assets",
            queryset=Asset.objects.select_related("payment_account").order_by("sort_order", "id"),
        )
    ).order_by("sort_order", "id")
    return render(request, "masters/assets.html", {"menu": "settings", "groups": groups})


def display(request: HttpRequest) -> HttpResponse:
    """SC-14 表示設定。保存した時点でテーマなどを画面に反映する（画面設計書 4.15）。"""
    settings = AppSettings.load()
    if request.method == "POST":
        form = AppSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            messages.success(request, MSG_I02)
            return redirect("masters:display")
    else:
        form = AppSettingsForm(instance=settings)
    return render(request, "masters/display.html", {"menu": "settings", "form": form})
