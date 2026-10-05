"""定期収支の入力フォーム（SC-12、画面設計書 4.13）。"""

from typing import Any

from django import forms
from django.db.models import Q

from core.choices import AMOUNT_MAX, TransactionKind
from core.forms import MSG_E01, StyledFormMixin, range_error
from ledger.forms import MSG_E13, MSG_E14
from masters.models import Asset, Category, TaxRate
from recurring.models import RecurringItem

MSG_E08 = "終了日は開始日以降の日付にしてください。"
WEEKDAYS = [
    (0, "月曜"),
    (1, "火曜"),
    (2, "水曜"),
    (3, "木曜"),
    (4, "金曜"),
    (5, "土曜"),
    (6, "日曜"),
]


class RecurringItemForm(StyledFormMixin, forms.ModelForm[RecurringItem]):
    """種類・周期によって使う項目が変わる。

    使わない項目は保存しない（DB 設計書 4.10 の CHECK に合わせる）。
    """

    day_of_month = forms.TypedChoiceField(
        label="日",
        choices=[(d, f"{d}日") for d in range(1, 32)],
        coerce=int,
        required=False,
        initial=25,
    )
    weekday = forms.TypedChoiceField(
        label="曜日", choices=WEEKDAYS, coerce=int, required=False, initial=0
    )
    month = forms.TypedChoiceField(
        label="月",
        choices=[(m, f"{m}月") for m in range(1, 13)],
        coerce=int,
        required=False,
        initial=1,
    )

    class Meta:
        model = RecurringItem
        fields = [
            "kind",
            "asset",
            "transfer_to_asset",
            "category",
            "tax_rate",
            "amount_input_type",
            "amount",
            "description",
            "memo",
            "frequency",
            "day_of_month",
            "weekday",
            "month",
            "holiday_rule",
            "start_date",
            "end_date",
        ]
        labels = {
            "kind": "種類",
            "asset": "資産",
            "transfer_to_asset": "入金先",
            "category": "分類",
            "tax_rate": "税率",
            "amount_input_type": "金額の入力",
            "amount": "金額",
            "description": "内容",
            "memo": "メモ",
            "frequency": "周期",
            "holiday_rule": "土日祝日の扱い",
            "start_date": "開始日",
            "end_date": "終了日",
        }
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        keep_assets = {
            pk for pk in (self.instance.asset_id, self.instance.transfer_to_asset_id) if pk
        }
        assets = Asset.objects.filter(Q(is_hidden=False) | Q(pk__in=keep_assets)).order_by(
            "asset_group__sort_order", "sort_order", "id"
        )
        for name in ("asset", "transfer_to_asset"):
            field: Any = self.fields[name]
            field.queryset = assets
            field.empty_label = "選んでください"
        category: Any = self.fields["category"]
        category.queryset = Category.objects.filter(
            Q(is_hidden=False) | Q(pk=self.instance.category_id or 0)
        ).order_by("-kind", "sort_order", "id")
        category.empty_label = "選んでください"
        # 収入用・支出用を区別して出す。どちらの分類かは保存のときに確かめる（BR-30）
        category.label_from_instance = lambda c: f"{'支出' if c.kind == 'expense' else '収入'}：{c}"
        rate: Any = self.fields["tax_rate"]
        rate.queryset = TaxRate.objects.filter(
            Q(is_hidden=False) | Q(pk=self.instance.tax_rate_id or 0)
        )
        rate.empty_label = "選んでください"
        holiday_rule: Any = self.fields["holiday_rule"]
        holiday_rule.choices = [
            ("none", "そのまま"),
            ("previous", "前営業日"),
            ("next", "後営業日"),
        ]
        self.fields["amount"].widget.attrs.update({"class": "input amount", "inputmode": "numeric"})
        self.fields["amount"].error_messages["min_value"] = range_error(
            "金額", 1, f"{AMOUNT_MAX:,}"
        )

    def _require(self, cleaned: dict[str, Any], names: list[str]) -> None:
        for name in names:
            if cleaned.get(name) in (None, ""):
                self.add_error(name, MSG_E01.format(label=self.fields[name].label))

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        kind = cleaned.get("kind")
        amount = cleaned.get("amount")
        if amount is not None and not 1 <= amount <= AMOUNT_MAX:
            # 定期収支ではマイナス支出を扱わない（DB 設計書 4.10）
            self.add_error("amount", range_error("金額", 1, f"{AMOUNT_MAX:,}"))

        if kind == TransactionKind.TRANSFER:
            self._require(cleaned, ["transfer_to_asset"])
            if cleaned.get("transfer_to_asset") and cleaned.get("transfer_to_asset") == cleaned.get(
                "asset"
            ):
                self.add_error("transfer_to_asset", MSG_E13)
            for name in ("category", "tax_rate", "amount_input_type"):
                cleaned[name] = None
        else:
            self._require(cleaned, ["category", "tax_rate", "amount_input_type"])
            cleaned["transfer_to_asset"] = None
            category = cleaned.get("category")
            if category is not None and category.kind != kind:
                label = TransactionKind(kind).label if kind else ""
                self.add_error("category", MSG_E14.format(kind=label))

        # 周期に応じて、使う項目だけを残す（BR-61）
        frequency = cleaned.get("frequency")
        needs = {
            "monthly": ["day_of_month"],
            "month_end": [],
            "weekly": ["weekday"],
            "yearly": ["month", "day_of_month"],
        }.get(str(frequency), [])
        self._require(cleaned, needs)
        for name in ("day_of_month", "weekday", "month"):
            if name not in needs:
                cleaned[name] = None

        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", MSG_E08)
        return cleaned
