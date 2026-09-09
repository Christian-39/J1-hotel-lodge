"""Offer eligibility + discount maths.

The BACKEND decides whether an offer applies to a stay; the frontend only
displays what these functions return.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from apps.core.exceptions import OfferNotApplicableError

from .models import Offer

_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def discount_amount(offer: Offer, subtotal: Decimal) -> Decimal:
    """Absolute discount for a given subtotal (never exceeding the subtotal)."""
    if offer.discount_type == Offer.DiscountType.PERCENTAGE:
        amount = subtotal * (Decimal(offer.discount_value) / Decimal("100"))
    else:
        amount = Decimal(offer.discount_value)
    return max(_ZERO, min(_q(amount), subtotal))


def eligible_offers_queryset(room_type, check_in, check_out, nights):
    """Offers whose window fully covers the stay and meet stay-length rules.

    Window rule: check_in must fall on/after start_date and the LAST NIGHT
    (check_out - 1 day) must fall on/before end_date.
    """
    from datetime import timedelta

    last_night = check_out - timedelta(days=1)
    qs = Offer.objects.filter(
        is_active=True,
        start_date__lte=check_in,
        end_date__gte=last_night,
        min_nights__lte=nights,
    )
    qs = qs.filter(models_q_max_nights(nights))
    # Empty M2M means "applies to all room types".
    qs = qs.filter(models_q_room_types(room_type))
    return qs.distinct()


def models_q_max_nights(nights):
    from django.db.models import Q

    return Q(max_nights__isnull=True) | Q(max_nights__gte=nights)


def models_q_room_types(room_type):
    from django.db.models import Q

    return Q(room_types__isnull=True) | Q(room_types=room_type)


def best_offer(room_type, check_in, check_out, nights, subtotal):
    """Return (offer, discount) producing the largest discount, or (None, 0)."""
    best, best_discount = None, _ZERO
    for offer in eligible_offers_queryset(room_type, check_in, check_out, nights):
        amount = discount_amount(offer, subtotal)
        if amount > best_discount:
            best, best_discount = offer, amount
    return best, best_discount


def validate_offer_code(code, room_type, check_in, check_out, nights, subtotal):
    """Resolve a promo code to an (offer, discount) or raise OFFER_NOT_APPLICABLE."""
    offer = Offer.objects.filter(code__iexact=(code or "").strip(), is_active=True).first()
    if offer is None:
        raise OfferNotApplicableError("This offer code is not valid.")
    if not eligible_offers_queryset(room_type, check_in, check_out, nights).filter(pk=offer.pk).exists():
        raise OfferNotApplicableError("This offer cannot be applied to the selected stay.")
    return offer, discount_amount(offer, subtotal)


def offers_for_room_type(room_type, limit=5):
    """Public display helper: currently active offers usable for a room type."""
    today = timezone.localdate()
    qs = (
        Offer.objects.filter(is_active=True, start_date__lte=today, end_date__gte=today)
        .filter(models_q_room_types(room_type))
        .distinct()
        .order_by("-is_featured", "-discount_value")[:limit]
    )
    return [
        {
            "id": o.pk,
            "slug": o.slug,
            "title": o.title,
            "short_description": o.short_description,
            "discount_type": o.discount_type,
            "discount_value": f"{_q(o.discount_value)}",
            "end_date": o.end_date.isoformat(),
        }
        for o in qs
    ]
