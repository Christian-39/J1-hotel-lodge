from rest_framework import serializers

from apps.core.storage import absolute_media_url
from apps.rooms.models import RoomType

from .models import Offer


def _abs(serializer, image_field):
    return absolute_media_url(image_field, serializer.context.get("request"))


class OfferPublicSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    applicable_room_types = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = [
            "id", "title", "slug", "short_description", "description",
            "discount_type", "discount_value", "start_date", "end_date",
            "min_nights", "max_nights", "applicable_room_types", "is_featured",
            "image_url", "terms",
        ]

    def get_image_url(self, obj):
        return _abs(self, obj.image)

    def get_applicable_room_types(self, obj):
        types = obj.room_types.filter(is_active=True)
        if not types.exists():
            return []
        return [{"id": t.pk, "name": t.name, "slug": t.slug} for t in types]


class OfferAdminSerializer(serializers.ModelSerializer):
    room_type_ids = serializers.PrimaryKeyRelatedField(
        queryset=RoomType.objects.all(), many=True, required=False, source="room_types"
    )
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = [
            "id", "title", "slug", "description", "short_description", "code",
            "discount_type", "discount_value", "start_date", "end_date",
            "min_nights", "max_nights", "room_type_ids", "is_active", "is_featured",
            "image", "image_url", "terms", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]
        extra_kwargs = {"image": {"required": False, "write_only": True}}

    def get_image_url(self, obj):
        return _abs(self, obj.image)

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": ["End date cannot be before the start date."]})
        discount_type = attrs.get("discount_type", getattr(self.instance, "discount_type", None))
        value = attrs.get("discount_value", getattr(self.instance, "discount_value", None))
        if discount_type == Offer.DiscountType.PERCENTAGE and value is not None and value > 100:
            raise serializers.ValidationError({"discount_value": ["Percentage discounts cannot exceed 100."]})
        min_n = attrs.get("min_nights", getattr(self.instance, "min_nights", 1))
        max_n = attrs.get("max_nights", getattr(self.instance, "max_nights", None))
        if max_n is not None and min_n and max_n < min_n:
            raise serializers.ValidationError({"max_nights": ["Maximum nights must be >= minimum nights."]})
        return attrs
