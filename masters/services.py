"""マスタ（税率・分類・資産グループ・資産）の業務ルール。

画面設計書 4.9 の共通の操作（並べ替え・削除）と、
使用中のマスタを削除できないルール（DB 設計書 D-4）を置く。
"""

from typing import Any

from django.db import transaction
from django.db.models import Max, Model, QuerySet

from core.models import AppSettings
from masters.models import Asset, AssetGroup, Category, TaxRate

# 使用中のマスタを削除しようとしたとき（MSG-E07）
MSG_E07 = "「{name}」は{count}件の{source}で使われているため削除できません。非表示にできます。"
MSG_E07_GROUP = "「{name}」には{count}件の資産が属しているため削除できません。"


# 4種類のマスタのどれか
type Master = TaxRate | Category | AssetGroup | Asset


class InUseError(Exception):
    """使われているマスタを削除しようとした。message は画面にそのまま出す文言。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def siblings(obj: Master) -> QuerySet[Any]:
    """並び順を比べる範囲（同じ一覧に並ぶもの）を返す。"""
    if isinstance(obj, Category):
        return Category.objects.filter(kind=obj.kind, parent_id=obj.parent_id)
    if isinstance(obj, Asset):
        return Asset.objects.filter(asset_group_id=obj.asset_group_id)
    return type(obj).objects.all()


def list_key(obj: Master) -> tuple[object, ...]:
    """どの一覧に並ぶかを表す値。編集で値が変わったら、別の一覧へ移ったことになる。"""
    if isinstance(obj, Category):
        return (obj.kind, obj.parent_id)
    if isinstance(obj, Asset):
        return (obj.asset_group_id,)
    return ()


def next_sort_order(queryset: QuerySet[Any]) -> int:
    """新しく追加するものの並び順（一覧の最後）。"""
    current = queryset.aggregate(m=Max("sort_order"))["m"]
    return 0 if current is None else current + 1


@transaction.atomic
def move(obj: Master, direction: str) -> None:
    """同じ一覧の中で1つ上（up）または下（down）へ移す（画面設計書 4.9）。

    並び順に同じ値が混ざっていても確実に入れ替えられるよう、
    一覧の順に 0, 1, 2… と振り直してから入れ替える。
    """
    items = list(siblings(obj).order_by("sort_order", "id"))
    index = next(i for i, item in enumerate(items) if item.pk == obj.pk)
    target = index - 1 if direction == "up" else index + 1
    if not 0 <= target < len(items):
        return  # 先頭をさらに上へ、最後をさらに下へは動かさない
    items[index], items[target] = items[target], items[index]
    for order, item in enumerate(items):
        if item.sort_order != order:
            item.sort_order = order
            item.save(update_fields=["sort_order", "updated_at"])


def usages(obj: Model) -> list[tuple[str, int]]:
    """マスタがどこで何件使われているか（使用元の名前, 件数）の一覧。件数が 0 のものは含めない。"""
    if isinstance(obj, TaxRate):
        counts = [
            ("明細", obj.transaction_lines.values("transaction").distinct().count()),
            ("定期収支", obj.recurring_items.count()),
            ("分類の既定の税率", Category.objects.filter(default_tax_rate=obj).count()),
            ("表示設定の既定の税率", AppSettings.objects.filter(default_tax_rate=obj).count()),
        ]
    elif isinstance(obj, Category):
        counts = [
            ("明細", obj.transaction_lines.values("transaction").distinct().count()),
            ("定期収支", obj.recurring_items.count()),
            ("予算", 1 if hasattr(obj, "budget") else 0),
            ("小分類", obj.children.count()),
        ]
    elif isinstance(obj, Asset):
        counts = [
            ("明細", obj.transactions.count() + obj.incoming_transfers.count()),
            ("定期収支", obj.recurring_items.count() + obj.incoming_recurring_items.count()),
            ("クレジットカードの引き落とし口座", obj.paid_cards.count()),
        ]
    elif isinstance(obj, AssetGroup):
        counts = [("資産", obj.assets.count())]
    else:
        raise TypeError(type(obj))
    return [(source, count) for source, count in counts if count]


@transaction.atomic
def delete(obj: Master) -> None:
    """マスタを削除する。使われていれば削除せずに InUseError を出す（DB 設計書 D-4）。"""
    used = usages(obj)
    if used:
        source, count = used[0]
        if isinstance(obj, AssetGroup):
            raise InUseError(MSG_E07_GROUP.format(name=obj.name, count=count))
        raise InUseError(MSG_E07.format(name=obj.name, count=count, source=source))
    obj.delete()
