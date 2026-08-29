"""
analytics/views.py — SensorStatsView, AnomalyFeedView, TrendView
=================================================================
Response shape summary (IMPORTANT for Phase 6 frontend):
─────────────────────────────────────────────────────────
  GET /api/v1/analytics/stats/      → plain dict (no pagination envelope)
  GET /api/v1/analytics/trends/     → plain dict with "points" list (no envelope)
  GET /api/v1/analytics/anomalies/  → paginated envelope
                                       {"count", "next", "previous", "results"}

Rationale: stats and trends are always bounded by ?hours= / ?range= query params
so the result set is inherently small.  anomalies/ can grow to thousands of rows
as the ML scorer runs in Phase 5, so it gets the full paginated envelope.

See implementation_plan.md Fix 3 for the full explanation.

AnomalyFeedView — Phase 2 behaviour:
  Returns {"count": 0, "results": []} until Phase 5 ML scoring starts writing
  Alert rows with alert_type="ml".  The endpoint shape is final; no changes
  needed in Phase 5 — the view just starts returning populated results.
"""

from datetime import timedelta

from django.db.models import Avg, Count, Max, Min, StdDev
from django.db.models.functions import TruncDay, TruncHour
from django.utils import timezone

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from alerts.models import Alert
from sensors.models import SensorReading

from .serializers import AnomalyAlertSerializer, SensorStatsSerializer


VALID_TREND_PARAMS = {"pm25", "pm10", "temperature", "humidity"}


class SensorStatsView(APIView):
    """
    GET /api/v1/analytics/stats/?sensor=<id>&hours=<n>

    Returns aggregated statistics for a single sensor over the last <hours>
    hours (default: 24).

    Response shape: plain dict (no pagination envelope).
    400 if ?sensor= is missing.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        sensor_id = request.query_params.get("sensor")
        if not sensor_id:
            return Response(
                {"detail": "?sensor=<id> is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            hours = float(request.query_params.get("hours", 24))
        except ValueError:
            return Response(
                {"detail": "?hours= must be a number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        since = timezone.now() - timedelta(hours=hours)
        qs = SensorReading.objects.filter(sensor_id=sensor_id, timestamp__gte=since)

        agg = qs.aggregate(
            count=Count("id"),
            pm25_mean=Avg("pm25"),
            pm25_min=Min("pm25"),
            pm25_max=Max("pm25"),
            pm25_std=StdDev("pm25"),
            pm10_mean=Avg("pm10"),
            pm10_min=Min("pm10"),
            pm10_max=Max("pm10"),
            temp_mean=Avg("temperature"),
            humidity_mean=Avg("humidity"),
        )

        payload = {
            "sensor_id": int(sensor_id),
            "window_hours": hours,
            **agg,
        }
        serializer = SensorStatsSerializer(payload)
        return Response(serializer.data)


class AnomalyFeedView(generics.ListAPIView):
    """
    GET /api/v1/analytics/anomalies/?sensor=<id>&status=<open|…>

    Returns ML-flagged alerts (alert_type="ml").
    Returns {"count": 0, "results": []} in Phase 2 — no ML data yet.
    Phase 5 ML scorer will start writing alert_type="ml" rows; this view
    requires no changes to start returning populated results.

    Response shape: paginated envelope
      {"count": N, "next": "…", "previous": "…", "results": […]}

    NOTE: This is different from stats/ and trends/ which return plain dicts.
    See module docstring for rationale.
    """

    serializer_class = AnomalyAlertSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = (
            Alert.objects
            .filter(alert_type=Alert.TYPE_ML)
            .select_related("sensor", "reading")
            .order_by("-created_at")
        )
        sensor_id = self.request.query_params.get("sensor")
        status_filter = self.request.query_params.get("status")
        if sensor_id:
            qs = qs.filter(sensor_id=sensor_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class TrendView(APIView):
    """
    GET /api/v1/analytics/trends/?param=<pm25|pm10|temperature|humidity>&range=7d|30d

    Returns a time-bucketed series for charting a single parameter across all
    sensors (or filtered by ?sensor=<id>).

    Response shape: plain dict (no pagination envelope)
      {
        "param": "pm25",
        "range": "7d",
        "points": [{"bucket": "…ISO…", "avg_value": 12.5}, …]
      }

    400 if ?param= is missing or not in the valid set.
    400 if ?range= is invalid.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        param = request.query_params.get("param")
        if not param or param not in VALID_TREND_PARAMS:
            return Response(
                {
                    "detail": (
                        f"?param= is required and must be one of: "
                        f"{', '.join(sorted(VALID_TREND_PARAMS))}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        range_param = request.query_params.get("range", "7d")
        range_map = {
            "7d":  (timedelta(days=7),  TruncDay),
            "30d": (timedelta(days=30), TruncDay),
            "24h": (timedelta(hours=24), TruncHour),
        }
        if range_param not in range_map:
            return Response(
                {"detail": "range must be one of: 24h, 7d, 30d."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        delta, trunc_fn = range_map[range_param]
        since = timezone.now() - delta

        qs = SensorReading.objects.filter(timestamp__gte=since)
        sensor_id = request.query_params.get("sensor")
        if sensor_id:
            qs = qs.filter(sensor_id=sensor_id)

        points = (
            qs
            .annotate(bucket=trunc_fn("timestamp"))
            .values("bucket")
            .annotate(avg_value=Avg(param))
            .order_by("bucket")
        )

        return Response(
            {
                "param": param,
                "range": range_param,
                "points": [
                    {
                        "bucket": row["bucket"].isoformat(),
                        "avg_value": row["avg_value"],
                    }
                    for row in points
                ],
            }
        )
