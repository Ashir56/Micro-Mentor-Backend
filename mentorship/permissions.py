from rest_framework.permissions import BasePermission

from .models import MentorApplication, UserProfile


class IsProvider(BasePermission):
    """Allows access to mentor/provider users (role=mentor or has a MentorProfile)."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if hasattr(user, "mentorprofile"):
            return True
        profile = getattr(user, "profile", None)
        return bool(profile and profile.role == UserProfile.Role.MENTOR)


class IsMentorUser(BasePermission):
    """Allows access only to users with role=mentor."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        profile = getattr(user, "profile", None)
        return bool(profile and profile.role == UserProfile.Role.MENTOR)


class IsReviewer(BasePermission):
    """Allows access only to staff/reviewer users."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_staff)


class IsMenteeUser(BasePermission):
    """Allows access only to users with role=mentee."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        profile = getattr(user, "profile", None)
        return bool(profile and profile.role == UserProfile.Role.MENTEE)


class OwnsMentorApplication(BasePermission):
    """Object-level permission: grants access only to the owner of a MentorApplication.

    The view must pass the application instance to check_object_permissions().
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, MentorApplication):
            return obj.user_id == request.user.id
        # If the obj is a child (document, package, window), check via application.
        application = getattr(obj, "application", None)
        if application is not None:
            return application.user_id == request.user.id
        return False


class CanEditApplication(BasePermission):
    """Grants write access only when the application is in an editable state.

    Must be used together with OwnsMentorApplication.
    The view must call check_object_permissions(request, application).
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        application = obj if isinstance(obj, MentorApplication) else getattr(obj, "application", None)
        if application is None:
            return False
        return application.can_edit()
