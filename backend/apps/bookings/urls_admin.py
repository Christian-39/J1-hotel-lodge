from django.urls import path

from . import views_admin

app_name = "bookings_admin"

bookings_urlpatterns = [
    path("", views_admin.AdminBookingListCreateView.as_view(), name="booking-list"),
    path("<str:lookup>/", views_admin.AdminBookingDetailView.as_view(), name="booking-detail"),
    path("<str:lookup>/confirm/", views_admin.AdminBookingConfirmView.as_view(), name="booking-confirm"),
    path("<str:lookup>/cancel/", views_admin.AdminBookingCancelView.as_view(), name="booking-cancel"),
    path("<str:lookup>/check-in/", views_admin.AdminBookingCheckInView.as_view(), name="booking-check-in"),
    path("<str:lookup>/check-out/", views_admin.AdminBookingCheckOutView.as_view(), name="booking-check-out"),
    path("<str:lookup>/no-show/", views_admin.AdminBookingNoShowView.as_view(), name="booking-no-show"),
    path("<str:lookup>/assign-room/", views_admin.AdminBookingAssignRoomView.as_view(), name="booking-assign-room"),
]

guests_urlpatterns = [
    path("", views_admin.AdminGuestListView.as_view(), name="guest-list"),
    path("<int:pk>/", views_admin.AdminGuestDetailView.as_view(), name="guest-detail"),
]
