"""
alerts/services.py — Rule-based threshold alert engine
=======================================================
Entry point: check_thresholds(reading)
  Called by SensorReadingViewSet.perform_create() immediately after a new
  SensorReading is saved.  Runs synchronously in the same request cycle
  (no Celery required for an MVP with a 3-second simulator interval).

Algorithm
---------
For each of the four parameters (pm25, pm10, temperature, humidity):

  1. Look up the Threshold row for this parameter (if none exists, skip).
  2. Compare the reading value against warning_limit and critical_limit.
  3. Determine severity:
       value >= critical_limit  → HIGH
       value >= warning_limit   → MEDIUM
       (below warning_limit)    → no alert
  4. Deduplication guard:
       If an open or investigating Alert already exists for the same
       sensor + parameter that was created within ALERT_COOLDOWN_SECONDS,
       skip creating a duplicate.  This prevents alert storms during
       sustained breaches (e.g. PM2.5 stuck at 200 µg/m³ for 10 minutes).
  5. Create the Alert, linking it to the triggering SensorReading.

Return value
------------
  List of Alert objects that were created (empty list if none).
  The caller (perform_create) logs the count; it does not need the objects.

Settings used
-------------
  ALERT_COOLDOWN_SECONDS  (default 300 in settings.py)
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import Alert, Threshold

logger = logging.getLogger(__name__)

# Parameters the engine checks — must match Threshold.PARAMETER_CHOICES keys.
CHECKABLE_PARAMS = ("pm25", "pm10", "temperature", "humidity")


def _get_thresholds() -> dict[str, Threshold]:
    """
    Return a mapping of parameter → Threshold for all configured thresholds.
    Result is NOT cached because admins may update thresholds at runtime.
    The query hits at most 4 rows so the DB round-trip is negligible.
    """
    return {t.parameter: t for t in Threshold.objects.all()}


def _is_duplicate(sensor_id: int, parameter: str, cooldown: timedelta) -> bool:
    """
    Return True if an open/investigating alert for this sensor + parameter
    was already created within the cooldown window.
    """
    cutoff = timezone.now() - cooldown
    return Alert.objects.filter(
        sensor_id=sensor_id,
        parameter=parameter,
        status__in=[Alert.STATUS_OPEN, Alert.STATUS_INVESTIGATING],
        created_at__gte=cutoff,
    ).exists()


def check_thresholds(reading) -> list[Alert]:
    """
    Evaluate a SensorReading against all configured Threshold rows and create
    Alert objects for any breaches that are not already covered by a recent
    open alert.

    Parameters
    ----------
    reading : sensors.models.SensorReading
        The freshly-created reading to evaluate.  Must already be saved (pk set).

    Returns
    -------
    list[Alert]
        Alerts created during this call (may be empty).
    """
    thresholds = _get_thresholds()
    if not thresholds:
        # No thresholds configured yet — nothing to check.
        return []

    cooldown = timedelta(seconds=getattr(settings, "ALERT_COOLDOWN_SECONDS", 300))
    created_alerts: list[Alert] = []

    for param in CHECKABLE_PARAMS:
        threshold = thresholds.get(param)
        if threshold is None:
            continue  # No threshold configured for this parameter

        value = getattr(reading, param, None)
        if value is None:
            continue

        # ── Severity determination ────────────────────────────────────────────
        if value >= threshold.critical_limit:
            severity = Alert.SEV_HIGH
        elif value >= threshold.warning_limit:
            severity = Alert.SEV_MEDIUM
        else:
            continue  # Normal reading — no alert needed

        # ── Deduplication guard ───────────────────────────────────────────────
        if _is_duplicate(reading.sensor_id, param, cooldown):
            logger.debug(
                "Skipping duplicate %s alert for sensor %s (within %ss cooldown)",
                param,
                reading.sensor_id,
                cooldown.total_seconds(),
            )
            continue

        # ── Create alert ──────────────────────────────────────────────────────
        alert = Alert.objects.create(
            sensor=reading.sensor,
            reading=reading,
            alert_type=Alert.TYPE_THRESHOLD,
            parameter=param,
            value=value,
            severity=severity,
            status=Alert.STATUS_OPEN,
        )
        created_alerts.append(alert)
        logger.info(
            "Alert created: [%s] sensor=%s param=%s value=%.2f (threshold warn=%.2f crit=%.2f)",
            severity,
            reading.sensor.sensor_code,
            param,
            value,
            threshold.warning_limit,
            threshold.critical_limit,
        )

    return created_alerts
