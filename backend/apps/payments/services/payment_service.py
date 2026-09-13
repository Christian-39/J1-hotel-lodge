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
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log_action
from apps.bookings.models import Booking
from apps.bookings.services import booking_service
from apps.core.exceptions import (
    BookingExpiredError,
    BookingStateError,
    PaymentAlreadyCompletedError,
    PaymentAmountMismatchError,
    PaymentError,
    PaymentGatewayError,
    PaymentNotConfiguredError,
)
from apps.core.utils import generate_payment_reference, money
from apps.notifications.services import notify_staff, notify_users

from ..models import Payment
from . import paystack

logger = logging.getLogger("apps")

KOBO_PER_NAIRA = Decimal("100")


def _unique_payment_reference():
    for _ in range(10):
        reference = generate_payment_reference()
        if not Payment.objects.filter(reference=reference).exists():
            return reference
    raise RuntimeError("Could not allocate a unique payment reference.")


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
INITIALIZATION_LEASE = timedelta(minutes=2)
PROCESSING_GATEWAY_STATUSES = {"pending", "ongoing", "processing", "queued"}
FAILED_GATEWAY_STATUSES = {"failed", "abandoned", "reversed"}


def _amount_to_kobo(amount: Decimal) -> int:
    """Convert a two-decimal NGN amount without passing through float."""
    value = Decimal(amount).quantize(Decimal("0.01")) * KOBO_PER_NAIRA
    return int(value.to_integral_exact())


def _initialization_payload(payment):
    return {
        "reference": payment.reference,
        "booking_reference": payment.booking.booking_reference,
        "authorization_url": payment.metadata.get("authorization_url"),
        "amount": money(payment.amount),
        "currency": payment.currency,
        "reused": True,
    }


def _reserve_initialization(*, booking, user):
    """Short DB transaction which allocates (or reuses) one pending attempt.

    The booking row is the serialization point. The external Paystack request
    deliberately happens after this transaction commits.
    """
    with transaction.atomic():
        booking = (
            Booking.objects.select_for_update()
            .select_related("guest")
            .get(pk=booking.pk)
        )
        booking_service.refresh_expired_pending(booking)
        booking.refresh_from_db()
        if booking.status == Booking.Status.EXPIRED or booking.is_expired_pending:
            raise BookingExpiredError()
        if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
            raise BookingStateError(
                f"A booking with status {booking.get_status_display()} cannot accept payments."
            )
        if booking.amount_due <= 0:
            raise PaymentAlreadyCompletedError()
        if booking.currency.upper() != "NGN":
            raise PaymentError("Online payment is only available for NGN bookings.")

        charge = (
            booking.required_payment - booking.amount_paid
            if booking.amount_paid < booking.required_payment
            else booking.amount_due
        ).quantize(Decimal("0.01"))

        payment = (
            Payment.objects.select_for_update()
            .filter(
                booking=booking,
                provider=Payment.Provider.PAYSTACK,
                status=Payment.Status.PENDING,
                amount=charge,
                currency=booking.currency,
            )
            .order_by("-created_at")
            .first()
        )
        if payment and payment.metadata.get("authorization_url"):
            return booking, payment, False

        now = timezone.now()
        if payment:
            state = payment.metadata.get("initialization_state")
            started_raw = payment.metadata.get("initialization_started_at")
            try:
                from datetime import datetime
                started = datetime.fromisoformat(started_raw) if started_raw else None
            except (TypeError, ValueError):
                started = None
            if started and timezone.is_naive(started):
                started = timezone.make_aware(started)
            if state == "INITIALIZING" and started and now - started < INITIALIZATION_LEASE:
                raise PaymentError("Payment initialization is already in progress. Please wait a moment.")
        else:
            payment = Payment.objects.create(
                booking=booking,
                user=user,
                reference=_unique_payment_reference(),
                provider=Payment.Provider.PAYSTACK,
                amount=charge,
                currency=booking.currency,
                status=Payment.Status.PENDING,
                metadata={"booking_reference": booking.booking_reference},
            )

        payment.user = user or payment.user
        payment.metadata = {
            **payment.metadata,
            "initialization_state": "INITIALIZING",
            "initialization_started_at": now.isoformat(),
        }
        payment.save(update_fields=["user", "metadata", "updated_at"])
        return booking, payment, True


def initialize_booking_payment(*, booking: Booking, user, request=None):
    """Initialize one idempotent Paystack attempt without a long DB lock."""
    if not getattr(settings, "PAYSTACK_SECRET_KEY", "").strip():
        raise PaymentNotConfiguredError()
    booking, payment, should_call_gateway = _reserve_initialization(booking=booking, user=user)
    if not should_call_gateway:
        logger.info("Reused initialized payment: %s booking=%s", payment.reference, booking.booking_reference)
        return _initialization_payload(payment)

    try:
        paystack_data = paystack.initialize_transaction(
            email=booking.guest.email,
            amount_kobo=_amount_to_kobo(payment.amount),
            reference=payment.reference,
            callback_url=settings.PAYMENT_CALLBACK_URL,
            metadata={
                "booking_reference": booking.booking_reference,
                "payment_reference": payment.reference,
                "room_type_id": booking.room_type_id,
            },
        )
    except (PaymentGatewayError, PaymentNotConfiguredError):
        # Preserve this reference for a safe retry. A timeout is ambiguous: the
        # gateway may have accepted it, so creating a fresh attempt could lead
        # to two payable transactions.
        with transaction.atomic():
            current = Payment.objects.select_for_update().get(pk=payment.pk)
            current.metadata = {
                **current.metadata,
                "initialization_state": "RETRYABLE_ERROR",
                "initialization_failed_at": timezone.now().isoformat(),
            }
            current.save(update_fields=["metadata", "updated_at"])
        logger.exception("Payment initialization failed: reference=%s booking=%s", payment.reference, booking.booking_reference)
        raise

    if (
        not isinstance(paystack_data, dict)
        or not paystack_data.get("authorization_url")
        or not paystack_data.get("access_code")
        or paystack_data.get("reference") != payment.reference
    ):
        logger.error("Invalid Paystack initialization data: reference=%s booking=%s", payment.reference, booking.booking_reference)
        raise PaymentGatewayError("Unable to start payment. Please try again.")

    with transaction.atomic():
        payment = Payment.objects.select_for_update().select_related("booking").get(pk=payment.pk)
        payment.metadata = {
            **payment.metadata,
            "initialization_state": "READY",
            "access_code": paystack_data["access_code"],
            "authorization_url": paystack_data["authorization_url"],
            "provider_reference": paystack_data["reference"],
        }
        payment.save(update_fields=["metadata", "updated_at"])

    log_action(
        actor=user, action="PAYMENT_INITIALIZED", instance=payment,
        metadata={"reference": payment.reference, "booking": booking.booking_reference,
                  "amount": str(payment.amount)}, request=request,
    )
    logger.info("Payment initialized: reference=%s booking=%s amount=%s", payment.reference, booking.booking_reference, payment.amount)
    payload = _initialization_payload(payment)
    payload["reused"] = False
    return payload


# ---------------------------------------------------------------------------
# Verification (idempotent) — shared by browser verification and webhook
# ---------------------------------------------------------------------------
def _verified_receipt_payload(payment: Payment, transaction_status=None):
    booking = payment.booking
    return {
        "payment_reference": payment.reference,
        "booking_reference": booking.booking_reference,
        "transaction_status": transaction_status or payment.status,
        "booking_status": booking.status,
        "payment_status": booking.payment_status,
        "amount_paid_this_transaction": money(payment.amount) if payment.status == Payment.Status.SUCCESS else "0.00",
        "booking_amount_paid": money(booking.amount_paid),
        "booking_amount_due": money(booking.amount_due),
        "booking_total": money(booking.total_amount),
        "currency": booking.currency,
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
    }


def _parse_paid_at(value):
    if not value:
        return timezone.now()
    try:
        from datetime import datetime
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
    except (ValueError, TypeError):
        return timezone.now()


def process_verification(*, reference, request=None, triggered_by="api"):
    """Verify with Paystack, validate reference/amount/currency and reconcile."""
    payment = (
        Payment.objects.select_related("booking", "booking__guest", "booking__guest__user")
        .filter(reference=reference, provider=Payment.Provider.PAYSTACK)
        .first()
    )
    if payment is None:
        from rest_framework.exceptions import NotFound
        raise NotFound("Payment not found.")
    if payment.status == Payment.Status.SUCCESS:
        return _verified_receipt_payload(payment, "success")

    paystack_payload = paystack.verify_transaction(reference)
    data = paystack_payload["data"]
    gateway_status = str(data.get("status") or "").lower()

    with transaction.atomic():
        payment = (
            Payment.objects.select_for_update()
            .select_related("booking", "booking__guest", "booking__guest__user")
            .get(pk=payment.pk)
        )
        if payment.status == Payment.Status.SUCCESS:
            return _verified_receipt_payload(payment, "success")

        provider_reference = str(data.get("reference") or "")
        if provider_reference != payment.reference:
            logger.error("Paystack reference mismatch: expected=%s got=%s", payment.reference, provider_reference)
            raise PaymentAmountMismatchError("The verified payment reference does not match.")

        if gateway_status in PROCESSING_GATEWAY_STATUSES or gateway_status not in FAILED_GATEWAY_STATUSES | {"success"}:
            payment.status = Payment.Status.PENDING
            payment.gateway_response = str(data.get("gateway_response") or paystack_payload.get("message") or "")[:255]
            payment.save(update_fields=["status", "gateway_response", "updated_at"])
            logger.info("Payment remains pending: reference=%s gateway_status=%s", reference, gateway_status)
            return _verified_receipt_payload(payment, gateway_status or "pending")

        if gateway_status in FAILED_GATEWAY_STATUSES:
            payment.status = Payment.Status.FAILED
            payment.gateway_response = str(data.get("gateway_response") or paystack_payload.get("message") or "")[:255]
            payment.save(update_fields=["status", "gateway_response", "updated_at"])
            booking = Booking.objects.select_for_update().get(pk=payment.booking_id)
            if booking.amount_paid == 0 and booking.payment_status != Booking.PaymentStatus.PAID:
                booking.payment_status = Booking.PaymentStatus.FAILED
                booking.save(update_fields=["payment_status", "updated_at"])
            payment.booking = booking
            logger.warning("Payment terminal failure: reference=%s gateway_status=%s", reference, gateway_status)
            return _verified_receipt_payload(payment, gateway_status)

        try:
            paid_kobo = int(data.get("amount"))
        except (TypeError, ValueError, InvalidOperation):
            paid_kobo = None
        expected_kobo = _amount_to_kobo(payment.amount)
        paid_currency = str(data.get("currency") or "").upper()
        if paid_kobo != expected_kobo or paid_currency != payment.currency.upper():
            logger.error(
                "Payment amount/currency mismatch: reference=%s expected=%s/%s got=%s/%s",
                reference, expected_kobo, payment.currency, paid_kobo, paid_currency,
            )
            payment.metadata = {
                **payment.metadata,
                "verification_mismatch": {
                    "expected_amount_kobo": expected_kobo,
                    "received_amount_kobo": paid_kobo,
                    "received_currency": paid_currency,
                },
            }
            payment.save(update_fields=["metadata", "updated_at"])
            raise PaymentAmountMismatchError()

        booking = Booking.objects.select_for_update().get(pk=payment.booking_id)
        if booking.status in (Booking.Status.CANCELLED, Booking.Status.EXPIRED):
            logger.error("Successful payment for non-payable booking: reference=%s booking_status=%s", reference, booking.status)
            raise BookingStateError("This booking is no longer able to accept payment. Please contact the hotel.")

        payment.status = Payment.Status.SUCCESS
        payment.paid_at = _parse_paid_at(data.get("paid_at") or data.get("paidAt"))
        payment.channel = str(data.get("channel") or "")[:40]
        payment.gateway_response = str(data.get("gateway_response") or "")[:255]
        payment.transaction_id = str(data.get("id") or "")[:60]
        payment.metadata = {**payment.metadata, "paystack_id": data.get("id"), "channel": payment.channel}
        payment.save()
        booking = booking_service.register_successful_payment(booking, payment.amount, request=request)
        payment.booking = booking

    # Only the transaction winner reaches these side effects. Delivery helpers
    # log/swallow their own errors, so payment truth is never rolled back.
    log_action(
        actor=payment.user, action="PAYMENT_VERIFIED", instance=payment,
        metadata={"reference": reference, "booking": booking.booking_reference,
                  "amount": str(payment.amount), "channel": payment.channel,
                  "triggered_by": triggered_by}, request=request,
    )
    notify_staff(
        type="PAYMENT_SUCCESS", title=f"Payment received: {booking.booking_reference}",
        message=f"{booking.currency} {money(payment.amount)} via {payment.channel or 'Paystack'}.",
        link=booking_service.staff_booking_link(booking),
    )
    if booking.guest.user_id:
        notify_users(
            [booking.guest.user], type="PAYMENT_SUCCESS",
            title=f"Payment confirmed for {booking.booking_reference}",
            message=f"We received {booking.currency} {money(payment.amount)}.",
            link=booking_service.guest_booking_link(booking),
        )
    if booking.status == Booking.Status.CONFIRMED:
        transaction.on_commit(lambda: booking_service._send_confirmation_email(booking))
    logger.info("Payment verified: reference=%s booking=%s amount=%s status=%s", reference, booking.booking_reference, payment.amount, booking.payment_status)
    payment.refresh_from_db()
    return _verified_receipt_payload(payment, "success")


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
        except (PaymentError, PaymentGatewayError, BookingStateError) as exc:
            logger.warning("Webhook verification failed for %s: %s", reference, getattr(exc, "detail", str(exc)))
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
