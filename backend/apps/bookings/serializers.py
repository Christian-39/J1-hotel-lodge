"""Booking serializers.

Money always serializes as strings ("15000.00") so exact values travel the
wire without binary float artifacts.
"""
from rest_framework import serializers

from apps.core.utils import money

from .models import Booking, BookingRoom, Guest


# ---------------------------------------------------------------------------
# Shared nested shapes
# ---------------------------------------------------------------------------
class GuestWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Guest
        fields = [
            "first_name", "last_name", "email", "phone", "address", "city",
            "state", "country", "identification_type", "identification_number",
        ]
        extra_kwargs = {
            "first_name": {"required": False},
            "last_name": {"required": False},
            "email": {"required": False},
            "phone": {"required": False},
        }

    def validate_identification_number(self, value):
        # Stored only if the hotel collects it; basic sanitation.
        return value.strip()[:64]


class GuestReadSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Guest
        fields = [
            "id", "first_name", "last_name", "full_name", "email", "phone",
            "address", "city", "state", "country", "identification_type", "created_at",
        ]


class BookingRoomSerializer(serializers.ModelSerializer):
    room_number = serializers.CharField(source="room.room_number", read_only=True)
    floor = serializers.IntegerField(source="room.floor", read_only=True)

    class Meta:
        model = BookingRoom
        fields = ["id", "room_number", "floor", "check_in", "check_out"]


class BookingMoneyMixin:
    money_fields = ("price_per_night", "subtotal", "discount_amount", "extra_guest_fee_amount",
                    "tax_amount", "fee_amount", "total_amount", "required_payment",
                    "amount_paid", "amount_due", "refund_amount")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for field_name in self.money_fields:
            if field_name in data and data[field_name] is not None:
                data[field_name] = money(getattr(instance, field_name))
        return data


# ---------------------------------------------------------------------------
# Guest-facing
# ---------------------------------------------------------------------------
class BookingListSerializer(BookingMoneyMixin, serializers.ModelSerializer):
    room_type_name = serializers.CharField(source="room_type.name", read_only=True)
    room_type_slug = serializers.CharField(source="room_type.slug", read_only=True)
    nights = serializers.IntegerField(read_only=True)
    number_of_guests = serializers.IntegerField(read_only=True)
    amount_due = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id", "booking_reference", "room_type_name", "room_type_slug",
            "check_in", "check_out", "nights", "number_of_rooms", "number_of_guests",
            "total_amount", "amount_paid", "amount_due", "currency", "status",
            "payment_status", "created_at", "expires_at",
        ]


class BookingDetailSerializer(BookingMoneyMixin, serializers.ModelSerializer):
    guest = GuestReadSerializer(read_only=True)
    room_assignments = BookingRoomSerializer(many=True, read_only=True)
    room_type_name = serializers.CharField(source="room_type.name", read_only=True)
    room_type_slug = serializers.CharField(source="room_type.slug", read_only=True)
    offer_title = serializers.SerializerMethodField()
    nights = serializers.IntegerField(read_only=True)
    number_of_guests = serializers.IntegerField(read_only=True)
    amount_due = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    can_pay = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id", "booking_reference", "guest", "room_type_name", "room_type_slug",
            "room_assignments", "check_in", "check_out", "nights", "number_of_rooms",
            "adults", "children", "number_of_guests", "price_per_night", "subtotal",
            "discount_amount", "extra_guest_fee_amount", "tax_amount", "fee_amount",
            "total_amount", "required_payment", "amount_paid", "amount_due",
            "refund_amount", "currency", "offer_title", "status", "payment_status",
            "source", "special_requests", "cancellation_reason", "expires_at",
            "checked_in_at", "checked_out_at", "cancelled_at", "created_at",
            "can_pay", "can_cancel",
        ]

    def get_offer_title(self, obj):
        return obj.offer.title if obj.offer_id else None

    def get_can_pay(self, obj):
        return (
            obj.status == Booking.Status.PENDING
            and not obj.is_expired_pending
            and obj.amount_due > 0
        )

    def get_can_cancel(self, obj):
        return obj.status in (Booking.Status.PENDING, Booking.Status.CONFIRMED) and not obj.is_expired_pending


# ---------------------------------------------------------------------------
# Booking flow request shapes
# ---------------------------------------------------------------------------
class StayDetailsSerializer(serializers.Serializer):
    room_type = serializers.CharField(help_text="Room type slug or id")
    check_in = serializers.DateField()
    check_out = serializers.DateField()
    rooms = serializers.IntegerField(min_value=1, max_value=20, default=1)
    adults = serializers.IntegerField(min_value=1, max_value=60, default=1)
    children = serializers.IntegerField(min_value=0, max_value=60, default=0)
    offer_code = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_room_type(self, value):
        from .services.booking_service import resolve_room_type

        if resolve_room_type(value) is None:
            raise serializers.ValidationError("Unknown room type.")
        return value


class AvailabilityQuerySerializer(serializers.Serializer):
    check_in = serializers.DateField()
    check_out = serializers.DateField()
    guests = serializers.IntegerField(min_value=1, max_value=100, default=1)
    rooms = serializers.IntegerField(min_value=1, max_value=50, default=1)
    room_type = serializers.CharField(required=False, allow_blank=True, default="")


class QuoteRequestSerializer(StayDetailsSerializer):
    pass


class BookingCreateSerializer(StayDetailsSerializer):
    guest = GuestWriteSerializer(required=False)
    special_requests = serializers.CharField(required=False, allow_blank=True, default="")


class CancelBookingSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


# ---------------------------------------------------------------------------
# Receipts / confirmation
# ---------------------------------------------------------------------------
class ReceiptSerializer(serializers.Serializer):
    """Receipt data for a paid booking (owner/staff)."""

    def to_representation(self, booking: Booking):
        from apps.hotel.models import HotelSettings

        hotel = HotelSettings.get_settings()
        payments = booking.payments.filter(status="SUCCESS").order_by("paid_at")
        return {
            "hotel": {
                "name": hotel.hotel_name,
                "address": hotel.address,
                "phone": hotel.phone,
                "email": hotel.email,
            },
            "booking_reference": booking.booking_reference,
            "booking_status": booking.status,
            "payment_status": booking.payment_status,
            "guest": {
                "name": booking.guest.full_name,
                "email": booking.guest.email,
                "phone": booking.guest.phone,
            },
            "room_type": booking.room_type.name,
            "rooms": booking.number_of_rooms,
            "check_in": booking.check_in.isoformat(),
            "check_out": booking.check_out.isoformat(),
            "nights": booking.nights,
            "subtotal": money(booking.subtotal),
            "discount": money(booking.discount_amount),
            "tax": money(booking.tax_amount),
            "fees": money(booking.fee_amount + booking.extra_guest_fee_amount),
            "total": money(booking.total_amount),
            "amount_paid": money(booking.amount_paid),
            "amount_due": money(booking.amount_due),
            "currency": booking.currency,
            "payments": [
                {
                    "reference": p.reference,
                    "amount": money(p.amount),
                    "status": p.status,
                    "provider": p.provider,
                    "channel": p.channel,
                    "paid_at": p.paid_at.isoformat() if p.paid_at else None,
                }
                for p in payments
            ],
        }
