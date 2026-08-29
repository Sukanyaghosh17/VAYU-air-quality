"""
sensors/views.py — SensorViewSet and SensorReadingViewSet
==========================================================
SensorReadingViewSet — immutability:
  http_method_names excludes PUT, PATCH, DELETE.  DRF returns 405 Method Not
  Allowed automatically; no custom logic needed.

SensorReadingViewSet — pagination:
  Uses the global PageNumberPagination (PAGE_SIZE=50) from settings.  The
  viewset does not override pagination_class so the project default applies.

SensorReadingViewSet.latest():
  MySQL-compatible correlated subquery — see implementation_plan.md Fix 2.
  The subquery resolves the pk of the most-recent SensorReading for each Sensor.
  This hits the compound index idx_reading_sensor_ts (sensor, timestamp) from
  Phase 1 for the inner ORDER BY / LIMIT.

SensorReadingViewSet.history():
  Accepts ?sensor=<id>&range=24h|7d|30d.
  24h  → TruncHour  buckets (24 points)
  7d   → TruncDay   buckets (7 points)
  30d  → TruncDay   buckets (30 points)
  Returns a list of dicts: [{bucket, avg_pm25, avg_pm10, avg_temp, avg_humidity}]
  No serializer class needed — the ORM aggregate result is already a plain dict.
"""

from datetime import timedelta

from django.db.models import Avg, Count, OuterRef, Subquery
from django.db.models.functions import TruncDay, TruncHour
from django.utils import timezone

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Sensor, SensorReading
from .permissions import IsAdminOrReadOnly, IsAuthenticatedReadOrCreate
from .serializers import SensorReadingSerializer, SensorSerializer


class SensorViewSet(viewsets.ModelViewSet):
    """
    CRUD for Sensor objects.
    Write operations (POST/PUT/PATCH/DELETE) require admin role.
    Read operations are open to any authenticated user.
    """

    serializer_class = SensorSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        return (
            Sensor.objects
            .annotate(reading_count=Count("readings"))
            .order_by("sensor_code")
        )


class SensorReadingViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Ingest and retrieve SensorReading rows.

    Uses explicit mixins (not ModelViewSet) so that PUT / PATCH / DELETE
    routes are never registered by the router at all.  DRF returns 405
    before any permission check runs, which is the correct behaviour for
    immutable resources.

    Permissions:
      POST / GET: any authenticated user (simulator uses Token auth).
      PUT / PATCH / DELETE: not routed — 405 from the router.

    Query filters (GET list):
      ?sensor=<id>   — filter by sensor primary key
      ?since=<ISO>   — only readings at or after this datetime (UTC)

    Custom actions:
      GET /readings/latest/           — one row per sensor, most-recent timestamp
      GET /readings/history/          — time-bucketed averages
        ?sensor=<id>  (required)
        &range=24h|7d|30d  (default: 24h)
    """

    serializer_class = SensorReadingSerializer
    # IsAuthenticated (not IsAuthenticatedReadOrCreate) is correct here.
    # Immutability is enforced at the routing layer: no UpdateModelMixin means
    # the router never registers PUT/PATCH/DELETE routes, so the router itself
    # returns 405 before any permission check for those methods.
    # If we used IsAuthenticatedReadOrCreate, DRF's permission check would
    # run first and return 403 for PUT — masking the real reason (no route).
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = SensorReading.objects.select_related("sensor").order_by("-timestamp")
        sensor_id = self.request.query_params.get("sensor")
        since = self.request.query_params.get("since")
        if sensor_id:
            qs = qs.filter(sensor_id=sensor_id)
        if since:
            qs = qs.filter(timestamp__gte=since)
        return qs

    def perform_create(self, serializer):
        """
        Save the reading then run both the threshold alert engine (Phase 4)
        and the ML anomaly scorer (Phase 5) in sequence.

        Both imports are local to avoid circular imports:
          sensors → alerts.services  (ok at call time)
          sensors → analytics.ml     (ok at call time)
        """
        import logging as _logging
        _log = _logging.getLogger(__name__)

        reading = serializer.save()

        # ── Phase 4: threshold alert engine ───────────────────────────────────
        from alerts.services import check_thresholds
        threshold_alerts = check_thresholds(reading)
        if threshold_alerts:
            _log.info(
                "Threshold check: %d alert(s) for reading id=%d",
                len(threshold_alerts), reading.pk,
            )

        # ── Phase 5: ML anomaly scorer ────────────────────────────────────────
        from analytics.ml import score_reading
        from alerts.services import _is_duplicate
        from django.conf import settings
        from datetime import timedelta

        try:
            is_anomaly, score = score_reading(reading)
        except Exception as exc:  # noqa: BLE001
            _log.warning("ML scoring failed for reading id=%d: %s", reading.pk, exc)
            is_anomaly, score = False, 0.0

        if is_anomaly:
            from alerts.models import Alert
            cooldown = timedelta(seconds=getattr(settings, "ALERT_COOLDOWN_SECONDS", 300))
            # Dedup: skip if an open ML alert for this sensor already exists
            # within the cooldown window.  Use parameter="anomaly" to
            # distinguish ML composite alerts from per-parameter threshold alerts.
            if not _is_duplicate(reading.sensor_id, "anomaly", cooldown):
                Alert.objects.create(
                    sensor=reading.sensor,
                    reading=reading,
                    alert_type=Alert.TYPE_ML,
                    parameter="anomaly",
                    value=round(score, 6),
                    severity=Alert.SEV_HIGH,
                    status=Alert.STATUS_OPEN,
                )
                _log.info(
                    "ML anomaly alert created for sensor %s (score=%.4f)",
                    reading.sensor.sensor_code, score,
                )

    # ── Custom actions ────────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="latest")
    def latest(self, request):
        """
        Return the most-recent SensorReading for each sensor.

        MySQL-compatible implementation — DISTINCT ON is PostgreSQL-only.
        Uses a correlated subquery:

            SELECT * FROM sensors_sensorreading
            WHERE id IN (
                SELECT (
                    SELECT id FROM sensors_sensorreading sr2
                    WHERE sr2.sensor_id = s.id
                    ORDER BY sr2.timestamp DESC LIMIT 1
                )
                FROM sensors_sensor s
            )

        The inner subquery hits the compound index idx_reading_sensor_ts.
        """
        # Subquery: for each Sensor row, the PK of its latest reading.
        latest_pk_sq = (
            SensorReading.objects
            .filter(sensor=OuterRef("pk"))
            .order_by("-timestamp")
            .values("pk")[:1]
        )
        pks = (
            Sensor.objects
            .annotate(latest_pk=Subquery(latest_pk_sq))
            .exclude(latest_pk=None)
            .values_list("latest_pk", flat=True)
        )
        queryset = (
            SensorReading.objects
            .filter(pk__in=pks)
            .select_related("sensor")
            .order_by("sensor__sensor_code")
        )
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="history")
    def history(self, request):
        """
        Time-bucketed average readings for a sensor.

        Query params:
          ?sensor=<id>  (required)
          ?range=24h|7d|30d  (default: 24h)

        Response: list of dicts
          [{bucket (ISO), avg_pm25, avg_pm10, avg_temp, avg_humidity}]

        24h → TruncHour (up to 24 data points)
        7d  → TruncDay  (up to 7 data points)
        30d → TruncDay  (up to 30 data points)
        """
        sensor_id = request.query_params.get("sensor")
        if not sensor_id:
            return Response(
                {"detail": "?sensor=<id> is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        range_param = request.query_params.get("range", "24h")
        now = timezone.now()

        range_map = {
            "24h": (timedelta(hours=24), TruncHour),
            "7d":  (timedelta(days=7),   TruncDay),
            "30d": (timedelta(days=30),  TruncDay),
        }
        if range_param not in range_map:
            return Response(
                {"detail": "range must be one of: 24h, 7d, 30d."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        delta, trunc_fn = range_map[range_param]
        since = now - delta

        data = (
            SensorReading.objects
            .filter(sensor_id=sensor_id, timestamp__gte=since)
            .annotate(bucket=trunc_fn("timestamp"))
            .values("bucket")
            .annotate(
                avg_pm25=Avg("pm25"),
                avg_pm10=Avg("pm10"),
                avg_temp=Avg("temperature"),
                avg_humidity=Avg("humidity"),
            )
            .order_by("bucket")
        )

        result = [
            {
                "bucket": row["bucket"].isoformat(),
                "avg_pm25": row["avg_pm25"],
                "avg_pm10": row["avg_pm10"],
                "avg_temp": row["avg_temp"],
                "avg_humidity": row["avg_humidity"],
            }
            for row in data
        ]
        return Response(result)
