"""性能の確認用のダミーの明細を作る（テスト仕様書 6章、NF-PF-01〜03）。

開発の DB だけで使う。明細が1件でもあれば何もしない。消すときは --delete。
"""

import random
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.choices import AmountInputType, TransactionKind
from ledger.models import Transaction, TransactionLine
from masters.models import Asset, Category, TaxRate

DUMMY_MEMO = "dummy"


class Command(BaseCommand):
    help = "性能の確認用のダミーの明細を作る（既定は 10年分・40,000件）"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--count", type=int, default=40000)
        parser.add_argument("--years", type=int, default=10)
        parser.add_argument("--delete", action="store_true", help="ダミーの明細を消す")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        if options["delete"]:
            deleted, _ = Transaction.objects.filter(memo=DUMMY_MEMO).delete()
            self.stdout.write(f"{deleted}件を消しました")
            return
        if Transaction.objects.exists():
            raise CommandError("明細がすでにあるため、作りません。")
        rng = random.Random(1)  # noqa: S311  ダミーデータ用（暗号には使わない）
        assets = list(Asset.objects.all())
        rates = list(TaxRate.objects.all())
        expense = list(Category.objects.filter(kind="expense"))
        income = list(Category.objects.filter(kind="income"))
        end = date.today()
        days = options["years"] * 365
        headers: list[Transaction] = []
        for _ in range(options["count"]):
            kind = TransactionKind.INCOME if rng.random() < 0.05 else TransactionKind.EXPENSE
            amount = rng.randint(100, 300000 if kind == TransactionKind.INCOME else 20000)
            headers.append(
                Transaction(
                    kind=kind,
                    date=end - timedelta(days=rng.randrange(days)),
                    asset=rng.choice(assets),
                    amount=amount,
                    amount_input_type=AmountInputType.TAX_INCLUDED,
                    description=f"ダミー{rng.randint(1, 200)}",
                    memo=DUMMY_MEMO,
                )
            )
        Transaction.objects.bulk_create(headers, batch_size=2000)
        lines: list[TransactionLine] = []
        for tx in Transaction.objects.filter(memo=DUMMY_MEMO).only("id", "kind", "amount"):
            rate = rng.choice(rates)
            tax = int(
                (Decimal(tx.amount) * rate.rate / (100 + rate.rate)).quantize(
                    Decimal(1), ROUND_DOWN
                )
            )
            category = rng.choice(income if tx.kind == TransactionKind.INCOME else expense)
            lines.append(
                TransactionLine(
                    transaction=tx,
                    category=category,
                    tax_rate=rate,
                    tax_rate_value=rate.rate,
                    amount_excl=tx.amount - tax,
                    tax_amount=tax,
                    amount_incl=tx.amount,
                )
            )
        TransactionLine.objects.bulk_create(lines, batch_size=2000)
        self.stdout.write(f"{len(headers)}件を作りました")
