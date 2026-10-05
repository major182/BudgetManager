"""定期収支と登録履歴（DB 設計書 4.10・4.11）。"""

from django.db import models
from django.db.models import F, Q

from core.choices import AMOUNT_MAX, AmountInputType, HolidayRule, TransactionKind
from core.models import TimeStampedModel


class RecurringItem(TimeStampedModel):
    """定期収支。内訳は1つだけ持つ（DB 設計書 D-5）。"""

    class Frequency(models.TextChoices):
        MONTHLY = "monthly", "毎月◯日"
        MONTH_END = "month_end", "毎月末"
        WEEKLY = "weekly", "毎週◯曜日"
        YEARLY = "yearly", "毎年◯月◯日"

    kind = models.CharField("種類", max_length=10, choices=TransactionKind)
    asset = models.ForeignKey(
        "masters.Asset",
        verbose_name="資産",
        on_delete=models.PROTECT,
        related_name="recurring_items",
    )
    transfer_to_asset = models.ForeignKey(
        "masters.Asset",
        verbose_name="振替先の資産",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_recurring_items",
    )
    category = models.ForeignKey(
        "masters.Category",
        verbose_name="分類",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recurring_items",
    )
    tax_rate = models.ForeignKey(
        "masters.TaxRate",
        verbose_name="税率",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recurring_items",
    )
    # 振替では「空（NULL）」にする（DB 設計書 4.6・4.10）。
    # CHECK 制約で NULL かどうかを判定するため、
    # Django の慣習（文字列の列は空文字で表す）ではなく NULL を使う
    amount_input_type = models.CharField(  # noqa: DJ001
        "金額の入力", max_length=20, choices=AmountInputType, null=True, blank=True
    )
    amount = models.BigIntegerField("金額")
    description = models.CharField("内容", max_length=100, blank=True, default="")
    memo = models.CharField("メモ", max_length=500, blank=True, default="")
    frequency = models.CharField("周期", max_length=10, choices=Frequency)
    day_of_month = models.SmallIntegerField(
        "日", null=True, blank=True
    )  # 1〜31。その月にない日は末日
    weekday = models.SmallIntegerField("曜日", null=True, blank=True)  # 0＝月曜〜6＝日曜
    month = models.SmallIntegerField("月", null=True, blank=True)
    holiday_rule = models.CharField(
        "土日祝日の扱い", max_length=10, choices=HolidayRule, default=HolidayRule.NONE
    )
    start_date = models.DateField("開始日")
    end_date = models.DateField("終了日", null=True, blank=True)

    class Meta:
        db_table = "recurring_items"
        verbose_name = "定期収支"
        ordering = ["id"]
        constraints = [
            # 周期に応じて必要な列だけが入る
            models.CheckConstraint(
                condition=(
                    Q(
                        frequency="monthly",
                        day_of_month__isnull=False,
                        weekday__isnull=True,
                        month__isnull=True,
                    )
                    | Q(
                        frequency="month_end",
                        day_of_month__isnull=True,
                        weekday__isnull=True,
                        month__isnull=True,
                    )
                    | Q(
                        frequency="weekly",
                        day_of_month__isnull=True,
                        weekday__isnull=False,
                        month__isnull=True,
                    )
                    | Q(
                        frequency="yearly",
                        day_of_month__isnull=False,
                        weekday__isnull=True,
                        month__isnull=False,
                    )
                ),
                name="recurring_items_frequency_fields",
            ),
            models.CheckConstraint(
                condition=Q(day_of_month__isnull=True)
                | Q(day_of_month__gte=1, day_of_month__lte=31),
                name="recurring_items_day_of_month_range",
            ),
            models.CheckConstraint(
                condition=Q(weekday__isnull=True) | Q(weekday__gte=0, weekday__lte=6),
                name="recurring_items_weekday_range",
            ),
            models.CheckConstraint(
                condition=Q(month__isnull=True) | Q(month__gte=1, month__lte=12),
                name="recurring_items_month_range",
            ),
            # 定期収支ではマイナス支出を扱わない（DB 設計書 4.10）
            models.CheckConstraint(
                condition=Q(amount__gte=1, amount__lte=AMOUNT_MAX),
                name="recurring_items_amount_range",
            ),
            models.CheckConstraint(
                condition=Q(end_date__isnull=True) | Q(end_date__gte=F("start_date")),
                name="recurring_items_end_after_start",
            ),
            # 振替は振替先だけを持ち、分類・税率・税込税抜を持たない。収入・支出はその逆
            models.CheckConstraint(
                condition=(
                    Q(
                        kind=TransactionKind.TRANSFER,
                        transfer_to_asset__isnull=False,
                        category__isnull=True,
                        tax_rate__isnull=True,
                        amount_input_type__isnull=True,
                    )
                    | (
                        ~Q(kind=TransactionKind.TRANSFER)
                        & Q(
                            transfer_to_asset__isnull=True,
                            category__isnull=False,
                            tax_rate__isnull=False,
                            amount_input_type__isnull=False,
                        )
                    )
                ),
                name="recurring_items_transfer_fields",
            ),
        ]


class RecurringRun(TimeStampedModel):
    """定期収支の各回を登録した記録。同じ回の二重登録を防ぐ（BR-64）。"""

    recurring_item = models.ForeignKey(
        RecurringItem, verbose_name="定期収支", on_delete=models.CASCADE, related_name="runs"
    )
    scheduled_date = models.DateField("本来の登録日")
    registered_date = models.DateField("登録した日付")
    # 自動登録された明細を利用者が削除しても履歴は残し、同じ回を再び登録しない（BR-65）
    transaction = models.ForeignKey(
        "ledger.Transaction",
        verbose_name="登録した明細",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "recurring_runs"
        verbose_name = "定期収支の登録履歴"
        constraints = [
            models.UniqueConstraint(
                fields=["recurring_item", "scheduled_date"], name="recurring_runs_unique_occurrence"
            ),
        ]
