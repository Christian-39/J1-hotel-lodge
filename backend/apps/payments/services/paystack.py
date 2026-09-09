"""Thin Paystack API wrapper.

The secret key is read from settings (env-driven) at call time so tests can
override it, and is NEVER returned to clients. Calls have bounded timeouts;
network/HTTP failures surface as PaymentGatewayError.
"""
import logging

import requests
from django.conf import settings

from apps.core.exceptions import PaymentGatewayError, PaymentNotConfiguredError

logger = logging.getLogger("paystack")

BASE_URL = "https://api.paystack.co"
TIMEOUT = 30


def _secret_key():
    key = getattr(settings, "PAYSTACK_SECRET_KEY", "")
    if not key:
        raise PaymentNotConfiguredError()
    return key


def _headers():
    return {
        "Authorization": f"Bearer {_secret_key()}",
        "Content-Type": "application/json",
    }


def initialize_transaction(*, email, amount_kobo, reference, callback_url, metadata=None):
    """POST /transaction/initialize → returns Paystack `data` payload."""
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
        payload = response.json()
    except requests.RequestException as exc:
        logger.error("Paystack initialize unreachable: %s", exc.__class__.__name__)
        raise PaymentGatewayError() from exc
    except ValueError as exc:
        logger.error("Paystack initialize returned non-JSON body")
        raise PaymentGatewayError() from exc

    if response.status_code != 200 or not payload.get("status"):
        logger.warning("Paystack initialize rejected (HTTP %s): %s", response.status_code, payload.get("message"))
        raise PaymentGatewayError(
            payload.get("message") or "The payment provider rejected the transaction."
        )
    return payload["data"]


def verify_transaction(reference):
    """GET /transaction/verify/:reference → returns full payload dict."""
    try:
        response = requests.get(
            f"{BASE_URL}/transaction/verify/{reference}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        payload = response.json()
    except requests.RequestException as exc:
        logger.error("Paystack verify unreachable: %s", exc.__class__.__name__)
        raise PaymentGatewayError() from exc
    except ValueError as exc:
        logger.error("Paystack verify returned non-JSON body")
        raise PaymentGatewayError() from exc

    if response.status_code != 200:
        logger.warning("Paystack verify HTTP %s: %s", response.status_code, payload.get("message"))
        raise PaymentGatewayError(payload.get("message") or "Verification request failed.")

    if not payload.get("status"):
        from apps.core.exceptions import PaymentError

        raise PaymentError(payload.get("message") or "Transaction not found with the payment provider.")

    return payload
