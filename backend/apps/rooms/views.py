"""Public room catalog endpoints.

"Rooms" on the public site are bookable ROOM TYPES. Physical room numbers are
an internal/staff concept and are never exposed publicly.
"""
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny

from apps.core.responses import success_response
from apps.offers.services import offers_for_room_type

from .models import RoomType
from .serializers import RoomTypeDetailSerializer, RoomTypeListSerializer


def _catalog_queryset():
    return (
        RoomType.objects.filter(is_active=True)
        .prefetch_related("amenities", "images")
        .order_by("display_order", "name")
    )


@extend_schema(tags=["Rooms"], summary="List active room types")
class RoomTypeListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = RoomTypeListSerializer
    pagination_class = None

    def get_queryset(self):
        return _catalog_queryset()


@extend_schema(tags=["Rooms"], summary="Room type detail (images, amenities, applicable offers)")
class RoomTypeDetailView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = RoomTypeDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return _catalog_queryset()

    def get_object(self):
        lookup = self.kwargs.get("slug", "")
        qs = self.get_queryset()
        obj = qs.filter(slug=lookup).first()
        if obj is None and lookup.isdigit():
            obj = qs.filter(pk=int(lookup)).first()
        if obj is None:
            raise NotFound()
        return obj

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        data = self.get_serializer(instance).data
        data["offers"] = offers_for_room_type(instance)
        return success_response(data)
