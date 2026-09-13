"""Staff serializers for booking and guest management."""
from rest_framework import serializers

from apps.core.utils import money
from apps.rooms.models import Room
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
    # Optional exact physical room ("Room 203") the receptionist promised.
    # Advisory: availability is re-verified server-side and an equivalent room
    # of the same type may be assigned instead (reported as room_substitution).
    room_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_room_id(self, value):
        if not value:
            return None
        if not Room.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError("That room does not exist or is out of service.")
        return value

    def validate(self, attrs):
        room_id = attrs.get("room_id")
        if room_id:
            from .services.booking_service import resolve_room_type

            room_type = resolve_room_type(attrs["room_type"], active_only=False)
            if room_type is None or not Room.objects.filter(
                pk=room_id, room_type=room_type
            ).exists():
                raise serializers.ValidationError(
                    {"room_id": ["That room does not belong to the selected room type."]}
                )
        return attrs

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
    """Complete guest profile for the staff profile modal.

    Every non-sensitive field the ``Guest`` model actually stores is exposed so
    the dashboard can show it. The one sensitive column (``identification_number``)
    is masked for receptionists — full value only for managers and admins.
    """

    full_name = serializers.CharField(read_only=True)
    bookings = serializers.SerializerMethodField()
    user_id = serializers.IntegerField(read_only=True, allow_null=True)
    has_account = serializers.SerializerMethodField()
    identification_type_label = serializers.SerializerMethodField()
    identification_number = serializers.SerializerMethodField()
    bookings_count = serializers.SerializerMethodField()
    last_booking_at = serializers.SerializerMethodField()
    total_stays = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()
    outstanding_balance = serializers.SerializerMethodField()

    class Meta:
        model = Guest
        fields = [
            "id", "user_id", "has_account", "first_name", "last_name", "full_name",
            "email", "phone", "address", "city", "state", "country",
            "identification_type", "identification_type_label", "identification_number",
            "special_requests", "bookings", "bookings_count", "last_booking_at",
            "total_stays", "total_spent", "outstanding_balance",
            "created_at", "updated_at",
        ]

    # --- privacy ---------------------------------------------------------
    def _can_see_sensitive(self):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and user.role in ("ADMIN", "MANAGER"))

    def get_identification_number(self, obj):
        value = obj.identification_number or ""
        if not value:
            return ""
        if self._can_see_sensitive():
            return value
        # Receptionists see enough to recognise the document, not the number.
        return ("*" * max(0, len(value) - 4)) + value[-4:]

    def get_identification_type_label(self, obj):
        return obj.get_identification_type_display() if obj.identification_type else ""

    # --- metadata --------------------------------------------------------
    def get_has_account(self, obj):
        return obj.user_id is not None

    def get_bookings_count(self, obj):
        return getattr(obj, "bookings_count", None) or obj.bookings.count()

    def get_last_booking_at(self, obj):
        value = getattr(obj, "last_booking_at", None)
        if value is None:
            # Only the list endpoint annotates this; the detail view fetches it
            # from the already-prefetched rows (no extra query).
            value = obj.bookings.order_by("-created_at").values_list("created_at", flat=True).first()
        return value.isoformat() if value else None

    def get_total_stays(self, obj):
        return obj.bookings.count()

    def get_total_spent(self, obj):
        from django.db.models import Sum

        return money(
            obj.bookings.exclude(status="CANCELLED").aggregate(total=Sum("amount_paid"))["total"] or 0
        )

    def get_outstanding_balance(self, obj):
        from django.db.models import F, Sum

        balance = (
            obj.bookings.filter(status__in=("CONFIRMED", "CHECKED_IN"))
            .annotate(due=F("total_amount") - F("amount_paid"))
            .aggregate(total=Sum("due"))["total"]
        )
        return money(balance or 0)

    # --- history ---------------------------------------------------------
    def get_bookings(self, obj):
        # The detail view prefetches bookings + their rooms; slicing a *list* of
        # the already-fetched rows keeps this to zero extra queries (and avoids
        # a "already seen with a different queryset" prefetch clash).
        qs = obj.bookings.all()[:15]
        return [
            {
                "id": b.pk,
                "booking_reference": b.booking_reference,
                "room_type_name": b.room_type.name,
                "room_numbers": [a.room.room_number for a in b.room_assignments.all()],
                "check_in": b.check_in.isoformat(),
                "check_out": b.check_out.isoformat(),
                "nights": b.nights,
                "status": b.status,
                "payment_status": b.payment_status,
                "total_amount": money(b.total_amount),
                "amount_paid": money(b.amount_paid),
                "amount_due": money(b.amount_due),
                "currency": b.currency,
                "source": b.source,
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
