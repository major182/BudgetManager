from django.urls import path

from recurring import views

app_name = "recurring"

urlpatterns = [
    path("settings/recurring/", views.items, name="items"),
    path("settings/recurring/new/", views.new, name="new"),
    path("settings/recurring/<int:pk>/edit/", views.edit, name="edit"),
    path("settings/recurring/<int:pk>/delete/", views.delete, name="delete"),
    path("settings/recurring/preview/", views.preview, name="preview"),
]
