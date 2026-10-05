"""設定と祝日（DB 設計書 4.1・4.12）、全テーブル共通の列。"""

from django.db import models
from django.db.models import Q

from core.choices import AmountInputType, HolidayRule


class TimeStampedModel(models.Model):
    """作成日時・更新日時を持つ。

    不具合の調査で「いつ登録・変更されたか」を追えるようにする（DB 設計書 1.3）。
    """

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        abstract = True


class AppSettings(TimeStampedModel):
    """設定。利用者が1人なので1行だけを持ち、id は常に 1（DB 設計書 4.1）。"""

    class CurrencySymbol(models.TextChoices):
        YEN_SIGN = "yen_sign", "¥"
        YEN_TEXT = "yen_text", "円"
        NONE = "none", "なし"

    class WeekStart(models.TextChoices):
        SUNDAY = "sunday", "日曜"
        MONDAY = "monday", "月曜"

    class Theme(models.TextChoices):
        LIGHT = "light", "ライト"
        DARK = "dark", "ダーク"
        SYSTEM = "system", "端末に合わせる"

    class TaxRounding(models.TextChoices):
        FLOOR = "floor", "切り捨て"
        ROUND_HALF_UP = "round_half_up", "四捨五入"
        CEILING = "ceiling", "切り上げ"

    # MySQL は自動採番の列を CHECK 制約で参照できないため、id は自動採番にせず常に 1 を入れる
    id = models.SmallIntegerField("ID", primary_key=True, default=1, editable=False)
    currency_symbol = models.CharField(
        "通貨記号", max_length=10, choices=CurrencySymbol, default=CurrencySymbol.YEN_SIGN
    )
    use_thousands_separator = models.BooleanField("桁区切り", default=True)
    month_start_day = models.SmallIntegerField("月の開始日", default=1)  # 0 は月末（BR-20）
    month_start_holiday_rule = models.CharField(
        "開始日が土日祝日のとき", max_length=10, choices=HolidayRule, default=HolidayRule.NONE
    )
    week_start = models.CharField(
        "週の開始曜日", max_length=10, choices=WeekStart, default=WeekStart.SUNDAY
    )
    theme = models.CharField("テーマ", max_length=10, choices=Theme, default=Theme.SYSTEM)
    tax_rounding = models.CharField(
        "消費税の端数処理", max_length=20, choices=TaxRounding, default=TaxRounding.FLOOR
    )
    default_tax_rate = models.ForeignKey(
        "masters.TaxRate",
        verbose_name="既定の税率",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    default_amount_input_type = models.CharField(
        "金額の入力の初期値",
        max_length=20,
        choices=AmountInputType,
        default=AmountInputType.TAX_INCLUDED,
    )

    class Meta:
        db_table = "app_settings"
        verbose_name = "設定"
        constraints = [
            # 2行目を作らせない
            models.CheckConstraint(condition=Q(id=1), name="app_settings_single_row"),
            models.CheckConstraint(
                condition=Q(month_start_day__gte=0, month_start_day__lte=30),
                name="app_settings_month_start_day_range",
            ),
        ]

    def __str__(self) -> str:
        return "設定"

    @classmethod
    def load(cls) -> AppSettings:
        """設定の1行を返す（初期データで作成済み）。"""
        return cls.objects.get(pk=1)


class Holiday(TimeStampedModel):
    """祝日。日付を主キーにする（DB 設計書 4.12）。年末年始はここに入れず、営業日の判定で扱う。"""

    date = models.DateField("日付", primary_key=True)
    name = models.CharField("祝日の名前", max_length=50)

    class Meta:
        db_table = "holidays"
        verbose_name = "祝日"
        ordering = ["date"]

    def __str__(self) -> str:
        return f"{self.date} {self.name}"
