"""Read-only audit log access (ADMIN only). No write/delete endpoints exist."""
from drf_spectacular.utils import extend_schema
from rest_framework import generics

from apps.core.permissions import IsAdminRole

from .models import AuditLog
from .serializers import AuditLogSerializer


@extend_schema(tags=["Admin · Audit"])
class AuditLogListView(generics.ListAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor")
        params = self.request.query_params
        if action := params.get("action"):
            qs = qs.filter(action=action)
        if object_type := params.get("object_type"):
            qs = qs.filter(object_type=object_type)
        if actor := params.get("actor"):
            qs = qs.filter(actor__email__icontains=actor)
        if date_from := params.get("date_from"):
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to := params.get("date_to"):
            qs = qs.filter(created_at__date__lte=date_to)
        return qs.order_by("-created_at")


@extend_schema(tags=["Admin · Audit"])
class AuditLogDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = AuditLogSerializer
    queryset = AuditLog.objects.select_related("actor")
