"""予算設定のフォーム（SC-11、画面設計書 4.12）。

予算の欄は「全体」と支出の大分類の数だけあるため、分類ごとに欄を組み立てる。
欄の名前は「全体」なら all、大分類ならその id。
空欄は、基本額なら「予算なし」、月ごとの額なら「基本額を使う」の意味になる。
"""

from typing import Any

from django import forms

from core.choices import AMOUNT_MAX
from core.forms import MSG_E03, range_error

WHOLE = "all"


class BudgetAmountsForm(forms.Form):
    """予算額の欄の集まり。rows は（欄の名前, 表示名）の並び。"""

    def __init__(self, *args: Any, rows: list[tuple[str, str]], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.rows = rows
        for key, label in rows:
            # 誤りのメッセージは画面設計書 6.4（MSG-E03・E04）
            out_of_range = range_error(label, 0, f"{AMOUNT_MAX:,}")
            field = forms.IntegerField(
                label=label,
                required=False,
                min_value=0,
                max_value=AMOUNT_MAX,
                error_messages={
                    "invalid": MSG_E03.format(label=label),
                    "min_value": out_of_range,
                    "max_value": out_of_range,
                },
            )
            field.widget.attrs.update({"inputmode": "numeric", "class": "input amount"})
            self.fields[key] = field
