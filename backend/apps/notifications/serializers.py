from rest_framework import serializers

from .models import Notification


class UnreadCountSerializer(serializers.Serializer):
    unread_count = serializers.IntegerField(read_only=True)


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "type", "title", "message", "link", "is_read", "created_at"]
        read_only_fields = fields
