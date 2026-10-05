"""フォーム共通の部品。

入力の誤りのメッセージを、画面設計書 6.4 の文言にそろえる。
Django の標準のメッセージ（「このフィールドは必須です。」など）は、
どの項目の誤りかが文に入らないため使わない。
"""

from typing import Any

from django import forms

# 画面設計書 6.4 の共通のメッセージ
MSG_E01 = "{label}を入力してください。"
MSG_E02 = "{label}は{max}文字以内で入力してください。"
MSG_E03 = "{label}は整数で入力してください。"
MSG_E04 = "{label}は{min}〜{max}の範囲で入力してください。"
MSG_E05 = "{label}を正しい日付で入力してください。"
MSG_E06 = "この名前はすでに使われています。"


class StyledFormMixin:
    """入力欄の見た目（CSS のクラス）と、誤りのメッセージをそろえる。

    フォームの __init__ のあとで、各項目に次を設定する。
    - 入力欄に `input` クラス（画面設計書 1.5 の見た目）
    - 必須・文字数・数値・日付の誤りのメッセージ（画面設計書 6.4）
    """

    fields: dict[str, forms.Field]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            label = str(field.label)
            messages = {"required": MSG_E01.format(label=label)}
            if isinstance(field, forms.CharField) and field.max_length:
                messages["max_length"] = MSG_E02.format(label=label, max=field.max_length)
            if isinstance(field, forms.IntegerField | forms.DecimalField):
                messages["invalid"] = MSG_E03.format(label=label)
            if isinstance(field, forms.DateField):
                messages["invalid"] = MSG_E05.format(label=label)
            field.error_messages.update(messages)

            widget = field.widget
            if not isinstance(widget, forms.CheckboxInput | forms.RadioSelect | forms.HiddenInput):
                widget.attrs["class"] = f"input {widget.attrs.get('class', '')}".strip()
            # スマホで数字のキーボードを出す（画面設計書 1.5）
            if isinstance(field, forms.IntegerField):
                widget.attrs.setdefault("inputmode", "numeric")


def range_error(label: str, minimum: object, maximum: object) -> str:
    """範囲外の数値の誤り（MSG-E04）。"""
    return MSG_E04.format(label=label, min=minimum, max=maximum)
