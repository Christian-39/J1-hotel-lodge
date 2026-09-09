"""Staff dashboard aggregation.

Everything is computed with database-level aggregates — the endpoint does a
handful of queries regardless of table size, and financial figures are only
included for roles allowed to see them.
"""
from datetime import timedelta

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from apps.bookings.models import Booking, BookingRoom
from apps.core.utils import hotel_today, money
from apps.notifications.services import unread_count
from apps.payments.models import Payment
from apps.rooms.models import Room


def _money_or_zero(value):
    return money(value or 0)


def build_dashboard(user):
    today = hotel_today()
    now = timezone.now()
    month_start = today.replace(day=1)

    # --- Physical room state (operational truth) -----------------------------
    rooms_qs = Room.objects.filter(is_active=True)
    room_stats = rooms_qs.aggregate(
        total=Count("id"),
        occupied=Count("id", filter=Q(status=Room.Status.OCCUPIED)),
        maintenance=Count("id", filter=Q(status=Room.Status.MAINTENANCE)),
        out_of_service=Count("id", filter=Q(status=Room.Status.OUT_OF_SERVICE)),
    )
    total_rooms = room_stats["total"] or 0
    occupied_rooms = room_stats["occupied"] or 0
    unavailable_ops = (room_stats["maintenance"] or 0) + (room_stats["out_of_service"] or 0)
    available_rooms = max(total_rooms - occupied_rooms - unavailable_ops, 0)
    occupancy_rate = round((occupied_rooms / total_rooms) * 100, 1) if total_rooms else 0.0

    # --- Booking pipeline stats ----------------------------------------------
    bookings = Booking.objects.all()
    booking_stats = bookings.aggregate(
        arrivals_today=Count("id", filter=Q(check_in=today, status=Booking.Status.CONFIRMED)),
        departures_today=Count("id", filter=Q(check_out=today, status=Booking.Status.CHECKED_IN)),
        in_house=Count("id", filter=Q(status=Booking.Status.CHECKED_IN)),
        pending=Count("id", filter=Q(status=Booking.Status.PENDING, expires_at__gt=now)),
        confirmed=Count("id", filter=Q(status=Booking.Status.CONFIRMED, check_in__gte=today)),
        created_today=Count("id", filter=Q(created_at__date=today)),
        cancelled_today=Count("id", filter=Q(cancelled_at__date=today)),
        no_shows=Count("id", filter=Q(status=Booking.Status.NO_SHOW, check_in=today)),
    )

    recent_bookings = (
        bookings.select_related("guest", "room_type")
        .only("booking_reference", "status", "payment_status", "check_in", "check_out",
              "total_amount", "currency", "created_at",
              "guest__first_name", "guest__last_name", "room_type__name")
        .order_by("-created_at")[:7]
    )

    data = {
        "today": {
            "date": today.isoformat(),
            "arrivals": booking_stats["arrivals_today"],
            "departures": booking_stats["departures_today"],
            "in_house": booking_stats["in_house"],
            "no_shows": booking_stats["no_shows"],
        },
        "rooms": {
            "total": total_rooms,
            "occupied": occupied_rooms,
            "available": available_rooms,
            "out_of_order": unavailable_ops,
            "occupancy_rate_percent": occupancy_rate,
        },
        "bookings": {
            "created_today": booking_stats["created_today"],
            "pending": booking_stats["pending"],
            "confirmed_upcoming": booking_stats["confirmed"],
            "cancelled_today": booking_stats["cancelled_today"],
        },
        "recent_bookings": [
            {
                "booking_reference": b.booking_reference,
                "guest_name": b.guest.full_name,
                "room_type_name": b.room_type.name,
                "check_in": b.check_in.isoformat(),
                "check_out": b.check_out.isoformat(),
                "status": b.status,
                "payment_status": b.payment_status,
                "total_amount": money(b.total_amount),
                "currency": b.currency,
                "created_at": b.created_at.isoformat(),
            }
            for b in recent_bookings
        ],
        "notifications": {"unread_count": unread_count(user)},
    }

    # Financial visibility: managers & admins only (receptionists see operations).
    if user.is_manager_or_admin:
        today_revenue = (
            Payment.objects.filter(status=Payment.Status.SUCCESS, paid_at__date=today)
            .aggregate(total=Sum("amount"))["total"]
        )
        month_revenue = (
            Payment.objects.filter(status=Payment.Status.SUCCESS, paid_at__date__gte=month_start)
            .aggregate(total=Sum("amount"))["total"]
        )
        outstanding = (
            Booking.objects.filter(
                status__in=(Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN)
            )
            .annotate(balance=F("total_amount") - F("amount_paid"))
            .filter(balance__gt=0)
            .aggregate(total=Sum("balance"), count=Count("id"))
        )
        recent_payments = (
            Payment.objects.select_related("booking")
            .filter(status=Payment.Status.SUCCESS)
            .order_by("-paid_at")[:7]
        )
        data["revenue"] = {
            "today": _money_or_zero(today_revenue),
            "this_month": _money_or_zero(month_revenue),
            "outstanding_total": _money_or_zero(outstanding["total"]),
            "outstanding_bookings": outstanding["count"],
        }
        data["recent_payments"] = [
            {
                "reference": p.reference,
                "booking_reference": p.booking.booking_reference,
                "amount": money(p.amount),
                "currency": p.currency,
                "provider": p.provider,
                "channel": p.channel,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            }
            for p in recent_payments
        ]
        data["alerts"] = _operational_alerts(today, now)
    else:
        data["alerts"] = _operational_alerts(today, now, include_financial=False)

    return data


def _operational_alerts(today, now, include_financial=True):
    alerts = []
    overdue_checkins = Booking.objects.filter(
        status=Booking.Status.CONFIRMED, check_in__lt=today
    ).count()
    if overdue_checkins:
        alerts.append({
            "type": "OVERDUE_CHECKIN",
            "message": f"{overdue_checkins} confirmed booking(s) have not checked in yet.",
        })
    late_checkouts = Booking.objects.filter(
        status=Booking.Status.CHECKED_IN, check_out__lt=today
    ).count()
    if late_checkouts:
        alerts.append({
            "type": "LATE_CHECKOUT",
            "message": f"{late_checkouts} in-house booking(s) are past their check-out date.",
        })
    dirty_rooms = Room.objects.filter(
        is_active=True, housekeeping_status=Room.HousekeepingStatus.DIRTY
    ).count()
    if dirty_rooms:
        alerts.append({
            "type": "HOUSEKEEPING",
            "message": f"{dirty_rooms} room(s) are marked dirty and need housekeeping.",
        })
    return alerts
