"""Authentication endpoints (public/guest area of the API)."""
import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.core.emails import send_email_safe
from apps.core.responses import success_response

from .models import User
from .serializers import (
    JOneTokenObtainPairSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    LogoutSerializer,
    UserSerializer,
)
from rest_framework_simplejwt.views import TokenObtainPairView

logger = logging.getLogger("apps")


def _tokens_for(user):
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


@extend_schema(tags=["Auth"], summary="Guest registration disabled; guest checkout is account-free")
class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        return Response({
            "success": False,
            "code": "GUEST_ACCOUNT_NOT_REQUIRED",
            "message": "Hotel guests do not need an account. Please use guest checkout.",
        }, status=status.HTTP_410_GONE)


@extend_schema(tags=["Auth"], summary="Log in with email and password")
class LoginView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
    # Explicit serializer: simplejwt's TOKEN_OBTAIN_SERIALIZER setting is only
    # honored by its own view implementation path; our view opts in explicitly.
    serializer_class = JOneTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        payload = {"user": response.data.get("user"), "tokens": {
            "access": response.data.get("access"), "refresh": response.data.get("refresh")}}
        return success_response(payload, message="Logged in successfully.")


@extend_schema(tags=["Auth"], summary="Exchange a refresh token for new tokens")
class JOneTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        tokens = {"access": response.data.get("access")}
        if response.data.get("refresh"):
            tokens["refresh"] = response.data["refresh"]
        return success_response({"tokens": tokens}, message="Token refreshed.")


@extend_schema(tags=["Auth"], request=None, summary="Log out (blacklist refresh token)")
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"refresh": ["Refresh token is required."]})
        try:
            RefreshToken(refresh).blacklist()
        except Exception:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"refresh": ["Invalid or already-used refresh token."]})
        logger.info("User logged out: user_id=%s", request.user.id)
        return success_response(message="Logged out successfully.")


@extend_schema(tags=["Auth"], summary="Get or update the current profile")
class ProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        # Role/is_active/flags are read-only here; only profile fields are PATCHable.
        return ProfileUpdateSerializer if self.request.method in ("PUT", "PATCH") else UserSerializer

    def retrieve(self, request, *args, **kwargs):
        return success_response(self.get_serializer(self.get_object()).data)

    def update(self, request, *args, **kwargs):
        partial = request.method == "PATCH"
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            UserSerializer(self.get_object(), context={"request": request}).data,
            message="Profile updated.",
        )


@extend_schema(tags=["Auth"], summary="Change password (authenticated)")
class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PasswordChangeSerializer

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info("Password changed: user_id=%s", request.user.id)
        return success_response(message="Password changed successfully.")


@extend_schema(tags=["Auth"], summary="Request a password reset email")
class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    serializer_class = PasswordResetRequestSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        # Response is identical whether or not the account exists — do not
        # leak account existence to the internet.
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = f"{settings.FRONTEND_URL}/reset-password.html?uid={uid}&token={token}"
            send_email_safe(
                subject="Reset your J-ONE HOTEL & LODGE password",
                message=(
                    f"Hello {user.first_name},\n\n"
                    f"We received a request to reset your password. Open this link to continue:\n{reset_url}\n\n"
                    "If you did not request this, you can safely ignore this email.\n\n"
                    "— J-ONE HOTEL & LODGE"
                ),
                recipients=[user.email],
            )
        return success_response(message="If an account exists for this email, a reset link has been sent.")


@extend_schema(tags=["Auth"], summary="Confirm a password reset")
class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    serializer_class = PasswordResetConfirmSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        logger.info("Password reset completed: user_id=%s", user.id)
        return success_response(message="Password has been reset successfully. You can now log in.")
