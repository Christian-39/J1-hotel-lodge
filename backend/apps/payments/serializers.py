from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    """Safe payment representation — never contains gateway secrets/card data."""

    booking_reference = serializers.CharField(source="booking.booking_reference", read_only=True)
    guest_name = serializers.CharField(source="booking.guest.full_name", read_only=True)
    staff_email = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id", "reference", "booking_reference", "guest_name", "staff_email",
            "provider", "amount", "currency", "status", "channel",
            "gateway_response", "transaction_id", "paid_at", "notes", "created_at",
        ]
        read_only_fields = fields

    def get_staff_email(self, obj):
        return obj.user.email if obj.user_id else None


class InitializePaymentSerializer(serializers.Serializer):
    booking_reference = serializers.CharField()


class RecordOfflinePaymentSerializer(serializers.Serializer):
    booking_reference = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    provider = serializers.ChoiceField(
        choices=[Payment.Provider.CASH, Payment.Provider.POS, Payment.Provider.BANK_TRANSFER]
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")
