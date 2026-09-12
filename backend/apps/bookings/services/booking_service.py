"""Booking business operations.

All multi-step, integrity-sensitive operations live here — views stay thin.
Every state change is audited; every public notification is emitted here.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from apps.audit.services import log_action
from apps.core.emails import send_email_safe
from apps.core.exceptions import (
    BookingExpiredError,
    BookingStateError,
    CancellationNotAllowedError,
    InvalidDatesError,
    OutstandingBalanceError,
    RoomUnavailableError,
)
from apps.core.utils import combine_hotel_datetime, generate_booking_reference, hotel_today
from apps.hotel.models import HotelSettings
from apps.notifications.services import notify_staff, notify_users
from apps.offers import services as offer_services
from apps.rooms.models import Room, RoomType

from ..models import Booking, BookingRoom, Guest
from . import availability
from .pricing import calculate_quote

logger = logging.getLogger("apps")

GUEST_BOOKING_LINK = "/my-bookings.html"
STAFF_BOOKING_LINK = "/dashboard/booking-details.html"

# Staff are warned this many minutes before a checked-in guest's scheduled
# checkout time (spec: 30-minute checkout warning).
CHECKOUT_WARNING_MINUTES = 30


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def resolve_room_type(value, *, active_only=True, queryset=None):
    qs = queryset or RoomType.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    obj = qs.filter(slug=str(value)).first()
    if obj is None and str(value).isdigit():
        obj = qs.filter(pk=int(value)).first()
    return obj


def get_booking_by_reference_or_id(lookup):
    booking = Booking.objects.filter(booking_reference=lookup).first()
    if booking is None and str(lookup).isdigit():
        booking = Booking.objects.filter(pk=int(lookup)).first()
    return booking


def guest_booking_link(booking):
    return f"{GUEST_BOOKING_LINK}?ref={booking.booking_reference}"


def staff_booking_link(booking):
    return f"{STAFF_BOOKING_LINK}?ref={booking.booking_reference}"


def _unique_booking_reference():
    for _ in range(10):
        reference = generate_booking_reference()
        if not Booking.objects.filter(booking_reference=reference).exists():
            return reference
    raise RuntimeError("Could not allocate a unique booking reference.")


def refresh_expired_pending(booking):
    """Lazily flip an expired PENDING booking and release its hold."""
    if booking.is_expired_pending:
        expire_pending_booking(booking)
        booking.refresh_from_db()
    return booking


# ---------------------------------------------------------------------------
# Availability search (public)
# ---------------------------------------------------------------------------
def search_availability(*, check_in, check_out, guests=1, rooms=1, room_type_value=None):
    from apps.rooms.serializers import RoomTypeListSerializer

    settings_obj = HotelSettings.get_settings()
    types_qs = (
        RoomType.objects.filter(is_active=True)
        .prefetch_related("amenities", "images")
        .order_by("display_order", "name")
    )
    if room_type_value:
        selected = resolve_room_type(room_type_value, queryset=types_qs)
        types_qs = types_qs.filter(pk=selected.pk) if selected else types_qs.none()

    if guests and guests > rooms * 12:  # hard sanity cap on abuse
        from apps.core.exceptions import CapacityExceededError

        raise CapacityExceededError("Guest count is too large for the requested rooms.")

    results = []
    for room_type in types_qs:
        available_count = availability.available_room_count(
            room_type=room_type, check_in=check_in, check_out=check_out
        )
        capacity_error = None
        pricing = None
        bookable = False
        try:
            quote = calculate_quote(
                room_type=room_type, check_in=check_in, check_out=check_out,
                rooms=rooms, adults=guests, children=0, settings_obj=settings_obj,
            )
            pricing = quote.to_api_dict()
            bookable = available_count >= rooms
        except InvalidDatesError:
            raise
        except Exception as exc:  # capacity overflow → report but keep other types
            capacity_error = str(getattr(exc, "detail", exc))

        results.append(
            {
                "room_type": RoomTypeListSerializer(room_type).data,
                "available_rooms": available_count,
                "requested_rooms": rooms,
                "max_guests_per_room": room_type.max_guests,
                "extra_guest_allowed": room_type.extra_guest_allowed,
                "bookable": bookable and capacity_error is None,
                "pricing": pricing,
                "message": capacity_error
                or (None if bookable else "Not enough rooms available for these dates."),
            }
        )
    return results


# ---------------------------------------------------------------------------
# Guest records
# ---------------------------------------------------------------------------
def upsert_guest(*, user=None, guest_data=None) -> Guest:
    """Find-or-create the Guest record used for a booking.

    Logged-in guests reuse their profile-linked record; contact details sent
    with the booking may update it. Staff-supplied data (no user account)
    matches an existing standalone record by email.
    """
    data = guest_data or {}
    if user is not None:
        guest = getattr(user, "guest_profile", None)
    else:
        guest = Guest.objects.filter(
            email__iexact=data.get("email", "").strip(), user__isnull=True
        ).first() if data.get("email") else None

    values = {
        "first_name": data.get("first_name") or (user.first_name if user else ""),
        "last_name": data.get("last_name") or (user.last_name if user else ""),
        "email": data.get("email") or (user.email if user else ""),
        "phone": data.get("phone") or (user.phone if user else ""),
        "address": data.get("address", ""),
        "city": data.get("city", ""),
        "state": data.get("state", ""),
        "country": data.get("country") or "Nigeria",
        "identification_type": data.get("identification_type", ""),
        "identification_number": data.get("identification_number", ""),
        "special_requests": data.get("special_requests", ""),
    }
    if guest is None:
        guest = Guest(user=user)
        # A brand new record fills every field.
        for field_name, value in values.items():
            setattr(guest, field_name, value)
        guest.save()
        return guest

    changed = False
    for field_name, value in values.items():
        if value not in (None, "") and getattr(guest, field_name) != value:
            setattr(guest, field_name, value)
            changed = True
    if user is not None and guest.user_id is None:
        guest.user = user
        changed = True
    if changed:
        guest.save()
    return guest


# ---------------------------------------------------------------------------
# Booking creation (public guests + staff manual bookings)
# ---------------------------------------------------------------------------
@transaction.atomic
def create_booking(*, room_type_value, check_in, check_out, rooms, adults, children,
                   offer_code=None, special_requests="", user=None, guest_data=None,
                   source=Booking.Source.WEBSITE, require_payment=True, actor=None, request=None) -> Booking:
    is_staff = bool(actor and actor.is_staff_member)
    settings_obj = HotelSettings.get_settings()

    candidate = resolve_room_type(room_type_value, active_only=not is_staff)
    if candidate is None:
        from rest_framework.exceptions import NotFound

        raise NotFound("Room type not found.")
    # Lock the room type row: all bookings for the same type serialize here,
    # which makes the availability re-check below race-free.
    room_type = RoomType.objects.select_for_update().get(pk=candidate.pk)

    if rooms < 1:
        raise InvalidDatesError("At least one room must be requested.")

    quote = calculate_quote(
        room_type=room_type, check_in=check_in, check_out=check_out, rooms=rooms,
        adults=adults, children=children, offer_code=offer_code,
        settings_obj=settings_obj, for_staff=is_staff,
    )

    # Re-verify inventory INSIDE the lock; this check is authoritative —
    # an earlier availability search is never trusted at creation time.
    free_rooms = list(
        availability.available_rooms_queryset(
            room_type=room_type, check_in=check_in, check_out=check_out, for_update=True
        )[:rooms]
    )
    if len(free_rooms) < rooms:
        remaining = availability.available_room_count(
            room_type=room_type, check_in=check_in, check_out=check_out
        )
        raise RoomUnavailableError(
            f"Only {remaining} room(s) of this type remain for the selected dates."
        )

    guest = upsert_guest(user=user, guest_data=guest_data)

    pending = require_payment
    booking = Booking.objects.create(
        booking_reference=_unique_booking_reference(),
        guest=guest,
        room_type=room_type,
        check_in=check_in,
        check_out=check_out,
        number_of_rooms=rooms,
        adults=adults,
        children=children,
        currency=quote.currency,
        price_per_night=quote.price_per_night,
        subtotal=quote.subtotal,
        discount_amount=quote.discount,
        extra_guest_fee_amount=quote.extra_guest_fee,
        tax_amount=quote.tax,
        fee_amount=quote.service_fee,
        total_amount=quote.total,
        required_payment=quote.required_payment if require_payment else 0,
        offer=quote.offer,
        status=Booking.Status.PENDING if pending else Booking.Status.CONFIRMED,
        source=source,
        special_requests=special_requests or "",
        expires_at=(
            timezone.now() + timedelta(minutes=settings_obj.pending_booking_minutes)
            if pending
            else None
        ),
        created_by=actor if is_staff or (user and user.is_staff_member) else None,
    )
    BookingRoom.objects.bulk_create(
        [
            BookingRoom(booking=booking, room=room, check_in=check_in, check_out=check_out)
            for room in free_rooms
        ]
    )

    log_action(
        actor=actor or user,
        action="BOOKING_CREATED",
        instance=booking,
        metadata={
            "reference": booking.booking_reference,
            "source": booking.source,
            "total": str(booking.total_amount),
        },
        request=request,
        summary=f"Booking {booking.booking_reference} created ({booking.source})",
    )

    guest_name = booking.guest.full_name
    notify_staff(
        type="BOOKING_CREATED",
        title=f"New booking {booking.booking_reference}",
        message=(
            f"{guest_name} booked {booking.number_of_rooms} × {room_type.name}, "
            f"{booking.check_in} → {booking.check_out} ({booking.nights} night(s))."
        ),
        link=staff_booking_link(booking),
    )
    if booking.guest.user_id:
        notify_users(
            [booking.guest.user],
            type="BOOKING_CREATED",
            title=f"Booking {booking.booking_reference} created",
            message="Your reservation was created and is awaiting payment."
            if pending
            else "Your reservation is confirmed.",
            link=guest_booking_link(booking),
        )

    def _send_emails():
        hotel = HotelSettings.get_settings()
        if booking.guest.email:
            if pending:
                send_email_safe(
                    subject=f"Complete your booking {booking.booking_reference} — J-ONE HOTEL & LODGE",
                    message=(
                        f"Hello {booking.guest.first_name},\n\n"
                        f"Your reservation is on hold until "
                        f"{timezone.localtime(booking.expires_at):%d %b %Y %H:%M}.\n\n"
                        f"Room: {booking.number_of_rooms} × {room_type.name}\n"
                        f"Dates: {booking.check_in} → {booking.check_out} ({booking.nights} night(s))\n"
                        f"Total: {booking.currency} {booking.total_amount}\n"
                        f"Amount required to confirm: {booking.currency} {booking.required_payment}\n\n"
                        f"Complete payment here: {guest_booking_link(booking)}\n\n"
                        f"{hotel.hotel_name} · {hotel.phone}"
                    ),
                    recipients=[booking.guest.email],
                )
            else:
                _send_confirmation_email(booking, hotel)

    transaction.on_commit(_send_emails)
    logger.info(
        "Booking %s created: %s x%s %s→%s total=%s source=%s",
        booking.booking_reference, room_type.slug, rooms, check_in, check_out,
        booking.total_amount, source,
    )
    return booking


def _send_confirmation_email(booking, hotel=None):
    hotel = hotel or HotelSettings.get_settings()
    if not booking.guest.email:
        return
    rooms = ", ".join(a.room.room_number for a in booking.room_assignments.select_related("room"))
    send_email_safe(
        subject=f"Booking confirmed: {booking.booking_reference} — J-ONE HOTEL & LODGE",
        message=(
            f"Hello {booking.guest.first_name},\n\n"
            f"Your booking is CONFIRMED.\n\n"
            f"Booking reference: {booking.booking_reference}\n"
            f"Room: {booking.number_of_rooms} × {booking.room_type.name}"
            + (f" (room(s): {rooms})" if rooms else "")
            + f"\nCheck-in: {booking.check_in} (from {hotel.check_in_time:%H:%M})\n"
            f"Check-out: {booking.check_out} (by {hotel.check_out_time:%H:%M})\n"
            f"Total: {booking.currency} {booking.total_amount}\n"
            f"Paid: {booking.currency} {booking.amount_paid}\n"
            f"Balance due at hotel: {booking.currency} {booking.amount_due}\n\n"
            f"{hotel.hotel_name}\n{hotel.address}\n{hotel.phone} · {hotel.email}"
        ),
        recipients=[booking.guest.email],
    )


# ---------------------------------------------------------------------------
# Payments → booking state (called from the payments service in one transaction)
# ---------------------------------------------------------------------------
def register_successful_payment(booking: Booking, amount, *, request=None):
    """Credit a verified payment and (re-)derive payment status + confirmation."""
    booking.amount_paid = booking.amount_paid + amount
    if booking.amount_paid >= booking.total_amount:
        booking.payment_status = Booking.PaymentStatus.PAID
    elif booking.amount_paid > 0:
        booking.payment_status = Booking.PaymentStatus.PARTIALLY_PAID
    update_fields = ["amount_paid", "payment_status", "updated_at"]

    if (
        booking.status == Booking.Status.PENDING
        and booking.amount_paid >= booking.required_payment
    ):
        # Deposit requirement satisfied → confirm and release the hold timer.
        booking.status = Booking.Status.CONFIRMED
        booking.expires_at = None
        update_fields += ["status", "expires_at"]
        notify_staff(
            type="BOOKING_CONFIRMED",
            title=f"Booking {booking.booking_reference} confirmed",
            message="Payment received; booking confirmed automatically.",
            link=staff_booking_link(booking),
        )
    booking.save(update_fields=update_fields)
    return booking


# ---------------------------------------------------------------------------
# Expiration
# ---------------------------------------------------------------------------
def expire_pending_booking(booking: Booking):
    """Single-object expiration, safe to call twice (idempotent)."""
    if booking.status != Booking.Status.PENDING:
        return
    booking.status = Booking.Status.EXPIRED
    booking.save(update_fields=["status", "updated_at"])
    log_action(
        actor=None, action="BOOKING_EXPIRED", instance=booking,
        summary=f"Pending booking {booking.booking_reference} expired (unpaid hold released)",
    )
    if booking.guest.user_id:
        notify_users(
            [booking.guest.user],
            type="BOOKING_CANCELLED",
            title=f"Booking {booking.booking_reference} expired",
            message="Your reserved hold expired because payment was not completed in time.",
            link=guest_booking_link(booking),
        )
    logger.info("Pending booking expired: %s", booking.booking_reference)


def expire_stale_pending_bookings(now=None):
    """Batch job used by Celery beat; also invoked lazily by hot paths."""
    now = now or timezone.now()
    stale = list(
        Booking.objects.filter(status=Booking.Status.PENDING, expires_at__lte=now).order_by("pk")[:500]
    )
    for booking in stale:
        expire_pending_booking(booking)
    return len(stale)


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------
@transaction.atomic
def cancel_booking(booking: Booking, *, reason="", by_user=None, staff=False, request=None):
    booking = refresh_expired_pending(booking)
    if booking.status == Booking.Status.CANCELLED:
        return booking  # idempotent: cancelling twice is a no-op
    if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
        raise BookingStateError(
            f"A booking with status {booking.get_status_display()} cannot be cancelled."
        )

    settings_obj = HotelSettings.get_settings()
    if not staff:
        # Guests are bound by the configured cancellation deadline.
        check_in_dt = combine_hotel_datetime(booking.check_in, settings_obj.check_in_time)
        deadline = check_in_dt - timedelta(hours=settings_obj.cancellation_deadline_hours)
        if timezone.now() > deadline:
            raise CancellationNotAllowedError(
                f"Free cancellation ended {int(settings_obj.cancellation_deadline_hours)}h before check-in. "
                "Please contact the hotel directly."
            )

    refund_due = 0
    if booking.amount_paid > 0:
        fee = booking.amount_paid * settings_obj.cancellation_fee_percent / 100
        refund_due = booking.amount_paid - fee
        booking.refund_amount = refund_due
        booking.payment_status = (
            Booking.PaymentStatus.REFUNDED
            if refund_due >= booking.amount_paid
            else Booking.PaymentStatus.PARTIALLY_REFUNDED
        )

    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancellation_reason = reason or ("Cancelled by staff" if staff else "Cancelled by guest")
    booking.save(
        update_fields=["status", "cancelled_at", "cancellation_reason", "payment_status", "refund_amount", "updated_at"]
    )

    log_action(
        actor=by_user,
        action="BOOKING_CANCELLED",
        instance=booking,
        metadata={
            "reference": booking.booking_reference,
            "by": "staff" if staff else "guest",
            "refund_due": str(refund_due),
        },
        request=request,
        summary=f"Booking {booking.booking_reference} cancelled (refund due: {refund_due})",
    )
    notify_staff(
        type="BOOKING_CANCELLED",
        title=f"Booking {booking.booking_reference} cancelled",
        message=(
            f"Cancelled by {'staff' if staff else 'guest'}."
            + (f" Refund due: {booking.currency} {refund_due}." if refund_due > 0 else "")
        ),
        link=staff_booking_link(booking),
    )
    if booking.guest.user_id:
        notify_users(
            [booking.guest.user],
            type="BOOKING_CANCELLED",
            title=f"Booking {booking.booking_reference} cancelled",
            message="Your booking has been cancelled.",
            link=guest_booking_link(booking),
        )
    hotel = HotelSettings.get_settings()
    transaction.on_commit(
        lambda: send_email_safe(
            subject=f"Booking cancelled: {booking.booking_reference} — {hotel.hotel_name}",
            message=(
                f"Hello {booking.guest.first_name},\n\n"
                f"Booking {booking.booking_reference} has been cancelled."
                + (
                    f"\nA refund of {booking.currency} {refund_due} is due and will be processed by the hotel."
                    if refund_due > 0
                    else ""
                )
                + f"\n\n{hotel.hotel_name} · {hotel.phone}"
            ),
            recipients=[booking.guest.email],
        )
    )
    logger.info("Booking cancelled: %s (staff=%s, refund=%s)", booking.booking_reference, staff, refund_due)
    return booking


# ---------------------------------------------------------------------------
# Front-desk operations
# ---------------------------------------------------------------------------
@transaction.atomic
def check_in_booking(booking: Booking, *, staff_user, request=None):
    booking = refresh_expired_pending(booking)
    if booking.status == Booking.Status.CHECKED_IN:
        return booking  # idempotent retry
    if booking.status != Booking.Status.CONFIRMED:
        raise BookingStateError("Only CONFIRMED bookings can be checked in.")
    today = hotel_today()
    if today < booking.check_in:
        raise BookingStateError(f"Check-in is scheduled for {booking.check_in}.")

    assignments = list(booking.room_assignments.select_related("room").select_for_update())
    if len(assignments) < booking.number_of_rooms:
        # Fallback safeguard (should not happen): allocate the missing rooms now.
        missing = booking.number_of_rooms - len(assignments)
        free = list(
            availability.available_rooms_queryset(
                room_type=booking.room_type,
                check_in=booking.check_in,
                check_out=booking.check_out,
                for_update=True,
                exclude_booking_id=booking.pk,
            )[:missing]
        )
        if len(free) < missing:
            raise RoomUnavailableError("Not enough rooms available to complete check-in.")
        BookingRoom.objects.bulk_create(
            [BookingRoom(booking=booking, room=r, check_in=booking.check_in, check_out=booking.check_out) for r in free]
        )
        assignments = list(booking.room_assignments.select_related("room"))

    for assignment in assignments:
        room = assignment.room
        if room.status in (Room.Status.MAINTENANCE, Room.Status.OUT_OF_SERVICE):
            raise RoomUnavailableError(
                f"Room {room.room_number} is {room.get_status_display().lower()} and cannot be used."
            )
        room.status = Room.Status.OCCUPIED
        room.save(update_fields=["status", "updated_at"])

    booking.status = Booking.Status.CHECKED_IN
    booking.checked_in_at = timezone.now()
    booking.save(update_fields=["status", "checked_in_at", "updated_at"])

    log_action(
        actor=staff_user, action="CHECK_IN", instance=booking,
        metadata={"reference": booking.booking_reference,
                  "rooms": [a.room.room_number for a in assignments]},
        request=request,
        summary=f"Guest checked in: {booking.booking_reference}",
    )
    notify_staff(
        type="CHECK_IN",
        title=f"Checked in: {booking.booking_reference}",
        message=f"{booking.guest.full_name} checked in ({booking.room_type.name}).",
        link=staff_booking_link(booking),
    )
    logger.info("Check-in: %s by staff %s", booking.booking_reference, staff_user.id)
    return booking


def _release_rooms_for_checkout(booking):
    """Release every assigned room back to inventory and flag housekeeping."""
    assignments = list(booking.room_assignments.select_related("room").select_for_update())
    for assignment in assignments:
        room = assignment.room
        room.status = Room.Status.AVAILABLE
        room.housekeeping_status = Room.HousekeepingStatus.DIRTY
        room.save(update_fields=["status", "housekeeping_status", "updated_at"])
    return assignments


def _perform_checkout(booking: Booking, *, actor=None, automatic=False,
                      allow_balance_due=False, request=None):
    """Single authoritative checkout routine shared by the manual staff action
    and the automatic (scheduled) checkout task. Financial records are never
    touched — an outstanding balance is preserved on the booking."""
    if booking.status == Booking.Status.CHECKED_OUT:
        return booking  # idempotent retry
    if booking.status != Booking.Status.CHECKED_IN:
        raise BookingStateError("Only checked-in bookings can be checked out.")
    if booking.amount_due > 0 and not allow_balance_due:
        raise OutstandingBalanceError(
            f"Outstanding balance of {booking.currency} {booking.amount_due} must be settled before checkout."
        )

    assignments = _release_rooms_for_checkout(booking)

    booking.status = Booking.Status.CHECKED_OUT
    booking.checked_out_at = timezone.now()
    booking.save(update_fields=["status", "checked_out_at", "updated_at"])

    action = "AUTO_CHECK_OUT" if automatic else "CHECK_OUT"
    summary = (
        f"Guest automatically checked out: {booking.booking_reference}"
        if automatic else f"Guest checked out: {booking.booking_reference}"
    )
    log_action(
        actor=actor, action=action, instance=booking,
        metadata={"reference": booking.booking_reference,
                  "rooms": [a.room.room_number for a in assignments],
                  "balance_outstanding": str(booking.amount_due),
                  "automatic": automatic},
        request=request,
        summary=summary,
    )
    rooms_label = ", ".join(a.room.room_number for a in assignments) or booking.room_type.name
    if automatic:
        balance_note = (
            f" Outstanding balance: {booking.currency} {booking.amount_due}."
            if booking.amount_due > 0 else ""
        )
        notify_staff(
            type="CHECKOUT_AUTO",
            title=f"Auto checkout: {booking.booking_reference}",
            message=(
                f"{booking.guest.full_name} (room {rooms_label}) was automatically "
                f"checked out at {timezone.localtime(booking.checked_out_at):%H:%M}."
                + balance_note
            ),
            link=staff_booking_link(booking),
        )
    else:
        notify_staff(
            type="CHECK_OUT",
            title=f"Checked out: {booking.booking_reference}",
            message=f"{booking.guest.full_name} checked out (room {rooms_label}).",
            link=staff_booking_link(booking),
        )
    logger.info(
        "Check-out%s: %s by %s", " (auto)" if automatic else "",
        booking.booking_reference, actor.id if actor else "system",
    )
    return booking


@transaction.atomic
def check_out_booking(booking: Booking, *, staff_user, allow_balance_due=False, request=None):
    return _perform_checkout(
        booking, actor=staff_user, automatic=False,
        allow_balance_due=allow_balance_due, request=request,
    )


# ---------------------------------------------------------------------------
# Automatic checkout + 30-minute warning (Celery; hotel timezone aware)
# ---------------------------------------------------------------------------
def _scheduled_checkout_datetime(booking, settings_obj):
    """checkout date + configured checkout time in the hotel's timezone."""
    return combine_hotel_datetime(booking.check_out, settings_obj.check_out_time)


def auto_checkout_due_bookings(now=None):
    """Check out every in-house booking whose scheduled checkout time has
    passed. Idempotent and safe against concurrent workers: each booking is
    re-locked and re-checked inside its own transaction. Balances are
    preserved (allow_balance_due=True) — no financial record is altered."""
    now = now or timezone.now()
    settings_obj = HotelSettings.get_settings()
    candidate_ids = list(
        Booking.objects.filter(
            status=Booking.Status.CHECKED_IN,
            check_out__lte=timezone.localdate(now),
        ).values_list("pk", flat=True)
    )
    processed = 0
    for pk in candidate_ids:
        with transaction.atomic():
            booking = (
                Booking.objects.select_for_update()
                .select_related("guest", "room_type")
                .get(pk=pk)
            )
            if booking.status != Booking.Status.CHECKED_IN:
                continue  # another worker already handled it
            if now < _scheduled_checkout_datetime(booking, settings_obj):
                continue  # not due yet — never check out early
            _perform_checkout(booking, actor=None, automatic=True, allow_balance_due=True)
            processed += 1
    return processed


def send_checkout_due_soon_notifications(now=None, warning_minutes=CHECKOUT_WARNING_MINUTES):
    """Notify staff once per stay, ~30 minutes before scheduled checkout.

    Deduplication: a CHECKOUT_DUE_SOON notification whose link targets this
    booking and that was created after check-in means the warning was already
    sent — frequent Celery runs never re-notify the same stay."""
    from apps.notifications.models import Notification

    now = now or timezone.now()
    settings_obj = HotelSettings.get_settings()
    window_end = now + timedelta(minutes=warning_minutes)
    sent = 0
    candidates = (
        Booking.objects.filter(
            status=Booking.Status.CHECKED_IN,
            check_out__lte=timezone.localdate(window_end),
        )
        .select_related("guest", "room_type")
        .prefetch_related("room_assignments__room")
    )
    for booking in candidates:
        due_at = _scheduled_checkout_datetime(booking, settings_obj)
        if not (now <= due_at <= window_end):
            continue  # not inside the warning window (past-due handled by auto checkout)
        link = staff_booking_link(booking)
        already = Notification.objects.filter(
            type="CHECKOUT_DUE_SOON", link=link,
            created_at__gte=booking.checked_in_at or booking.created_at,
        ).exists()
        if already:
            continue
        rooms_label = ", ".join(
            a.room.room_number for a in booking.room_assignments.all()
        ) or booking.room_type.name
        notify_staff(
            type="CHECKOUT_DUE_SOON",
            title=f"Checkout due soon: {booking.booking_reference}",
            message=(
                f"{booking.guest.full_name} (room {rooms_label}) is scheduled to check out "
                f"at {timezone.localtime(due_at):%H:%M} today. Prepare for checkout, "
                f"contact the guest, or extend the stay."
            ),
            link=link,
        )
        sent += 1
    return sent


@transaction.atomic
def mark_no_show(booking: Booking, *, staff_user, request=None):
    if booking.status != Booking.Status.CONFIRMED:
        raise BookingStateError("Only CONFIRMED bookings can be marked as no-show.")
    if hotel_today() <= booking.check_in:
        raise BookingStateError("A booking can only be marked no-show after its check-in date.")
    booking.status = Booking.Status.NO_SHOW
    booking.save(update_fields=["status", "updated_at"])
    for assignment in booking.room_assignments.select_related("room"):
        pass  # assignment rows stop blocking automatically (status is NO_SHOW)
    log_action(
        actor=staff_user, action="NO_SHOW", instance=booking,
        metadata={"reference": booking.booking_reference}, request=request,
        summary=f"Booking {booking.booking_reference} marked as no-show",
    )
    logger.info("No-show: %s", booking.booking_reference)
    return booking


@transaction.atomic
def confirm_manual_booking(booking: Booking, *, staff_user, request=None):
    """Staff confirms a booking without an online payment (pay at hotel)."""
    booking = refresh_expired_pending(booking)
    if booking.status == Booking.Status.CONFIRMED:
        return booking
    if booking.status != Booking.Status.PENDING:
        raise BookingStateError("Only PENDING bookings can be confirmed.")
    booking.status = Booking.Status.CONFIRMED
    booking.expires_at = None
    booking.save(update_fields=["status", "expires_at", "updated_at"])
    log_action(
        actor=staff_user, action="BOOKING_CONFIRMED", instance=booking,
        metadata={"reference": booking.booking_reference, "method": "manual (staff)"},
        request=request,
        summary=f"Booking {booking.booking_reference} confirmed by staff",
    )
    if booking.guest.user_id:
        notify_users([booking.guest.user], type="BOOKING_CONFIRMED",
                     title=f"Booking {booking.booking_reference} confirmed",
                     message="Your booking has been confirmed by the hotel.",
                     link=guest_booking_link(booking))
    transaction.on_commit(lambda: _send_confirmation_email(booking))
    logger.info("Manual confirmation: %s by staff %s", booking.booking_reference, staff_user.id)
    return booking


@transaction.atomic
def assign_room(assignment: BookingRoom, *, new_room: Room, staff_user, request=None):
    """Re-point one assignment at a different physical room (validated).

    Serializes on the room-type row (same lock as create_booking) so two staff
    members assigning the same room at nearly the same time cannot both pass
    the overlap re-check below."""
    booking = assignment.booking
    if new_room.room_type_id != booking.room_type_id:
        raise BookingStateError("The room must match the booking's room type.")
    RoomType.objects.select_for_update().get(pk=booking.room_type_id)
    new_room.refresh_from_db()
    if not new_room.is_active or new_room.status in availability.OPERATIONALLY_BLOCKED:
        raise RoomUnavailableError(f"Room {new_room.room_number} is not in service.")
    conflicts = availability.blocked_room_ids(
        room_type_id=booking.room_type_id,
        check_in=assignment.check_in,
        check_out=assignment.check_out,
        exclude_booking_id=booking.pk,
    )
    if new_room.pk in set(conflicts):
        raise RoomUnavailableError(
            f"Room {new_room.room_number} is already reserved for overlapping dates."
        )
    old_number = assignment.room.room_number
    assignment.room = new_room
    assignment.save(update_fields=["room", "updated_at"])
    log_action(
        actor=staff_user, action="ROOM_ASSIGNED", instance=booking,
        changes={"room": [old_number, new_room.room_number]},
        metadata={"reference": booking.booking_reference},
        request=request,
        summary=f"Booking {booking.booking_reference}: room {old_number} → {new_room.room_number}",
    )
    logger.info("Assignment changed on %s: %s -> %s", booking.booking_reference, old_number, new_room.room_number)
    return assignment


@transaction.atomic
def modify_booking(booking: Booking, *, staff_user, data: dict, request=None):
    """Staff edit. Changing dates/rooms re-runs availability + repricing
    inside the room-type lock so integrity is preserved."""
    booking = refresh_expired_pending(booking)
    if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
        raise BookingStateError(
            f"A {booking.get_status_display().lower()} booking cannot be modified."
        )

    changes = {}
    room_type = RoomType.objects.select_for_update().get(pk=booking.room_type_id)

    # Simple text fields first.
    for field_name in ("special_requests", "internal_notes"):
        if field_name in data and data[field_name] is not None:
            old = getattr(booking, field_name)
            if old != data[field_name]:
                setattr(booking, field_name, data[field_name])
                changes[field_name] = [old or "", data[field_name]]

    stays = {"check_in", "check_out", "number_of_rooms", "adults", "children"}
    if stays & data.keys():
        new_check_in = data.get("check_in", booking.check_in)
        new_check_out = data.get("check_out", booking.check_out)
        new_rooms = int(data.get("number_of_rooms", booking.number_of_rooms))
        new_adults = int(data.get("adults", booking.adults))
        new_children = int(data.get("children", booking.children))

        quote = calculate_quote(
            room_type=room_type, check_in=new_check_in, check_out=new_check_out,
            rooms=new_rooms, adults=new_adults, children=new_children, for_staff=True,
        )
        current_room_ids = list(
            booking.room_assignments.values_list("room_id", flat=True)
        )
        dates_changed = (new_check_in, new_check_out) != (booking.check_in, booking.check_out)
        if dates_changed and current_room_ids:
            # Kept rooms must be free of OTHER bookings for the NEW dates.
            conflicts = set(
                availability.blocked_room_ids(
                    room_type_id=booking.room_type_id,
                    check_in=new_check_in,
                    check_out=new_check_out,
                    exclude_booking_id=booking.pk,
                )
            )
            clashing = conflicts & set(current_room_ids)
            if clashing:
                numbers = ", ".join(
                    Room.objects.filter(pk__in=clashing).values_list("room_number", flat=True)
                )
                raise RoomUnavailableError(
                    f"Room(s) {numbers} are already reserved by another booking for the new dates."
                )
        if new_rooms <= len(current_room_ids):
            keep_ids = current_room_ids[:new_rooms]
            # Freed rooms (when shrinking) must still be free of OTHER bookings.
            booking.room_assignments.exclude(room_id__in=keep_ids).delete()
            new_room_ids = keep_ids
        else:
            extra_needed = new_rooms - len(current_room_ids)
            free = list(
                availability.available_rooms_queryset(
                    room_type=room_type, check_in=new_check_in, check_out=new_check_out,
                    for_update=True, exclude_booking_id=booking.pk,
                ).exclude(pk__in=current_room_ids)[:extra_needed]
            )
            if len(free) < extra_needed:
                raise RoomUnavailableError(
                    "Not enough rooms of this type are available for the new stay."
                )
            BookingRoom.objects.bulk_create(
                [BookingRoom(booking=booking, room=r, check_in=new_check_in, check_out=new_check_out) for r in free]
            )
            new_room_ids = current_room_ids + [r.pk for r in free]
        booking.room_assignments.filter(room_id__in=new_room_ids).update(
            check_in=new_check_in, check_out=new_check_out
        )

        snapshot = {
            "check_in": (booking.check_in, new_check_in),
            "check_out": (booking.check_out, new_check_out),
            "number_of_rooms": (booking.number_of_rooms, new_rooms),
            "adults": (booking.adults, new_adults),
            "children": (booking.children, new_children),
            "total_amount": (booking.total_amount, quote.total),
        }
        for key, (old, new) in snapshot.items():
            if str(old) != str(new):
                changes[key] = [str(old), str(new)]

        booking.check_in, booking.check_out = new_check_in, new_check_out
        booking.number_of_rooms, booking.adults, booking.children = new_rooms, new_adults, new_children
        booking.price_per_night = quote.price_per_night
        booking.subtotal = quote.subtotal
        booking.discount_amount = quote.discount
        booking.extra_guest_fee_amount = quote.extra_guest_fee
        booking.tax_amount = quote.tax
        booking.fee_amount = quote.service_fee
        booking.total_amount = quote.total
        booking.required_payment = quote.required_payment
        booking.offer = quote.offer
        booking.payment_status = (
            Booking.PaymentStatus.PAID
            if booking.amount_paid >= booking.total_amount
            else (Booking.PaymentStatus.PARTIALLY_PAID if booking.amount_paid > 0 else Booking.PaymentStatus.UNPAID)
        )

    booking.save()
    if changes:
        log_action(
            actor=staff_user, action="BOOKING_MODIFIED", instance=booking, changes=changes,
            metadata={"reference": booking.booking_reference}, request=request,
            summary=f"Booking {booking.booking_reference} modified by staff",
        )
        notify_staff(
            type="BOOKING_MODIFIED",
            title=f"Booking {booking.booking_reference} modified",
            message="; ".join(f"{k}: {v[0]} → {v[1]}" for k, v in changes.items()),
            link=staff_booking_link(booking),
        )
    logger.info("Booking modified: %s changes=%s", booking.booking_reference, list(changes))
    return booking
