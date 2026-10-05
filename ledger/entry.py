"""明細入力（SC-02）の画面の状態を組み立てる部品。

入力中の操作（種類の切り替え・内訳の追加と削除・分類を選んだときの税率・候補の反映）は、
フォームの内容をそのままサーバーに送り、ここで内容を書き換えてから描き直す。
入力した値はそのまま残る（画面設計書 4.2）。
"""

from typing import Any

from django.http import QueryDict

from core.choices import TransactionKind
from core.models import AppSettings
from ledger import services
from ledger.forms import MAX_LINES
from ledger.models import Transaction
from masters.models import Category

PREFIX = "lines"


def initial(
    instance: Transaction | None, *, copy: bool, kind: str | None, date: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """フォームの初期値（見出し, 内訳の各行）。"""
    settings = AppSettings.load()
    if instance is not None:
        header: dict[str, Any] = {
            "kind": instance.kind,
            # コピーでは日付を今日にする（BR-15）
            "date": services.today() if copy else instance.date,
            "asset": instance.asset_id,
            "transfer_to_asset": instance.transfer_to_asset_id,
            "description": instance.description,
            "memo": instance.memo,
            "amount_input_type": instance.amount_input_type or settings.default_amount_input_type,
            "amount": instance.amount if instance.kind == TransactionKind.TRANSFER else None,
        }
        lines = [
            {
                "category": line.category_id,
                "tax_rate": line.tax_rate_id,
                "amount": services.input_amount(line, instance.amount_input_type),
            }
            for line in instance.lines.order_by("sort_order", "id")
        ]
        return header, lines or [_empty_line(settings)]

    kind = kind if kind in TransactionKind.values else TransactionKind.EXPENSE
    asset = services.default_asset(kind)
    header = {
        "kind": kind,
        "date": date or services.today(),
        "asset": asset.pk if asset else None,
        "transfer_to_asset": _pk(services.default_transfer_to(asset)),
        "amount_input_type": settings.default_amount_input_type,
    }
    return header, [_empty_line(settings)]


def _pk(obj: Any) -> Any:
    return obj.pk if obj is not None else None


def _empty_line(settings: AppSettings) -> dict[str, Any]:
    return {"category": "", "tax_rate": settings.default_tax_rate_id, "amount": ""}


def _count(data: QueryDict) -> int:
    try:
        return max(1, int(data.get(f"{PREFIX}-TOTAL_FORMS", "1")))
    except ValueError:
        return 1


def _set_count(data: QueryDict, count: int) -> None:
    data[f"{PREFIX}-TOTAL_FORMS"] = str(count)


def _key(index: int, name: str) -> str:
    return f"{PREFIX}-{index}-{name}"


def apply_action(data: QueryDict, action: str) -> QueryDict:
    """入力中の操作を、送られてきたフォームの内容に反映する。保存はしない。"""
    data = data.copy()
    name, _, arg = action.partition(":")
    count = _count(data)

    if name == "kind" and arg in TransactionKind.values and arg != data.get("kind"):
        previous = data.get("kind")
        data["kind"] = arg
        # 収入用と支出用で分類が違うため、分類を空に戻す（画面設計書 4.2）
        for i in range(count):
            data[_key(i, "category")] = ""
        if arg == TransactionKind.TRANSFER:
            # 振替へ：内訳の金額の合計を振替の金額として引き継ぐ
            total = 0
            for i in range(count):
                try:
                    total += int(data.get(_key(i, "amount"), "") or 0)
                except ValueError:
                    pass
            data["amount"] = str(total) if total else ""
        elif previous == TransactionKind.TRANSFER:
            # 振替から：振替の金額を1行目の内訳の金額として引き継ぐ
            _set_count(data, 1)
            data[_key(0, "amount")] = data.get("amount", "")
            data[_key(0, "tax_rate")] = str(AppSettings.load().default_tax_rate_id)

    elif name == "add_line" and count < MAX_LINES:
        data[_key(count, "category")] = ""
        data[_key(count, "tax_rate")] = str(AppSettings.load().default_tax_rate_id)
        data[_key(count, "amount")] = ""
        _set_count(data, count + 1)

    elif name == "remove" and arg.isdigit() and 0 < int(arg) < count:
        # その行を消し、後ろの行を1つずつ前へ詰める
        for i in range(int(arg), count - 1):
            for field in ("category", "tax_rate", "amount"):
                data[_key(i, field)] = data.get(_key(i + 1, field), "")
        for field in ("category", "tax_rate", "amount"):
            data.pop(_key(count - 1, field), None)
        _set_count(data, count - 1)

    elif name == "category" and arg.isdigit():
        # 分類を選ぶと、その内訳の税率を分類の既定の税率にする（BR-78）
        selected = data.get(_key(int(arg), "category")) or ""
        category = Category.objects.filter(pk=int(selected)).first() if selected.isdigit() else None
        rate = services.default_tax_rate(category)
        if rate is not None:
            data[_key(int(arg), "tax_rate")] = str(rate.pk)

    elif name == "apply" and arg.isdigit():
        # 候補を選ぶと、その内容で最後に登録した明細の資産・分類・税率・金額を入れる。
        # 入力済みの金額は上書きしない（画面設計書 4.2）
        tx = Transaction.objects.filter(pk=int(arg)).prefetch_related("lines").first()
        if tx is not None:
            data["description"] = tx.description
            data["asset"] = str(tx.asset_id)
            line = tx.lines.order_by("sort_order", "id").first()
            if line is not None:
                data[_key(0, "category")] = str(line.category_id)
                data[_key(0, "tax_rate")] = str(line.tax_rate_id)
                if not data.get(_key(0, "amount")):
                    data[_key(0, "amount")] = str(services.input_amount(line, tx.amount_input_type))

    return data
