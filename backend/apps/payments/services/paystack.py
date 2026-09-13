"""Strict, server-only Paystack API wrapper.

The secret key is read from environment-backed Django settings at call time and
is never returned to clients. Network calls have bounded timeouts and every
response is validated before the payment service sees it.
"""
import logging
from urllib.parse import quote

import requests
from django.conf import settings

from apps.core.exceptions import PaymentError, PaymentGatewayError, PaymentNotConfiguredError

logger = logging.getLogger("paystack")

BASE_URL = "https://api.paystack.co"
TIMEOUT = (5, 25)  # connect, read


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
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("Paystack initialize unreachable: %s", exc.__class__.__name__)
        raise PaymentGatewayError() from exc

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
            timeout=TIMEOUT,
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
