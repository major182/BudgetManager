from django.urls import path, register_converter

from masters import views


class MasterKindConverter:
    """マスタの種類（URL の一部）。4 種類の名前にだけ当てはまる。

    `settings/<種類>/new/` が、ほかの画面の URL（`settings/recurring/new/` など）に
    当てはまらないようにする。
    """

    regex = "tax-rates|categories|asset-groups|assets"

    def to_python(self, value: str) -> str:
        return value

    def to_url(self, value: str) -> str:
        return value


register_converter(MasterKindConverter, "master")

app_name = "masters"

urlpatterns = [
    # 一覧の画面（画面設計書 3章）
    path("settings/tax-rates/", views.tax_rates, name="tax_rates"),
    path("settings/categories/", views.categories, name="categories"),
    path("settings/assets/", views.assets, name="assets"),
    path("settings/display/", views.display, name="display"),
    # 4種類のマスタに共通の操作。kind は tax-rates・categories・asset-groups・assets
    path("settings/<master:kind>/new/", views.new, name="new"),
    path("settings/<master:kind>/<int:pk>/edit/", views.edit, name="edit"),
    path("settings/<master:kind>/<int:pk>/delete/", views.delete, name="delete"),
    path("settings/<master:kind>/<int:pk>/move/<slug:direction>/", views.move, name="move"),
]
