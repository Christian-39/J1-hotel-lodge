from rest_framework import serializers

from .models import Enquiry
import re

_TAG_RE = re.compile(r"<[^>]*>")


def _plain(value: str) -> str:
    """Strip any HTML — enquiry content is plain text only (XSS defence)."""
    return _TAG_RE.sub("", value or "").strip()


class EnquiryCreateSerializer(serializers.ModelSerializer):
    """Public contact form.

    `website` is an ANTI-SPAM HONEYPOT, not an Enquiry column. It is declared
    here so the API accepts (and drf-spectacular documents) the field, but it
    MUST be dropped before the row is written — `write_only` only hides a field
    on output, it does not keep it out of `validated_data`, so leaving it in
    made `Enquiry.objects.create()` raise
    ``TypeError: Enquiry() got unexpected keyword arguments: 'website'``
    which surfaced to the browser as an opaque HTTP 500 and meant NO enquiry
    was ever persisted.
    """

    website = serializers.CharField(required=False, allow_blank=True, write_only=True, default="")

    class Meta:
        model = Enquiry
        fields = ["name", "email", "phone", "subject", "message", "website"]

    def create(self, validated_data):
        validated_data.pop("website", None)
        return super().create(validated_data)

    def is_honeypot_filled(self):
        """True when a bot filled the hidden field.

        Read from `initial_data` as well as `validated_data` so the check is
        correct even if the field is ever removed from `Meta.fields`.
        """
        raw = ""
        initial = getattr(self, "initial_data", None)
        if isinstance(initial, dict):
            raw = initial.get("website") or ""
        if not raw:
            raw = (self.validated_data or {}).get("website") or ""
        return bool(str(raw).strip())

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
