from django.urls import path

from . import views_admin

app_name = "payments_admin"

urlpatterns = [
    path("", views_admin.AdminPaymentListView.as_view(), name="payment-list"),
    path("record/", views_admin.AdminRecordOfflinePaymentView.as_view(), name="payment-record"),
    path("<str:lookup>/", views_admin.AdminPaymentDetailView.as_view(), name="payment-detail"),
]
