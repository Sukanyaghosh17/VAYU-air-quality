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

IsAuthenticatedReadOrCreate
---------------------------
  GET / HEAD / OPTIONS / POST are open to any authenticated user.
  PUT / PATCH / DELETE are blocked for *everyone* — SensorReading rows are
  immutable once written (audit-trail requirement; simulators must not be able
  to retroactively alter raw sensor data).
  Used by: SensorReadingViewSet.
"""

from rest_framework.permissions import BasePermission


class IsAdminOrReadOnly(BasePermission):
    """
    Safe methods: any authenticated user.
    Unsafe methods: admin role only (user.is_admin() == True).
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        # SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return bool(request.user.is_admin())


class IsAuthenticatedReadOrCreate(BasePermission):
    """
    Any authenticated user may GET, HEAD, OPTIONS, or POST.
    PUT / PATCH / DELETE are blocked for everyone.

    IMPORTANT — DRF ordering caveat:
      DRF runs check_permissions() BEFORE method dispatch inside initial().
      If this class returns False for PUT, DRF returns 403 before the view
      ever gets to say 405 (method not allowed).  Therefore this class is
      only correct when paired with a ModelViewSet that ALSO restricts
      http_method_names, AND you are deliberately choosing 403 over 405.

      For SensorReadingViewSet we use the mixin approach (no UpdateModelMixin
      → no PUT route) + plain IsAuthenticated, so the router itself returns
      405 before permissions even matter.  That gives the correct semantics:
        - PUT to /readings/<pk>/  →  405 (method not supported on this resource)
        - PUT unauthenticated     →  401 (checked before 405)
    """

    SAFE_OR_CREATE = ("GET", "HEAD", "OPTIONS", "POST")

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated) \
               and request.method in self.SAFE_OR_CREATE
