"""Celery tasks owned by the notifications app.

``send_email_task`` is the single place transactional email is actually
delivered. It is driven entirely by a database row (``EmailLog``) — the task
receives a stable integer id, re-reads everything it needs from the DB, and is
the source of truth for the receipt attachment (regenerated server-side). It
records the real outcome so the dashboard can distinguish QUEUED / SENT /
FAILED / RETRYING instead of blindly reporting success.

No SMTP credentials or secrets are ever logged.
"""
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

logger = logging.getLogger("apps")

# SMTP responses that are worth retrying (transient). Everything else is
# treated as permanent so we never loop forever on e.g. auth failures or a
# malformed recipient.
_TRANSIENT_EXC_NAMES = {
    "SMTPServerDisconnected",
    "SMTPConnectError",
    "SMTPHeloError",
    "SMTPResponseException",  # inspect code below
    "TimeoutError",
    "ConnectionError",
    "ConnectionResetError",
    "ConnectionRefusedError",
    "socket.timeout",
    "gaierror",
}
_PERMANENT_EXC_NAMES = {
    "SMTPAuthenticationError",
    "SMTPRecipientsRefused",
    "SMTPSenderRefused",
    "SMTPNotSupportedError",
}


def _is_transient(exc) -> bool:
    name = exc.__class__.__name__
    if name in _PERMANENT_EXC_NAMES:
        return False
    # 4xx SMTP codes are transient; 5xx are permanent.
    code = getattr(exc, "smtp_code", None)
    if isinstance(code, int):
        return 400 <= code < 500
    return name in _TRANSIENT_EXC_NAMES


def _safe_reason(exc) -> str:
    """A short, credential-free description of a delivery failure."""
    mapping = {
        "SMTPAuthenticationError": "SMTP authentication failed (check email user / app password).",
        "SMTPRecipientsRefused": "The recipient address was rejected by the mail server.",
        "SMTPSenderRefused": "The sender address was rejected (check DEFAULT_FROM_EMAIL).",
        "SMTPServerDisconnected": "Could not connect to the SMTP server (check EMAIL_HOST/PORT).",
        "SMTPConnectError": "Could not connect to the SMTP server (check EMAIL_HOST/PORT).",
        "SMTPNotSupportedError": "The SMTP server rejected the requested TLS/SSL mode.",
        "SMTPResponseException": "The SMTP server returned an error response.",
        "TimeoutError": "The connection to the SMTP server timed out.",
    }
    return mapping.get(exc.__class__.__name__, f"Delivery failed ({exc.__class__.__name__}).")


def _build_attachment(log):
    """Regenerate the receipt PDF from the DB. Returns (filename, bytes) or None."""
    if not (log.attach_receipt_pdf and log.booking_id):
        return None
    try:
        from apps.bookings.models import Booking
        from apps.bookings.serializers import ReceiptSerializer
        from apps.bookings.services.receipt_pdf import render_receipt_pdf

        booking = Booking.objects.select_related("guest", "room_type", "offer").get(
            pk=log.booking_id
        )
        receipt = ReceiptSerializer().to_representation(booking)
        pdf_bytes = render_receipt_pdf(receipt)
        if pdf_bytes:
            return (f"receipt-{booking.booking_reference}.pdf", pdf_bytes)
    except Exception as exc:
        # Attachment failure must NOT masquerade as a delivered receipt.
        logger.warning(
            "Receipt PDF generation failed for EmailLog#%s (%s)",
            log.pk, exc.__class__.__name__,
        )
        raise
    return None


def deliver_email_log(log_id, *, allow_retry=True, task=None):
    """Deliver one EmailLog row through the configured backend.

    Returns the final status string. When ``allow_retry`` is True and the
    failure is transient and retries remain, raises ``_RetryRequested`` so the
    Celery wrapper can schedule a retry with backoff.
    """
    from apps.notifications.models import EmailLog

    log = EmailLog.objects.filter(pk=log_id).first()
    if log is None:
        logger.warning("EmailLog#%s vanished before delivery", log_id)
        return None
    if log.status == EmailLog.Status.SENT:
        # Idempotency: never send the same tracked email twice.
        logger.info("EmailLog#%s already SENT; skipping duplicate", log_id)
        return EmailLog.Status.SENT

    EmailLog.objects.filter(pk=log.pk).update(status=EmailLog.Status.SENDING)

    try:
        attachment = _build_attachment(log)
        connection = get_connection(fail_silently=False)
        email = EmailMessage(
            subject=log.subject,
            body=log.body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[log.to_email],
            connection=connection,
        )
        if attachment:
            filename, content = attachment
            email.attach(filename, content, "application/pdf")
        sent = email.send(fail_silently=False)
        if not sent:
            raise RuntimeError("Email backend reported zero messages delivered.")
    except Exception as exc:
        transient = _is_transient(exc)
        can_retry = allow_retry and transient and log.retry_count < log.max_retries
        new_status = EmailLog.Status.RETRYING if can_retry else EmailLog.Status.FAILED
        EmailLog.objects.filter(pk=log.pk).update(
            status=new_status,
            retry_count=log.retry_count + 1,
            error_class=exc.__class__.__name__,
            error_message=_safe_reason(exc),
            failed_at=timezone.now(),
        )
        logger.warning(
            "EmailLog#%s delivery %s: %s (attempt %s/%s)",
            log.pk,
            "will retry" if can_retry else "FAILED",
            exc.__class__.__name__,  # never the message → no credential leakage
            log.retry_count + 1,
            log.max_retries,
        )
        if can_retry:
            raise _RetryRequested(exc)
        return EmailLog.Status.FAILED

    EmailLog.objects.filter(pk=log.pk).update(
        status=EmailLog.Status.SENT,
        sent_at=timezone.now(),
        error_class="",
        error_message="",
    )
    logger.info(
        "EmailLog#%s SENT kind=%s booking=%s to=%s",
        log.pk, log.kind, log.booking_reference or "-", log.to_email,
    )
    return EmailLog.Status.SENT


class _RetryRequested(Exception):
    """Internal signal: transient failure, caller should schedule a retry."""

    def __init__(self, original):
        super().__init__(str(original.__class__.__name__))
        self.original = original


@shared_task(
    bind=True,
    max_retries=3,
    name="apps.notifications.send_email",
)
def send_email_task(self, log_id):
    """Deliver a tracked email off the request path; retry transient failures."""
    try:
        return deliver_email_log(log_id, allow_retry=True, task=self)
    except _RetryRequested as retry:
        # Exponential backoff: 30s, 60s, 120s.
        countdown = 30 * (2 ** self.request.retries)
        raise self.retry(exc=retry.original, countdown=countdown)
