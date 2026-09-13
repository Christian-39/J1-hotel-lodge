from django.urls import path

from . import views_admin

app_name = "accounts_admin"

urlpatterns = [
    path("", views_admin.AdminUserListCreateView.as_view(), name="user-list"),
    # Registered BEFORE the numeric detail route so "staff/" is never captured
    # as a user id.
    path("staff/<int:pk>/", views_admin.AdminStaffProfileView.as_view(), name="staff-profile"),
    path("<int:pk>/", views_admin.AdminUserDetailView.as_view(), name="user-detail"),
]
