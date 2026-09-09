"""Small shared helpers."""
import secrets
from datetime import date, datetime, time

from django.utils import timezone


def hotel_today() -> date:
    """'Today' in the hotel's local timezone (Africa/Lagos)."""
    return timezone.localdate()


def combine_hotel_datetime(day: date, at: time) -> datetime:
    """Attach the hotel-local wall-clock time to a booking date."""
    return timezone.make_aware(datetime.combine(day, at))


def generate_booking_reference() -> str:
    """Human-friendly, unguessable, collision-checked callerside."""
    return f"J1-{timezone.now():%Y%m%d}-{secrets.token_hex(4).upper()}"


def generate_payment_reference() -> str:
    return f"J1P-{timezone.now():%Y%m%d}-{secrets.token_hex(5).upper()}"


def money(value) -> str:
    """Canonical API representation of a Decimal money amount."""
    from decimal import Decimal

    if value is None:
        return None
    return f"{Decimal(value).quantize(Decimal('0.01'))}"
