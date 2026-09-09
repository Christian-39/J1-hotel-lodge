"""Health check + API index."""
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from apps.core.responses import success_response


@extend_schema(responses={200: dict}, summary="API index", tags=["Meta"])
@api_view(["GET"])
@permission_classes([AllowAny])
def api_index(request):
    return success_response(
        {
            "name": "J-ONE HOTEL & LODGE API",
            "version": "1.0.0",
            "documentation": "/api/docs/",
            "health": "/api/health/",
        }
    )


@extend_schema(responses={200: dict}, summary="Lightweight health check", tags=["Meta"])
@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    from rest_framework import status as drf_status

    from rest_framework.response import Response

    db_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        db_ok = False
    # "success" key present so the envelope renderer passes it through; keeps
    # the top-level "status": "ok" shape load-balancer probes expect.
    payload = {
        "success": db_ok,
        "status": "ok" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
    }
    return Response(payload, status=drf_status.HTTP_200_OK if db_ok else drf_status.HTTP_503_SERVICE_UNAVAILABLE)
