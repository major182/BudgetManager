"""
URL の割り当て。

管理画面（/admin/）はログインがないため登録しない（技術選定書 7.2 S-06）。
画面を作り始めたら、ここに各画面の URL を追加する。
"""

from django.urls import URLPattern, URLResolver

urlpatterns: list[URLPattern | URLResolver] = []
