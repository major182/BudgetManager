"""設定の初期値（DB 設計書 7.4）。id = 1 の1行を登録し、既定の税率を「標準税率 10%」にする。"""

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def create(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    AppSettings = apps.get_model("core", "AppSettings")
    TaxRate = apps.get_model("masters", "TaxRate")
    # そのほかの列は、モデルの既定値（DB 設計書 4.1）のとおり
    AppSettings.objects.create(id=1, default_tax_rate=TaxRate.objects.get(name="標準税率 10%"))


def remove(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    apps.get_model("core", "AppSettings").objects.filter(id=1).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("masters", "0002_initial_data"),
    ]

    operations = [migrations.RunPython(create, remove)]
