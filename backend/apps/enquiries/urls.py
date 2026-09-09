from django.urls import path

from . import views

app_name = "enquiries"

urlpatterns = [
    path("", views.EnquiryCreateView.as_view(), name="create"),
]

admin_urlpatterns = [
    path("", views.EnquiryAdminListView.as_view(), name="admin-list"),
    path("<int:pk>/", views.EnquiryAdminDetailView.as_view(), name="admin-detail"),
]
