"""消費税の計算（DB 設計書 5.6、BR-72〜76）。

計算は Decimal で行い、float は使わない（CLAUDE.md 3.1）。
画面の税額の表と、明細の保存の両方がこの計算を使う（同じ結果にするため。技術選定書 5.3）。
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from core.choices import AmountInputType
from core.models import AppSettings

# 端数処理の方法（設定の tax_rounding）→ Decimal の丸め方
_ROUNDING: dict[str, str] = {
    AppSettings.TaxRounding.FLOOR: ROUND_FLOOR,
    AppSettings.TaxRounding.ROUND_HALF_UP: ROUND_HALF_UP,
    AppSettings.TaxRounding.CEILING: ROUND_CEILING,
}


@dataclass(frozen=True)
class LineInput:
    """内訳1行の入力。amount は税込または税抜で入力した金額（円）。"""

    amount: int
    rate: Decimal


@dataclass(frozen=True)
class Amounts:
    """税抜額・消費税額・税込額（円）。"""

    excl: int
    tax: int
    incl: int


@dataclass(frozen=True)
class TaxResult:
    lines: list[Amounts]  # 入力と同じ順の、内訳ごとの金額
    by_rate: list[tuple[Decimal, Amounts]]  # 税率ごとの合計（税率の小さい順）
    total: Amounts  # 明細全体の合計


def _round(value: Decimal, rounding: str) -> int:
    return int(value.quantize(Decimal("1"), rounding=_ROUNDING[rounding]))


def calculate(lines: list[LineInput], input_type: str, rounding: str) -> TaxResult:
    """内訳ごと・税率ごと・全体の税抜額・消費税額・税込額を求める。

    手順（DB 設計書 5.6）：
    1. 同じ税率の内訳を1つのまとまりにする
    2. まとまりの金額の合計から消費税額を計算し、端数処理を1回だけ行う（BR-74）
    3. まとまりの消費税額を、金額の割合で各内訳に割り振る。各内訳は1円未満切り捨てとし、
       余った円は金額の最も大きい内訳に足す（同じ金額なら先の内訳）
    4. 税込入力なら 税抜額 ＝ 税込額 − 消費税額、税抜入力なら 税込額 ＝ 税抜額 ＋ 消費税額

    マイナス支出は、金額の絶対値で計算してから符号を付ける（BR-74）。
    1件の明細でプラスとマイナスを混ぜないことは、呼び出す側で確かめる（MSG-E12）。
    """
    sign = -1 if lines and lines[0].amount < 0 else 1
    groups: dict[Decimal, list[int]] = {}
    for index, line in enumerate(lines):
        groups.setdefault(line.rate, []).append(index)

    result: list[Amounts | None] = [None] * len(lines)
    by_rate: list[tuple[Decimal, Amounts]] = []
    for rate in sorted(groups):
        indexes = groups[rate]
        bases = [abs(lines[i].amount) for i in indexes]
        group_sum = sum(bases)
        if input_type == AmountInputType.TAX_INCLUDED:
            exact = Decimal(group_sum) * rate / (Decimal(100) + rate)
        else:
            exact = Decimal(group_sum) * rate / Decimal(100)
        group_tax = _round(exact, rounding)

        # 割り振り：各内訳は切り捨て、余りは最も大きい内訳へ
        shares = [group_tax * base // group_sum if group_sum else 0 for base in bases]
        largest = max(range(len(bases)), key=lambda k: (bases[k], -k))
        shares[largest] += group_tax - sum(shares)

        for k, i in enumerate(indexes):
            base, tax = bases[k], shares[k]
            if input_type == AmountInputType.TAX_INCLUDED:
                excl, incl = base - tax, base
            else:
                excl, incl = base, base + tax
            result[i] = Amounts(sign * excl, sign * tax, sign * incl)

        group_amounts = [result[i] for i in indexes]
        by_rate.append(
            (
                rate,
                Amounts(
                    sum(a.excl for a in group_amounts if a),
                    sum(a.tax for a in group_amounts if a),
                    sum(a.incl for a in group_amounts if a),
                ),
            )
        )

    line_amounts = [a for a in result if a is not None]
    total = Amounts(
        sum(a.excl for a in line_amounts),
        sum(a.tax for a in line_amounts),
        sum(a.incl for a in line_amounts),
    )
    return TaxResult(line_amounts, by_rate, total)
