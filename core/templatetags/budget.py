"""テンプレートで使う部品（金額の表示など）。"""

from typing import Any

from django import template

from core.models import AppSettings
from core.money import format_yen

register = template.Library()


@register.simple_tag(takes_context=True)
def yen(context: dict[str, Any], value: int) -> str:
    """金額を設定の通貨記号・桁区切りで表示する（符号は付けない。画面設計書 1.3）。

    使い方：{% yen transaction.amount %}
    """
    settings: AppSettings = context["app_settings"]
    return format_yen(value, settings.currency_symbol, settings.use_thousands_separator)


@register.filter
def comma(value: int) -> str:
    """数値に桁区切りを付ける（通貨記号なし。税額の表など）。マイナスは「-」を付ける。"""
    return f"{value:,}"


@register.filter
def amount_class(tx: Any) -> str:
    """明細の金額の色（画面設計書 1.2・4.1）。

    収入は青、支出は赤、振替は灰色。マイナス支出（返品など）は青。符号は付けないため、色で表す。
    """
    if tx.kind == "transfer":
        return "transfer"
    if tx.kind == "income" or tx.amount < 0:
        return "income"
    return "expense"


@register.filter
def signed_class(value: int) -> str:
    """合計・残高など、プラスとマイナスで色を変える値の色。マイナスは赤（画面設計書 1.3）。"""
    return "expense" if value < 0 else ""


@register.filter
def expense_class(value: int) -> str:
    """支出の合計の色。

    返品などでマイナスになったときは、返品の行と同じく青にする（画面設計書 1.2・1.3）。
    """
    return "income" if value < 0 else "expense"


@register.filter
def short_yen(value: int) -> str:
    """カレンダーのマスに出す短い金額。1万円以上は「3.2万」のように縮める（画面設計書 4.1）。"""
    if abs(value) >= 10_000:
        return f"{value / 10_000:.1f}".rstrip("0").rstrip(".") + "万"
    return f"{abs(value):,}"
