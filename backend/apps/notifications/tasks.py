"""Synchronous transactional email delivery for the notifications app.

``deliver_email_log`` is the single place transactional email is actually
delivered. It is driven entirely by a database row (``EmailLog``) — it
receives a stable integer id, re-reads everything it needs from the DB, and is
the source of truth for the receipt attachment (regenerated server-side). It
records the real outcome so the dashboard can distinguish SENDING / SENT /
FAILED instead of blindly reporting success.

Delivery transport: if ``settings.BREVO_API_KEY`` is set, mail is sent over
Brevo's HTTPS transactional API (port 443) instead of raw SMTP. This exists
because Render's free web-service tier blocks outbound traffic on SMTP ports
25/465/587 — HTTPS is never blocked, so this is what actually works there.
When BREVO_API_KEY is not set, the original Django SMTP/console backend path
is used unchanged (this keeps local development, which uses the console
backend, working exactly as before).

Email delivery is SYNCHRONOUS either way: this module is invoked directly by
``apps.core.emails`` during the originating HTTP request (Send receipt click,
verified payment, booking events). No broker/worker is required for mail to
leave the system.

No SMTP credentials, API keys, or secrets are ever logged.
"""
import base64
import logging
from email.utils import parseaddr

from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives, get_connection
from django.utils import timezone

logger = logging.getLogger("apps")

_TRANSIENT_EXC_NAMES = {
    "SMTPServerDisconnected",
    "SMTPConnectError",
    "SMTPHeloError",
    "SMTPResponseException",
    "TimeoutError",
    "Timeout",  # requests.exceptions.Timeout
    "ConnectionError",  # matches both socket and requests exceptions
    "ConnectionResetError",
    "ConnectionRefusedError",
    "socket.timeout",
    "gaierror",
    "OSError",  # e.g. "Network is unreachable" when a port is firewalled
}
_PERMANENT_EXC_NAMES = {
    "SMTPAuthenticationError",
    "SMTPRecipientsRefused",
    "SMTPSenderRefused",
    "SMTPNotSupportedError",
}


class BrevoAPIError(Exception):
    """Raised when Brevo's HTTPS API rejects or fails to accept a send."""

    def __init__(self, http_status, message):
        super().__init__(f"HTTP {http_status}: {message}")
        self.http_status = http_status
        self.safe_message = str(message)[:255]


def _is_transient(exc) -> bool:
    name = exc.__class__.__name__
    if name in _PERMANENT_EXC_NAMES:
        return False
    smtp_code = getattr(exc, "smtp_code", None)
    if isinstance(smtp_code, int):
        return 400 <= smtp_code < 500
    http_status = getattr(exc, "http_status", None)
    if isinstance(http_status, int):
        return http_status == 429 or http_status >= 500
    return name in _TRANSIENT_EXC_NAMES


def _safe_reason(exc) -> str:
    """A short, credential-free description of a delivery failure."""
    if isinstance(exc, BrevoAPIError):
        return f"Brevo API rejected the message (HTTP {exc.http_status}): {exc.safe_message}"[:255]
    mapping = {
        "SMTPAuthenticationError": "SMTP authentication failed (check email user / app password).",
        "SMTPRecipientsRefused": "The recipient address was rejected by the mail server.",
        "SMTPSenderRefused": "The sender address was rejected (check DEFAULT_FROM_EMAIL).",
        "SMTPServerDisconnected": "Could not connect to the SMTP server (check EMAIL_HOST/PORT).",
        "SMTPConnectError": "Could not connect to the SMTP server (check EMAIL_HOST/PORT).",
        "SMTPNotSupportedError": "The SMTP server rejected the requested TLS/SSL mode.",
        "SMTPResponseException": "The SMTP server returned an error response.",
        "TimeoutError": "The connection to the mail server timed out.",
        "OSError": "The network connection to the mail server was refused/unreachable.",
    }
    return mapping.get(exc.__class__.__name__, f"Delivery failed ({exc.__class__.__name__}).")


def _embed_logo(email):
    """Attach the official J-ONE logo inline (Django SMTP/console path only)."""
    import os
    from email.mime.image import MIMEImage

    from apps.bookings.services.receipt_email import LOGO_CID

    try:
        assets = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "bookings", "services", "assets", "logo-official.png",
        )
        with open(assets, "rb") as handle:
            image = MIMEImage(handle.read(), _subtype="png")
        image.add_header("Content-ID", f"<{LOGO_CID}>")
        image.add_header("Content-Disposition", "inline", filename="jone-logo.png")
        email.mixed_subtype = "related"
        email.attach(image)
    except Exception as exc:  # noqa: BLE001 - branding is best-effort
        logger.info("Inline logo not embedded (%s); alt text will be shown", exc.__class__.__name__)


def _logo_data_uri_html(html_body):
    """Brevo API path: inline the logo as a base64 data: URI, replacing the
    cid: reference the template uses for the SMTP path.
    """
    import os

    from apps.bookings.services.receipt_email import LOGO_CID

    try:
        assets = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "bookings", "services", "assets", "logo-official.png",
        )
        with open(assets, "rb") as handle:
            b64 = base64.b64encode(handle.read()).decode("ascii")
        data_uri = f"data:image/png;base64,{b64}"
        return html_body.replace(f"cid:{LOGO_CID}", data_uri)
    except Exception as exc:  # noqa: BLE001 - branding is best-effort
        logger.info("Inline logo not embedded (%s); alt text will be shown", exc.__class__.__name__)
        return html_body


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
        logger.warning(
            "Receipt PDF generation failed for EmailLog#%s (%s)",
            log.pk, exc.__class__.__name__,
        )
        raise
    return None


def _send_via_brevo_api(log, attachment):
    """Send one EmailLog row over Brevo's HTTPS transactional API."""
    import requests

    api_key = (getattr(settings, "BREVO_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("BREVO_API_KEY is not configured.")

    sender_name, sender_email = parseaddr(settings.DEFAULT_FROM_EMAIL)
    payload = {
        "sender": {"email": sender_email, **({"name": sender_name} if sender_name else {})},
        "to": [{"email": log.to_email}],
        "subject": log.subject,
        "textContent": log.body or "",
    }
    html_body = (log.html_body or "").strip()
    if html_body:
        payload["htmlContent"] = _logo_data_uri_html(html_body)
    if attachment:
        filename, content = attachment
        payload["attachment"] = [
            {"name": filename, "content": base64.b64encode(content).decode("ascii")}
        ]

    timeout = getattr(settings, "EMAIL_TIMEOUT", 20) or 20
    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        raise ConnectionError(f"Brevo API request failed: {exc.__class__.__name__}") from exc

    if response.status_code not in (200, 201):
        try:
            body = response.json()
            message = body.get("message") or body.get("code") or response.text[:200]
        except ValueError:
            message = response.text[:200]
        raise BrevoAPIError(response.status_code, message)


def _send_via_smtp(log, attachment):
    """Django's configured EMAIL_BACKEND (SMTP or console) — unchanged local-dev path."""
    connection = get_connection(fail_silently=False)
    html_body = (log.html_body or "").strip()
    if html_body:
        email = EmailMultiAlternatives(
            subject=log.subject,
            body=log.body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[log.to_email],
            connection=connection,
        )
        email.attach_alternative(html_body, "text/html")
        _embed_logo(email)
    else:
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


def deliver_email_log(log_id, *, allow_retry=True, task=None):
    """Deliver one EmailLog row through the configured transport."""
    from apps.notifications.models import EmailLog

    log = EmailLog.objects.filter(pk=log_id).first()
    if log is None:
        logger.warning("EmailLog#%s vanished before delivery", log_id)
        return None
    if log.status == EmailLog.Status.SENT:
        logger.info("EmailLog#%s already SENT; skipping duplicate", log_id)
        return EmailLog.Status.SENT

    EmailLog.objects.filter(pk=log.pk).update(status=EmailLog.Status.SENDING)

    failure_stage = EmailLog.FailureStage.ATTACHMENT
    try:
        attachment = _build_attachment(log)
        failure_stage = EmailLog.FailureStage.SMTP
        use_brevo_api = bool((getattr(settings, "BREVO_API_KEY", "") or "").strip())
        if use_brevo_api:
            _send_via_brevo_api(log, attachment)
        else:
            _send_via_smtp(log, attachment)
    except Exception as exc:
        transient = _is_transient(exc)
        can_retry = allow_retry and transient and log.retry_count < log.max_retries
        new_status = EmailLog.Status.RETRYING if can_retry else EmailLog.Status.FAILED
        EmailLog.objects.filter(pk=log.pk).update(
            status=new_status,
            retry_count=log.retry_count + 1,
            error_class=exc.__class__.__name__,
            error_message=_safe_reason(exc),
            failure_stage=failure_stage,
            failed_at=timezone.now(),
        )
        logger.warning(
            "EmailLog#%s delivery %s: %s (attempt %s/%s)",
            log.pk,
            "will retry" if can_retry else "FAILED",
            exc.__class__.__name__,
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
        failure_stage="",
    )
    logger.info(
        "EmailLog#%s SENT kind=%s booking=%s to=%s",
        log.pk, log.kind, log.booking_reference or "-", log.to_email,
    )
    return EmailLog.Status.SENT


class _RetryRequested(Exception):
    """Internal signal: transient failure, a retry may be scheduled by the caller."""

    def __init__(self, original):
        super().__init__(str(original.__class__.__name__))
        self.original = original