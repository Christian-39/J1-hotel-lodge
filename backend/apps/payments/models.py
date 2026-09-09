"""Payment records.

Card data never touches this system: Paystack hosts the card capture. We only
store transaction metadata sent back by Paystack that is safe to keep.
"""
from django.conf import settings
from django.db import models

from apps.bookings.models import Booking
from apps.core.models import TimeStampedModel


class Payment(TimeStampedModel):
    class Provider(models.TextChoices):
        PAYSTACK = "PAYSTACK", "Paystack (online)"
        CASH = "CASH", "Cash"
        POS = "POS", "POS Terminal"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="payments")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="payments_made",
        help_text="Payer (online) or staff member who recorded the payment (offline).",
    )
    reference = models.CharField(max_length=60, unique=True, db_index=True)
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.PAYSTACK)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(max_length=20, choices=Status.choices,
                              default=Status.PENDING, db_index=True)
    channel = models.CharField(max_length=40, blank=True, default="")  # card / bank / ussd / cash...
    gateway_response = models.CharField(max_length=255, blank=True, default="")
    transaction_id = models.CharField(max_length=60, blank=True, default="", db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    # Whitelisted gateway metadata only — never raw authorization/card data.
    metadata = models.JSONField(default=dict, blank=True)
    notes = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["booking", "status"]),
            models.Index(fields=["provider", "status"]),
        ]

    def __str__(self):
        return f"{self.reference} · {self.amount} {self.currency} · {self.status}"
