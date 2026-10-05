from django.urls import path

from budgets import views

app_name = "budgets"

urlpatterns = [
    path("settings/budgets/", views.budget_settings, name="settings"),
]
