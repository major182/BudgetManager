from django.urls import path

from ledger import views

app_name = "ledger"

urlpatterns = [
    # SC-01 家計簿（画面設計書 3章）
    path("ledger/daily/<ym:year_month>/", views.daily, name="daily"),
    path("ledger/calendar/<ym:year_month>/", views.calendar, name="calendar"),
    path("ledger/monthly/<yr:year>/", views.monthly, name="monthly"),
    path("ledger/jump/", views.jump, name="jump"),
    # SC-03 検索
    path("transactions/search/", views.search, name="search"),
    # SC-02 明細入力
    path("transactions/new/", views.new, name="new"),
    path("transactions/<int:pk>/edit/", views.edit, name="edit"),
    path("transactions/<int:pk>/copy/", views.copy, name="copy"),
    path("transactions/<int:pk>/delete/", views.delete, name="delete"),
    # 入力中に htmx が呼ぶもの
    path("transactions/tax-table/", views.tax_table, name="tax_table"),
    path("transactions/suggest/", views.suggest, name="suggest"),
]
