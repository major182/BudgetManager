from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("stats/", views.stats_current, name="stats_current"),
    path("stats/<ym:year_month>/", views.stats, name="stats"),
    path("assets/", views.assets, name="assets"),
]
