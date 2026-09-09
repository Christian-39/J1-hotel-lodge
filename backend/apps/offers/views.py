from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, viewsets
from rest_framework.permissions import AllowAny

from apps.core.permissions import IsStaffReadOnlyManagerWrite

from .models import Offer
from .serializers import OfferAdminSerializer, OfferPublicSerializer


@extend_schema(tags=["Offers"], summary="Currently running offers")
class OfferPublicListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = OfferPublicSerializer
    pagination_class = None

    def get_queryset(self):
        today = timezone.localdate()
        return (
            Offer.objects.filter(is_active=True, start_date__lte=today, end_date__gte=today)
            .prefetch_related("room_types")
            .order_by("-is_featured", "-start_date", "title")
        )


@extend_schema(tags=["Admin · Offers"])
class OfferAdminViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStaffReadOnlyManagerWrite]
    serializer_class = OfferAdminSerializer

    def get_queryset(self):
        qs = Offer.objects.prefetch_related("room_types").order_by("-is_featured", "-start_date")
        if active := self.request.query_params.get("is_active"):
            qs = qs.filter(is_active=active.lower() in ("1", "true", "yes"))
        return qs

    def perform_create(self, serializer):
        from apps.audit.services import log_action

        instance = serializer.save()
        log_action(actor=self.request.user, action="OFFER_CREATED", instance=instance,
                   request=self.request)

    def perform_update(self, serializer):
        from apps.audit.services import log_action

        before = {
            f: str(getattr(serializer.instance, f))
            for f in ("is_active", "discount_type", "discount_value", "start_date", "end_date")
        }
        instance = serializer.save()
        changes = {
            f: [before[f], str(getattr(instance, f))]
            for f in before
            if before[f] != str(getattr(instance, f))
        }
        log_action(actor=self.request.user, action="OFFER_UPDATED", instance=instance,
                   changes=changes, request=self.request)
