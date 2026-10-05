"""マスタの入力フォーム（画面設計書 4.10・4.11・4.16）。"""

from decimal import Decimal
from typing import Any

from django import forms

from core.choices import DAY_CHOICES
from core.forms import MSG_E06, StyledFormMixin, range_error
from core.models import AppSettings
from masters.models import Asset, AssetGroup, Category, TaxRate

MSG_E20 = "小分類の下には分類を作れません。親には大分類を選んでください。"
MSG_E21 = "小分類がある大分類は、ほかの分類の下に移動できません。"
MSG_E22 = "クレジットカードの引き落とし口座には、カード以外の資産を選んでください。"
MSG_E23 = "既定の税率に設定されている税率は、非表示にできません。"
MSG_E24 = "税率は 0〜100 の範囲で、小数第1位まで入力してください。"


class TaxRateForm(StyledFormMixin, forms.ModelForm[TaxRate]):
    """SC-15 税率。"""

    class Meta:
        model = TaxRate
        fields = ["name", "rate", "is_hidden"]
        labels = {"name": "名前", "rate": "税率（%）", "is_hidden": "非表示にする"}
        error_messages = {"name": {"unique": MSG_E06}}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["rate"].error_messages.update(
            {"invalid": MSG_E24, "max_decimal_places": MSG_E24}
        )
        self.fields["rate"].widget.attrs["inputmode"] = "decimal"

    def clean_rate(self) -> Decimal:
        rate: Decimal = self.cleaned_data["rate"]
        if not Decimal("0") <= rate <= Decimal("100"):
            raise forms.ValidationError(MSG_E24)
        return rate

    def clean_is_hidden(self) -> bool:
        hidden: bool = self.cleaned_data["is_hidden"]
        # 入力の初期値がなくなるため、設定の既定の税率は非表示にできない（画面設計書 4.16）
        if (
            hidden
            and self.instance.pk
            and AppSettings.load().default_tax_rate_id == self.instance.pk
        ):
            raise forms.ValidationError(MSG_E23)
        return hidden


class CategoryForm(StyledFormMixin, forms.ModelForm[Category]):
    """SC-09 分類。

    種類（収入用・支出用）は画面のタブで決まり、登録後は変えない（画面設計書 4.10）。
    """

    class Meta:
        model = Category
        fields = ["name", "parent", "default_tax_rate", "is_hidden"]
        labels = {
            "name": "名前",
            "parent": "親の分類",
            "default_tax_rate": "既定の税率",
            "is_hidden": "非表示にする",
        }

    def __init__(self, *args: Any, kind: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.kind = kind
        parents = Category.objects.filter(kind=kind, parent__isnull=True)
        if self.instance.pk:
            parents = parents.exclude(pk=self.instance.pk)
        parent_field: Any = self.fields["parent"]
        parent_field.queryset = parents
        parent_field.empty_label = "なし（大分類にする）"
        rate_field: Any = self.fields["default_tax_rate"]
        rate_field.queryset = TaxRate.objects.filter(is_hidden=False)
        rate_field.empty_label = "設定の既定値を使う"
        # 小分類を持つ大分類は移動できない（BR-32）。選べないことを画面でも示す
        if self.instance.pk and self.instance.children.exists():
            parent_field.disabled = True
            parent_field.help_text = MSG_E21

    def clean_parent(self) -> Category | None:
        parent: Category | None = self.cleaned_data["parent"]
        if parent is not None and parent.parent_id is not None:
            raise forms.ValidationError(MSG_E20)  # BR-31：2階層まで
        return parent

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        name = cleaned.get("name")
        # 同じ種類・同じ親の中で名前が重複しない（DB 設計書 4.3。NULL のため DB では守れない）
        same = Category.objects.filter(kind=self.kind, parent=cleaned.get("parent"), name=name)
        if self.instance.pk:
            same = same.exclude(pk=self.instance.pk)
        if name and same.exists():
            self.add_error("name", MSG_E06)
        return cleaned

    def save(self, commit: bool = True) -> Category:
        self.instance.kind = self.kind
        category: Category = super().save(commit)
        return category


class AssetGroupForm(StyledFormMixin, forms.ModelForm[AssetGroup]):
    """SC-10 資産グループ。"""

    class Meta:
        model = AssetGroup
        fields = ["name"]
        labels = {"name": "名前"}
        error_messages = {"name": {"unique": MSG_E06}}


class AssetForm(StyledFormMixin, forms.ModelForm[Asset]):
    """SC-10 資産。クレジットカードは締め日・引き落とし日などを持つ（BR-42・43）。"""

    closing_day = forms.TypedChoiceField(
        label="締め日", choices=DAY_CHOICES, coerce=int, required=False, initial=0
    )
    payment_month_offset = forms.TypedChoiceField(
        label="引き落とし月",
        choices=[(1, "翌月"), (2, "翌々月")],
        coerce=int,
        required=False,
        initial=1,
    )
    payment_day = forms.TypedChoiceField(
        label="引き落とし日", choices=DAY_CHOICES, coerce=int, required=False, initial=27
    )

    class Meta:
        model = Asset
        fields = [
            "name",
            "asset_group",
            "opening_balance",
            "is_credit_card",
            "closing_day",
            "payment_month_offset",
            "payment_day",
            "payment_account",
            "is_hidden",
        ]
        labels = {
            "name": "名前",
            "asset_group": "資産グループ",
            "opening_balance": "開始残高",
            "is_credit_card": "クレジットカード",
            "payment_account": "引き落とし口座",
            "is_hidden": "非表示にする",
        }
        error_messages = {"name": {"unique": MSG_E06}}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        group_field: Any = self.fields["asset_group"]
        group_field.empty_label = None
        accounts = Asset.objects.filter(is_credit_card=False)
        if self.instance.pk:
            accounts = accounts.exclude(pk=self.instance.pk)
        account_field: Any = self.fields["payment_account"]
        account_field.queryset = accounts
        account_field.empty_label = "選んでください"
        self.fields["opening_balance"].widget.attrs["inputmode"] = "numeric"

    def clean_opening_balance(self) -> int:
        value: int = self.cleaned_data["opening_balance"]
        if abs(value) > 99_999_999:
            raise forms.ValidationError(range_error("開始残高", "−99,999,999", "99,999,999"))
        return value

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        card_fields = ["closing_day", "payment_month_offset", "payment_day", "payment_account"]
        if cleaned.get("is_credit_card"):
            # カードなら4項目すべてが必要（BR-43）
            for name in card_fields:
                if cleaned.get(name) in (None, ""):
                    self.add_error(name, f"{self.fields[name].label}を入力してください。")
            account = cleaned.get("payment_account")
            if account is not None and account.is_credit_card:
                self.add_error("payment_account", MSG_E22)
        else:
            # カード以外はカードの項目を持たない（DB 設計書 4.5 の CHECK に合わせて空にする）
            for name in card_fields:
                cleaned[name] = None
        return cleaned


class AppSettingsForm(StyledFormMixin, forms.ModelForm[AppSettings]):
    """SC-14 表示設定。"""

    month_start_day = forms.TypedChoiceField(label="月の開始日", choices=DAY_CHOICES, coerce=int)

    class Meta:
        model = AppSettings
        fields = [
            "currency_symbol",
            "use_thousands_separator",
            "month_start_day",
            "month_start_holiday_rule",
            "week_start",
            "theme",
            "tax_rounding",
            "default_tax_rate",
            "default_amount_input_type",
        ]
        labels = {
            "currency_symbol": "通貨記号",
            "use_thousands_separator": "桁区切りを付ける",
            "month_start_holiday_rule": "開始日が土日祝日のとき",
            "week_start": "週の開始曜日",
            "theme": "テーマ",
            "tax_rounding": "消費税の端数処理",
            "default_tax_rate": "既定の税率",
            "default_amount_input_type": "金額の入力の初期値",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # 月の開始日の休日の扱いは「前の平日／次の平日」（BR-21）。
        # 定期収支の「営業日」とは言葉を分ける
        rule_field: Any = self.fields["month_start_holiday_rule"]
        rule_field.choices = [
            ("none", "そのまま"),
            ("previous", "前の平日"),
            ("next", "次の平日"),
        ]
        rate_field: Any = self.fields["default_tax_rate"]
        rate_field.queryset = TaxRate.objects.filter(is_hidden=False)
        rate_field.empty_label = None
        rate_field.required = True
