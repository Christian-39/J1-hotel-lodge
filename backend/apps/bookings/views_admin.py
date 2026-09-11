"""Staff booking & guest management endpoints (/api/admin/...)."""
import logging
from datetime import datetime

from django.db.models import Count, Max, Prefetch, Q
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsStaffRole
from apps.core.responses import success_response
from apps.core.emails import send_email_safe
from apps.rooms.models import Room

from .models import Booking, BookingRoom, Guest
from .serializers_admin import (
    AdminBookingCreateSerializer,
    AdminBookingDetailSerializer,
    AdminBookingListSerializer,
    AdminBookingModifySerializer,
    AdminGuestDetailSerializer,
    AdminGuestListSerializer,
    AdminGuestUpdateSerializer,
    AssignRoomSerializer,
    RecordActionSerializer,
)
from .serializers import ReceiptSerializer
from .services import booking_service

logger = logging.getLogger("apps")


def _admin_booking_queryset():
    return (
        Booking.objects.select_related("guest", "room_type", "offer")
        .prefetch_related(Prefetch("room_assignments", queryset=BookingRoom.objects.select_related("room"), to_attr="_assignments"))
        .order_by("-created_at")
    )


@extend_schema(tags=["Admin · Bookings"])
class AdminBookingListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsStaffRole]

    def get_serializer_class(self):
        return AdminBookingCreateSerializer if self.request.method == "POST" else AdminBookingListSerializer

    def get_queryset(self):
        qs = _admin_booking_queryset()
        params = self.request.query_params
        if status_param := params.get("status"):
            # Accept comma-separated statuses for operational screens (for
            # example CONFIRMED,CHECKED_IN) without loading all bookings.
            statuses = [value.strip().upper() for value in status_param.split(",") if value.strip()]
            qs = qs.filter(status__in=statuses) if len(statuses) > 1 else qs.filter(status=statuses[0])
        if payment_status := params.get("payment_status"):
            qs = qs.filter(payment_status=payment_status.upper())
        if source := params.get("source"):
            qs = qs.filter(source=source.upper())
        if room_type := params.get("room_type"):
            qs = qs.filter(Q(room_type__slug=room_type) | Q(room_type__pk=room_type if str(room_type).isdigit() else -1))
        if date_from := params.get("date_from"):
            qs = qs.filter(check_in__gte=date_from)
        if date_to := params.get("date_to"):
            qs = qs.filter(check_in__lte=date_to)
        if check_in_on := params.get("check_in"):
            qs = qs.filter(check_in=check_in_on)
        if check_out_on := params.get("check_out"):
            qs = qs.filter(check_out=check_out_on)
        if search := params.get("search"):
            qs = qs.filter(
                Q(booking_reference__icontains=search)
                | Q(guest__first_name__icontains=search)
                | Q(guest__last_name__icontains=search)
                | Q(guest__email__icontains=search)
                | Q(guest__phone__icontains=search)
            )
        ordering = params.get("ordering", "-created_at")
        allowed = {"created_at", "-created_at", "check_in", "-check_in", "check_out", "-check_out", "total_amount", "-total_amount"}
        if ordering in allowed:
            qs = qs.order_by(ordering)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
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
            user=None,
            guest_data=data["guest"],
            source=data["source"],
            require_payment=data["status"] == Booking.Status.PENDING,
            actor=request.user,
            request=request,
        )
        if data.get("internal_notes"):
            booking.internal_notes = data["internal_notes"]
            booking.save(update_fields=["internal_notes", "updated_at"])
        logger.info("Staff %s created manual booking %s", request.user.id, booking.booking_reference)
        return success_response(
            AdminBookingDetailSerializer(booking, context={"request": request}).data,
            message="Booking created.",
            status=status.HTTP_201_CREATED,
        )


def _get_admin_booking(lookup):
    booking = _admin_booking_queryset().filter(
        Q(booking_reference=lookup) | Q(pk=lookup if str(lookup).isdigit() else -1)
    ).first()
    if booking is None:
        raise NotFound()
    return booking


@extend_schema(tags=["Admin · Bookings"])
class AdminBookingDetailView(APIView):
    permission_classes = [IsStaffRole]
    serializer_class = AdminBookingDetailSerializer  # for schema introspection

    def get(self, request, lookup):
        booking = _get_admin_booking(lookup)
        return success_response(AdminBookingDetailSerializer(booking, context={"request": request}).data)

    def patch(self, request, lookup):
        booking = _get_admin_booking(lookup)
        serializer = AdminBookingModifySerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        booking = booking_service.modify_booking(
            booking, staff_user=request.user, data=serializer.validated_data, request=request
        )
        booking = _get_admin_booking(booking.booking_reference)
        return success_response(
            AdminBookingDetailSerializer(booking, context={"request": request}).data,
            message="Booking updated.",
        )


class _BookingActionView(APIView):
    permission_classes = [IsStaffRole]
    # NOTE: do NOT define an `action` attribute on this class — spectacular
    # introspection reads `view.action` (ViewSet concept) and crashes when it
    # is a non-string leftover like `action = None`.
    serializer_class = RecordActionSerializer

    def post(self, request, lookup):
        booking = _get_admin_booking(lookup)
        serializer = RecordActionSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        return self.perform(booking, request, serializer.validated_data)


@extend_schema(tags=["Admin · Bookings"], summary="Confirm a pending booking (pay at hotel)")
class AdminBookingConfirmView(_BookingActionView):
    def perform(self, booking, request, data):
        booking = booking_service.confirm_manual_booking(booking, staff_user=request.user, request=request)
        return success_response(message="Booking confirmed.",
                                data={"booking_reference": booking.booking_reference, "status": booking.status})


@extend_schema(tags=["Admin · Bookings"], summary="Staff-cancel a booking")
class AdminBookingCancelView(_BookingActionView):
    def perform(self, booking, request, data):
        booking = booking_service.cancel_booking(
            booking, reason=data.get("reason", ""), by_user=request.user, staff=True, request=request
        )
        return success_response(message="Booking cancelled.",
                                data={"booking_reference": booking.booking_reference, "status": booking.status})


@extend_schema(tags=["Admin · Bookings"], summary="Check a guest in")
class AdminBookingCheckInView(_BookingActionView):
    def perform(self, booking, request, data):
        booking = booking_service.check_in_booking(booking, staff_user=request.user, request=request)
        return success_response(
            {
                "booking_reference": booking.booking_reference,
                "status": booking.status,
                "checked_in_at": booking.checked_in_at,
            },
            message="Guest checked in.",
        )


@extend_schema(tags=["Admin · Bookings"], summary="Check a guest out")
class AdminBookingCheckOutView(_BookingActionView):
    def perform(self, booking, request, data):
        booking = booking_service.check_out_booking(
            booking,
            staff_user=request.user,
            allow_balance_due=data.get("allow_balance_due", False),
            request=request,
        )
        return success_response(
            {
                "booking_reference": booking.booking_reference,
                "status": booking.status,
                "checked_out_at": booking.checked_out_at,
            },
            message="Guest checked out.",
        )


@extend_schema(tags=["Admin · Bookings"], summary="Mark a booking as no-show")
class AdminBookingNoShowView(_BookingActionView):
    def perform(self, booking, request, data):
        booking = booking_service.mark_no_show(booking, staff_user=request.user, request=request)
        return success_response(message="Booking marked as no-show.",
                                data={"booking_reference": booking.booking_reference, "status": booking.status})


@extend_schema(tags=["Admin · Bookings"], summary="Assign/change a physical room")
class AdminBookingAssignRoomView(_BookingActionView):
    def perform(self, booking, request, data):
        serializer = AssignRoomSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        assignment = booking.room_assignments.select_related("room").filter(pk=payload["assignment_id"]).first()
        if assignment is None:
            raise NotFound("Room assignment not found on this booking.")
        room = Room.objects.filter(pk=payload["room_id"]).first()
        if room is None:
            raise NotFound("Room not found.")
        assignment = booking_service.assign_room(
            assignment, new_room=room, staff_user=request.user, request=request
        )
        return success_response(
            {"assignment_id": assignment.pk, "room_number": assignment.room.room_number},
            message="Room assigned.",
        )


# ---------------------------------------------------------------------------
# Guests
# ---------------------------------------------------------------------------
@extend_schema(tags=["Admin · Guests"])
class AdminGuestListView(generics.ListAPIView):
    permission_classes = [IsStaffRole]
    serializer_class = AdminGuestListSerializer

    def get_queryset(self):
        qs = Guest.objects.annotate(
            bookings_count=Count("bookings", distinct=True),
            last_booking_at=Max("bookings__created_at"),
        ).order_by("-last_booking_at", "-created_at")
        params = self.request.query_params
        if search := params.get("search"):
            qs = qs.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
            )
        return qs


@extend_schema(tags=["Admin · Guests"])
class AdminGuestDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsStaffRole]
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        return AdminGuestUpdateSerializer if self.request.method == "PATCH" else AdminGuestDetailSerializer

    def get_queryset(self):
        return Guest.objects.prefetch_related("bookings__room_type")

    def retrieve(self, request, *args, **kwargs):
        return success_response(self.get_serializer(self.get_object(), context={"request": request}).data)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        from apps.audit.services import log_action

        before = {f: str(getattr(instance, f)) for f in serializer.validated_data}
        instance = serializer.save()
        changes = {
            f: [before[f], str(getattr(instance, f))]
            for f in before
            if before[f] != str(getattr(instance, f))
        }
        if changes:
            log_action(actor=request.user, action="GUEST_UPDATED", instance=instance,
                       changes=changes, request=request)
        return success_response(
            AdminGuestDetailSerializer(instance, context={"request": request}).data,
            message="Guest updated.",
        )

class AdminBookingSendReceiptView(APIView):
    """Send a confirmed payment receipt to the guest after staff approval."""
    permission_classes = [IsStaffRole]

    def post(self, request, lookup):
        booking = _get_admin_booking(lookup)
        if not booking.guest.email:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"email": ["This guest has no email address."]})
        receipt = ReceiptSerializer().to_representation(booking)
        payments = "\n".join(
            f"{p['reference']}: {p['amount']} {p['status']} ({p['paid_at'] or 'date unavailable'})"
            for p in receipt["payments"]
        ) or "No successful payment recorded."
        message = (
            f"{receipt['hotel']['name']}\n\nPayment receipt for booking {receipt['booking_reference']}\n"
            f"Guest: {receipt['guest']['name']}\nStay: {receipt['check_in']} to {receipt['check_out']}\n"
            f"Room: {receipt['room_type']}\nTotal: {receipt['total']} {receipt['currency']}\n"
            f"Amount paid: {receipt['amount_paid']} {receipt['currency']}\n"
            f"Outstanding: {receipt['amount_due']} {receipt['currency']}\n\nPayments:\n{payments}"
        )
        send_email_safe(
            f"Payment receipt — {receipt['booking_reference']}", message, [booking.guest.email]
        )
        return success_response(
            {"booking_reference": booking.booking_reference, "recipient": booking.guest.email},
            message="Receipt queued for delivery.",
        )
