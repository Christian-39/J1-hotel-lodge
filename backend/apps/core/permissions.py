"""Role-based permission classes.

Roles live on the User model and are ALWAYS evaluated server-side; a role
claim from the frontend is never trusted.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

STAFF_ROLES = ("ADMIN", "MANAGER", "RECEPTIONIST")
MANAGER_ROLES = ("ADMIN", "MANAGER")


def _active(user):
    return bool(user and user.is_authenticated and user.is_active)


class IsStaffRole(BasePermission):
    """Any authenticated staff member (admin, manager, receptionist)."""

    message = "Staff access is required."

    def has_permission(self, request, view):
        return _active(request.user) and request.user.role in STAFF_ROLES


class IsManagerOrAdmin(BasePermission):
    """Operational managers and administrators."""

    message = "Manager or administrator access is required."

    def has_permission(self, request, view):
        return _active(request.user) and request.user.role in MANAGER_ROLES


class IsAdminRole(BasePermission):
    """Administrators only (user management, settings, audit logs)."""

    message = "Administrator access is required."

    def has_permission(self, request, view):
        return _active(request.user) and request.user.role == "ADMIN"


class IsStaffReadOnlyManagerWrite(BasePermission):
    """All staff may read; only managers/admins may modify."""

    def has_permission(self, request, view):
        if not (_active(request.user) and request.user.role in STAFF_ROLES):
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.role in MANAGER_ROLES


class IsOwnerOrStaff(BasePermission):
    """Object-level access: a guest may only touch their own records.

    Works with objects that expose ``guest.user`` (Booking, Payment) or a
    direct ``user`` attribute. Protects against IDOR (e.g. /api/bookings/2/).
    """

    message = "You do not have permission to access this resource."

    def has_permission(self, request, view):
        return _active(request.user)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.role in STAFF_ROLES:
            return True
        guest = getattr(obj, "guest", None)
        if guest is not None:
            return guest.user_id == user.id
        obj_user = getattr(obj, "user", None)
        if obj_user is not None:
            return obj_user.id == user.id
        return False
