from rest_framework import serializers

from .models import Amenity, Room, RoomType, RoomTypeImage, RoomImage


def _absolute(serializer, image_field):
    if not image_field:
        return None
    request = serializer.context.get("request")
    url = image_field.url
    return request.build_absolute_uri(url) if request else url


class AmenitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Amenity
        fields = ["id", "name", "slug", "icon", "is_active"]


class RoomTypeImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = RoomTypeImage
        fields = ["id", "image", "image_url", "alt_text", "caption", "display_order", "is_primary", "is_active"]
        read_only_fields = ["id", "image_url"]

    def get_image_url(self, obj):
        return _absolute(self, obj.image)


class RoomImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    class Meta:
        model = RoomImage
        fields = ["id", "image", "image_url", "alt_text", "caption", "display_order", "is_primary", "is_active"]
        read_only_fields = ["id", "image_url"]
    def get_image_url(self, obj):
        return _absolute(self, obj.image)


class RoomTypeListSerializer(serializers.ModelSerializer):
    """Lightweight representation for catalog/availability lists."""

    primary_image_url = serializers.SerializerMethodField()
    amenities = serializers.SerializerMethodField()

    class Meta:
        model = RoomType
        fields = [
            "id", "name", "slug", "short_description", "base_price", "max_guests",
            "bed_type", "bed_count", "room_size", "view", "is_featured",
            "primary_image_url", "amenities",
        ]

    def get_primary_image_url(self, obj):
        images = getattr(obj, "_prefetched_images", None)
        primary = None
        if images is not None:
            primary = next((img for img in images if img.is_primary), images[0] if images else None)
        else:
            primary = obj.images.filter(is_active=True).order_by("-is_primary", "display_order").first()
        return _absolute(self, primary.image if primary else None)

    def get_amenities(self, obj):
        return [{"name": a.name, "icon": a.icon} for a in obj.amenities.filter(is_active=True)]


class RoomTypeDetailSerializer(RoomTypeListSerializer):
    """Full representation for the room detail page."""

    images = serializers.SerializerMethodField()
    amenities = serializers.SerializerMethodField()

    class Meta(RoomTypeListSerializer.Meta):
        fields = RoomTypeListSerializer.Meta.fields + [
            "description", "smoking_policy", "children_allowed",
            "extra_guest_allowed", "extra_guest_fee", "images",
        ]

    def get_images(self, obj):
        images = obj.images.filter(is_active=True).order_by("display_order", "id")
        return RoomTypeImageSerializer(images, many=True, context=self.context).data

    def get_amenities(self, obj):
        return AmenitySerializer(obj.amenities.filter(is_active=True), many=True).data


# ---------------------------------------------------------------------------
# Staff serializers
# ---------------------------------------------------------------------------
class RoomTypeAdminSerializer(serializers.ModelSerializer):
    amenity_ids = serializers.PrimaryKeyRelatedField(
        queryset=Amenity.objects.filter(is_active=True), many=True, required=False, source="amenities"
    )
    images = RoomTypeImageSerializer(many=True, read_only=True)
    room_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = RoomType
        fields = [
            "id", "name", "slug", "description", "short_description", "base_price",
            "max_guests", "bed_type", "bed_count", "room_size", "view", "smoking_policy",
            "children_allowed", "extra_guest_allowed", "extra_guest_fee", "amenity_ids",
            "is_featured", "is_active", "display_order", "images", "room_count",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]


class RoomSerializer(serializers.ModelSerializer):
    room_type_name = serializers.CharField(source="room_type.name", read_only=True)
    room_type_slug = serializers.CharField(source="room_type.slug", read_only=True)
    images = serializers.SerializerMethodField()
    effective_status = serializers.SerializerMethodField()

    def get_images(self, obj):
        # Prefer the prefetched active-images cache set by the admin viewset;
        # fall back to a filtered query for other callers.
        cached = getattr(obj, "_active_images", None)
        qs = cached if cached is not None else obj.images.filter(is_active=True)
        return RoomImageSerializer(qs, many=True, context=self.context).data

    def get_effective_status(self, obj) -> str:
        """Reservation-aware status for tonight (spec §12).

        Operational blocks (maintenance / out-of-service) win; otherwise a
        checked-in stay ⇒ OCCUPIED, an active reservation covering tonight ⇒
        RESERVED, else AVAILABLE. Uses the annotations computed by the admin
        viewset from the authoritative availability engine; falls back to the
        raw operational status when annotations are absent.
        """
        if obj.status in (Room.Status.MAINTENANCE, Room.Status.OUT_OF_SERVICE):
            return obj.status
        if not obj.is_active:
            return Room.Status.OUT_OF_SERVICE
        occupied = getattr(obj, "_occupied_tonight", None)
        reserved = getattr(obj, "_reserved_tonight", None)
        if occupied is None and reserved is None:
            return obj.status
        if occupied:
            return Room.Status.OCCUPIED
        if reserved:
            return Room.Status.RESERVED
        return Room.Status.AVAILABLE

    class Meta:
        model = Room
        fields = [
            "id", "room_number", "room_type", "room_type_name", "room_type_slug", "floor",
            "status", "effective_status", "housekeeping_status", "notes", "is_active",
            "images", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
