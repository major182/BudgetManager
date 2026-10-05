from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("", views.top, name="top"),
    path("settings/", views.settings_menu, name="settings_menu"),
]
