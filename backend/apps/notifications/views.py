from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.responses import success_response

from .models import Notification
from .serializers import NotificationSerializer, UnreadCountSerializer
from .services import unread_count


@extend_schema(tags=["Notifications"], summary="List my notifications (paginated)")
class NotificationListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user)
        if self.request.query_params.get("unread") in ("1", "true"):
            qs = qs.filter(is_read=False)
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response = self.get_paginated_response(serializer.data)
        response.data["data"] = {"unread_count": unread_count(request.user), "notifications": response.data["data"]}
        return response


@extend_schema(tags=["Notifications"], summary="Unread notification count")
class UnreadCountView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UnreadCountSerializer

    def get(self, request):
        return success_response({"unread_count": unread_count(request.user)})


@extend_schema(tags=["Notifications"], summary="Mark one notification as read")
class MarkReadView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UnreadCountSerializer

    def post(self, request, pk):
        updated = Notification.objects.filter(recipient=request.user, pk=pk, is_read=False).update(is_read=True)
        if not updated and not Notification.objects.filter(recipient=request.user, pk=pk).exists():
            from rest_framework.exceptions import NotFound

            raise NotFound()
        return success_response({"unread_count": unread_count(request.user)}, message="Notification marked as read.")


@extend_schema(tags=["Notifications"], summary="Mark all notifications as read")
class MarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UnreadCountSerializer

    def post(self, request):
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return success_response({"unread_count": 0}, message="All notifications marked as read.")
