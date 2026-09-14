"""Public room catalog endpoints.

"Rooms" on the public site are bookable ROOM TYPES. A room type is also the
only thing a guest can search availability for; the individual physical rooms
behind it are exposed through one narrow, read-only endpoint
(``/api/rooms/{slug}/rooms/``) so that "Book this room — Room 203" can be
honoured. That endpoint deliberately returns the bare minimum (id, number,
floor and, when dates are supplied, whether the room is free) — housekeeping
state, notes, status flags and anything else operational stay internal.
"""
from datetime import datetime, timedelta

from django.db.models import Prefetch
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from drf_spectacular.types import OpenApiTypes
from rest_framework import generics
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny

from apps.bookings.services import availability
from apps.core.responses import success_response
from apps.offers.services import offers_for_room_type

from .models import Room, RoomType, RoomTypeImage
from .serializers import (
    PublicRoomOptionSerializer,
    RoomTypeDetailSerializer,
    RoomTypeListSerializer,
)


def _catalog_queryset():
    # Only active images are ever shown publicly; prefetching the filtered set
    # lets the serializers reuse one cache instead of querying per room type.
    return (
        RoomType.objects.filter(is_active=True)
        .prefetch_related(
            "amenities",
            Prefetch("images", queryset=RoomTypeImage.objects.filter(is_active=True).order_by("display_order", "id")),
        )
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


@extend_schema(
    tags=["Rooms"],
    summary='Physical rooms of a room type (for book-this-room)',
    parameters=[
        OpenApiParameter("check_in", OpenApiTypes.DATE, required=False,
                         description="Optional. When both dates are given each "
                                     "room reports whether it is free."),
        OpenApiParameter("check_out", OpenApiTypes.DATE, required=False),
    ],
)
class RoomTypeUnavailableDatesView(generics.GenericAPIView):
    """Return sold-out dates for one room type using a bounded, two-query sweep."""
    permission_classes = [AllowAny]
    serializer_class = PublicRoomOptionSerializer

    def get(self, request, slug):
        room_type = _catalog_queryset().filter(slug=slug).first()
        if room_type is None and str(slug).isdigit():
            room_type = _catalog_queryset().filter(pk=int(slug)).first()
        if room_type is None:
            raise NotFound()
        today = timezone.localdate()
        try:
            days = min(max(int(request.query_params.get("days", 365)), 1), 366)
        except (TypeError, ValueError):
            raise ValidationError({"days": ["Days must be a whole number."]})
        end = today + timedelta(days=days)
        sellable_ids = set(Room.objects.filter(
            room_type=room_type, is_active=True
        ).exclude(status__in=availability.OPERATIONALLY_BLOCKED).values_list("id", flat=True))
        assignments = list(
            availability.BookingRoom.objects.filter(room_id__in=sellable_ids)
            .filter(availability.blocking_booking_q(prefix="booking"))
            .filter(booking__check_in__lt=end, booking__check_out__gt=today)
            .values_list("room_id", "booking__check_in", "booking__check_out")
        )
        unavailable = []
        current = today
        while current < end:
            following = current + timedelta(days=1)
            blocked = {room_id for room_id, check_in, check_out in assignments
                       if check_in < following and check_out > current}
            if not sellable_ids or len(blocked) >= len(sellable_ids):
                unavailable.append(current.isoformat())
            current = following
        return success_response({
            "room_type": room_type.slug,
            "from": today.isoformat(),
            "through": (end - timedelta(days=1)).isoformat(),
            "unavailable_dates": unavailable,
        })


class RoomTypeRoomsView(generics.ListAPIView):
    """The physical rooms that make up one room type.

    Only rooms the hotel can actually sell are listed: the type must be active,
    the room must be active and it must not be under maintenance or out of
    service. Availability is answered by the authoritative availability engine,
    never by a client-side hint.
    """

    permission_classes = [AllowAny]
    serializer_class = PublicRoomOptionSerializer
    pagination_class = None

    def get_room_type(self):
        lookup = self.kwargs.get("slug", "")
        qs = _catalog_queryset()
        obj = qs.filter(slug=lookup).first()
        if obj is None and str(lookup).isdigit():
            obj = qs.filter(pk=int(lookup)).first()
        if obj is None:
            raise NotFound()
        return obj

    def _window(self):
        params = self.request.query_params
        raw_in, raw_out = params.get("check_in"), params.get("check_out")
        if not raw_in and not raw_out:
            return None
        if not raw_in or not raw_out:
            raise ValidationError({"check_in": ["Provide both dates to check availability."]})
        try:
            check_in = datetime.strptime(raw_in, "%Y-%m-%d").date()
            check_out = datetime.strptime(raw_out, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            raise ValidationError({"check_in": ["Dates must use YYYY-MM-DD format."]})
        if check_out <= check_in:
            raise ValidationError({"check_out": ["Check-out must be after check-in."]})
        return (check_in, check_out, timezone.now())

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["window"] = self._window()
        return context

    def get_queryset(self):
        return (
            Room.objects.filter(room_type=self.get_room_type(), is_active=True)
            .exclude(status__in=availability.OPERATIONALLY_BLOCKED)
            .select_related("room_type")
            .order_by("room_number")
        )
