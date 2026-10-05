"""初期データ（DB 設計書 7.1〜7.3、要件定義書 5.3）。

マイグレーションで登録することで、どの環境でも同じ内容になる。
"""

from decimal import Decimal

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

TAX_RATES = [
    ("標準税率 10%", Decimal("10.0")),
    ("軽減税率 8%", Decimal("8.0")),
    ("非課税・対象外 0%", Decimal("0.0")),
]

# (名前, 既定の税率の名前)。既定の税率は、その分類で一般的に最も多い取引に合わせる（7.2）
EXPENSE_CATEGORIES = [
    ("食費", "軽減税率 8%"),
    ("備品・衣類", "標準税率 10%"),
    ("交通費", "標準税率 10%"),
    ("レジャー・趣味", "標準税率 10%"),
    ("交際費", "標準税率 10%"),
    ("通信費", "標準税率 10%"),
    ("健康・医療", "非課税・対象外 0%"),
    ("光熱費", "標準税率 10%"),
    ("保険", "非課税・対象外 0%"),
    ("税金", "非課税・対象外 0%"),
    ("その他", "標準税率 10%"),
]
INCOME_CATEGORIES = ["給与", "賞与", "臨時収入", "利息", "その他"]  # すべて 0%

ASSET_GROUPS = ["現金", "銀行", "クレジットカード", "電子マネー"]


def create(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    TaxRate = apps.get_model("masters", "TaxRate")
    Category = apps.get_model("masters", "Category")
    AssetGroup = apps.get_model("masters", "AssetGroup")
    Asset = apps.get_model("masters", "Asset")

    rates = {}
    for order, (name, rate) in enumerate(TAX_RATES, start=1):
        rates[name] = TaxRate.objects.create(name=name, rate=rate, sort_order=order)

    for order, (name, rate_name) in enumerate(EXPENSE_CATEGORIES, start=1):
        Category.objects.create(kind="expense", name=name, default_tax_rate=rates[rate_name], sort_order=order)
    for order, name in enumerate(INCOME_CATEGORIES, start=1):
        Category.objects.create(
            kind="income", name=name, default_tax_rate=rates["非課税・対象外 0%"], sort_order=order
        )

    groups = {}
    for order, name in enumerate(ASSET_GROUPS, start=1):
        groups[name] = AssetGroup.objects.create(name=name, sort_order=order)
    Asset.objects.create(asset_group=groups["現金"], name="現金", opening_balance=0, sort_order=1)


def remove(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    # 戻すときは初期データだけを消す（登録した順と逆に）
    apps.get_model("masters", "Asset").objects.filter(name="現金").delete()
    apps.get_model("masters", "AssetGroup").objects.filter(name__in=ASSET_GROUPS).delete()
    apps.get_model("masters", "Category").objects.all().delete()
    apps.get_model("masters", "TaxRate").objects.filter(name__in=[n for n, _ in TAX_RATES]).delete()


class Migration(migrations.Migration):
    dependencies = [("masters", "0001_initial")]

    operations = [migrations.RunPython(create, remove)]
