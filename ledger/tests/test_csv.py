"""CSV の出力と取り込みのテスト（テスト仕様書 3.6・4.10）。"""

import csv
import io
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from ledger import csv_io, services
from ledger.models import Transaction
from masters.models import Asset, AssetGroup, Category, TaxRate

pytestmark = pytest.mark.django_db

HEADER = ",".join(csv_io.HEADER)


def _cat(name: str, kind: str = "expense") -> Category:
    return Category.objects.get(kind=kind, name=name)


def _rate(value: str) -> TaxRate:
    return TaxRate.objects.get(rate=Decimal(value))


def _save(day: date, lines: list[tuple[Category, str, int]], **header: object) -> Transaction:
    values: dict[str, object] = {
        "kind": "expense",
        "date": day,
        "asset": Asset.objects.get(name="現金"),
        "amount_input_type": "tax_included",
        "description": "",
        "memo": "",
    }
    values.update(header)
    return services.save(values, [services.LineData(c, _rate(r), a) for c, r, a in lines])


@pytest.fixture
def sample() -> None:
    """往復のテストに使う明細：内訳が複数・小分類・税抜入力・返品・収入・振替・数式に見える内容。"""
    eat_out = Category.objects.create(kind="expense", name="外食", parent=_cat("食費"))
    bank = Asset.objects.create(asset_group=AssetGroup.objects.get(name="銀行"), name="〇〇銀行")
    _save(
        date(2026, 10, 15),
        [
            (_cat("食費"), "8", 1080),
            (_cat("備品・衣類"), "10", 550),
            (_cat("備品・衣類"), "10", 330),
        ],
        description="スーパー",
        memo="週末の買い出し, 2袋",
    )
    _save(
        date(2026, 10, 8),
        [(eat_out, "10", 1000)],
        amount_input_type="tax_excluded",
        description="ランチ",
    )
    _save(date(2026, 10, 13), [(_cat("備品・衣類"), "10", -550)], description="返品")
    _save(date(2026, 10, 14), [(_cat("給与", "income"), "0", 250000)], kind="income", asset=bank)
    _save(date(2026, 10, 20), [(_cat("その他"), "10", 100)], description="=SUM(A1:A9)")
    services.save(
        {
            "kind": "transfer",
            "date": date(2026, 10, 5),
            "asset": bank,
            "transfer_to_asset": Asset.objects.get(name="現金"),
            "amount": 30000,
            "description": "ATM",
        },
        [],
    )


def _rows(content: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))


def _snapshot() -> list[tuple[Any, ...]]:
    """明細と内訳の中身（id と作成日時を除く）。往復の前後で比べる。"""
    result: list[tuple[Any, ...]] = []
    for tx in Transaction.objects.order_by("date", "description"):
        lines = tuple(
            (
                line.category_id,
                line.tax_rate_value,
                line.amount_excl,
                line.tax_amount,
                line.amount_incl,
            )
            for line in tx.lines.order_by("sort_order")
        )
        result.append(
            (
                tx.date,
                tx.kind,
                tx.asset_id,
                tx.transfer_to_asset_id,
                tx.amount,
                tx.amount_input_type,
                tx.description,
                tx.memo,
                lines,
            )
        )
    return result


# ---------------------------------------------------------------- 出力


@pytest.mark.usefixtures("sample")
def test_出力の形式() -> None:
    content = csv_io.export(date(2026, 10, 1), date(2026, 10, 31))
    assert content.startswith(b"\xef\xbb\xbf")  # BOM 付き
    assert b"\r\n" in content  # 改行は CRLF
    rows = _rows(content)
    assert rows[0] == csv_io.HEADER
    assert len(rows) == 1 + 8  # 内訳が3つの明細は3行、振替は1行
    supermarket = [r for r in rows if r[13] == "スーパー"]
    assert [r[0] for r in supermarket] == [supermarket[0][0]] * 3  # 同じ明細番号
    assert supermarket[0][2:13] == [
        "支出",
        "現金",
        "",
        "食費",
        "",
        "8",
        "税込",
        "1080",
        "1000",
        "80",
        "1080",
    ]
    assert supermarket[0][14] == "週末の買い出し, 2袋"  # カンマを含む値も1つの列
    lunch = next(r for r in rows if r[13] == "ランチ")
    assert lunch[5:10] == ["食費", "外食", "10", "税抜", "1000"]  # 小分類、税抜で入れた金額
    transfer = next(r for r in rows if r[2] == "振替")
    assert transfer[3:13] == ["〇〇銀行", "現金", "", "", "", "", "30000", "", "", ""]
    returned = next(r for r in rows if r[13] == "返品")
    assert returned[9] == "-550"  # データとしてのマイナスは「-」を使う


@pytest.mark.usefixtures("sample")
def test_CSVインジェクションの対策() -> None:
    rows = _rows(csv_io.export(date(2026, 10, 1), date(2026, 10, 31)))
    formula = next(r for r in rows if "SUM" in r[13])
    assert formula[13] == "'=SUM(A1:A9)"  # 文字の列は先頭に ' を付ける（S-04）
    assert next(r for r in rows if r[13] == "返品")[9] == "-550"  # 数値の列には付けない


# ---------------------------------------------------------------- 往復


@pytest.mark.usefixtures("sample")
def test_出力したファイルをそのまま取り込める() -> None:
    before = _snapshot()
    content = csv_io.export(date(2026, 10, 1), date(2026, 10, 31))
    Transaction.objects.all().delete()
    result = csv_io.parse(content)
    assert result.ok, result.errors
    assert csv_io.import_all(result) == 6
    assert _snapshot() == before
    assert set(Transaction.objects.values_list("source", flat=True)) == {"csv"}


# ---------------------------------------------------------------- 取り込みの誤り（画面設計書 6.4）


def _parse(*lines: str) -> csv_io.ImportResult:
    return csv_io.parse(("\r\n".join([HEADER, *lines]) + "\r\n").encode("utf-8"))


ROW = "1,2026-10-15,支出,現金,,食費,,8,税込,1080,,,,スーパー,"


def test_正しい行と日付の形() -> None:
    result = _parse(ROW, "2,2026/10/16,支出,現金,,食費,,8,税込,500,,,,,")  # 2026/10/16 の形も読める
    assert result.ok and len(result.transactions) == 2
    assert result.date_range == (date(2026, 10, 15), date(2026, 10, 16))


def test_見出しが違う() -> None:
    assert csv_io.parse("日付,金額\r\n".encode()).errors == [csv_io.MSG_E34]


def test_文字コードと大きさと行数() -> None:
    assert csv_io.parse((HEADER + "\r\n").encode("cp932")).errors == [csv_io.MSG_E31]
    assert csv_io.parse(b"x" * (csv_io.MAX_BYTES + 1)).errors == [csv_io.MSG_E32]
    many = [f"{i},2026-10-15,支出,現金,,食費,,8,税込,1,,,,," for i in range(csv_io.MAX_ROWS + 1)]
    assert _parse(*many).errors == [csv_io.MSG_E33]


def test_行ごとの誤りは行番号と理由を出す() -> None:
    result = _parse(
        ROW,
        "2,2026-10-15,支出,財布,,食費,,8,税込,100,,,,,",  # 3行目：資産がない
        "3,2026-10-15,支出,現金,,食費,,5,税込,100,,,,,",  # 4行目：税率がない
        "4,2026-13-01,支出,現金,,食費,,8,税込,100,,,,,",  # 5行目：日付の誤り
        "5,2026-10-15,支出,現金,,食費,,8,税込,0,,,,,",  # 6行目：0円
        "6,2026-10-15,収入,現金,,給与,,0,税込,-1,,,,,",  # 7行目：収入のマイナス
    )
    assert result.errors == [
        "3行目：資産「財布」が見つかりません。",
        "4行目：税率 5% が見つかりません。",
        "5行目：日付を正しい日付で入力してください。",
        "6行目：0円は登録できません。",
        "7行目：マイナスの金額は、支出でだけ入力できます。",
    ]
    assert result.transactions == []  # 1件でも誤りがあれば取り込まない


def test_同じ明細番号の行の一致と符号の混在() -> None:
    result = _parse(ROW, "1,2026-10-16,支出,現金,,食費,,8,税込,100,,,,スーパー,")
    assert result.errors == ["3行目：明細番号 1 の行で、日付が一致していません。"]  # MSG-E38
    result = _parse(ROW, "1,2026-10-15,支出,現金,,食費,,8,税込,-100,,,,スーパー,")
    assert "プラスとマイナスの金額を混ぜることはできません。" in result.errors[0]


def test_分類と小分類が見つからない() -> None:
    result = _parse(
        "1,2026-10-15,支出,現金,,食費,おやつ,8,税込,100,,,,,",
        "2,2026-10-15,支出,現金,,給与,,0,税込,100,,,,,",
    )
    assert result.errors == [
        "2行目：分類「食費／おやつ」が見つかりません。",
        "3行目：分類「給与」が見つかりません。",  # 支出の明細に収入用の分類は使えない
    ]


# ---------------------------------------------------------------- 画面（SC-13）


@pytest.mark.usefixtures("sample")
def test_月と年の出力(client: Client) -> None:
    response = client.get("/settings/csv/export/?unit=month&month=2026-10")
    assert response["Content-Disposition"] == 'attachment; filename="budget_2026-10.csv"'
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert len(_rows(response.content)) == 9
    response = client.get("/settings/csv/export/?unit=year&year=2026")
    assert response["Content-Disposition"] == 'attachment; filename="budget_2026.csv"'


def _upload(text: str) -> SimpleUploadedFile:
    return SimpleUploadedFile("data.csv", text.encode("utf-8-sig"), content_type="text/csv")


def test_確認してから取り込む(client: Client) -> None:
    html = client.post(
        "/settings/csv/check/", {"file": _upload(HEADER + "\r\n" + ROW + "\r\n")}
    ).content.decode()
    assert "1件の明細（2026/10/15〜2026/10/15）" in html and "取り込む" in html
    assert not Transaction.objects.exists()  # 確認ではまだ登録しない
    response = client.post("/settings/csv/import/")
    assert response.status_code == 302
    assert Transaction.objects.count() == 1
    assert (
        'data-toast="1件の明細を取り込みました"' in client.get("/settings/csv/").content.decode()
    )  # MSG-I04


def test_誤りがあれば取り込めない(client: Client) -> None:
    html = client.post(
        "/settings/csv/check/",
        {"file": _upload(HEADER + "\r\n1,2026-10-15,支出,財布,,食費,,8,税込,1,,,,,\r\n")},
    ).content.decode()
    assert "2行目：資産「財布」が見つかりません。" in html and "取り込む</button>" not in html
    client.post("/settings/csv/import/")
    assert not Transaction.objects.exists()


def test_ファイルを選ばずに確認(client: Client) -> None:
    assert (
        "ファイルを選んでください。" in client.post("/settings/csv/check/").content.decode()
    )  # MSG-E30


def test_同じファイルを2回取り込むと2回登録される(client: Client) -> None:
    for _ in range(2):
        client.post("/settings/csv/check/", {"file": _upload(HEADER + "\r\n" + ROW + "\r\n")})
        client.post("/settings/csv/import/")
    assert Transaction.objects.count() == 2
