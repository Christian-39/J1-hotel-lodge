from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="list"),
    path("unread-count/", views.UnreadCountView.as_view(), name="unread-count"),
    path("read-all/", views.MarkAllReadView.as_view(), name="read-all"),
    # Detail MUST be registered before "<int:pk>/read/" is resolved — with
    # DRF's default trailing-slash routing both are distinct paths, but keeping
    # the ordering explicit documents the intent.
    path("<int:pk>/", views.NotificationDetailView.as_view(), name="detail"),
    path("<int:pk>/read/", views.MarkReadView.as_view(), name="mark-read"),
]
