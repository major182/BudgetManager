"""金額の表示（画面設計書 1.3）。

- 通貨記号と桁区切りは設定に従う（F-CF-01）
- 「＋」「−」の符号は付けない。プラス・マイナスや収支の違いは、テンプレート側で色を付けて表す
"""

from core.models import AppSettings

# 通貨記号を金額の前に付けるか後ろに付けるか
_SYMBOL_PREFIX: dict[str, str] = {AppSettings.CurrencySymbol.YEN_SIGN: "¥"}
_SYMBOL_SUFFIX: dict[str, str] = {AppSettings.CurrencySymbol.YEN_TEXT: "円"}


def format_yen(value: int, currency_symbol: str, use_thousands_separator: bool) -> str:
    """金額を表示用の文字列にする。マイナスの値も符号を付けずに表示する。

    >>> format_yen(-1234567, "yen_sign", True)
    '¥1,234,567'
    """
    number = f"{abs(value):,}" if use_thousands_separator else str(abs(value))
    prefix = _SYMBOL_PREFIX.get(currency_symbol, "")
    suffix = _SYMBOL_SUFFIX.get(currency_symbol, "")
    return f"{prefix}{number}{suffix}"
