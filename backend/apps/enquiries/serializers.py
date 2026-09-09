from rest_framework import serializers

from .models import Enquiry
import re

_TAG_RE = re.compile(r"<[^>]*>")


def _plain(value: str) -> str:
    """Strip any HTML — enquiry content is plain text only (XSS defence)."""
    return _TAG_RE.sub("", value or "").strip()


class EnquiryCreateSerializer(serializers.ModelSerializer):
    # Honeypot: real users leave this blank; bots tend to fill every field.
    website = serializers.CharField(required=False, allow_blank=True, write_only=True, default="")

    class Meta:
        model = Enquiry
        fields = ["name", "email", "phone", "subject", "message", "website"]

    def validate_name(self, value):
        value = _plain(value)
        if not value:
            raise serializers.ValidationError("Name is required.")
        return value[:120]

    def validate_subject(self, value):
        value = _plain(value)
        if not value:
            raise serializers.ValidationError("Subject is required.")
        return value[:150]

    def validate_message(self, value):
        value = _plain(value)
        if len(value) < 5:
            raise serializers.ValidationError("Please enter a more detailed message.")
        return value[:5000]

    def is_honeypot_filled(self):
        return bool((self.validated_data.get("website") or "").strip())


class EnquiryAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Enquiry
        fields = [
            "id", "name", "email", "phone", "subject", "message", "status",
            "internal_notes", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "name", "email", "phone", "subject", "message",
                            "created_at", "updated_at"]

    def validate_status(self, value):
        if value not in Enquiry.Status.values:
            raise serializers.ValidationError("Unknown status.")
        return value
