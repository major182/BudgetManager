"""消費税の計算のテスト（テスト仕様書 3.2）。期待値は DB 設計書 5.6 の例。"""

from decimal import Decimal

from ledger.tax import Amounts, LineInput, calculate

INCL = "tax_included"
EXCL = "tax_excluded"
R8 = Decimal("8.0")
R10 = Decimal("10.0")
R0 = Decimal("0.0")


def test_設計書の例_税込入力で税率が混在する() -> None:
    # DB 設計書 5.6 の例：食費 8% 1,080、日用品 10% 550、衣服・美容 10% 330
    r = calculate([LineInput(1080, R8), LineInput(550, R10), LineInput(330, R10)], INCL, "floor")
    assert r.lines == [Amounts(1000, 80, 1080), Amounts(500, 50, 550), Amounts(300, 30, 330)]
    assert r.by_rate == [(R8, Amounts(1000, 80, 1080)), (R10, Amounts(800, 80, 880))]
    assert r.total == Amounts(1800, 160, 1960)


def test_税抜入力() -> None:
    r = calculate([LineInput(1000, R10)], EXCL, "floor")
    assert r.total == Amounts(1000, 100, 1100)


def test_端数処理の3つの方法() -> None:
    # 税込 105 円・10%：105 × 10 ÷ 110 = 9.545…
    line = [LineInput(105, R10)]
    assert calculate(line, INCL, "floor").total.tax == 9
    assert calculate(line, INCL, "round_half_up").total.tax == 10
    assert calculate(line, INCL, "ceiling").total.tax == 10
    # 税抜 104 円・8%：8.32
    assert calculate([LineInput(104, R8)], EXCL, "round_half_up").total.tax == 8


def test_同じ税率は合計してから1回だけ端数処理する() -> None:
    # 1行ずつ切り捨てると 9 + 9 = 18 円だが、合計 210 円で計算すると 19 円（210 × 10 ÷ 110 = 19.09）
    r = calculate([LineInput(105, R10), LineInput(105, R10)], INCL, "floor")
    assert r.total.tax == 19
    # 余りの1円は、金額が同じなら先の内訳へ
    assert [a.tax for a in r.lines] == [10, 9]


def test_割り振りの余りは金額の最も大きい内訳へ() -> None:
    r = calculate([LineInput(100, R10), LineInput(300, R10)], INCL, "floor")
    # 400 × 10 ÷ 110 = 36.36 → 36。割り振り：100 → 9、300 → 27（合計 36）
    assert r.total.tax == 36
    assert [a.tax for a in r.lines] == [9, 27]


def test_マイナス支出は絶対値で計算してから符号を付ける() -> None:
    r = calculate([LineInput(-550, R10)], INCL, "floor")
    assert r.total == Amounts(-500, -50, -550)


def test_税率0パーセント() -> None:
    r = calculate([LineInput(250000, R0)], INCL, "floor")
    assert r.total == Amounts(250000, 0, 250000)
