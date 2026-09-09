"""Staff serializers for booking and guest management."""
from rest_framework import serializers

from apps.core.utils import money
from apps.rooms.serializers import RoomSerializer

from .models import Booking, BookingRoom, Guest
from .serializers import BookingRoomSerializer, GuestReadSerializer


class AdminBookingListSerializer(serializers.ModelSerializer):
    """Row shape for the staff bookings table — one request for the whole page."""

    guest_name = serializers.CharField(source="guest.full_name", read_only=True)
    guest_phone = serializers.CharField(source="guest.phone", read_only=True)
    guest_email = serializers.CharField(source="guest.email", read_only=True)
    room_type_name = serializers.CharField(source="room_type.name", read_only=True)
    room_numbers = serializers.SerializerMethodField()
    nights = serializers.IntegerField(read_only=True)
    amount_due = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id", "booking_reference", "guest_name", "guest_phone", "guest_email",
            "room_type_name", "room_numbers", "check_in", "check_out", "nights",
            "number_of_rooms", "number_of_guests", "total_amount", "amount_paid",
            "amount_due", "currency", "status", "payment_status", "source", "created_at",
        ]

    def get_room_numbers(self, obj) -> list:
        return [a.room.room_number for a in getattr(obj, "_assignments", obj.room_assignments.all())]

    def get_amount_due(self, obj) -> str:
        return money(obj.amount_due)


class AdminBookingDetailSerializer(AdminBookingListSerializer):
    guest = GuestReadSerializer(read_only=True)
    room_assignments = BookingRoomSerializer(many=True, read_only=True)
    offer_title = serializers.SerializerMethodField()

    class Meta(AdminBookingListSerializer.Meta):
        fields = AdminBookingListSerializer.Meta.fields + [
            "guest", "room_assignments", "adults", "children", "price_per_night",
            "subtotal", "discount_amount", "extra_guest_fee_amount", "tax_amount",
            "fee_amount", "required_payment", "refund_amount", "offer_title",
            "special_requests", "internal_notes", "cancellation_reason",
            "expires_at", "checked_in_at", "checked_out_at", "cancelled_at", "updated_at",
        ]

    def get_offer_title(self, obj):
        return obj.offer.title if obj.offer_id else None


class AdminBookingCreateSerializer(serializers.Serializer):
    """Staff manual booking (walk-in/phone). Guest details are mandatory."""

    room_type = serializers.CharField()
    check_in = serializers.DateField()
    check_out = serializers.DateField()
    rooms = serializers.IntegerField(min_value=1, max_value=50, default=1)
    adults = serializers.IntegerField(min_value=1, max_value=100, default=1)
    children = serializers.IntegerField(min_value=0, max_value=100, default=0)
    source = serializers.ChoiceField(
        choices=[Booking.Source.WALK_IN, Booking.Source.PHONE], default=Booking.Source.WALK_IN
    )
    status = serializers.ChoiceField(
        choices=[Booking.Status.PENDING, Booking.Status.CONFIRMED], default=Booking.Status.CONFIRMED
    )
    offer_code = serializers.CharField(required=False, allow_blank=True, default="")
    special_requests = serializers.CharField(required=False, allow_blank=True, default="")
    internal_notes = serializers.CharField(required=False, allow_blank=True, default="")
    guest = serializers.DictField(child=serializers.CharField(allow_blank=True), required=True)

    def validate_guest(self, value):
        required = ["first_name", "last_name", "email", "phone"]
        missing = [key for key in required if not (value.get(key) or "").strip()]
        if missing:
            raise serializers.ValidationError({key: "This field is required." for key in missing})
        return value


class AdminBookingModifySerializer(serializers.Serializer):
    check_in = serializers.DateField(required=False)
    check_out = serializers.DateField(required=False)
    number_of_rooms = serializers.IntegerField(min_value=1, max_value=50, required=False)
    adults = serializers.IntegerField(min_value=1, max_value=100, required=False)
    children = serializers.IntegerField(min_value=0, max_value=100, required=False)
    special_requests = serializers.CharField(required=False, allow_blank=True)
    internal_notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if "check_in" in attrs and "check_out" in attrs and attrs["check_out"] <= attrs["check_in"]:
            raise serializers.ValidationError({"check_out": ["Must be after check-in."]})
        return attrs


class AssignRoomSerializer(serializers.Serializer):
    assignment_id = serializers.IntegerField(min_value=1)
    room_id = serializers.IntegerField(min_value=1)


class RecordActionSerializer(serializers.Serializer):
    """For actions accepting an optional note/flag."""

    reason = serializers.CharField(required=False, allow_blank=True, default="")
    allow_balance_due = serializers.BooleanField(required=False, default=False)


class AdminGuestListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    bookings_count = serializers.IntegerField(read_only=True)
    last_booking_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = Guest
        fields = [
            "id", "first_name", "last_name", "full_name", "email", "phone",
            "city", "state", "country", "bookings_count", "last_booking_at", "created_at",
        ]


class AdminGuestDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    bookings = serializers.SerializerMethodField()
    user_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = Guest
        fields = [
            "id", "user_id", "first_name", "last_name", "full_name", "email", "phone",
            "address", "city", "state", "country", "identification_type",
            "identification_number", "special_requests", "bookings", "created_at", "updated_at",
        ]

    def get_bookings(self, obj):
        qs = (
            obj.bookings.select_related("room_type")
            .order_by("-created_at")
            .only(
                "id", "booking_reference", "status", "payment_status", "check_in",
                "check_out", "total_amount", "currency", "created_at", "room_type__name",
            )[:15]
        )
        return [
            {
                "id": b.pk,
                "booking_reference": b.booking_reference,
                "room_type_name": b.room_type.name,
                "check_in": b.check_in.isoformat(),
                "check_out": b.check_out.isoformat(),
                "status": b.status,
                "payment_status": b.payment_status,
                "total_amount": money(b.total_amount),
                "currency": b.currency,
                "created_at": b.created_at.isoformat(),
            }
            for b in qs
        ]


class AdminGuestUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Guest
        fields = [
            "first_name", "last_name", "email", "phone", "address", "city",
            "state", "country", "identification_type", "identification_number",
            "special_requests",
        ]
