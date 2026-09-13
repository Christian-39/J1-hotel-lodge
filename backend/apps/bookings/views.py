"""Guest-facing booking endpoints: availability, quotes, booking lifecycle."""
import logging
from datetime import datetime

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from drf_spectacular.types import OpenApiTypes
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.exceptions import InvalidDatesError
from apps.core.permissions import IsOwnerOrStaff
from apps.core.responses import success_response
from apps.hotel.models import HotelSettings

from .models import Booking
from .serializers import (
    AvailabilityQuerySerializer,
    BookingCreateSerializer,
    BookingDetailSerializer,
    BookingListSerializer,
    CancelBookingSerializer,
    QuoteRequestSerializer,
    ReceiptSerializer,
)
from .services import booking_service, pricing

logger = logging.getLogger("apps")


def _parse_date(value, field_name):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise InvalidDatesError(f"Parameter '{field_name}' must be a date in YYYY-MM-DD format.")


@extend_schema(
    tags=["Bookings"],
    summary="Authoritative room availability search",
    parameters=[
        OpenApiParameter("check_in", OpenApiTypes.DATE, required=True),
        OpenApiParameter("check_out", OpenApiTypes.DATE, required=True),
        OpenApiParameter("guests", int, required=False),
        OpenApiParameter("rooms", int, required=False),
        OpenApiParameter("room_type", str, required=False, description="Room type slug or id"),
    ],
)
class AvailabilityView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "availability"
    serializer_class = AvailabilityQuerySerializer  # schema + date validation

    def get(self, request):
        params = request.query_params
        check_in_raw, check_out_raw = params.get("check_in"), params.get("check_out")
        if not check_in_raw or not check_out_raw:
            raise ValidationError(
                {"check_in": ["Required."], "check_out": ["Required."]}
            )
        check_in = _parse_date(check_in_raw, "check_in")
        check_out = _parse_date(check_out_raw, "check_out")
        try:
            guests = max(1, int(params.get("guests", 1)))
            rooms = max(1, int(params.get("rooms", 1)))
        except ValueError:
            raise ValidationError({"guests": ["Must be a number."], "rooms": ["Must be a number."]})

        # Date sanity is a pricing-engine rule, applied here too for clean errors.
        pricing.validate_stay_dates(check_in, check_out)

        results = booking_service.search_availability(
            check_in=check_in,
            check_out=check_out,
            guests=guests,
            rooms=rooms,
            room_type_value=params.get("room_type") or None,
            request=request,   # absolute image URLs for the separately hosted frontend
        )
        return success_response(
            {
                "check_in": check_in.isoformat(),
                "check_out": check_out.isoformat(),
                "nights": (check_out - check_in).days,
                "guests": guests,
                "rooms": rooms,
                "results": results,
            },
            message="Availability retrieved." if results else "No room types available.",
        )


@extend_schema(tags=["Bookings"], summary="Authoritative price quote (no booking created)")
class QuoteView(APIView):
    permission_classes = [AllowAny]
    serializer_class = QuoteRequestSerializer

    def post(self, request):
        serializer = QuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        room_type = booking_service.resolve_room_type(data["room_type"])
        settings_obj = HotelSettings.get_settings()
        quote = pricing.calculate_quote(
            room_type=room_type,
            check_in=data["check_in"],
            check_out=data["check_out"],
            rooms=data["rooms"],
            adults=data["adults"],
            children=data["children"],
            offer_code=data.get("offer_code") or None,
            settings_obj=settings_obj,
        )
        payload = {
            "room_type": {"id": room_type.pk, "name": room_type.name, "slug": room_type.slug},
            "check_in": data["check_in"].isoformat(),
            "check_out": data["check_out"].isoformat(),
            **quote.to_api_dict(),
            "policies": {
                "check_in_time": settings_obj.check_in_time.strftime("%H:%M"),
                "check_out_time": settings_obj.check_out_time.strftime("%H:%M"),
                "cancellation_deadline_hours": settings_obj.cancellation_deadline_hours,
                "cancellation_fee_percent": str(settings_obj.cancellation_fee_percent),
            },
            "hold_info": {
                "pending_booking_minutes": settings_obj.pending_booking_minutes,
                "note": "Inventory is held for this many minutes once the booking is created.",
            },
        }
        return success_response(payload, message="Quote calculated.")


@extend_schema(tags=["Bookings"])
class MyBookingsView(generics.ListCreateAPIView):
    """GET: my bookings (paginated). POST: create a pending booking."""

    permission_classes = [IsAuthenticated]
    serializer_class = BookingListSerializer

    def get_queryset(self):
        qs = (
            Booking.objects.filter(guest__user=self.request.user)
            .select_related("guest", "room_type")
            .order_by("-created_at")
        )
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param.upper())
        return qs

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "booking_create"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def create(self, request, *args, **kwargs):
        serializer = BookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        booking = booking_service.create_booking(
            room_type_value=data["room_type"],
            check_in=data["check_in"],
            check_out=data["check_out"],
            rooms=data["rooms"],
            adults=data["adults"],
            children=data["children"],
            offer_code=data.get("offer_code") or None,
            special_requests=data.get("special_requests", ""),
            user=request.user,
            guest_data=data.get("guest") or None,
            request=request,
            room_id=data.get("room_id"),
        )
        payload = BookingDetailSerializer(booking, context={"request": request}).data
        substitution = getattr(booking, "room_substitution", None)
        if substitution:
            # Never switch rooms silently — the guest is told on the
            # confirmation screen (and the receipt shows the assigned room).
            payload["room_substitution"] = substitution
        return success_response(
            payload,
            message="Booking created. Complete payment to confirm your reservation.",
            status=status.HTTP_201_CREATED,
        )


class _OwnedBookingMixin:
    """Resolve a booking by pk or reference + enforce object ownership."""

    permission_classes = [IsAuthenticated, IsOwnerOrStaff]

    def get_booking(self):
        lookup = self.kwargs["lookup"]
        booking = (
            Booking.objects.filter(
                Q(booking_reference=lookup) | Q(pk=lookup if str(lookup).isdigit() else -1)
            )
            .select_related("guest", "guest__user", "room_type", "offer")
            .prefetch_related("room_assignments__room", "payments")
            .first()
        )
        if booking is None:
            raise NotFound()
        self.check_object_permissions(self.request, booking)
        return booking_service.refresh_expired_pending(booking)


@extend_schema(tags=["Bookings"], summary="Booking detail by id or reference")
class BookingDetailView(_OwnedBookingMixin, APIView):
    serializer_class = BookingDetailSerializer

    def get(self, request, lookup):
        booking = self.get_booking()
        return success_response(
            BookingDetailSerializer(booking, context={"request": request}).data
        )


@extend_schema(tags=["Bookings"], summary="Cancel my booking")
class BookingCancelView(_OwnedBookingMixin, APIView):
    serializer_class = CancelBookingSerializer

    def post(self, request, lookup):
        booking = self.get_booking()
        serializer = CancelBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = booking_service.cancel_booking(
            booking,
            reason=serializer.validated_data.get("reason", ""),
            by_user=request.user,
            staff=False,
            request=request,
        )
        return success_response(
            BookingDetailSerializer(booking, context={"request": request}).data,
            message="Booking cancelled.",
        )


@extend_schema(tags=["Bookings"], summary="Receipt for a booking")
class BookingReceiptView(_OwnedBookingMixin, APIView):
    serializer_class = BookingDetailSerializer  # response envelope documented in contract

    def get(self, request, lookup):
        booking = self.get_booking()
        return success_response(ReceiptSerializer().to_representation(booking))
