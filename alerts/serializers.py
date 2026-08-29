"""
alerts/serializers.py — Alert and Threshold DRF serializers
============================================================
AlertSerializer:
  All fields are read-only except `status`.  Alerts are system-generated
  (rule engine / ML scorer) — the API only lets admins update the lifecycle
  state (open → investigating → resolved).

  Extra read-only convenience fields:
    sensor_code       — avoids a client-side Sensor lookup just for display
    reading_timestamp — the exact moment of the triggering reading (nullable)

ThresholdSerializer:
  Full CRUD (admin-only write enforced in the view).
  Cross-field validation: warning_limit must be strictly less than
  critical_limit.  Enforced at the serializer layer so the error is
  returned as a 400 with a clear field-level message.
"""

from rest_framework import serializers

from .models import Alert, Threshold


class AlertSerializer(serializers.ModelSerializer):
    # Convenience read-only fields for dashboard display.
    sensor_code = serializers.CharField(
        source="sensor.sensor_code", read_only=True
    )
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
            "alert_type",
            "parameter",
            "value",
            "severity",
            "status",
            "created_at",
            "resolved_at",
        ]
        read_only_fields = [
            "id",
            "sensor",
            "sensor_code",
            "reading",
            "reading_timestamp",
            "alert_type",
            "parameter",
            "value",
            "severity",
            "created_at",
            "resolved_at",
        ]


class ThresholdSerializer(serializers.ModelSerializer):
    class Meta:
        model = Threshold
        fields = ["id", "parameter", "warning_limit", "critical_limit"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        warning = attrs.get(
            "warning_limit",
            getattr(self.instance, "warning_limit", None),
        )
        critical = attrs.get(
            "critical_limit",
            getattr(self.instance, "critical_limit", None),
        )
        if warning is not None and critical is not None and warning >= critical:
            raise serializers.ValidationError(
                "warning_limit must be strictly less than critical_limit."
            )
        return attrs
