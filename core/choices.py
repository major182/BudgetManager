"""複数の app で使う選択肢（DB 設計書 1.3：選択肢は英語の短い文字列で保存する）。"""

from django.db import models


class TransactionKind(models.TextChoices):
    """明細・定期収支の種類（BR-10）。"""

    INCOME = "income", "収入"
    EXPENSE = "expense", "支出"
    TRANSFER = "transfer", "振替"


class CategoryKind(models.TextChoices):
    """分類の種類。収入用と支出用に分かれる（BR-30）。"""

    INCOME = "income", "収入"
    EXPENSE = "expense", "支出"


class AmountInputType(models.TextChoices):
    """金額を税込・税抜のどちらで入力したか（BR-72）。"""

    TAX_INCLUDED = "tax_included", "税込"
    TAX_EXCLUDED = "tax_excluded", "税抜"


class HolidayRule(models.TextChoices):
    """日付が土日祝日にあたるときの扱い（BR-21・BR-62）。"""

    NONE = "none", "そのまま"
    PREVIOUS = "previous", "前にずらす"
    NEXT = "next", "後にずらす"


# 「日」の値（DB 設計書 4.0）：0 は月末、1〜30 は日付
MONTH_END = 0
DAY_CHOICES = [(MONTH_END, "月末")] + [(d, f"{d}日") for d in range(1, 31)]

# 金額の上限（BR-03）
AMOUNT_MAX = 99_999_999
