"""Administrator-only user & staff account management (ADMIN role)."""
import logging

from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema
from rest_framework import filters, generics, status
from rest_framework.response import Response

from apps.audit.services import log_action
from apps.core.permissions import IsAdminRole
from apps.core.responses import success_response

from .models import User
from .serializers import (
    AdminUserCreateSerializer,
    AdminUserListSerializer,
    AdminUserUpdateSerializer,
    UserSerializer,
)

logger = logging.getLogger("apps")


class AdminUserQuerysetMixin:
    permission_classes = [IsAdminRole]

    def get_queryset(self):
        qs = User.objects.all().annotate(bookings_count=Count("guest_profile__bookings", distinct=True))
        params = self.request.query_params
        role = params.get("role")
        if role:
            qs = qs.filter(role=role.upper())
        is_active = params.get("is_active")
        if is_active is not None and is_active != "":
            qs = qs.filter(is_active=is_active.lower() in ("1", "true", "yes"))
        search = params.get("search")
        if search:
            qs = qs.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(phone__icontains=search)
            )
        ordering = params.get("ordering", "-date_joined")
        allowed = {"date_joined", "-date_joined", "email", "-email", "role", "-role", "last_login", "-last_login"}
        if ordering in allowed:
            qs = qs.order_by(ordering)
        return qs


@extend_schema(tags=["Admin · Users"])
class AdminUserListCreateView(AdminUserQuerysetMixin, generics.ListCreateAPIView):
    def get_serializer_class(self):
        return AdminUserCreateSerializer if self.request.method == "POST" else AdminUserListSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        log_action(
            actor=request.user,
            action="USER_CREATED",
            instance=user,
            metadata={"role": user.role, "email": user.email},
            request=request,
        )
        logger.info("Admin %s created user %s (%s)", request.user.id, user.id, user.role)
        return success_response(
            AdminUserListSerializer(user).data, message="User created.", status=status.HTTP_201_CREATED
        )


@extend_schema(tags=["Admin · Users"])
class AdminUserDetailView(AdminUserQuerysetMixin, generics.RetrieveUpdateAPIView):
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        return AdminUserUpdateSerializer if self.request.method == "PATCH" else AdminUserListSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        data = AdminUserListSerializer(instance, context={"request": request}).data
        data["profile"] = UserSerializer(instance, context={"request": request}).data
        return success_response(data)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        before = {"role": instance.role, "is_active": instance.is_active}
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        changes = {}
        for field in before:
            old = before[field]
            new = getattr(instance, field)
            if old != new:
                changes[field] = [old, new]
        log_action(
            actor=request.user,
            action="USER_ROLE_CHANGED" if "role" in changes else "USER_UPDATED",
            instance=instance,
            changes=changes,
            request=request,
        )
        logger.info("Admin %s updated user %s: %s", request.user.id, instance.id, changes)
        return success_response(
            AdminUserListSerializer(instance, context={"request": request}).data, message="User updated."
        )
