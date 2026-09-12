from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Type(models.TextChoices):
        BOOKING_CREATED = "BOOKING_CREATED", "New booking"
        BOOKING_CONFIRMED = "BOOKING_CONFIRMED", "Booking confirmed"
        BOOKING_CANCELLED = "BOOKING_CANCELLED", "Booking cancelled"
        BOOKING_MODIFIED = "BOOKING_MODIFIED", "Booking modified"
        PAYMENT_SUCCESS = "PAYMENT_SUCCESS", "Payment received"
        PAYMENT_FAILED = "PAYMENT_FAILED", "Payment failed"
        PAYMENT_REFUNDED = "PAYMENT_REFUNDED", "Payment refunded"
        PAYMENT_DISPUTED = "PAYMENT_DISPUTED", "Payment disputed"
        CHECK_IN = "CHECK_IN", "Guest checked in"
        CHECK_OUT = "CHECK_OUT", "Guest checked out"
        CHECKOUT_DUE_SOON = "CHECKOUT_DUE_SOON", "Checkout due soon"
        CHECKOUT_AUTO = "CHECKOUT_AUTO", "Automatic checkout"
        ENQUIRY_NEW = "ENQUIRY_NEW", "New enquiry"
        SYSTEM = "SYSTEM", "System"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=30, choices=Type.choices, db_index=True)
    title = models.CharField(max_length=150)
    message = models.TextField()
    # Frontend-relative deep link (e.g. "/dashboard/bookings.html?ref=J1-...").
    link = models.CharField(max_length=255, blank=True, default="")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read"])]

    def __str__(self):
        return f"[{self.type}] {self.title} -> {self.recipient_id}"
