from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "offers"

urlpatterns = [
    path("", views.OfferPublicListView.as_view(), name="offer-list"),
]

_router = DefaultRouter()
_router.register("", views.OfferAdminViewSet, basename="admin-offer")
admin_urlpatterns = _router.urls
