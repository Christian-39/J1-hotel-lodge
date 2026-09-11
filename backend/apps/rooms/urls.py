from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views, views_admin

app_name = "rooms"

# Public catalog ("rooms" == room types for guests)
urlpatterns = [
    path("", views.RoomTypeListView.as_view(), name="room-type-list"),
    path("<slug:slug>/", views.RoomTypeDetailView.as_view(), name="room-type-detail"),
]

# Staff management routers
_room_type_router = DefaultRouter()
_room_type_router.register("", views_admin.RoomTypeAdminViewSet, basename="admin-room-type")

_room_router = DefaultRouter()
_room_router.register("", views_admin.RoomAdminViewSet, basename="admin-room")

_amenity_router = DefaultRouter()
_amenity_router.register("", views_admin.AmenityAdminViewSet, basename="admin-amenity")

admin_room_types_urlpatterns = _room_type_router.urls + [
    path("<int:room_type_id>/images/", views_admin.RoomTypeImageUploadView.as_view(), name="room-type-image-upload"),
]
admin_rooms_urlpatterns = _room_router.urls
admin_amenities_urlpatterns = _amenity_router.urls
admin_room_images_urlpatterns = [
    path("room/<int:room_id>/", views_admin.RoomImageUploadView.as_view(), name="room-image-upload"),
    path("<int:pk>/", views_admin.RoomImageDetailView.as_view(), name="room-image-detail"),
]
