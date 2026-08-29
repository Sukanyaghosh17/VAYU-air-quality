"""
analytics/serializers.py — Output-only serializers for analytics endpoints
===========================================================================
All three serializers are output-only (no write path) because the analytics
endpoints are read-only aggregations — they never accept POST data.

SensorStatsSerializer:
  Flat dict with ORM aggregate outputs for a single sensor over a time window.

TrendPointSerializer:
  One data point in a time-series: ISO bucket timestamp + averaged value for
  the requested parameter.  Used by TrendView.

AnomalyAlertSerializer:
  Thin slice of AlertSerializer scoped to ML-flagged alerts.  Includes the
  same convenience fields (sensor_code, reading_timestamp) for dashboard use.
  Returns an empty list until Phase 5 ML scoring populates Alert rows with
  alert_type="ml".
"""

from rest_framework import serializers

from alerts.models import Alert


class SensorStatsSerializer(serializers.Serializer):
    sensor_id = serializers.IntegerField()
    window_hours = serializers.FloatField()
    count = serializers.IntegerField()
    # Per-parameter stats — null when no readings exist in the window.
    pm25_mean = serializers.FloatField(allow_null=True)
    pm25_min = serializers.FloatField(allow_null=True)
    pm25_max = serializers.FloatField(allow_null=True)
    pm25_std = serializers.FloatField(allow_null=True)
    pm10_mean = serializers.FloatField(allow_null=True)
    pm10_min = serializers.FloatField(allow_null=True)
    pm10_max = serializers.FloatField(allow_null=True)
    temp_mean = serializers.FloatField(allow_null=True)
    humidity_mean = serializers.FloatField(allow_null=True)


class TrendPointSerializer(serializers.Serializer):
    bucket = serializers.DateTimeField()
    avg_value = serializers.FloatField(allow_null=True)


class AnomalyAlertSerializer(serializers.ModelSerializer):
    """
    Subset of Alert fields for the anomaly feed.
    Always scoped to alert_type="ml" in the view queryset.

    Response shape: paginated envelope (ListAPIView auto-wraps):
      {"count": N, "next": "…", "previous": "…", "results": […]}

    NOTE: This differs from SensorStatsSerializer and TrendPointSerializer
    which return plain dicts (no pagination envelope).  See implementation_plan.md
    Fix 3 for the rationale and Phase 6 frontend handling notes.
    """

    sensor_code = serializers.CharField(source="sensor.sensor_code", read_only=True)
    reading_timestamp = serializers.DateTimeField(
        source="reading.timestamp", read_only=True, default=None
    )

    class Meta:
        model = Alert
        fields = [
            "id",
            "sensor",
            "sensor_code",
            "reading",
            "reading_timestamp",
            "parameter",
            "value",
            "severity",
            "status",
            "created_at",
        ]
