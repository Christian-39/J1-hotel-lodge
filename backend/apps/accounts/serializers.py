"""Account serializers. Never expose password hashes or role-equality tricks."""
from django.contrib.auth import password_validation
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.core.storage import absolute_media_url

from .models import User


class UserSerializer(serializers.ModelSerializer):
    """Safe public representation of the authenticated user."""

    full_name = serializers.CharField(read_only=True)
    profile_image_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "full_name", "phone",
            "role", "email_verified", "profile_image_url", "date_joined", "last_login",
        ]
        read_only_fields = fields  # role changes only happen via admin endpoints

    def get_profile_image_url(self, obj):
        return absolute_media_url(obj.profile_image, self.context.get("request"))


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "profile_image"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "phone", "password", "password_confirm"]

    def validate_email(self, value):
        email = User.objects.normalize_email(value)
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return email

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": ["Passwords do not match."]})
        password_validation.validate_password(attrs["password"])
        return attrs

    def create(self, validated_data):
        # Public registration always produces a GUEST. Staff roles are only
        # ever granted by an administrator through the admin endpoints.
        return User.objects.create_user(role=User.Role.GUEST, **validated_data)


class JOneTokenObtainPairSerializer(TokenObtainPairSerializer):
    default_error_messages = {"no_active_account": "Invalid email or password."}

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role  # display convenience; never authorization input
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user, context=self.context).data
        return data


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)
    new_password_confirm = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": ["Passwords do not match."]})
        password_validation.validate_password(attrs["new_password"], user=self.context["request"].user)
        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return User.objects.normalize_email(value)


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)
    new_password_confirm = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": ["Passwords do not match."]})
        try:
            uid = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"uid": ["Invalid password reset link."]})
        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": ["This reset link is invalid or has expired."]})
        password_validation.validate_password(attrs["new_password"], user=user)
        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        return user


# ---------------------------------------------------------------------------
# Admin user management
# ---------------------------------------------------------------------------
class AdminUserListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    profile_image_url = serializers.SerializerMethodField()
    bookings_count = serializers.SerializerMethodField()

    def get_profile_image_url(self, obj):
        return absolute_media_url(obj.profile_image, self.context.get("request"))

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "full_name", "phone", "role",
            "profile_image_url", "is_active", "email_verified", "bookings_count", "date_joined", "last_login",
        ]

    def get_bookings_count(self, obj):
        return getattr(obj, "bookings_count", None)


class AdminUserCreateSerializer(serializers.ModelSerializer):
    """Administrator-created staff accounts (roles above GUEST)."""

    password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "phone", "role", "password", "is_active", "profile_image"]

    def validate_email(self, value):
        email = User.objects.normalize_email(value)
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return email

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value

    def create(self, validated_data):
        # is_staff grants Django-admin access for privileged roles only.
        role = validated_data.get("role", User.Role.GUEST)
        validated_data["is_staff"] = role in (User.Role.ADMIN,)
        return User.objects.create_user(**validated_data)


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "role", "is_active", "email_verified", "profile_image"]

    def validate(self, attrs):
        request = self.context["request"]
        target = self.instance
        # An admin cannot lock themselves out or strip their own admin role.
        if target and target.id == request.user.id:
            if attrs.get("is_active") is False:
                raise serializers.ValidationError({"is_active": ["You cannot deactivate your own account."]})
            if "role" in attrs and attrs["role"] != User.Role.ADMIN:
                raise serializers.ValidationError({"role": ["You cannot remove your own admin role."]})
        if target and target.is_superuser and request.user != target and not request.user.is_superuser:
            raise serializers.ValidationError("Only a superuser can modify another superuser account.")
        return attrs
