"""
alerts/views.py — AlertViewSet and ThresholdViewSet
====================================================
AlertViewSet permission split:
  list / retrieve  → any authenticated user (IsAuthenticated default)
  partial_update   → admin only (get_permissions override)
  create / destroy → not routed (alerts are system-generated)

  This is implemented via get_permissions() returning different classes
  based on the action name, rather than a single class on permission_classes.
  This keeps the logic explicit and avoids custom per-method checks scattered
  through the view.

AlertViewSet.partial_update — status-only:
  The serializer already marks every field except `status` as read-only,
  so a PATCH with extra fields silently ignores them (DRF default behaviour).
  We do not need to whitelist fields in the view.

ThresholdViewSet:
  Full CRUD.  IsAdminOrReadOnly blocks non-admins from write operations.
"""

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from sensors.permissions import IsAdminOrReadOnly

from .models import Alert, Threshold
from .serializers import AlertSerializer, ThresholdSerializer


class AlertViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    list     GET  /alerts/          any auth user
    retrieve GET  /alerts/<pk>/     any auth user
    partial  PATCH /alerts/<pk>/    admin only — status field only
    """

    serializer_class = AlertSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_permissions(self):
        """
        list / retrieve → any authenticated user.
        partial_update  → admin only.
        """
        if self.action == "partial_update":
            return [IsAdminOrReadOnly()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = Alert.objects.select_related("sensor", "reading").order_by("-created_at")
        status_filter = self.request.query_params.get("status")
        sensor_id = self.request.query_params.get("sensor")
        if status_filter:
            qs = qs.filter(status=status_filter)
        if sensor_id:
            qs = qs.filter(sensor_id=sensor_id)
        return qs


class ThresholdViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for Threshold objects.
    Write operations require admin role (IsAdminOrReadOnly).
    """

    serializer_class = ThresholdSerializer
    permission_classes = [IsAdminOrReadOnly]
    queryset = Threshold.objects.all().order_by("parameter")
