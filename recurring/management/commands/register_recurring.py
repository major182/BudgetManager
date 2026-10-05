"""BT-01 定期収支の自動登録。毎日 0:05（日本時間）に cron から実行する（技術選定書 5.9）。

使い方：uv run python manage.py register_recurring
        uv run python manage.py register_recurring --date 2026-10-25  （その日として動かす。確認用）
"""

import logging
from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from recurring.services import register_due

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "定期収支のうち、登録日が来た回を明細として登録する（BT-01）"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--date", type=date.fromisoformat, help="今日の日付の代わりに使う日（YYYY-MM-DD）"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            count = register_due(options["date"])
        except Exception:
            # 失敗もログに残す（NF-OP-02）。cron が失敗に気づけるよう、例外はそのまま投げ直す
            logger.exception("定期収支の自動登録に失敗しました")
            raise
        # 実行結果（登録件数）をログに残す（NF-OP-02）
        logger.info("定期収支の自動登録が終わりました：%d 件", count)
        self.stdout.write(f"{count} 件を登録しました")
