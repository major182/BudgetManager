"""予算の保存（BR-50・51、画面設計書 4.12）。"""

from datetime import date

from django.db import transaction

from budgets.forms import WHOLE
from budgets.models import Budget, MonthlyBudget
from core.choices import CategoryKind
from masters.models import Category


def budget_rows() -> list[tuple[str, str, Budget | None]]:
    """予算の欄の並び：全体、支出の大分類（並び順）。非表示の大分類は、予算がある場合だけ下に出す。"""
    budgets = {b.category_id: b for b in Budget.objects.all()}
    rows: list[tuple[str, str, Budget | None]] = [(WHOLE, "全体", budgets.get(None))]
    tops = list(
        Category.objects.filter(kind=CategoryKind.EXPENSE, parent__isnull=True).order_by(
            "sort_order", "id"
        )
    )
    rows += [(str(c.pk), c.name, budgets.get(c.pk)) for c in tops if not c.is_hidden]
    rows += [
        (str(c.pk), f"{c.name}（非表示）", budgets[c.pk])
        for c in tops
        if c.is_hidden and c.pk in budgets
    ]
    return rows


def _category(key: str) -> Category | None:
    return None if key == WHOLE else Category.objects.get(pk=int(key))


@transaction.atomic
def save_base(values: dict[str, int | None]) -> None:
    """基本額を保存する。空欄の予算は削除する（月ごとの額も一緒に消える）。"""
    budgets = {b.category_id: b for b in Budget.objects.all()}
    for key, amount in values.items():
        category = _category(key)
        budget = budgets.get(category.pk if category else None)
        if amount is None:
            if budget is not None:
                budget.delete()
        elif budget is None:
            Budget.objects.create(category=category, base_amount=amount)
        elif budget.base_amount != amount:
            budget.base_amount = amount
            budget.save(update_fields=["base_amount", "updated_at"])


@transaction.atomic
def save_month(month: date, values: dict[str, int | None]) -> None:
    """その月の額を保存する。空欄は月ごとの額を消し、基本額を使う状態に戻す（BR-51）。

    月ごとの額は、基本額のある予算だけに設定できる（画面設計書 4.12）。基本額のない欄は無視する。
    """
    budgets = {b.category_id: b for b in Budget.objects.all()}
    for key, amount in values.items():
        category = _category(key)
        budget = budgets.get(category.pk if category else None)
        if budget is None:
            continue
        if amount is None:
            MonthlyBudget.objects.filter(budget=budget, year_month=month).delete()
        else:
            MonthlyBudget.objects.update_or_create(
                budget=budget, year_month=month, defaults={"amount": amount}
            )
