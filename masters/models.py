"""税率・分類・資産グループ・資産（DB 設計書 4.2〜4.5）。

外部キーはすべて「削除を禁止（PROTECT）」にする。使われているマスタはアプリの不具合があっても
消えないようにし、使われなくなったものは「非表示」で扱う（DB 設計書 D-4）。
"""

from django.db import models
from django.db.models import Q

from core.choices import CategoryKind
from core.models import TimeStampedModel


class TaxRate(TimeStampedModel):
    """税率（DB 設計書 4.2、BR-71）。"""

    name = models.CharField("名前", max_length=50, unique=True)
    rate = models.DecimalField("税率（%）", max_digits=4, decimal_places=1)
    is_hidden = models.BooleanField("非表示", default=False)
    sort_order = models.IntegerField("並び順", default=0)

    class Meta:
        db_table = "tax_rates"
        verbose_name = "税率"
        ordering = ["sort_order", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(rate__gte=0, rate__lte=100), name="tax_rates_rate_range"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Category(TimeStampedModel):
    """分類。parent が空なら大分類、入っていれば小分類（DB 設計書 4.3、BR-31）。

    同じ親の中での名前の重複・2階層までの制限は、MySQL の制約では守れないため
    アプリで守る（4.3 ※1）。
    """

    kind = models.CharField("種類", max_length=10, choices=CategoryKind)
    name = models.CharField("名前", max_length=50)
    parent = models.ForeignKey(
        "self",
        verbose_name="親の分類",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    default_tax_rate = models.ForeignKey(
        TaxRate,
        verbose_name="既定の税率",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    is_hidden = models.BooleanField("非表示", default=False)
    sort_order = models.IntegerField("並び順", default=0)

    class Meta:
        db_table = "categories"
        verbose_name = "分類"
        ordering = ["sort_order", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=CategoryKind.values), name="categories_kind_valid"
            ),
        ]
        indexes = [
            models.Index(fields=["kind", "parent", "sort_order"], name="categories_list_idx")
        ]

    def __str__(self) -> str:
        return f"{self.parent.name}／{self.name}" if self.parent_id and self.parent else self.name


class AssetGroup(TimeStampedModel):
    """資産グループ（DB 設計書 4.4）。"""

    name = models.CharField("名前", max_length=50, unique=True)
    sort_order = models.IntegerField("並び順", default=0)

    class Meta:
        db_table = "asset_groups"
        verbose_name = "資産グループ"
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.name


class Asset(TimeStampedModel):
    """資産。クレジットカードは負債として扱い、締め日などを持つ（DB 設計書 4.5、BR-40〜45）。

    「日」の列は 0 が月末、1〜30 が日付（DB 設計書 4.0）。
    """

    asset_group = models.ForeignKey(
        AssetGroup, verbose_name="資産グループ", on_delete=models.PROTECT, related_name="assets"
    )
    name = models.CharField("名前", max_length=50, unique=True)
    opening_balance = models.BigIntegerField("開始残高", default=0)
    is_credit_card = models.BooleanField("クレジットカード", default=False)
    closing_day = models.SmallIntegerField("締め日", null=True, blank=True)
    payment_month_offset = models.SmallIntegerField("引き落とし月", null=True, blank=True)
    payment_day = models.SmallIntegerField("引き落とし日", null=True, blank=True)
    payment_account = models.ForeignKey(
        "self",
        verbose_name="引き落とし口座",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="paid_cards",
    )
    is_hidden = models.BooleanField("非表示", default=False)
    sort_order = models.IntegerField("並び順", default=0)

    class Meta:
        db_table = "assets"
        verbose_name = "資産"
        ordering = ["sort_order", "id"]
        constraints = [
            # カードなら締め日・引き落とし月・引き落とし日・引き落とし口座がすべて入り、
            # カード以外ならすべて空
            models.CheckConstraint(
                condition=(
                    Q(
                        is_credit_card=True,
                        closing_day__isnull=False,
                        payment_month_offset__isnull=False,
                        payment_day__isnull=False,
                        payment_account__isnull=False,
                    )
                    | Q(
                        is_credit_card=False,
                        closing_day__isnull=True,
                        payment_month_offset__isnull=True,
                        payment_day__isnull=True,
                        payment_account__isnull=True,
                    )
                ),
                name="assets_card_fields",
            ),
            models.CheckConstraint(
                condition=Q(closing_day__isnull=True) | Q(closing_day__gte=0, closing_day__lte=30),
                name="assets_closing_day_range",
            ),
            models.CheckConstraint(
                condition=Q(payment_day__isnull=True) | Q(payment_day__gte=0, payment_day__lte=30),
                name="assets_payment_day_range",
            ),
            models.CheckConstraint(
                condition=Q(payment_month_offset__isnull=True) | Q(payment_month_offset__in=[1, 2]),
                name="assets_payment_month_offset_range",
            ),
        ]

    def __str__(self) -> str:
        return self.name
