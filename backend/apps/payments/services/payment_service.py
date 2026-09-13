"""Payment orchestration — initialization, verification, webhooks, offline records.

Invariants guarded here:
* amounts always come from the BOOKING, never from the request body
* verification is idempotent (a retry is a read, not a re-credit)
* a booking only becomes CONFIRMED when verified money covers required_payment
* webhook signatures are validated before any processing
"""
import hashlib
import hmac
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log_action
from apps.bookings.models import Booking
from apps.bookings.services import booking_service
from apps.core.emails import send_email_safe
from apps.core.exceptions import (
    BookingExpiredError,
    BookingStateError,
    PaymentAlreadyCompletedError,
    PaymentAmountMismatchError,
    PaymentError,
    PaymentNotConfiguredError,
)
from apps.core.utils import generate_payment_reference, money
from apps.notifications.services import notify_staff, notify_users

from ..models import Payment
from . import paystack

logger = logging.getLogger("apps")

KOB0_PER_NAIRA = Decimal("100")


def _unique_payment_reference():
    for _ in range(10):
        reference = generate_payment_reference()
        if not Payment.objects.filter(reference=reference).exists():
            return reference
    raise RuntimeError("Could not allocate a unique payment reference.")


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
@transaction.atomic
def initialize_booking_payment(*, booking: Booking, user, request=None):
    """Create a Payment(PENDING) + Paystack transaction. Returns safe public data."""
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    booking_service.refresh_expired_pending(booking)
    if booking.is_expired_pending:
        raise BookingExpiredError()

    if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
        raise BookingStateError(
            f"A booking with status {booking.get_status_display()} cannot accept payments."
        )
    if booking.amount_due <= 0:
        raise PaymentAlreadyCompletedError()

    # What must be charged now: the (remaining) deposit requirement, then any balance.
    if booking.amount_paid < booking.required_payment:
        charge = booking.required_payment - booking.amount_paid
    else:
        charge = booking.amount_due

    reference = _unique_payment_reference()
    payment = Payment.objects.create(
        booking=booking,
        user=user,
        reference=reference,
        provider=Payment.Provider.PAYSTACK,
        amount=charge,
        currency=booking.currency,
        status=Payment.Status.PENDING,
        metadata={"booking_reference": booking.booking_reference},
    )
    # Paystack opens the callback in the browser after payment. Preserve the
    # guest bearer token across that redirect so a guest does not need a JWT.
    # The token is never logged or persisted in the Payment record.
    callback_url = settings.PAYMENT_CALLBACK_URL
    guest_token = request.headers.get("X-Guest-Access-Token", "") if request else ""
    if guest_token and callback_url:
        parts = urlsplit(callback_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["token"] = guest_token
        callback_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    paystack_data = paystack.initialize_transaction(
        email=booking.guest.email,
        amount_kobo=int(charge * KOB0_PER_NAIRA),
        reference=reference,
        callback_url=callback_url,
        metadata={
            "booking_reference": booking.booking_reference,
            "payment_id": payment.pk,
            "guest_name": booking.guest.full_name,
        },
    )
    payment.metadata = {
        **payment.metadata,
        "access_code": paystack_data.get("access_code"),
        "authorization_url": paystack_data.get("authorization_url"),
    }
    payment.save(update_fields=["metadata", "updated_at"])

    log_action(
        actor=user, action="PAYMENT_INITIALIZED", instance=payment,
        metadata={"reference": reference, "booking": booking.booking_reference, "amount": str(charge)},
        request=request,
    )
    logger.info("Payment initialized: %s for booking %s amount=%s", reference, booking.booking_reference, charge)
    return {
        "reference": reference,
        "booking_reference": booking.booking_reference,
        "authorization_url": paystack_data.get("authorization_url"),
        "access_code": paystack_data.get("access_code"),
        "amount": money(charge),
        "currency": booking.currency,
        "public_key": settings.PAYSTACK_PUBLIC_KEY or None,
    }


# ---------------------------------------------------------------------------
# Verification (idempotent) — used by the API endpoint and by the webhook path
# ---------------------------------------------------------------------------
def _verified_receipt_payload(payment: Payment):
    booking = payment.booking
    return {
        "payment_reference": payment.reference,
        "booking_reference": booking.booking_reference,
        "booking_status": booking.status,
        "payment_status": booking.payment_status,
        "amount_paid_this_transaction": money(payment.amount),
        "booking_amount_paid": money(booking.amount_paid),
        "booking_amount_due": money(booking.amount_due),
        "booking_total": money(booking.total_amount),
        "currency": booking.currency,
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
    }


def process_verification(*, reference, request=None, triggered_by="api"):
    """Verify a transaction with Paystack and reconcile local state.

    Safe to call any number of times: once the local Payment is SUCCESS the
    function becomes a pure read of already-recorded state.
    """
    payment = (
        Payment.objects.select_related("booking", "booking__guest", "booking__guest__user")
        .filter(reference=reference)
        .first()
    )
    if payment is None:
        from rest_framework.exceptions import NotFound

        raise NotFound("Payment not found.")

    if payment.status == Payment.Status.SUCCESS:
        # Idempotent fast path — no re-crediting, no duplicate side effects.
        return _verified_receipt_payload(payment)

    paystack_payload = paystack.verify_transaction(reference)
    data = paystack_payload.get("data") or {}
    gateway_status = data.get("status")

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == Payment.Status.SUCCESS:
            return _verified_receipt_payload(payment)

        if gateway_status != "success":
            payment.status = Payment.Status.FAILED
            payment.gateway_response = data.get("gateway_response") or paystack_payload.get("message", "")
            payment.save(update_fields=["status", "gateway_response", "updated_at"])
            if payment.booking.guest.user_id:
                notify_users(
                    [payment.booking.guest.user],
                    type="PAYMENT_FAILED",
                    title=f"Payment failed for {payment.booking.booking_reference}",
                    message=payment.gateway_response or "The payment could not be completed.",
                    link=booking_service.guest_booking_link(payment.booking),
                )
            logger.warning("Payment failed: %s status=%s", reference, gateway_status)
            raise PaymentError(payment.gateway_response or "Payment was not successful.")

        expected_kobo = int(payment.amount * KOB0_PER_NAIRA)
        paid_kobo = data.get("amount")
        paid_currency = data.get("currency")
        if paid_kobo != expected_kobo or paid_currency != payment.currency:
            logger.error(
                "Payment amount/currency mismatch: %s expected=%s%s got=%s%s",
                reference, expected_kobo, payment.currency, paid_kobo, paid_currency,
            )
            payment.metadata = {**payment.metadata, "mismatch": {"expected": expected_kobo, "received": paid_kobo, "currency": paid_currency}}
            payment.save(update_fields=["metadata", "updated_at"])
            raise PaymentAmountMismatchError()

        paid_at_raw = data.get("paid_at") or data.get("paidAt")
        paid_at = timezone.now()
        if paid_at_raw:
            try:
                from datetime import datetime

                parsed = datetime.fromisoformat(str(paid_at_raw).replace("Z", "+00:00"))
                paid_at = parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
            except (ValueError, TypeError):
                paid_at = timezone.now()

        payment.status = Payment.Status.SUCCESS
        payment.paid_at = paid_at
        payment.channel = (data.get("channel") or "")[:40]
        payment.gateway_response = data.get("gateway_response", "")[:255]
        payment.transaction_id = str(data.get("id", ""))[:60]
        # NB: payer IP is deliberately NOT stored (PDPA/data-minimisation —
        # no fraud-review use case consumes it, so we don't retain it).
        payment.metadata = {
            **payment.metadata,
            "paystack_id": data.get("id"),
            "channel": payment.channel,
        }
        payment.save()

        booking = booking_service.register_successful_payment(
            Booking.objects.select_for_update().get(pk=payment.booking_id),
            payment.amount,
            request=request,
        )

    log_action(
        actor=payment.user, action="PAYMENT_VERIFIED", instance=payment,
        metadata={
            "reference": reference,
            "booking": booking.booking_reference,
            "amount": str(payment.amount),
            "channel": payment.channel,
            "triggered_by": triggered_by,
        },
        request=request,
    )
    notify_staff(
        type="PAYMENT_SUCCESS",
        title=f"Payment received: {booking.booking_reference}",
        message=f"{booking.currency} {money(payment.amount)} via {payment.channel or 'Paystack'}.",
        link=booking_service.staff_booking_link(booking),
    )
    if booking.guest.user_id:
        notify_users(
            [booking.guest.user],
            type="PAYMENT_SUCCESS",
            title=f"Payment confirmed for {booking.booking_reference}",
            message=f"We received {booking.currency} {money(payment.amount)}.",
            link=booking_service.guest_booking_link(booking),
        )
    if booking.status == Booking.Status.CONFIRMED:
        transaction.on_commit(lambda: booking_service._send_confirmation_email(booking))
    logger.info(
        "Payment verified: %s booking=%s amount=%s channel=%s",
        reference, booking.booking_reference, payment.amount, payment.channel,
    )
    payment.refresh_from_db()
    return _verified_receipt_payload(payment)


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------
def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    secret = getattr(settings, "PAYSTACK_SECRET_KEY", "")
    if not secret or not signature:
        return False
    calculated = hmac.new(secret.encode(), msg=raw_body, digestmod=hashlib.sha512).hexdigest()
    return hmac.compare_digest(calculated, signature)


def process_webhook(event_payload: dict, *, request=None):
    """Handle a signature-verified payload. Always swallows business errors —
    Paystack expects a 200 once we've accepted the event.

    Branches (all arrive here only AFTER HMAC signature validation):
    * charge.success    — verify + credit via the shared verification path
    * refund.processed  — reconcile the local payment to REFUNDED + alert staff
    * charge.dispute.create — alert staff of a chargeback (no auto state change)
    """
    event = event_payload.get("event")
    data = event_payload.get("data") or {}
    reference = data.get("reference")

    if event == "charge.success":
        logger.info("Paystack webhook received: event=%s reference=%s", event, reference)
        if not reference:
            return {"handled": False, "reason": "unsupported_event"}
        if not Payment.objects.filter(reference=reference).exists():
            # Not one of ours (e.g. terminal/POS) — acknowledge without error.
            logger.info("Webhook for unknown reference %s ignored", reference)
            return {"handled": False, "reason": "unknown_reference"}
        try:
            result = process_verification(reference=reference, request=request, triggered_by="webhook")
            return {"handled": True, "booking_reference": result["booking_reference"]}
        except PaymentAmountMismatchError:
            logger.error("Webhook verification amount mismatch (%s)", reference)
            return {"handled": False, "reason": "amount_mismatch"}
        except PaymentError as exc:
            logger.warning("Webhook verification failed for %s: %s", reference, exc.detail)
            return {"handled": False, "reason": "verification_failed"}

    if event == "refund.processed":
        return _handle_refund_processed(data, request=request)

    if event == "charge.dispute.create":
        return _handle_dispute_created(data, request=request)

    logger.info("Paystack webhook received: event=%s reference=%s", event, reference)
    return {"handled": False, "reason": "unsupported_event"}


def _handle_refund_processed(data, *, request=None):
    """A refund issued from the Paystack dashboard.

    Reconciles the local payment to REFUNDED and alerts front-desk staff. The
    BOOKING is deliberately untouched: a refund does not automatically mean
    cancellation — that judgment belongs to staff.
    """
    # Refund events nest the charge reference under `transaction`.
    reference = (data.get("transaction") or {}).get("reference") or data.get("reference")
    if not reference:
        return {"handled": False, "reason": "no_reference"}

    with transaction.atomic():
        payment = (
            Payment.objects.select_for_update()
            .select_related("booking", "booking__guest")
            .filter(reference=reference)
            .first()
        )
        if payment is None:
            logger.info("Refund webhook for unknown reference %s ignored", reference)
            return {"handled": False, "reason": "unknown_reference"}
        if payment.status != Payment.Status.SUCCESS:
            # Only a successful charge can become refunded; repeat deliveries
            # of the same event are therefore idempotent no-ops.
            return {"handled": False, "reason": "not_refundable_state", "payment_status": payment.status}
        payment.status = Payment.Status.REFUNDED
        payment.save(update_fields=["status", "updated_at"])

    log_action(
        actor=None, action="PAYMENT_REFUNDED", instance=payment,
        metadata={"reference": reference, "booking": payment.booking.booking_reference,
                  "amount": str(payment.amount)},
        request=request,
        summary=f"Refund processed via Paystack for {reference}",
    )
    notify_staff(
        type="PAYMENT_REFUNDED",
        title=f"Refund processed: {payment.booking.booking_reference}",
        message=(
            f"A Paystack refund of {payment.currency} {money(payment.amount)} was processed "
            f"for booking {payment.booking.booking_reference}. Please review and reconcile."
        ),
        link=booking_service.staff_booking_link(payment.booking),
    )
    logger.info("Refund reconciled: payment=%s booking=%s", reference, payment.booking.booking_reference)
    return {"handled": True, "reason": "refund_recorded", "payment_reference": reference}


def _handle_dispute_created(data, *, request=None):
    """A chargeback/dispute was opened on a charge — alert staff for human review.

    No payment or booking status is changed automatically.
    """
    # Dispute payloads carry the reference at top level, but tolerate nesting.
    reference = data.get("reference") or (data.get("transaction") or {}).get("reference")
    if not reference:
        return {"handled": False, "reason": "no_reference"}
    payment = (
        Payment.objects.select_related("booking")
        .filter(reference=reference)
        .first()
    )
    if payment is None:
        logger.info("Dispute webhook for unknown reference %s ignored", reference)
        return {"handled": False, "reason": "unknown_reference"}

    log_action(
        actor=None, action="PAYMENT_DISPUTED", instance=payment,
        metadata={"reference": reference, "booking": payment.booking.booking_reference,
                  "dispute_status": str(data.get("status", ""))},
        request=request,
        summary=f"Chargeback opened on {reference}",
    )
    notify_staff(
        type="PAYMENT_DISPUTED",
        title=f"Chargeback alert: {payment.booking.booking_reference}",
        message=(
            f"A dispute was opened against payment {reference} "
            f"({payment.currency} {money(payment.amount)}) for booking "
            f"{payment.booking.booking_reference}. Evidence may be required — review in Paystack."
        ),
        link=booking_service.staff_booking_link(payment.booking),
    )
    logger.warning("Dispute opened: payment=%s booking=%s", reference, payment.booking.booking_reference)
    return {"handled": True, "reason": "dispute_notified", "payment_reference": reference}


# ---------------------------------------------------------------------------
# Staff-recorded offline payments (cash / POS / transfer at the front desk)
# ---------------------------------------------------------------------------
@transaction.atomic
def record_offline_payment(*, booking: Booking, staff_user, amount, provider, notes="", request=None):
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    booking_service.refresh_expired_pending(booking)
    if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN):
        raise BookingStateError(
            f"A booking with status {booking.get_status_display()} cannot accept payments."
        )
    if booking.amount_due <= 0:
        raise PaymentAlreadyCompletedError()
    if amount > booking.amount_due:
        raise PaymentError(
            f"Amount exceeds the outstanding balance of {booking.currency} {money(booking.amount_due)}."
        )

    payment = Payment.objects.create(
        booking=booking,
        user=staff_user,
        reference=_unique_payment_reference(),
        provider=provider,
        amount=amount,
        currency=booking.currency,
        status=Payment.Status.SUCCESS,
        channel=provider.lower(),
        gateway_response=f"Recorded at front desk by {staff_user.email}",
        paid_at=timezone.now(),
        notes=notes,
        metadata={"booking_reference": booking.booking_reference, "recorded_by": staff_user.email},
    )
    booking = booking_service.register_successful_payment(booking, amount, request=request)
    log_action(
        actor=staff_user, action="PAYMENT_RECORDED", instance=payment,
        metadata={
            "reference": payment.reference,
            "booking": booking.booking_reference,
            "amount": str(amount),
            "provider": provider,
        },
        request=request,
        summary=f"Offline payment {payment.reference} recorded ({money(amount)} {booking.currency})",
    )
    logger.info("Offline payment recorded: %s booking=%s amount=%s by=%s",
                payment.reference, booking.booking_reference, amount, staff_user.id)
    return payment
