"""PAYMENT tests (spec §32–§36, §88–§89): initialization, verified success,
failures, amount mismatch, webhooks + signatures, idempotency, offline records."""
import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from rest_framework.throttling import ScopedRateThrottle

from apps.bookings.models import Booking
from apps.core.utils import hotel_today
from apps.notifications.models import Notification
from apps.payments.models import Payment

from .base import BaseAPITestCase
from .factories import make_room, make_room_type, make_staff, make_user
from apps.accounts.models import User


class PaymentFlowTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.room_type = make_room_type("Deluxe", price="25000.00")
        make_room(self.room_type, "201")
        self.user = make_user("payer@pay.dev", password="Str0ng!Pass")
        self.auth(self.user)
        self.today = hotel_today()
        response = self.client.post("/api/bookings/", {
            "room_type": self.room_type.slug,
            "check_in": (self.today + timedelta(days=5)).isoformat(),
            "check_out": (self.today + timedelta(days=7)).isoformat(),
            "rooms": 1, "adults": 2, "children": 0,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.json())
        self.booking_ref = response.json()["data"]["booking_reference"]
        self.booking = Booking.objects.get(booking_reference=self.booking_ref)

    # --- Initialization ------------------------------------------------------
    def test_initialize_without_paystack_config_returns_503(self):
        response = self.client.post("/api/payments/initialize/",
                                    {"booking_reference": self.booking_ref})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "PAYMENT_NOT_CONFIGURED")
        self.assertEqual(Payment.objects.count(), 0)  # rolled back, no orphan record

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_mock", PAYSTACK_PUBLIC_KEY="pk_test_mock")
    @patch("apps.payments.services.paystack.initialize_transaction")
    def test_initialize_creates_payment_and_returns_checkout_payload(self, mock_init):
        mock_init.return_value = {
            "authorization_url": "https://checkout.paystack.com/abc",
            "access_code": "abc",
        }
        response = self.client.post("/api/payments/initialize/",
                                    {"booking_reference": self.booking_ref})
        self.assertEqual(response.status_code, 201, response.json())
        data = response.json()["data"]
        self.assertEqual(data["authorization_url"], "https://checkout.paystack.com/abc")
        self.assertEqual(data["amount"], "50000.00")   # server-derived amount
        payment = Payment.objects.get()
        self.assertEqual(payment.amount, Decimal("50000.00"))
        # The amount sent to Paystack is the booking's, never client input.
        _, kwargs = mock_init.call_args
        self.assertEqual(kwargs["amount_kobo"], 5_000_000)

    # --- Verification --------------------------------------------------------
    def _make_payment(self):
        return Payment.objects.create(
            booking=self.booking, user=self.user, reference="J1P-TEST-0001",
            provider=Payment.Provider.PAYSTACK, amount=Decimal("50000.00"),
            currency="NGN", status=Payment.Status.PENDING,
        )

    def _paystack_payload(self, reference, amount_kobo=5_000_000, status_value="success"):
        return {
            "status": True,
            "message": "Verification successful",
            "data": {
                "status": status_value,
                "reference": reference,
                "amount": amount_kobo,
                "currency": "NGN",
                "channel": "card",
                "gateway_response": "Successful" if status_value == "success" else "Declined",
                "id": 99887766,
                "paid_at": "2026-09-09T10:00:00Z",
                "ip_address": "127.0.0.1",
            },
        }

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_mock")
    @patch("apps.payments.services.paystack.verify_transaction")
    def test_verify_success_confirms_booking(self, mock_verify):
        payment = self._make_payment()
        mock_verify.return_value = self._paystack_payload(payment.reference)
        response = self.client.get(f"/api/payments/verify/{payment.reference}/")
        self.assertEqual(response.status_code, 200, response.json())
        data = response.json()["data"]
        self.assertEqual(data["payment_status"], "PAID")
        self.assertEqual(data["booking_status"], "CONFIRMED")
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "CONFIRMED")
        self.assertEqual(self.booking.amount_paid, Decimal("50000.00"))
        self.assertIsNone(self.booking.expires_at)  # hold released

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_mock")
    @patch("apps.payments.services.paystack.verify_transaction")
    def test_verify_is_idempotent(self, mock_verify):
        payment = self._make_payment()
        mock_verify.return_value = self._paystack_payload(payment.reference)
        first = self.client.get(f"/api/payments/verify/{payment.reference}/")
        self.assertEqual(first.status_code, 200)
        # Second call must NOT re-credit the booking or call the gateway again.
        second = self.client.get(f"/api/payments/verify/{payment.reference}/")
        self.assertEqual(second.status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.amount_paid, Decimal("50000.00"))
        self.assertEqual(mock_verify.call_count, 1)

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_mock")
    @patch("apps.payments.services.paystack.verify_transaction")
    def test_verify_failed_payment_does_not_confirm(self, mock_verify):
        payment = self._make_payment()
        mock_verify.return_value = self._paystack_payload(payment.reference, status_value="failed")
        response = self.client.get(f"/api/payments/verify/{payment.reference}/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "PAYMENT_FAILED")
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "PENDING")
        self.assertEqual(self.booking.amount_paid, Decimal("0.00"))

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_mock")
    @patch("apps.payments.services.paystack.verify_transaction")
    def test_verify_amount_mismatch_rejected(self, mock_verify):
        payment = self._make_payment()
        mock_verify.return_value = self._paystack_payload(payment.reference, amount_kobo=10)
        response = self.client.get(f"/api/payments/verify/{payment.reference}/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "PAYMENT_AMOUNT_MISMATCH")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "PENDING")
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.amount_paid, Decimal("0.00"))

    # --- Webhook -------------------------------------------------------------
    def _post_webhook(self, payload: dict, secret="sk_test_mock", sign=True):
        body = json.dumps(payload).encode()
        signature = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha512).hexdigest() if sign else "bogus"
        return self.client.post(
            "/api/payments/webhook/", data=body, content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_mock")
    def test_webhook_rejects_invalid_signature(self):
        payment = self._make_payment()
        payload = {"event": "charge.success", "data": {"reference": payment.reference}}
        response = self._post_webhook(payload, sign=False)
        self.assertEqual(response.status_code, 401)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "PENDING")

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_mock")
    @patch("apps.payments.services.paystack.verify_transaction")
    def test_webhook_success_processes_payment(self, mock_verify):
        payment = self._make_payment()
        mock_verify.return_value = self._paystack_payload(payment.reference)
        response = self._post_webhook({
            "event": "charge.success",
            "data": {"reference": payment.reference,
                     "amount": 5_000_000, "currency": "NGN", "status": "success"},
        })
        self.assertEqual(response.status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "CONFIRMED")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "SUCCESS")

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_mock")
    def test_webhook_unknown_reference_acknowledged(self):
        response = self._post_webhook({
            "event": "charge.success", "data": {"reference": "J1P-UNKNOWN-X"},
        })
        self.assertEqual(response.status_code, 200)

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_mock")
    def test_webhook_refund_processed_marks_payment_refunded(self):
        staff = make_staff("refunds@staff.dev", role=User.Role.ADMIN)
        payment = self._make_payment()
        payment.status = Payment.Status.SUCCESS
        payment.save(update_fields=["status"])
        self.booking.status = "CONFIRMED"
        self.booking.save(update_fields=["status"])
        response = self._post_webhook({
            "event": "refund.processed",
            "data": {"amount": 5_000_000, "transaction": {"reference": payment.reference}},
        })
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REFUNDED)
        # A refund does NOT auto-cancel the booking — staff judgment required.
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "CONFIRMED")
        Notification.objects.get(recipient=staff, type="PAYMENT_REFUNDED")
        # Idempotent: a duplicate delivery is acknowledged without side effects.
        response = self._post_webhook({
            "event": "refund.processed",
            "data": {"amount": 5_000_000, "transaction": {"reference": payment.reference}},
        })
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REFUNDED)

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_mock")
    def test_webhook_dispute_create_notifies_staff_without_state_change(self):
        staff = make_staff("disputes@staff.dev", role=User.Role.ADMIN)
        payment = self._make_payment()
        payment.status = Payment.Status.SUCCESS
        payment.save(update_fields=["status"])
        response = self._post_webhook({
            "event": "charge.dispute.create",
            "data": {"reference": payment.reference, "amount": 5_000_000, "status": "pending"},
        })
        self.assertEqual(response.status_code, 200)  # must ACK, never raise
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCESS)  # untouched
        Notification.objects.get(recipient=staff, type="PAYMENT_DISPUTED")

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_mock")
    def test_webhook_throttled_after_burst(self):
        # DRF captures THROTTLE_RATES at class-definition time, so
        # override_settings(REST_FRAMEWORK=...) never reaches an already-imported
        # ScopedRateThrottle — patch the shared rates dict instead.
        cache.clear()  # isolate throttle history from earlier webhook tests
        try:
            with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"paystack_webhook": "3/min"}):
                payload = {"event": "charge.success", "data": {"reference": "J1P-BURST-1"}}
                for _ in range(3):
                    response = self._post_webhook(payload)
                    self.assertEqual(response.status_code, 200)
                response = self._post_webhook(payload)
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.json()["code"], "RATE_LIMITED")
        finally:
            cache.clear()

    # --- Access control ------------------------------------------------------
    def test_other_user_cannot_initialize_payment_for_my_booking(self):
        other = make_user("thief@pay.dev", password="Str0ng!Pass")
        self.auth(other)
        response = self.client.post("/api/payments/initialize/",
                                    {"booking_reference": self.booking_ref})
        self.assertEqual(response.status_code, 403)

    # --- Offline (staff) -----------------------------------------------------
    def test_staff_records_cash_payment_and_confirms_booking(self):
        receptionist = make_staff("desk@staff.dev", role=User.Role.RECEPTIONIST)
        self.auth(receptionist)
        response = self.client.post("/api/admin/payments/record/", {
            "booking_reference": self.booking_ref,
            "amount": "50000.00",
            "provider": "CASH",
            "notes": "Paid at front desk",
        })
        self.assertEqual(response.status_code, 201, response.json())
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "CONFIRMED")
        self.assertEqual(self.booking.payment_status, "PAID")

    def test_offline_payment_above_balance_rejected(self):
        receptionist = make_staff("desk2@staff.dev", role=User.Role.RECEPTIONIST)
        self.auth(receptionist)
        response = self.client.post("/api/admin/payments/record/", {
            "booking_reference": self.booking_ref,
            "amount": "60000.00",
            "provider": "POS",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "PAYMENT_FAILED")
