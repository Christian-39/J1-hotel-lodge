from django.urls import path

from . import views_admin

app_name = "accounts_admin"

urlpatterns = [
    path("", views_admin.AdminUserListCreateView.as_view(), name="user-list"),
    path("<int:pk>/", views_admin.AdminUserDetailView.as_view(), name="user-detail"),
]
