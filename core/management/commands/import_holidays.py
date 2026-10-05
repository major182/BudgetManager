"""BT-02 祝日データの更新（要件定義書 IF-01）。年に1回以上、手動または cron で実行する。

内閣府「国民の祝日について」の CSV（Shift_JIS）を取り込み、holidays テーブルを最新にする。
振替休日・国民の休日も CSV に含まれる。年末年始（12/31〜1/3）は祝日ではないため入らない。

使い方：uv run python manage.py import_holidays
        uv run python manage.py import_holidays --file syukujitsu.csv
        （--file を付けると、ダウンロード済みのファイルを使う）
"""

import csv
import io
import logging
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from core.models import Holiday

logger = logging.getLogger(__name__)

SOURCE_URL = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"


def parse(content: bytes) -> list[tuple[date, str]]:
    """CSV の中身を（日付, 祝日の名前）の並びにする。1行目は見出し。日付は 2026/1/1 の形。"""
    rows = []
    reader = csv.reader(io.StringIO(content.decode("cp932")))
    next(reader, None)  # 見出し
    for row in reader:
        if len(row) < 2 or not row[0].strip():
            continue
        year, month, day = (int(x) for x in row[0].strip().split("/"))
        rows.append((date(year, month, day), row[1].strip()))
    return rows


class Command(BaseCommand):
    help = "内閣府の CSV から祝日を取り込む（BT-02）"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--file", type=Path, help="ダウンロード済みの CSV ファイル（省略すると内閣府から取得）"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["file"]:
            content = options["file"].read_bytes()
        else:
            # 取得先は内閣府の決まった URL だけ（利用者の入力から URL を作らない）
            try:
                with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:  # noqa: S310
                    content = response.read()
            except OSError as e:
                # 通信の失敗（証明書の確認の失敗を含む）。
                # 一時的なことが多いので、やり直すか、手で取得して --file で指定してもらう
                raise CommandError(
                    f"祝日の CSV を取得できませんでした：{e}\n"
                    "時間をおいてやり直すか、"
                    f"{SOURCE_URL} をダウンロードして --file で指定してください。"
                ) from e
        try:
            holidays = parse(content)
        except (UnicodeDecodeError, ValueError) as e:
            raise CommandError(f"祝日の CSV を読めませんでした：{e}") from e
        if not holidays:
            raise CommandError("祝日の CSV に祝日がありません")

        # 全部を入れ替える（祝日が変更・削除された場合にも合わせるため）。1つの DB の更新処理で行う
        with transaction.atomic():
            Holiday.objects.all().delete()
            Holiday.objects.bulk_create(Holiday(date=day, name=name) for day, name in holidays)
        logger.info(
            "祝日を %d 件取り込みました（%s〜%s）", len(holidays), holidays[0][0], holidays[-1][0]
        )
        self.stdout.write(f"{len(holidays)} 件の祝日を取り込みました")
