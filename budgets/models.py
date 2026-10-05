"""予算と月別予算（DB 設計書 4.8・4.9）。"""

from django.db import models
from django.db.models import Q

from core.models import TimeStampedModel


class Budget(TimeStampedModel):
    """予算。category が空なら全体予算（BR-50）。

    全体予算が1つだけであることは、MySQL の一意制約が NULL どうしを同じ値とみなさないため、
    アプリで守る。
    """

    # 1つの分類に予算は1つ（DB 設計書 4.8 の UNIQUE）。Django では1対1の関係（OneToOneField）で表す
    category = models.OneToOneField(
        "masters.Category",
        verbose_name="分類",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="budget",
    )
    base_amount = models.BigIntegerField("基本額")

    class Meta:
        db_table = "budgets"
        verbose_name = "予算"
        constraints = [
            models.CheckConstraint(
                condition=Q(base_amount__gte=0), name="budgets_base_amount_non_negative"
            ),
        ]


class MonthlyBudget(TimeStampedModel):
    """特定の月だけ基本額から変えた予算額（BR-51）。year_month はその月の1日で表す。"""

    budget = models.ForeignKey(
        Budget, verbose_name="予算", on_delete=models.CASCADE, related_name="monthly"
    )
    year_month = models.DateField("対象の年月")
    amount = models.BigIntegerField("予算額")

    class Meta:
        db_table = "monthly_budgets"
        verbose_name = "月別予算"
        constraints = [
            models.UniqueConstraint(
                fields=["budget", "year_month"], name="monthly_budgets_unique_month"
            ),
            models.CheckConstraint(
                condition=Q(amount__gte=0), name="monthly_budgets_amount_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(year_month__day=1), name="monthly_budgets_first_day"
            ),
        ]
