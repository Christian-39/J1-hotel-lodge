from rest_framework import serializers

from .models import GalleryItem


class GalleryItemSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = GalleryItem
        fields = [
            "id", "title", "description", "category", "alt_text",
            "image_url", "display_order", "is_active", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get("request")
            url = obj.image.url
            return request.build_absolute_uri(url) if request else url
        return None


class GalleryItemAdminSerializer(GalleryItemSerializer):
    class Meta(GalleryItemSerializer.Meta):
        fields = GalleryItemSerializer.Meta.fields + ["image"]
        extra_kwargs = {"image": {"write_only": True, "required": False}}
