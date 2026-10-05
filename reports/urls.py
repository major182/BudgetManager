from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("stats/", views.stats_current, name="stats_current"),
    path("stats/<ym:year_month>/", views.stats, name="stats"),
    path("assets/", views.assets, name="assets"),
    path("assets/<int:pk>/", views.asset_current, name="asset_current"),
    path("assets/<int:pk>/<ym:year_month>/", views.asset, name="asset"),
]
