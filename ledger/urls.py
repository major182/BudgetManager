from django.urls import path

from ledger import views

app_name = "ledger"

urlpatterns = [
    path("ledger/daily/<ym:year_month>/", views.daily, name="daily"),
]
