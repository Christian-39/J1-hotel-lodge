from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "booking", "amount", "currency", "status", "provider", "channel", "paid_at")
    list_filter = ("status", "provider")
    search_fields = ("reference", "transaction_id", "booking__booking_reference")
    readonly_fields = (
        "booking", "user", "reference", "provider", "amount", "currency", "status",
        "channel", "gateway_response", "transaction_id", "paid_at", "metadata", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # Payment records are never deleted; refunds change status.
        return False
