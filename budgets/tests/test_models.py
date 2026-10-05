"""予算・月別予算の制約のテスト（テスト仕様書 2.5）。"""

from collections.abc import Callable
from datetime import date

import pytest
from django.db import IntegrityError, transaction

from budgets.models import Budget, MonthlyBudget
from masters.models import Category

pytestmark = pytest.mark.django_db


def _raises_integrity(create: Callable[[], object]) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        create()


def test_予算は分類ごとに1つで月別予算は月の1日() -> None:
    food = Category.objects.get(kind="expense", name="食費")
    budget = Budget.objects.create(category=food, base_amount=30000)
    _raises_integrity(lambda: Budget.objects.create(category=food, base_amount=1))
    _raises_integrity(lambda: Budget.objects.create(category=None, base_amount=-1))
    MonthlyBudget.objects.create(budget=budget, year_month=date(2026, 12, 1), amount=40000)
    _raises_integrity(
        lambda: MonthlyBudget.objects.create(budget=budget, year_month=date(2026, 11, 2), amount=1)
    )
    _raises_integrity(
        lambda: MonthlyBudget.objects.create(budget=budget, year_month=date(2026, 12, 1), amount=1)
    )
