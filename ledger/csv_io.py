"""明細の CSV の出力と取り込み（画面設計書 4.14・5章、要件定義書 IF-02）。

- 出力したファイルを、そのまま取り込める形にする
- 1行は明細の内訳1つ（振替は1行）。内訳が複数ある明細は、同じ「明細番号」の複数の行になる
- 文字コードは UTF-8（BOM 付き）、改行は CRLF（Excel でそのまま開けるように）
"""

import csv
import io
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction

from core.choices import AMOUNT_MAX, AmountInputType, TransactionKind
from core.models import AppSettings
from ledger import services
from ledger.models import Transaction
from ledger.tax import LineInput, calculate
from masters.models import Asset, Category, TaxRate

HEADER = [
    "明細番号",
    "日付",
    "種類",
    "資産",
    "振替先",
    "大分類",
    "小分類",
    "税率",
    "金額の入力",
    "金額",
    "税抜額",
    "消費税額",
    "税込額",
    "内容",
    "メモ",
]
# 文字の列（CSV インジェクションの対策の対象。画面設計書 5.4）
TEXT_COLUMNS = {"資産", "振替先", "大分類", "小分類", "内容", "メモ"}

MAX_BYTES = 2 * 1024 * 1024  # 2MB
MAX_ROWS = 5000  # NF-PF-04
MAX_ERRORS = 100  # 誤りは最大 100 件まで出す

KIND_LABELS = {
    TransactionKind.INCOME: "収入",
    TransactionKind.EXPENSE: "支出",
    TransactionKind.TRANSFER: "振替",
}
INPUT_LABELS = {AmountInputType.TAX_INCLUDED: "税込", AmountInputType.TAX_EXCLUDED: "税抜"}

# 画面設計書 6.4 のメッセージ
MSG_E31 = "CSV ファイル（UTF-8）を選んでください。"
MSG_E32 = "ファイルが大きすぎます。2MB までのファイルを選んでください。"
MSG_E33 = f"行が多すぎます。{MAX_ROWS:,}行までにしてください。"
MSG_E34 = "1行目の見出しが正しくありません。出力した CSV の見出しに合わせてください。"
MSG_E35 = "{line}行目：{reason}"
MSG_E36 = "{kind}「{name}」が見つかりません。"
MSG_E37 = "税率 {value}% が見つかりません。"
MSG_E38 = "明細番号 {number} の行で、{item}が一致していません。"


# ---------------------------------------------------------------- CSV インジェクションの対策
# 技術選定書 7.2 S-04

_FORMULA_START = ("=", "+", "-", "@")


def protect(value: str) -> str:
    """出力：先頭が = + - @ の文字は、Excel で数式として実行されないよう先頭に ' を付ける。"""
    return "'" + value if value.startswith(_FORMULA_START) else value


def unprotect(value: str) -> str:
    """取り込み：出力で付けた ' を取り除き、元の値に戻す。"""
    return value[1:] if value.startswith("'") and value[1:].startswith(_FORMULA_START) else value


# ---------------------------------------------------------------- 出力


def _rate_text(rate: Decimal) -> str:
    """税率の値を「10」「8」「8.5」の形にする。"""
    return format(rate.normalize(), "f")


def export(start: date, end: date) -> bytes:
    """期間内の明細を CSV にする（F-IO-01）。日付の古い順。"""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(HEADER)
    transactions = (
        Transaction.objects.filter(date__gte=start, date__lte=end)
        .select_related("asset", "transfer_to_asset")
        .prefetch_related("lines__category__parent")
        .order_by("date", "id")
    )
    for tx in transactions:
        common = [
            str(tx.pk),
            tx.date.isoformat(),
            KIND_LABELS[TransactionKind(tx.kind)],
            tx.asset.name,
        ]
        if tx.kind == TransactionKind.TRANSFER:
            to = tx.transfer_to_asset.name if tx.transfer_to_asset else ""
            row = [*common, to, "", "", "", "", str(tx.amount), "", "", "", tx.description, tx.memo]
            writer.writerow(_protect_row(row))
            continue
        # 収入・支出の明細は必ず税込・税抜のどちらかを持つ（DB の CHECK 制約）
        input_label = INPUT_LABELS[
            AmountInputType(tx.amount_input_type or AmountInputType.TAX_INCLUDED)
        ]
        for line in tx.lines.all():
            top, sub = (
                (line.category.parent, line.category)
                if line.category.parent
                else (line.category, None)
            )
            amount = services.input_amount(line, tx.amount_input_type)
            row = [
                *common,
                "",
                top.name if top else "",
                sub.name if sub else "",
                _rate_text(line.tax_rate_value),
                input_label,
                str(amount),
                str(line.amount_excl),
                str(line.tax_amount),
                str(line.amount_incl),
                tx.description,
                tx.memo,
            ]
            writer.writerow(_protect_row(row))
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")  # BOM 付き


def _protect_row(row: list[str]) -> list[str]:
    return [protect(value) if HEADER[i] in TEXT_COLUMNS else value for i, value in enumerate(row)]


# ---------------------------------------------------------------- 取り込み


@dataclass
class ParsedTransaction:
    """取り込む明細1件（同じ明細番号の行をまとめたもの）。"""

    first_line: int
    header: dict[str, object]
    lines: list[services.LineData] = field(default_factory=list)


@dataclass
class ImportResult:
    errors: list[str]
    transactions: list[ParsedTransaction]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def date_range(self) -> tuple[date, date] | None:
        dates = [t.header["date"] for t in self.transactions]
        days = [d for d in dates if isinstance(d, date)]
        return (min(days), max(days)) if days else None


def _parse_date(text: str) -> date:
    """日付を読む。2026-10-15 の形と、2026/10/15 の形（Excel で保存し直した場合）を受け付ける。"""
    if "/" in text:
        year, month, day = (int(x) for x in text.split("/"))
        return date(year, month, day)
    return date.fromisoformat(text)


def _amount(text: str) -> int:
    value = int(text.replace(",", ""))
    if abs(value) > AMOUNT_MAX:
        raise ValueError
    return value


def parse(content: bytes) -> ImportResult:
    """CSV を読み、すべての行をチェックする。取り込みはまだしない（F-IO-02）。"""
    if len(content) > MAX_BYTES:
        return ImportResult([MSG_E32], [])
    try:
        text = content.decode("utf-8-sig")  # BOM があってもなくても読める
    except UnicodeDecodeError:
        return ImportResult([MSG_E31], [])
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or [h.strip() for h in rows[0]] != HEADER:
        return ImportResult([MSG_E34], [])
    body = [(i + 2, row) for i, row in enumerate(rows[1:]) if any(cell.strip() for cell in row)]
    if len(body) > MAX_ROWS:
        return ImportResult([MSG_E33], [])

    assets = {a.name: a for a in Asset.objects.all()}
    tops = {(c.kind, c.name): c for c in Category.objects.filter(parent__isnull=True)}
    subs = {(c.parent_id, c.name): c for c in Category.objects.filter(parent__isnull=False)}
    rates: dict[Decimal, TaxRate] = {}
    for rate in TaxRate.objects.order_by("sort_order", "id"):
        rates.setdefault(rate.rate, rate)  # 同じ値の税率が複数あれば、並び順が最初のもの
    kinds = {label: kind for kind, label in KIND_LABELS.items()}
    inputs = {label: value for value, label in INPUT_LABELS.items()}

    errors: list[str] = []
    grouped: OrderedDict[str, ParsedTransaction] = OrderedDict()
    for line_no, raw in body:
        row = dict(
            zip(
                HEADER,
                [cell.strip() for cell in raw] + [""] * (len(HEADER) - len(raw)),
                strict=False,
            )
        )
        for name in TEXT_COLUMNS:
            row[name] = unprotect(row[name])

        def fail(reason: str, line_no: int = line_no) -> None:
            errors.append(MSG_E35.format(line=line_no, reason=reason))

        try:
            day = _parse_date(row["日付"])
        except ValueError:
            fail("日付を正しい日付で入力してください。")
            continue
        kind = kinds.get(row["種類"])
        if kind is None:
            fail("種類は「収入」「支出」「振替」のどれかにしてください。")
            continue
        asset = assets.get(row["資産"])
        if asset is None:
            fail(MSG_E36.format(kind="資産", name=row["資産"]))
            continue
        try:
            amount = _amount(row["金額"])
        except ValueError:
            fail("金額は −99,999,999〜99,999,999 の整数で入力してください。")
            continue
        if amount == 0:
            fail("0円は登録できません。")
            continue

        header: dict[str, object] = {
            "kind": kind,
            "date": day,
            "asset": asset,
            "description": row["内容"][:100],
            "memo": row["メモ"][:500],
        }
        line: services.LineData | None = None
        if kind == TransactionKind.TRANSFER:
            to = assets.get(row["振替先"])
            if to is None:
                fail(MSG_E36.format(kind="資産", name=row["振替先"]))
                continue
            if to == asset:
                fail("出金元と入金先には、別の資産を選んでください。")
                continue
            if amount < 0:
                fail("マイナスの金額は、支出でだけ入力できます。")
                continue
            header.update({"transfer_to_asset": to, "amount": amount})
        else:
            top = tops.get((kind, row["大分類"]))
            if top is None:
                fail(MSG_E36.format(kind="分類", name=row["大分類"]))
                continue
            category = top
            if row["小分類"]:
                sub = subs.get((top.pk, row["小分類"]))
                if sub is None:
                    fail(MSG_E36.format(kind="分類", name=f"{row['大分類']}／{row['小分類']}"))
                    continue
                category = sub
            try:
                rate = rates[Decimal(row["税率"])]
            except InvalidOperation, KeyError:
                fail(MSG_E37.format(value=row["税率"]))
                continue
            input_type = inputs.get(row["金額の入力"])
            if input_type is None:
                fail("金額の入力は「税込」「税抜」のどちらかにしてください。")
                continue
            if amount < 0 and kind != TransactionKind.EXPENSE:
                fail("マイナスの金額は、支出でだけ入力できます。")
                continue
            header["amount_input_type"] = input_type
            line = services.LineData(category, rate, amount)

        number = row["明細番号"] or f"#{line_no}"  # 番号が空の行は、それだけで1件の明細
        group = grouped.get(number)
        if group is None:
            grouped[number] = ParsedTransaction(line_no, header, [line] if line else [])
            continue
        # 同じ明細番号の行は、見出しの内容が同じでなければならない
        differs = _first_difference(group.header, header)
        if differs:
            fail(MSG_E38.format(number=number, item=differs))
            continue
        if kind == TransactionKind.TRANSFER:
            fail(MSG_E38.format(number=number, item="振替の行の数"))
            continue
        if line:
            group.lines.append(line)

    for number, parsed in grouped.items():
        error = _check_transaction(parsed)
        if error:
            errors.append(
                MSG_E35.format(line=parsed.first_line, reason=f"明細番号 {number}：{error}")
            )
    return ImportResult(errors[:MAX_ERRORS], list(grouped.values()) if not errors else [])


_LABELS = {
    "date": "日付",
    "kind": "種類",
    "asset": "資産",
    "transfer_to_asset": "振替先",
    "amount_input_type": "金額の入力",
    "description": "内容",
    "memo": "メモ",
}


def _first_difference(a: dict[str, object], b: dict[str, object]) -> str:
    for key, label in _LABELS.items():
        if a.get(key) != b.get(key):
            return label
    return ""


def _check_transaction(parsed: ParsedTransaction) -> str:
    """明細1件としてのチェック（画面から入力したときと同じ。画面設計書 5.3）。"""
    if parsed.header["kind"] == TransactionKind.TRANSFER:
        return ""
    amounts = [line.amount for line in parsed.lines]
    if any(a < 0 for a in amounts) and any(a > 0 for a in amounts):
        return "1件の明細の中で、プラスとマイナスの金額を混ぜることはできません。"
    result = calculate(
        [LineInput(line.amount, line.tax_rate.rate) for line in parsed.lines],
        str(parsed.header["amount_input_type"]),
        AppSettings.load().tax_rounding,
    )
    if abs(result.total.incl) > AMOUNT_MAX:
        return "明細の金額の合計は −99,999,999〜99,999,999 円の範囲にしてください。"
    return ""


@transaction.atomic
def import_all(result: ImportResult) -> int:
    """チェック済みの明細をすべて登録する。

    1つの DB の更新処理で行い、途中で失敗したら何も登録しない。
    """
    for parsed in result.transactions:
        services.save(parsed.header, parsed.lines, source=Transaction.Source.CSV)
    return len(result.transactions)
