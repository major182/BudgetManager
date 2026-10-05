"""明細入力のフォーム（画面設計書 4.2）。

明細の見出し（日付・資産・内容など）は TransactionForm、内訳の各行は LineForm で受け取る。
内訳は行数が変わるため、Django のフォームセット（同じ形のフォームを複数まとめる仕組み）で扱う。
"""

from decimal import Decimal
from typing import Any

from django import forms
from django.db.models import Q
from django.forms import BaseFormSet, formset_factory

from core.choices import AMOUNT_MAX, AmountInputType, TransactionKind
from core.forms import MSG_E01, StyledFormMixin, range_error
from ledger.tax import LineInput, calculate
from masters.models import Asset, Category, TaxRate

MAX_LINES = 20

MSG_E10 = "0円は登録できません。"
MSG_E11 = "マイナスの金額は、支出でだけ入力できます。"
MSG_E12 = "1件の明細の中で、プラスとマイナスの金額を混ぜることはできません。"
MSG_E13 = "出金元と入金先には、別の資産を選んでください。"
MSG_E14 = "{kind}の明細には、{kind}用の分類を選んでください。"
MSG_E15 = f"内訳は{MAX_LINES}行までです。"
MSG_E16 = "明細の金額の合計は −99,999,999〜99,999,999 円の範囲にしてください。"


def category_choices(kind: str, keep: set[int] | None = None) -> list[tuple[str, str]]:
    """分類の選択肢。大分類の下に、その小分類を「　└ 名前」で並べる（画面設計書 4.2）。

    非表示の分類は出さない。ただし編集中の明細が使っているもの（keep）は出す。
    """
    keep = keep or set()
    visible = Category.objects.filter(kind=kind).order_by("sort_order", "id")
    tops = [c for c in visible if c.parent_id is None and (not c.is_hidden or c.pk in keep)]
    choices = [("", "選んでください")]
    for top in tops:
        choices.append((str(top.pk), top.name))
        for child in visible:
            if child.parent_id == top.pk and (not child.is_hidden or child.pk in keep):
                choices.append((str(child.pk), f"　└ {child.name}"))
    return choices


def _visible_assets(keep: set[int]) -> Any:
    return Asset.objects.filter(Q(is_hidden=False) | Q(pk__in=keep)).order_by(
        "asset_group__sort_order", "sort_order", "id"
    )


class TransactionForm(StyledFormMixin, forms.Form):
    """明細の見出し。種類は画面のタブで切り替える（hidden で送る）。"""

    kind = forms.ChoiceField(choices=TransactionKind.choices, widget=forms.HiddenInput)
    date = forms.DateField(
        label="日付", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    asset = forms.ModelChoiceField(label="資産", queryset=Asset.objects.none(), empty_label=None)
    transfer_to_asset = forms.ModelChoiceField(
        label="入金先", queryset=Asset.objects.none(), required=False, empty_label=None
    )
    description = forms.CharField(label="内容", max_length=100, required=False)
    amount_input_type = forms.ChoiceField(
        label="金額の入力",
        choices=AmountInputType.choices,
        required=False,
        widget=forms.RadioSelect,
    )
    amount = forms.IntegerField(label="金額", required=False)  # 振替のときだけ使う
    memo = forms.CharField(label="メモ", max_length=500, required=False)

    def __init__(self, *args: Any, keep_assets: set[int] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        assets = _visible_assets(keep_assets or set())
        asset_field: Any = self.fields["asset"]
        asset_field.queryset = assets
        to_field: Any = self.fields["transfer_to_asset"]
        to_field.queryset = assets
        self.fields["description"].widget.attrs.update(
            {"autocomplete": "off", "placeholder": "例：スーパー"}
        )

    @property
    def kind_value(self) -> str:
        """表示中の種類（入力の誤りがあっても画面の切り替えに使う）。"""
        return str(self["kind"].value() or TransactionKind.EXPENSE)

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        if cleaned.get("kind") == TransactionKind.TRANSFER:
            self.fields["asset"].label = "出金元"
            to = cleaned.get("transfer_to_asset")
            amount = cleaned.get("amount")
            if to is None:
                self.add_error("transfer_to_asset", MSG_E01.format(label="入金先"))
            elif to == cleaned.get("asset"):
                self.add_error("transfer_to_asset", MSG_E13)
            if amount is None and "amount" not in self.errors:
                self.add_error("amount", MSG_E01.format(label="金額"))
            elif amount is not None and not 1 <= amount <= AMOUNT_MAX:
                # 振替はマイナスにできない（BR-03）
                message = MSG_E11 if amount < 0 else range_error("金額", 1, f"{AMOUNT_MAX:,}")
                self.add_error("amount", message)
        elif not cleaned.get("amount_input_type"):
            self.add_error("amount_input_type", MSG_E01.format(label="金額の入力"))
        return cleaned


class LineForm(StyledFormMixin, forms.Form):
    """内訳の1行：分類・税率・金額（BR-80）。"""

    category = forms.TypedChoiceField(label="分類", coerce=int)
    tax_rate = forms.ModelChoiceField(
        label="税率", queryset=TaxRate.objects.none(), empty_label=None
    )
    amount = forms.IntegerField(label="金額")

    def __init__(
        self,
        *args: Any,
        kind: str,
        keep_categories: set[int] | None = None,
        keep_rates: set[int] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.kind = kind
        category_field: Any = self.fields["category"]
        category_field.choices = category_choices(kind, keep_categories)
        rate_field: Any = self.fields["tax_rate"]
        rate_field.queryset = TaxRate.objects.filter(
            Q(is_hidden=False) | Q(pk__in=keep_rates or set())
        ).order_by("sort_order", "id")
        self.fields["amount"].widget.attrs.update({"class": "input amount", "placeholder": "0"})

    def clean_amount(self) -> int:
        amount: int = self.cleaned_data["amount"]
        if amount == 0:
            raise forms.ValidationError(MSG_E10)
        if abs(amount) > AMOUNT_MAX:
            raise forms.ValidationError(range_error("金額", f"−{AMOUNT_MAX:,}", f"{AMOUNT_MAX:,}"))
        return amount

    def clean_category(self) -> Category:
        category = Category.objects.get(pk=self.cleaned_data["category"])
        if category.kind != self.kind:  # BR-30（選択肢の外の値を送られた場合）
            label = TransactionKind(self.kind).label
            raise forms.ValidationError(MSG_E14.format(kind=label))
        return category


class BaseLineFormSet(BaseFormSet[LineForm]):
    """内訳の全体のチェック（画面設計書 4.2、DB 設計書 5.6）。"""

    # 行数の誤り（画面設計書 6.4）
    default_error_messages = {
        "too_many_forms": MSG_E15,
        "too_few_forms": "内訳を入力してください。",
        "missing_management_form": (
            "入力の内容が正しく送られませんでした。画面を開き直してください。"
        ),
    }
    input_type: str = AmountInputType.TAX_INCLUDED
    rounding: str = "floor"

    def clean(self) -> None:
        super().clean()
        if any(form.errors for form in self.forms):
            return  # 行ごとの誤りを先に直してもらう
        amounts = [form.cleaned_data["amount"] for form in self.forms if form.cleaned_data]
        kind = self.form_kwargs.get("kind")
        if any(a < 0 for a in amounts) and any(a > 0 for a in amounts):
            raise forms.ValidationError(MSG_E12)
        if kind != TransactionKind.EXPENSE and any(a < 0 for a in amounts):
            raise forms.ValidationError(MSG_E11)
        lines = [
            LineInput(form.cleaned_data["amount"], Decimal(form.cleaned_data["tax_rate"].rate))
            for form in self.forms
            if form.cleaned_data
        ]
        total = calculate(lines, self.input_type, self.rounding).total.incl
        if abs(total) > AMOUNT_MAX:
            raise forms.ValidationError(MSG_E16)


LineFormSet = formset_factory(
    LineForm,
    formset=BaseLineFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
    max_num=MAX_LINES,
    validate_max=True,
)
