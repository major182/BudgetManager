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
