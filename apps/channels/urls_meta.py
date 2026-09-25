"""Public Meta lifecycle routes for Instagram Login."""

from django.urls import path

from apps.channels import views_meta

urlpatterns = [
    path("deauthorize/", views_meta.instagram_deauthorize, name="instagram_deauthorize"),
    path("data-deletion/", views_meta.instagram_data_deletion, name="instagram_data_deletion"),
    path(
        "data-deletion/status/<str:confirmation_code>/",
        views_meta.instagram_data_deletion_status,
        name="instagram_data_deletion_status",
    ),
]
