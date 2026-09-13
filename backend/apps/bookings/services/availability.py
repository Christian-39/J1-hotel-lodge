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
                             for_update=False, exclude_booking_id=None, exclude_room_ids=()):
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
    if exclude_room_ids:
        qs = qs.exclude(pk__in=[pk for pk in exclude_room_ids if pk])
    if for_update:
        qs = qs.select_for_update()
    return qs


def _first_available_room(room_type, *, check_in, check_out, now=None, exclude_room_ids=()):
    """Cheapest possible answer to \"is anything free in this type?\" — one row."""
    return available_rooms_queryset(
        room_type=room_type,
        check_in=check_in,
        check_out=check_out,
        now=now,
        exclude_room_ids=exclude_room_ids,
    ).select_related("room_type").first()


def find_substitute_room(*, room_type, check_in, check_out, guests=1, now=None,
                         exclude_room_ids=()):
    """Deterministic replacement for an exact room that just became unavailable.

    The availability engine stays authoritative: nothing here trusts a
    frontend claim, and a substitute is only returned when it is genuinely
    free for the requested ``[check_in, check_out)`` window.

    Preference order
    ----------------
    1. another room of the **same room type** with the **same nightly rate**
       (within one type the rate is identical by definition; ties break on
       ``room_number`` so the choice is deterministic, never random).
    2. same room type, closest nightly rate — a no-op under the current
       per-type pricing model, kept so the ordering stays correct if
       per-room rates are ever introduced.
    3. a different **active room type** whose nightly rate is **identical**
       and whose capacity covers the party. Because the rate matches, the
       stay total the guest already saw does not change.
    4. "Closest suitable room" at a *different* price is deliberately NOT
       auto-selected: a changed total may never be applied to a guest's
       booking without their explicit consent. The caller surfaces
       ``ROOM_UNAVAILABLE`` and the availability search lists what is free.

    Returns ``None`` when no acceptable substitute exists, otherwise a dict
    describing the substitution (the caller is responsible for telling the
    guest — a substitution may never happen silently).
    """
    from decimal import Decimal

    guests = max(1, int(guests or 1))
    exclude = {pk for pk in (exclude_room_ids or ()) if pk}

    # --- Levels 1 & 2: same room type, closest rate, deterministic order ----
    candidates = list(
        available_rooms_queryset(
            room_type=room_type, check_in=check_in, check_out=check_out,
            now=now, exclude_room_ids=exclude,
        ).select_related("room_type")
    )
    if candidates:
        target = Decimal(room_type.base_price)
        candidates.sort(key=lambda r: (abs(Decimal(r.room_type.base_price) - target), r.room_number))
        room = candidates[0]
        return {
            "room": room,
            "room_type": room.room_type,
            "level": 1 if room.room_type.base_price == target else 2,
            "price_changed": room.room_type.base_price != target,
            "reason": (
                f"Room {room.room_number} is available in the same room type "
                f"({room.room_type.name}) for the same nightly rate."
            ),
        }

    # --- Level 3: identical rate in another type that can hold the party ----
    target = Decimal(room_type.base_price)
    alt_types = (
        RoomType.objects.filter(is_active=True, max_guests__gte=guests)
        .exclude(pk=room_type.pk)
        .order_by("display_order", "name")
    )
    best = None
    for alt in alt_types:
        room = _first_available_room(
            alt, check_in=check_in, check_out=check_out, now=now, exclude_room_ids=exclude
        )
        if room is None:
            continue
        diff = abs(Decimal(alt.base_price) - target)
        key = (diff, alt.max_guests, alt.name)
        if best is None or key < best[0]:
            best = (key, room, alt, diff)
    if best is not None and best[3] == 0:
        _, room, alt, _diff = best
        return {
            "room": room,
            "room_type": alt,
            "level": 3,
            "price_changed": False,
            "reason": (
                f"Room {room.room_number} ({alt.name}) has the same nightly rate "
                f"and sleeps up to {alt.max_guests} guests."
            ),
        }
    return None


def available_room_count(*, room_type, check_in, check_out, now=None):
    return available_rooms_queryset(
        room_type=room_type, check_in=check_in, check_out=check_out, now=now
    ).count()


def count_active_blocking(booking):
    """How many physical rooms a booking currently blocks (usually == number_of_rooms)."""
    return BookingRoom.objects.filter(booking=booking).count()
