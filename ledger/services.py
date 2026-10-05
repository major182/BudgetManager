"""明細の業務ルール（画面設計書 4.2、DB 設計書 3.1・5.6）。"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.choices import AmountInputType, TransactionKind
from core.models import AppSettings
from ledger.models import Transaction, TransactionLine
from ledger.tax import LineInput, calculate
from masters.models import Asset, Category, TaxRate

SUGGEST_LIMIT = 10


def today() -> date:
    """今日の日付（日本時間。BR-04）。"""
    return timezone.localdate()


@dataclass(frozen=True)
class LineData:
    category: Category
    tax_rate: TaxRate
    amount: int


@transaction.atomic
def save(
    header: dict[str, Any],
    lines: list[LineData],
    instance: Transaction | None = None,
    source: str = Transaction.Source.MANUAL,
) -> Transaction:
    """明細と内訳を1つの DB の更新処理で保存する（DB 設計書 3.1）。

    - 収入・支出：内訳ごとに税額を計算して保存し、明細の金額は内訳の税込額の合計にする
    - 振替：内訳を持たず、明細に振替額を持つ
    - 内訳の税率の値は、保存する時点のマスタの値を写す（BR-76）
    編集のときは、内訳を一度消して作り直す。
    """
    tx = instance or Transaction(source=source)
    tx.kind = header["kind"]
    tx.date = header["date"]
    tx.asset = header["asset"]
    tx.description = header.get("description", "")
    tx.memo = header.get("memo", "")

    if tx.kind == TransactionKind.TRANSFER:
        tx.transfer_to_asset = header["transfer_to_asset"]
        tx.amount_input_type = None
        tx.amount = header["amount"]
        tx.save()
        tx.lines.all().delete()
        return tx

    rounding = AppSettings.load().tax_rounding
    input_type = header["amount_input_type"]
    result = calculate(
        [LineInput(line.amount, line.tax_rate.rate) for line in lines], input_type, rounding
    )
    tx.transfer_to_asset = None
    tx.amount_input_type = input_type
    tx.amount = result.total.incl
    tx.save()
    tx.lines.all().delete()
    TransactionLine.objects.bulk_create(
        TransactionLine(
            transaction=tx,
            category=line.category,
            tax_rate=line.tax_rate,
            tax_rate_value=line.tax_rate.rate,
            amount_excl=amounts.excl,
            tax_amount=amounts.tax,
            amount_incl=amounts.incl,
            sort_order=order,
        )
        for order, (line, amounts) in enumerate(zip(lines, result.lines, strict=True))
    )
    return tx


def input_amount(line: TransactionLine, input_type: str | None) -> int:
    """編集の画面に出す、内訳の入力の金額（税込入力なら税込額、税抜入力なら税抜額）。"""
    return line.amount_incl if input_type == AmountInputType.TAX_INCLUDED else line.amount_excl


def default_asset(kind: str) -> Asset | None:
    """資産の初期値：前回その種類で登録した明細の資産。なければ並び順の最初（画面設計書 4.2）。"""
    last = (
        Transaction.objects.filter(kind=kind, asset__is_hidden=False)
        .select_related("asset")
        .order_by("-created_at", "-id")
        .first()
    )
    if last:
        return last.asset
    return (
        Asset.objects.filter(is_hidden=False)
        .order_by("asset_group__sort_order", "sort_order", "id")
        .first()
    )


def default_transfer_to(source: Asset | None) -> Asset | None:
    """振替の入金先の初期値：前回の振替の入金先。なければ出金元と違う最初の資産。"""
    last = (
        Transaction.objects.filter(
            kind=TransactionKind.TRANSFER, transfer_to_asset__is_hidden=False
        )
        .select_related("transfer_to_asset")
        .order_by("-created_at", "-id")
        .first()
    )
    if last and last.transfer_to_asset != source:
        return last.transfer_to_asset
    candidates = Asset.objects.filter(is_hidden=False)
    if source is not None:
        candidates = candidates.exclude(pk=source.pk)
    return candidates.order_by("asset_group__sort_order", "sort_order", "id").first()


def default_tax_rate(category: Category | None) -> TaxRate | None:
    """税率の初期値：分類の既定の税率。なければ設定の既定値（BR-78・79）。"""
    if category is not None and category.default_tax_rate is not None:
        return category.default_tax_rate
    return AppSettings.load().default_tax_rate


def suggestions(kind: str, prefix: str) -> list[Transaction]:
    """入力の補完の候補：入力した文字で始まる過去の内容を、新しい順に最大10件（F-TX-05）。

    同じ内容が何件あっても候補には1回だけ出し、その内容で最後に登録した明細を返す。
    """
    prefix = prefix.strip()
    if not prefix:
        return []
    found: dict[str, Transaction] = {}
    query = (
        Transaction.objects.filter(kind=kind, description__startswith=prefix)
        .prefetch_related("lines__category__parent", "lines__tax_rate")
        .select_related("asset")
        .order_by("-date", "-id")
    )
    for tx in query[:200]:
        if tx.description not in found:
            found[tx.description] = tx
        if len(found) >= SUGGEST_LIMIT:
            break
    return list(found.values())


def assets_used(tx: Transaction | None) -> set[int]:
    """編集中の明細が使っている資産（非表示でも選択肢に出すため）。"""
    if tx is None:
        return set()
    return {pk for pk in (tx.asset_id, tx.transfer_to_asset_id) if pk}


def categories_used(tx: Transaction | None) -> set[int]:
    """編集中の明細の内訳が使っている分類（非表示でも選択肢に出すため）。"""
    if tx is None:
        return set()
    return set(tx.lines.values_list("category_id", flat=True))


def tax_rates_used(tx: Transaction | None) -> set[int]:
    """編集中の明細の内訳が使っている税率（非表示でも選択肢に出すため）。"""
    if tx is None:
        return set()
    return set(tx.lines.values_list("tax_rate_id", flat=True))
