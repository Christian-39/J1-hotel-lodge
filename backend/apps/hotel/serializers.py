from django.conf import settings as django_settings
from rest_framework import serializers

from apps.core.storage import absolute_media_url, save_upload

from .models import Facility, HotelPolicy, HotelSettings

# Optional admin-uploaded website images (HotelSettings). Each is exposed to
# the public site as ``<name>_url`` (absolute URL, or null when unset so the
# frontend keeps its built-in fallback asset).
SITE_IMAGE_FIELDS = [
    "hero_image",
    "intro_image",
    "experience_image",
    "location_image",
    "policy_image",
    "contact_image",
]


class HotelPublicSerializer(serializers.ModelSerializer):
    """Everything the public website needs to render hotel information."""

    # The hotel operates in the server's configured timezone (Africa/Lagos).
    # The frontend uses this to compute "today"/date constraints correctly
    # for visitors in other timezones — it must come from the backend, not
    # from the browser clock.
    timezone = serializers.SerializerMethodField()

    hero_image_url = serializers.SerializerMethodField()
    intro_image_url = serializers.SerializerMethodField()
    experience_image_url = serializers.SerializerMethodField()
    location_image_url = serializers.SerializerMethodField()
    policy_image_url = serializers.SerializerMethodField()
    contact_image_url = serializers.SerializerMethodField()

    class Meta:
        model = HotelSettings
        fields = [
            "hotel_name", "tagline", "description", "address", "city", "state",
            "country", "phone", "email", "google_maps_url", "google_review_url",
            "social_links", "check_in_time", "check_out_time", "currency",
            "min_stay_nights", "max_stay_nights", "timezone",
            "hero_image_url", "intro_image_url", "experience_image_url",
            "location_image_url", "policy_image_url", "contact_image_url",
        ]
        read_only_fields = fields

    def get_timezone(self, obj):
        return django_settings.TIME_ZONE

    def _image_url(self, obj, field):
        return absolute_media_url(getattr(obj, field, None), self.context.get("request"))

    def get_hero_image_url(self, obj):
        return self._image_url(obj, "hero_image")

    def get_intro_image_url(self, obj):
        return self._image_url(obj, "intro_image")

    def get_experience_image_url(self, obj):
        return self._image_url(obj, "experience_image")

    def get_location_image_url(self, obj):
        return self._image_url(obj, "location_image")

    def get_policy_image_url(self, obj):
        return self._image_url(obj, "policy_image")

    def get_contact_image_url(self, obj):
        return self._image_url(obj, "contact_image")


class HotelPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = HotelPolicy
        fields = ["id", "key", "title", "content", "is_active", "display_order", "updated_at"]
        read_only_fields = ["id", "updated_at"]


class FacilitySerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Facility
        fields = ["id", "name", "slug", "description", "icon", "image_url", "is_active", "display_order"]
        read_only_fields = ["id"]

    def get_image_url(self, obj):
        return absolute_media_url(obj.image, self.context.get("request"))


class HotelSettingsAdminSerializer(serializers.ModelSerializer):
    """Full settings payload for staff; only ADMIN may write.

    Website images are written via multipart PATCH (file upload) and cleared
    via a JSON PATCH with ``null``. The ``*_image_url`` companions are read-only
    absolute URLs for admin previews.
    """

    hero_image_url = serializers.SerializerMethodField()
    intro_image_url = serializers.SerializerMethodField()
    experience_image_url = serializers.SerializerMethodField()
    location_image_url = serializers.SerializerMethodField()
    policy_image_url = serializers.SerializerMethodField()
    contact_image_url = serializers.SerializerMethodField()

    class Meta:
        model = HotelSettings
        fields = [
            "hotel_name", "tagline", "description", "address", "city", "state",
            "country", "phone", "email", "google_maps_url", "google_review_url",
            "social_links",
            "check_in_time", "check_out_time", "min_stay_nights", "max_stay_nights",
            "currency", "tax_rate_percent", "service_fee", "deposit_percent",
            "pending_booking_minutes", "cancellation_deadline_hours",
            "cancellation_fee_percent",
            "policy_text",
            "hero_image", "intro_image", "experience_image", "location_image",
            "policy_image", "contact_image",
            "hero_image_url", "intro_image_url", "experience_image_url",
            "location_image_url", "policy_image_url", "contact_image_url",
            "updated_at",
        ]
        read_only_fields = [
            "hero_image_url", "intro_image_url", "experience_image_url",
            "location_image_url", "policy_image_url", "contact_image_url",
            "updated_at",
        ]
        extra_kwargs = {
            # Optional everywhere: never required, clearable with null.
            "hero_image": {"required": False, "allow_null": True},
            "intro_image": {"required": False, "allow_null": True},
            "experience_image": {"required": False, "allow_null": True},
            "location_image": {"required": False, "allow_null": True},
            "policy_image": {"required": False, "allow_null": True},
            "contact_image": {"required": False, "allow_null": True},
        }

    def _image_url(self, obj, field):
        return absolute_media_url(getattr(obj, field, None), self.context.get("request"))

    def get_hero_image_url(self, obj):
        return self._image_url(obj, "hero_image")

    def get_intro_image_url(self, obj):
        return self._image_url(obj, "intro_image")

    def get_experience_image_url(self, obj):
        return self._image_url(obj, "experience_image")

    def get_location_image_url(self, obj):
        return self._image_url(obj, "location_image")

    def get_policy_image_url(self, obj):
        return self._image_url(obj, "policy_image")

    def get_contact_image_url(self, obj):
        return self._image_url(obj, "contact_image")

    def validate_policy_text(self, value):
        # Plain text only — strip any NUL/control characters except \n, \r, \t
        # so the stored content is always safely renderable as text.
        if not value:
            return ""
        return "".join(ch for ch in str(value) if ch in "\n\r\t" or ord(ch) >= 32)

    def validate_social_links(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list of objects.")
        for item in value:
            if not isinstance(item, dict) or "platform" not in item or "url" not in item:
                raise serializers.ValidationError('Each entry needs "platform" and "url".')
        return value

    def create(self, validated_data):
        return save_upload(
            lambda: super(HotelSettingsAdminSerializer, self).create(validated_data),
            context="hotel settings website image",
        )

    def update(self, instance, validated_data):
        return save_upload(
            lambda: super(HotelSettingsAdminSerializer, self).update(instance, validated_data),
            context="hotel settings website image",
        )
