"""
sensors/models.py – Sensor and SensorReading
=============================================
SensorReading is the hot table — the simulator will insert rows every few seconds
per sensor, so index strategy matters:

Compound index (sensor, timestamp):
  Every useful query is "readings for sensor X in time range Y–Z".
  A compound index on (sensor_id, timestamp) satisfies both the equality filter
  on sensor and the range scan on timestamp in a single B-tree traversal.
  We do NOT add a separate db_index=True on timestamp because:
    a) The compound index already covers timestamp lookups when sensor is known.
    b) MySQL would maintain a redundant single-column index, wasting write I/O
       on every INSERT — in a high-frequency time-series table this matters.

FloatField vs DecimalField:
  Sensor readings are inherently imprecise measurements (±5% accuracy on most
  sensors). The rounding error of IEEE 754 floats is smaller than sensor noise,
  so FloatField is appropriate and faster than DecimalField for aggregations.

Validators are defined at the model layer (not only the serializer) so that
Django admin and any future non-REST write paths also enforce constraints.
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Sensor(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_MAINTENANCE = "maintenance"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
        (STATUS_MAINTENANCE, "Maintenance"),
    ]

    sensor_code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Human-readable identifier, e.g. SEN-001.",
    )
    location = models.CharField(max_length=200, help_text="Physical location description.")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    installed_at = models.DateField(help_text="Date the sensor was physically deployed.")

    class Meta:
        ordering = ["sensor_code"]

    def __str__(self) -> str:
        return f"{self.sensor_code} — {self.location}"


class SensorReading(models.Model):
    sensor = models.ForeignKey(
        Sensor,
        on_delete=models.CASCADE,
        related_name="readings",
    )
    # Particulate matter (µg/m³) — physically cannot be negative
    pm25 = models.FloatField(
        validators=[MinValueValidator(0.0)],
        help_text="PM2.5 concentration in µg/m³.",
    )
    pm10 = models.FloatField(
        validators=[MinValueValidator(0.0)],
        help_text="PM10 concentration in µg/m³.",
    )
    # Temperature in Celsius — no hard lower bound enforced at model level
    # (extreme cold environments may read below 0) but validated in serializer
    temperature = models.FloatField(help_text="Temperature in °C.")
    # Relative humidity 0–100 %
    humidity = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Relative humidity in %.",
    )
    # timestamp is NOT individually indexed — see module docstring.
    # The compound index below covers all time-range queries.
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        # Compound index: the primary access pattern is
        #   WHERE sensor_id = ? AND timestamp BETWEEN ? AND ?
        # MySQL uses this index for both the equality and range predicates.
        indexes = [
            models.Index(fields=["sensor", "timestamp"], name="idx_reading_sensor_ts"),
        ]
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"{self.sensor.sensor_code} @ {self.timestamp:%Y-%m-%d %H:%M:%S} UTC"
