from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("stats/", views.stats_current, name="stats_current"),
    path("stats/<ym:year_month>/", views.stats, name="stats"),
    path("stats/year/<yr:year>/", views.stats_year, name="stats_year"),
    path("stats/trends/categories/<int:pk>/", views.trend_category, name="trend_category"),
    path("stats/trends/assets/", views.trend_assets, name="trend_assets"),
    path("assets/", views.assets, name="assets"),
    path("assets/<int:pk>/", views.asset_current, name="asset_current"),
    path("assets/<int:pk>/<ym:year_month>/", views.asset, name="asset"),
]
