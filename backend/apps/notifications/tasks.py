"""Synchronous transactional email delivery for the notifications app.

``deliver_email_log`` is the single place transactional email is actually
delivered. It is driven entirely by a database row (``EmailLog``) — it
receives a stable integer id, re-reads everything it needs from the DB, and is
the source of truth for the receipt attachment (regenerated server-side). It
records the real outcome so the dashboard can distinguish SENDING / SENT /
FAILED instead of blindly reporting success.

Transport selection is DETERMINISTIC (see :func:`active_transport`):

* ``EMAIL_PROVIDER=brevo``  → Brevo's HTTPS transactional API
  (https://api.brevo.com/v3/smtp/email, authenticated with the ``api-key``
  header). This is the required production transport: Render's free tier
  blocks outbound SMTP ports (25/465/587), while HTTPS/443 always works.
* ``EMAIL_PROVIDER=django`` (or ``smtp``/``console``) → Django's configured
  ``EMAIL_BACKEND`` (console in development, SMTP where explicitly wanted).
* unset → Brevo when ``BREVO_API_KEY`` is configured, otherwise the Django
  backend. Production settings pin the provider explicitly so Gmail SMTP can
  never be selected by accident merely because EMAIL_* variables exist.

Email delivery is SYNCHRONOUS: this module is invoked directly by
``apps.core.emails`` during the originating HTTP request (Send receipt click,
verified payment, booking events). No Celery task, broker, Redis connection or
worker is required — or used — for mail to leave the system. A row is marked
SENT only after the provider accepted the message (Brevo answered 200/201 with
a messageId, or the Django backend reported delivery); anything else is FAILED
with a safe, credential-free reason.

No SMTP credentials, API keys, or secrets are ever logged or stored.
"""
import base64
import logging
from email.utils import parseaddr

from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives, get_connection
from django.utils import timezone

logger = logging.getLogger("apps")

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


class BrevoAPIError(Exception):
    """Raised when Brevo's HTTPS API rejects or fails to accept a send."""

    def __init__(self, http_status, message):
        super().__init__(f"HTTP {http_status}: {message}")
        self.http_status = http_status
        self.safe_message = str(message)[:255]


def active_transport() -> str:
    """Which transport a delivery attempt will use: ``"brevo"`` or ``"django"``.

    Deterministic: an explicit ``EMAIL_PROVIDER`` setting always wins; when it
    is not set, Brevo is used whenever a ``BREVO_API_KEY`` is configured.
    """
    provider = str(getattr(settings, "EMAIL_PROVIDER", "") or "").strip().lower()
    if provider == "brevo":
        return "brevo"
    if provider in ("django", "smtp", "console"):
        return "django"
    return "brevo" if (getattr(settings, "BREVO_API_KEY", "") or "").strip() else "django"


def sender_identity():
    """(name, email) parsed from DEFAULT_FROM_EMAIL, with validation.

    Raises ``ValueError`` naming the setting when the configured value does
    not contain a usable address — this must surface precisely, never as a
    silent substitution of another sender.
    """
    raw = str(getattr(settings, "DEFAULT_FROM_EMAIL", "") or "").strip()
    # Tolerate an accidentally quote-wrapped env value: "Name <a@b>" (quotes
    # typed into the Render dashboard become part of the value).
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        raw = raw[1:-1].strip()
    name, email = parseaddr(raw)
    if not email or "@" not in email or "<" in email or ">" in email:
        raise ValueError(
            "DEFAULT_FROM_EMAIL is not a valid sender address. Set it to "
            "'Display Name <address@example.com>' using a sender verified in Brevo."
        )
    return name, email


def _safe_reason(exc) -> str:
    """A short, credential-free description of a delivery failure."""
    if isinstance(exc, BrevoAPIError):
        return f"Brevo rejected the request (HTTP {exc.http_status}): {exc.safe_message}"[:255]
    mapping = {
        "ValueError": str(exc)[:255] if "DEFAULT_FROM_EMAIL" in str(exc) else "Delivery failed (ValueError).",
        "SMTPAuthenticationError": "SMTP authentication failed (check email user / app password).",
        "SMTPRecipientsRefused": "The recipient address was rejected by the mail server.",
        "SMTPSenderRefused": "The sender address was rejected (check DEFAULT_FROM_EMAIL).",
        "SMTPServerDisconnected": "Could not connect to the SMTP server (check EMAIL_HOST/PORT).",
        "SMTPConnectError": "Could not connect to the SMTP server (check EMAIL_HOST/PORT).",
        "SMTPNotSupportedError": "The SMTP server rejected the requested TLS/SSL mode.",
        "SMTPResponseException": "The SMTP server returned an error response.",
        "TimeoutError": "The connection to the mail server timed out.",
        "Timeout": "The HTTPS request to the email provider timed out.",
        "ConnectionError": "The email provider could not be reached over the network.",
        "OSError": "The network connection to the mail server was refused/unreachable.",
        "RuntimeError": str(exc)[:255],
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
    """Send one EmailLog row over Brevo's HTTPS transactional API.

    Returns the provider message id on success; raises ``BrevoAPIError`` with
    the real HTTP status + sanitized provider message on rejection, and
    ``ConnectionError``/``TimeoutError`` when the request cannot complete.
    Never logs or stores the API key.
    """
    import requests

    api_key = (getattr(settings, "BREVO_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError(
            "BREVO_API_KEY is not configured — set the BREVO_API_KEY environment variable."
        )

    sender_name, sender_email = sender_identity()
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
            BREVO_API_URL,
            json=payload,
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
    except requests.exceptions.Timeout as exc:
        raise TimeoutError("The HTTPS request to Brevo timed out.") from exc
    except requests.exceptions.RequestException as exc:
        raise ConnectionError(f"Brevo API request failed: {exc.__class__.__name__}") from exc

    if response.status_code not in (200, 201):
        try:
            body = response.json()
            message = body.get("message") or body.get("code") or response.text[:200]
        except ValueError:
            message = response.text[:200]
        raise BrevoAPIError(response.status_code, message)

    # HTTP 200/201: Brevo accepted the message. Record its real message id.
    try:
        message_id = str((response.json() or {}).get("messageId") or "")
    except ValueError:
        message_id = ""
    if not message_id:
        # 200/201 without a message id is not a normal Brevo acceptance.
        raise BrevoAPIError(
            response.status_code, "Brevo returned success without a messageId."
        )
    return message_id[:255]


def _send_via_django_backend(log, attachment):
    """Django's configured EMAIL_BACKEND (SMTP or console) — local-dev path."""
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
    return ""  # Django backends expose no provider message id


# Back-compat alias for older imports/tests.
_send_via_smtp = _send_via_django_backend


def deliver_email_log(log_id, **_ignored):
    """Deliver one EmailLog row synchronously through the active transport.

    Exactly one honest attempt: the row ends SENT (provider accepted) or
    FAILED (with error class, safe reason and failure stage). The final
    status is returned. Never raises for delivery failures — the outcome is
    persisted instead.
    """
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
        failure_stage = EmailLog.FailureStage.PROVIDER
        if active_transport() == "brevo":
            provider_message_id = _send_via_brevo_api(log, attachment)
        else:
            provider_message_id = _send_via_django_backend(log, attachment)
    except Exception as exc:  # noqa: BLE001 - outcome persisted below
        EmailLog.objects.filter(pk=log.pk).update(
            status=EmailLog.Status.FAILED,
            error_class=exc.__class__.__name__,
            error_message=_safe_reason(exc),
            failure_stage=failure_stage,
            failed_at=timezone.now(),
        )
        logger.warning(
            "EmailLog#%s delivery FAILED at %s: %s",
            log.pk, failure_stage, exc.__class__.__name__,
        )
        return EmailLog.Status.FAILED

    EmailLog.objects.filter(pk=log.pk).update(
        status=EmailLog.Status.SENT,
        sent_at=timezone.now(),
        provider_message_id=provider_message_id or "",
        error_class="",
        error_message="",
        failure_stage="",
    )
    logger.info(
        "EmailLog#%s SENT kind=%s booking=%s to=%s provider_id=%s",
        log.pk, log.kind, log.booking_reference or "-", log.to_email,
        provider_message_id or "-",
    )
    return EmailLog.Status.SENT
