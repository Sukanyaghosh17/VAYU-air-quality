"""
sensors/permissions.py — Shared DRF permission classes
=======================================================
Both classes subclass BasePermission so DRF's permission machinery (has_permission,
has_object_permission, allow_request) works correctly.

IsAdminOrReadOnly
-----------------
  Safe HTTP methods (GET, HEAD, OPTIONS) are open to any authenticated user.
  Unsafe methods (POST, PUT, PATCH, DELETE) require user.is_admin() == True.
  Used by: SensorViewSet, ThresholdViewSet, AlertViewSet.partial_update.

AllowAnyReadRequireAuthCreate
-----------------------------
  GET / HEAD / OPTIONS are open to everyone (including anonymous dashboard visitors).
  POST requires user.is_authenticated (simulator telemetry ingest).
  PUT / PATCH / DELETE are blocked for everyone — raw readings are immutable.
  Used by: SensorReadingViewSet.
"""

from rest_framework.permissions import BasePermission


class CanCreateSensor(BasePermission):
    """
    Allows sensor creation (POST) to admin users and authorized service accounts.
    Safe methods (GET, HEAD, OPTIONS) are open to everyone.
    Applied specifically to SensorViewSet's create action so service accounts
    cannot perform other administrative mutations (PUT/PATCH/DELETE) or access
    admin-only alert/threshold endpoints.
    """

    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return bool(
            getattr(user, "can_provision_sensors", False)
            or (callable(getattr(user, "is_admin", None)) and user.is_admin())
            or (callable(getattr(user, "is_service", None)) and user.is_service())
            or getattr(user, "role", "") in ("admin", "service")
        )


class IsAdminOrReadOnly(BasePermission):
    """
    Safe methods (GET, HEAD, OPTIONS): open to everyone.
    Unsafe methods: admin role only (user.is_admin() == True).
    """

    def has_permission(self, request, view):
        # SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_admin())


class AllowAnyReadRequireAuthCreate(BasePermission):
    """
    Public reads, authenticated writes (sensor readings ingest).

    - GET / HEAD / OPTIONS are open to everyone, including anonymous visitors
      (ensures the public dashboard and anonymous map/chart views can read live telemetry).
    - POST requires authentication (request.user.is_authenticated), ensuring only
      authorized simulators or service accounts with a valid Token can ingest readings.
    - PUT / PATCH / DELETE return False for all users (readings are immutable raw data;
      mutations are blocked).
    """

    SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

    def has_permission(self, request, view):
        if request.method in self.SAFE_METHODS:
            return True
        if request.method == "POST":
            return bool(request.user and request.user.is_authenticated)
        return False


