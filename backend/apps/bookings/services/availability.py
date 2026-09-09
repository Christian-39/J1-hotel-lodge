"""Authoritative availability engine.

A room blocks a requested [check_in, check_out) range when it has an ACTIVE
assignment that OVERLAPS:

    existing.check_in < new.check_out  AND  new.check_in < existing.check_out

=> a booking ending 2026-10-15 does not block one starting 2026-10-15
(checkout day == next guest's check-in day).

"Active" assignments belong to bookings that are CONFIRMED/CHECKED_IN, or
PENDING with a live (unexpired) hold. Expired pending holds never block
inventory. Rooms under maintenance/out-of-service are excluded altogether.
"""
from datetime import date

from django.db.models import Q
from django.utils import timezone

from apps.rooms.models import Room, RoomType

from ..models import Booking, BookingRoom

BLOCKING_STATUSES = (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN)
OPERATIONALLY_BLOCKED = (Room.Status.MAINTENANCE, Room.Status.OUT_OF_SERVICE)


def blocking_booking_q(now=None, prefix=""):
    now = now or timezone.now()
    p = f"{prefix}__" if prefix else ""
    return Q(**{f"{p}status__in": BLOCKING_STATUSES}) | Q(
        **{f"{p}status": Booking.Status.PENDING, f"{p}expires_at__gt": now}
    )


def overlap_q(check_in: date, check_out: date, prefix=""):
    p = f"{prefix}__" if prefix else ""
    return Q(**{f"{p}check_in__lt": check_out}) & Q(**{f"{p}check_out__gt": check_in})


def blocked_room_ids(*, room_type_id, check_in, check_out, now=None, exclude_booking_id=None):
    qs = (
        BookingRoom.objects.filter(room__room_type_id=room_type_id)
        .filter(blocking_booking_q(now=now, prefix="booking"))
        .filter(overlap_q(check_in, check_out))
    )
    if exclude_booking_id:
        qs = qs.exclude(booking_id=exclude_booking_id)
    return qs.values_list("room_id", flat=True).distinct()


def available_rooms_queryset(*, room_type, check_in, check_out, now=None,
                             for_update=False, exclude_booking_id=None):
    qs = (
        Room.objects.filter(room_type=room_type, is_active=True)
        .exclude(status__in=OPERATIONALLY_BLOCKED)
        .exclude(
            pk__in=blocked_room_ids(
                room_type_id=room_type.pk,
                check_in=check_in,
                check_out=check_out,
                now=now,
                exclude_booking_id=exclude_booking_id,
            )
        )
        .order_by("room_number")
    )
    if for_update:
        qs = qs.select_for_update()
    return qs


def available_room_count(*, room_type, check_in, check_out, now=None):
    return available_rooms_queryset(
        room_type=room_type, check_in=check_in, check_out=check_out, now=now
    ).count()


def count_active_blocking(booking):
    """How many physical rooms a booking currently blocks (usually == number_of_rooms)."""
    return BookingRoom.objects.filter(booking=booking).count()
