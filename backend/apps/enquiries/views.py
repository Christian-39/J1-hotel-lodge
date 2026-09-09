import logging

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.permissions import IsStaffRole
from apps.core.responses import success_response
from apps.notifications.services import notify_staff

from .models import Enquiry
from .serializers import EnquiryAdminSerializer, EnquiryCreateSerializer

logger = logging.getLogger("apps")


@extend_schema(tags=["Enquiries"], summary="Submit a contact/enquiry message")
class EnquiryCreateView(APIView):
    permission_classes = [AllowAny]
    serializer_class = EnquiryCreateSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "enquiry"

    def post(self, request):
        serializer = EnquiryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.is_honeypot_filled():
            # Silently "accept" spam: no row, no signal to the bot.
            logger.info("Honeypot enquiry dropped from %s", request.META.get("REMOTE_ADDR"))
        else:
            enquiry = serializer.save(ip_address=request.META.get("REMOTE_ADDR"))
            notify_staff(
                type="ENQUIRY_NEW",
                title=f"New enquiry: {enquiry.subject}",
                message=f"{enquiry.name} ({enquiry.email}): {enquiry.message[:140]}",
                link="/dashboard/enquiries.html",
            )
            logger.info("New enquiry #%s from %s", enquiry.pk, enquiry.email)
        return success_response(
            message="Thank you for your message. The hotel team will respond shortly.",
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Admin · Enquiries"])
class EnquiryAdminListView(generics.ListAPIView):
    permission_classes = [IsStaffRole]
    serializer_class = EnquiryAdminSerializer

    def get_queryset(self):
        qs = Enquiry.objects.all().order_by("-created_at")
        params = self.request.query_params
        if status_param := params.get("status"):
            qs = qs.filter(status=status_param.upper())
        if search := params.get("search"):
            from django.db.models import Q

            qs = qs.filter(
                Q(name__icontains=search) | Q(email__icontains=search) | Q(subject__icontains=search)
            )
        return qs


@extend_schema(tags=["Admin · Enquiries"])
class EnquiryAdminDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsStaffRole]
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        return EnquiryAdminSerializer

    def get_queryset(self):
        return Enquiry.objects.all()

    def retrieve(self, request, *args, **kwargs):
        return success_response(self.get_serializer(self.get_object()).data)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        before = {"status": instance.status}
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        if before["status"] != instance.status:
            from apps.audit.services import log_action

            log_action(actor=request.user, action="ENQUIRY_STATUS_CHANGED", instance=instance,
                       changes={"status": [before["status"], instance.status]}, request=request)
        return success_response(self.get_serializer(instance).data, message="Enquiry updated.")
