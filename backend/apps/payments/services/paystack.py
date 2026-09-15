"""Strict, server-only Paystack API wrapper.

The secret key is read from environment-backed Django settings at call time and
is never returned to clients. Network calls have bounded timeouts and every
response is validated before the payment service sees it.
"""
import logging
import time
from urllib.parse import quote

import requests
from django.conf import settings

from apps.core.exceptions import PaymentError, PaymentGatewayError, PaymentNotConfiguredError

logger = logging.getLogger("paystack")

BASE_URL = "https://api.paystack.co"


def _timeout():
    """Bounded below the browser's payment-init timeout so errors reach it."""
    return (
        getattr(settings, "PAYSTACK_CONNECT_TIMEOUT", 4),
        getattr(settings, "PAYSTACK_READ_TIMEOUT", 12),
    )


def _secret_key():
    key = getattr(settings, "PAYSTACK_SECRET_KEY", "").strip()
    if not key:
        raise PaymentNotConfiguredError()
    return key


def _headers():
    return {
        "Authorization": f"Bearer {_secret_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _json(response, operation):
    try:
        payload = response.json()
    except ValueError as exc:
        logger.error("Paystack %s returned non-JSON (HTTP %s)", operation, response.status_code)
        raise PaymentGatewayError() from exc
    if not isinstance(payload, dict):
        logger.error("Paystack %s returned an invalid JSON shape (HTTP %s)", operation, response.status_code)
        raise PaymentGatewayError()
    return payload


def initialize_transaction(*, email, amount_kobo, reference, callback_url, metadata=None):
    """POST /transaction/initialize and return validated Paystack data."""
    started = time.monotonic()
    logger.info("PAYMENT_INIT_PAYSTACK_REQUEST reference=%s amount_kobo=%s", reference, amount_kobo)
    try:
        response = requests.post(
            f"{BASE_URL}/transaction/initialize",
            json={
                "email": email,
                "amount": amount_kobo,
                "reference": reference,
                "currency": "NGN",
                "callback_url": callback_url,
                "metadata": metadata or {},
            },
            headers=_headers(),
            timeout=_timeout(),
        )
    except requests.Timeout as exc:
        logger.error(
            "PAYMENT_INIT_FAILURE reference=%s category=GATEWAY_TIMEOUT elapsed_ms=%s",
            reference, round((time.monotonic() - started) * 1000),
        )
        raise PaymentGatewayError("The payment provider timed out. Please try again.") from exc
    except requests.ConnectionError as exc:
        logger.error(
            "PAYMENT_INIT_FAILURE reference=%s category=GATEWAY_CONNECTION elapsed_ms=%s",
            reference, round((time.monotonic() - started) * 1000),
        )
        raise PaymentGatewayError() from exc
    except requests.RequestException as exc:
        logger.error(
            "PAYMENT_INIT_FAILURE reference=%s category=%s elapsed_ms=%s",
            reference, exc.__class__.__name__, round((time.monotonic() - started) * 1000),
        )
        raise PaymentGatewayError() from exc

    logger.info(
        "PAYMENT_INIT_PAYSTACK_RESPONSE reference=%s http_status=%s elapsed_ms=%s",
        reference, response.status_code, round((time.monotonic() - started) * 1000),
    )
    payload = _json(response, "initialize")
    data = payload.get("data")
    valid = (
        response.status_code == 200
        and payload.get("status") is True
        and isinstance(data, dict)
        and isinstance(data.get("authorization_url"), str)
        and data.get("authorization_url", "").startswith("https://")
        and bool(data.get("access_code"))
        and data.get("reference") == reference
    )
    if not valid:
        logger.warning(
            "Paystack initialize rejected/invalid: HTTP=%s status=%r message=%s reference=%s",
            response.status_code, payload.get("status"), payload.get("message"), reference,
        )
        # Keep provider details in server logs; customers get a stable safe error.
        raise PaymentGatewayError("Unable to start payment. Please try again.")
    return data


def verify_transaction(reference):
    """GET /transaction/verify/:reference and return a validated envelope."""
    try:
        response = requests.get(
            f"{BASE_URL}/transaction/verify/{quote(str(reference), safe='')}",
            headers=_headers(),
            timeout=_timeout(),
        )
    except requests.RequestException as exc:
        logger.error("Paystack verify unreachable: %s", exc.__class__.__name__)
        raise PaymentGatewayError() from exc

    payload = _json(response, "verify")
    if response.status_code != 200:
        logger.warning(
            "Paystack verify failed: HTTP=%s status=%r message=%s reference=%s",
            response.status_code, payload.get("status"), payload.get("message"), reference,
        )
        raise PaymentGatewayError("Unable to verify payment. Please try again.")
    if payload.get("status") is not True or not isinstance(payload.get("data"), dict):
        logger.warning("Paystack verify rejected: message=%s reference=%s", payload.get("message"), reference)
        raise PaymentError("The transaction could not be verified with the payment provider.")
    return payload


def create_refund(*, transaction, amount_kobo=None, currency="NGN", customer_note="", merchant_note=""):
    """POST /refund server-side and return the validated Paystack refund data.

    ``transaction`` must be the original Paystack transaction reference or ID.
    ``amount_kobo`` is omitted only for a full refund; partial refunds pass the
    integer amount in the currency subunit. The secret key never leaves the
    backend.
    """
    body = {"transaction": str(transaction), "currency": currency or "NGN"}
    if amount_kobo is not None:
        body["amount"] = int(amount_kobo)
    if customer_note:
        body["customer_note"] = str(customer_note)[:500]
    if merchant_note:
        body["merchant_note"] = str(merchant_note)[:500]

    try:
        response = requests.post(
            f"{BASE_URL}/refund",
            json=body,
            headers=_headers(),
            timeout=_timeout(),
        )
    except requests.RequestException as exc:
        logger.error("Paystack refund unreachable: %s", exc.__class__.__name__)
        raise PaymentGatewayError("Unable to submit refund. Please try again.") from exc

    payload = _json(response, "refund")
    data = payload.get("data")
    if response.status_code not in (200, 201) or payload.get("status") is not True or not isinstance(data, dict):
        logger.warning(
            "Paystack refund rejected/invalid: HTTP=%s status=%r message=%s transaction=%s",
            response.status_code, payload.get("status"), payload.get("message"), transaction,
        )
        raise PaymentGatewayError("Unable to submit refund to Paystack. Please review the transaction and try again.")
    return data
