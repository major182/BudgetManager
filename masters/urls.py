from django.urls import path

from masters import views

app_name = "masters"

urlpatterns = [
    # 一覧の画面（画面設計書 3章）
    path("settings/tax-rates/", views.tax_rates, name="tax_rates"),
    path("settings/categories/", views.categories, name="categories"),
    path("settings/assets/", views.assets, name="assets"),
    path("settings/display/", views.display, name="display"),
    # 4種類のマスタに共通の操作。kind は tax-rates・categories・asset-groups・assets
    path("settings/<slug:kind>/new/", views.new, name="new"),
    path("settings/<slug:kind>/<int:pk>/edit/", views.edit, name="edit"),
    path("settings/<slug:kind>/<int:pk>/delete/", views.delete, name="delete"),
    path("settings/<slug:kind>/<int:pk>/move/<slug:direction>/", views.move, name="move"),
]
