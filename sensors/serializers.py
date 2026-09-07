"""
sensors/serializers.py — Sensor and SensorReading DRF serializers
==================================================================
Design decisions:

SensorSerializer.reading_count:
  Annotated in the viewset queryset (not a DB hit per-row) so the field
  is O(1) per serialized object, not O(n) in Python.

SensorReadingSerializer write path:
  Model-level validators (MinValueValidator, MaxValueValidator) are
  already declared on the fields, so DRF will automatically run them
  during serializer.is_valid(). We do not need to duplicate them here.
  We only add the extra cross-field check (none needed for readings).

SensorReadingSerializer read path:
  sensor_code is exposed as a read-only field via source="sensor.sensor_code"
  so callers don't need a separate Sensor lookup to display a human-readable
  identifier alongside each reading.
"""

from rest_framework import serializers

from .aqi import compute_aqi
from .models import Sensor, SensorReading


class SensorSerializer(serializers.ModelSerializer):
    # Annotated by the viewset queryset; read-only computed field.
    reading_count = serializers.IntegerField(read_only=True, default=0)
    aqi = serializers.SerializerMethodField()
    aqi_category = serializers.SerializerMethodField()

    class Meta:
        model = Sensor
        fields = [
            "id",
            "sensor_code",
            "location",
            "latitude",
            "longitude",
            "status",
            "installed_at",
            "reading_count",
            "aqi",
            "aqi_category",
        ]
        read_only_fields = ["id"]

    def _get_latest_reading(self, obj):
        if not hasattr(self, "_reading_cache"):
            self._reading_cache = {}
        if obj.pk not in self._reading_cache:
            self._reading_cache[obj.pk] = obj.readings.order_by("-timestamp").first()
        return self._reading_cache[obj.pk]

    def get_aqi(self, obj) -> int | None:
        r = self._get_latest_reading(obj)
        if not r:
            return None
        return compute_aqi(r.pm25, r.pm10)["aqi"]

    def get_aqi_category(self, obj) -> str:
        r = self._get_latest_reading(obj)
        if not r:
            return "N/A"
        return compute_aqi(r.pm25, r.pm10)["category"]


class SensorReadingSerializer(serializers.ModelSerializer):
    # Convenience read-only field — avoids a second round-trip in the frontend.
    sensor_code = serializers.CharField(source="sensor.sensor_code", read_only=True)

    class Meta:
        model = SensorReading
        fields = [
            "id",
            "sensor",
            "sensor_code",
            "pm25",
            "pm10",
            "temperature",
            "humidity",
            "timestamp",
        ]
        read_only_fields = ["id", "sensor_code"]
        extra_kwargs = {
            # sensor is write-only on input (client sends sensor id);
            # sensor_code is the human-readable equivalent on output.
            "sensor": {"write_only": False},
        }
