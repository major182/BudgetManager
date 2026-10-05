"""全テンプレートで使う値。"""

from django.http import HttpRequest

from core.models import AppSettings


def app_settings(request: HttpRequest) -> dict[str, AppSettings]:
    """設定（テーマ・金額の表示など）をテンプレートに渡す。"""
    return {"app_settings": AppSettings.load()}
