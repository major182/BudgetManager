"""明細と明細の内訳（DB 設計書 4.6・4.7）。

明細の amount は、収入・支出では内訳の税込額の合計、振替では振替額（DB 設計書 3.1）。
内訳との合計の一致は、保存をサービス層の1つの処理にまとめて守る。
"""

from django.db import models
from django.db.models import F, Q

from core.choices import AMOUNT_MAX, AmountInputType, TransactionKind
from core.models import TimeStampedModel


class Transaction(TimeStampedModel):
    """明細（収入・支出・振替）。"""

    class Source(models.TextChoices):
        MANUAL = "manual", "手入力"
        RECURRING = "recurring", "定期収支"
        CSV = "csv", "CSV 取り込み"

    kind = models.CharField("種類", max_length=10, choices=TransactionKind)
    date = models.DateField("日付")
    asset = models.ForeignKey(
        "masters.Asset", verbose_name="資産", on_delete=models.PROTECT, related_name="transactions"
    )
    transfer_to_asset = models.ForeignKey(
        "masters.Asset",
        verbose_name="振替先の資産",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_transfers",
    )
    amount = models.BigIntegerField("金額")
    # 振替では「空（NULL）」にする（DB 設計書 4.6・4.10）。
    # CHECK 制約で NULL かどうかを判定するため、
    # Django の慣習（文字列の列は空文字で表す）ではなく NULL を使う
    amount_input_type = models.CharField(  # noqa: DJ001
        "金額の入力", max_length=20, choices=AmountInputType, null=True, blank=True
    )
    description = models.CharField("内容", max_length=100, blank=True, default="")
    memo = models.CharField("メモ", max_length=500, blank=True, default="")
    source = models.CharField("登録元", max_length=10, choices=Source, default=Source.MANUAL)

    class Meta:
        db_table = "transactions"
        verbose_name = "明細"
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=TransactionKind.values), name="transactions_kind_valid"
            ),
            # BR-03：±99,999,999 の範囲で 0 は不可
            models.CheckConstraint(
                condition=Q(amount__gte=-AMOUNT_MAX, amount__lte=AMOUNT_MAX) & ~Q(amount=0),
                name="transactions_amount_range",
            ),
            # BR-03・BR-12：マイナスは支出だけ
            models.CheckConstraint(
                condition=Q(kind=TransactionKind.EXPENSE) | Q(amount__gt=0),
                name="transactions_amount_negative_only_expense",
            ),
            # 振替は税込・税抜の区別を持たず、振替先を必ず持つ。収入・支出はその逆
            models.CheckConstraint(
                condition=(
                    Q(
                        kind=TransactionKind.TRANSFER,
                        amount_input_type__isnull=True,
                        transfer_to_asset__isnull=False,
                    )
                    | (
                        ~Q(kind=TransactionKind.TRANSFER)
                        & Q(amount_input_type__isnull=False, transfer_to_asset__isnull=True)
                    )
                ),
                name="transactions_transfer_fields",
            ),
            # BR-13：振替の出金元と入金先は別の資産
            models.CheckConstraint(
                condition=Q(transfer_to_asset__isnull=True) | ~Q(asset=F("transfer_to_asset")),
                name="transactions_transfer_different_assets",
            ),
        ]
        indexes = [
            models.Index(fields=["date"], name="transactions_date_idx"),
            models.Index(fields=["asset", "date"], name="transactions_asset_date_idx"),
            models.Index(fields=["transfer_to_asset", "date"], name="transactions_to_date_idx"),
            models.Index(fields=["description"], name="transactions_desc_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.date} {self.get_kind_display()} {self.amount}"


class TransactionLine(TimeStampedModel):
    """明細の内訳。分類と税率の組み合わせごとの金額（BR-80）。"""

    transaction = models.ForeignKey(
        Transaction, verbose_name="明細", on_delete=models.CASCADE, related_name="lines"
    )
    category = models.ForeignKey(
        "masters.Category",
        verbose_name="分類",
        on_delete=models.PROTECT,
        related_name="transaction_lines",
    )
    tax_rate = models.ForeignKey(
        "masters.TaxRate",
        verbose_name="税率",
        on_delete=models.PROTECT,
        related_name="transaction_lines",
    )
    # 登録時点の税率の値。マスタの税率を変えても、登録済みの明細の金額は変わらない（BR-76）
    tax_rate_value = models.DecimalField("税率の値", max_digits=4, decimal_places=1)
    amount_excl = models.BigIntegerField("税抜額")
    tax_amount = models.BigIntegerField("消費税額")
    amount_incl = models.BigIntegerField("税込額")
    sort_order = models.IntegerField("表示順", default=0)

    class Meta:
        db_table = "transaction_lines"
        verbose_name = "明細の内訳"
        ordering = ["sort_order", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_incl=F("amount_excl") + F("tax_amount")),
                name="transaction_lines_amount_sum",
            ),
            models.CheckConstraint(
                condition=Q(tax_rate_value__gte=0, tax_rate_value__lte=100),
                name="transaction_lines_tax_rate_value_range",
            ),
        ]
        indexes = [models.Index(fields=["category"], name="transaction_lines_category_idx")]
