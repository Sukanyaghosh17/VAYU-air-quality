"""
alerts/models.py – Alert and Threshold
=======================================
Alert.reading (FK → SensorReading, SET_NULL):
  Linking an alert directly to the reading that triggered it enables the
  dashboard to show the exact value, timestamp, and context without a
  separate lookup.  SET_NULL (not CASCADE) is intentional — if a reading
  is ever deleted for housekeeping, we want to keep the alert audit trail.

Alert deduplication strategy (implemented in Phase 4):
  Alerts have a `status` lifecycle: open → investigating → resolved.
  The rule-based checker will skip creating a new Alert if an open alert
  already exists for the same sensor + parameter combination, preventing
  flood behaviour during sustained breaches.

Threshold is global per parameter (MVP simplification — see README):
  A single Threshold row covers all sensors for a given parameter.
  The unique constraint enforces "exactly one row per parameter" at the
  DB level, making the lookup unambiguous.  Per-sensor thresholds would
  require a FK to Sensor and a more complex lookup query; that is called
  out as a future enhancement in ARCHITECTURE.md.

Index on (status, created_at):
  The alerts page filters by status first (open alerts), then sorts by
  created_at descending.  This composite index supports that pattern
  without a full table scan as the alert count grows.
"""

from django.db import models
from django.utils import timezone


class Alert(models.Model):
    TYPE_THRESHOLD = "threshold"
    TYPE_ML = "ml"
    ALERT_TYPE_CHOICES = [
        (TYPE_THRESHOLD, "Threshold"),
        (TYPE_ML, "ML Anomaly"),
    ]

    SEV_LOW = "low"
    SEV_MEDIUM = "medium"
    SEV_HIGH = "high"
    SEVERITY_CHOICES = [
        (SEV_LOW, "Low"),
        (SEV_MEDIUM, "Medium"),
        (SEV_HIGH, "High"),
    ]

    STATUS_OPEN = "open"
    STATUS_INVESTIGATING = "investigating"
    STATUS_RESOLVED = "resolved"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_INVESTIGATING, "Investigating"),
        (STATUS_RESOLVED, "Resolved"),
    ]

    sensor = models.ForeignKey(
        "sensors.Sensor",
        on_delete=models.CASCADE,
        related_name="alerts",  # sensor.alerts.filter(status="open")
    )
    # Direct link to the triggering reading for context display on the dashboard.
    # SET_NULL: deleting a reading does not cascade-delete the audit trail.
    reading = models.ForeignKey(
        "sensors.SensorReading",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alerts",
        help_text="The specific reading that triggered this alert (if applicable).",
    )
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPE_CHOICES)
    parameter = models.CharField(
        max_length=50,
        help_text="Which measurement triggered the alert (e.g. 'pm25').",
    )
    value = models.FloatField(help_text="The measurement value at alert creation time.")
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            # Primary query pattern: list open alerts sorted by newest first
            models.Index(fields=["status", "created_at"], name="idx_alert_status_created"),
        ]
        ordering = ["-created_at"]

    def resolve(self) -> None:
        """Mark this alert resolved and record the resolution timestamp."""
        self.status = self.STATUS_RESOLVED
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolved_at"])

    def __str__(self) -> str:
        return (
            f"[{self.get_severity_display()}] {self.get_alert_type_display()} alert "
            f"on {self.sensor.sensor_code} — {self.parameter} = {self.value}"
        )


class Threshold(models.Model):
    PARAMETER_PM25 = "pm25"
    PARAMETER_PM10 = "pm10"
    PARAMETER_TEMPERATURE = "temperature"
    PARAMETER_HUMIDITY = "humidity"
    PARAMETER_CHOICES = [
        (PARAMETER_PM25, "PM2.5 (µg/m³)"),
        (PARAMETER_PM10, "PM10 (µg/m³)"),
        (PARAMETER_TEMPERATURE, "Temperature (°C)"),
        (PARAMETER_HUMIDITY, "Humidity (%)"),
    ]

    parameter = models.CharField(
        max_length=50,
        choices=PARAMETER_CHOICES,
        unique=True,  # DB-level enforcement: exactly one threshold per parameter
        help_text="The air-quality parameter this threshold applies to.",
    )
    warning_limit = models.FloatField(
        help_text="Value above which a LOW/MEDIUM severity alert is raised."
    )
    critical_limit = models.FloatField(
        help_text="Value above which a HIGH severity alert is raised."
    )

    class Meta:
        ordering = ["parameter"]

    def __str__(self) -> str:
        return f"{self.get_parameter_display()} | warn={self.warning_limit} crit={self.critical_limit}"
