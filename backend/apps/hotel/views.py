"""Public hotel content endpoints (no authentication required)."""
from django.core.cache import cache
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.responses import success_response

from .models import Facility, HotelPolicy, HotelSettings
from .serializers import FacilitySerializer, HotelPolicySerializer, HotelPublicSerializer

PUBLIC_HOTEL_CACHE_KEY = "hotel:public:payload"
FACILITIES_CACHE_KEY = "hotel:facilities:list"

# Built-in hotel policy used ONLY when an admin has neither saved a custom
# policy text nor published any HotelPolicy documents (brand-new installs).
# Existing installs keep displaying their HotelPolicy documents; installing
# this update can therefore never blank the public policies page.
DEFAULT_POLICY_FALLBACK = [
    {
        "key": "check-in-out",
        "title": "Check-in & Check-out",
        "content": "Check-in from 14:00. Check-out by 12:00.",
        "display_order": 1,
    },
    {
        "key": "cancellation",
        "title": "Cancellation Policy",
        "content": "Free cancellation up to 48 hours before check-in. "
                   "Later cancellations may forfeit the booking deposit.",
        "display_order": 2,
    },
    {
        "key": "identification",
        "title": "Identification",
        "content": "A valid government-issued photo ID is required at check-in "
                   "for all adult guests.",
        "display_order": 3,
    },
    {
        "key": "payment",
        "title": "Payment & Deposit",
        "content": "Online bookings are confirmed upon successful payment. "
                   "Balances may be settled at the front desk by cash, POS or "
                   "bank transfer.",
        "display_order": 4,
    },
    {
        "key": "smoking",
        "title": "Smoking Policy",
        "content": "Smoking is not permitted inside guest rooms.",
        "display_order": 5,
    },
    {
        "key": "pets",
        "title": "Pet Policy",
        "content": "Pets are not allowed on the property.",
        "display_order": 6,
    },
]


@extend_schema(tags=["Hotel"], summary="Public hotel information")
class HotelInfoView(APIView):
    permission_classes = [AllowAny]
    serializer_class = HotelPublicSerializer

    def get(self, request):
        payload = cache.get(PUBLIC_HOTEL_CACHE_KEY)
        if payload is None:
            payload = HotelPublicSerializer(
                HotelSettings.get_settings(), context={"request": request}
            ).data
            cache.set(PUBLIC_HOTEL_CACHE_KEY, payload, 300)
        return success_response(payload)


@extend_schema(tags=["Hotel"], summary="Active hotel policies")
class PolicyListView(generics.ListAPIView):
    """Public policy documents with a safe fallback chain:

    1. an admin-saved custom policy text (HotelSettings.policy_text) wins;
    2. otherwise the existing HotelPolicy documents (current behaviour);
    3. otherwise the built-in default policy (fresh installs).

    The response shape never changes, so the public page needs no special
    handling and can never end up empty.
    """

    permission_classes = [AllowAny]
    serializer_class = HotelPolicySerializer
    pagination_class = None

    def get_queryset(self):
        return HotelPolicy.objects.filter(is_active=True).order_by("display_order", "title")

    def list(self, request, *args, **kwargs):
        hotel = HotelSettings.get_settings()
        custom = (hotel.policy_text or "").strip()
        if custom:
            payload = [{
                "id": None,
                "key": "hotel-policy",
                "title": "Hotel Policy",
                "content": custom,
                "is_active": True,
                "display_order": 0,
                "updated_at": hotel.updated_at,
            }]
            return Response(self.get_serializer(payload, many=True).data)

        queryset = self.filter_queryset(self.get_queryset())
        if not queryset.exists():
            now = timezone.now()
            payload = [
                {
                    "id": None,
                    "key": item["key"],
                    "title": item["title"],
                    "content": item["content"],
                    "is_active": True,
                    "display_order": item["display_order"],
                    "updated_at": now,
                }
                for item in DEFAULT_POLICY_FALLBACK
            ]
            return Response(self.get_serializer(payload, many=True).data)
        return Response(self.get_serializer(queryset, many=True).data)


@extend_schema(tags=["Hotel"], summary="Active hotel facilities")
class FacilityListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = FacilitySerializer
    pagination_class = None

    def get_queryset(self):
        return Facility.objects.filter(is_active=True).order_by("display_order", "name")
