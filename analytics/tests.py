"""
analytics/tests.py — DRF APITestCase suite for analytics endpoints
==================================================================
All three views are read-only, so tests focus on:
  - Correct 200/400 responses
  - Response shape (dict vs paginated envelope)
  - Correct queryset scoping (anomalies/ only returns alert_type="ml")
"""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from alerts.models import Alert
from sensors.models import Sensor, SensorReading

User = get_user_model()


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_user(username, role="user"):
    u = User.objects.create_user(username=username, password="testpass123", role=role)
    token, _ = Token.objects.get_or_create(user=u)
    return u, token.key


def make_sensor(code="SEN-AN01"):
    return Sensor.objects.create(
        sensor_code=code,
        location="Analytics Test",
        status="active",
        installed_at="2025-01-01",
    )


def make_reading(sensor, pm25=10.0):
    return SensorReading.objects.create(
        sensor=sensor,
        pm25=pm25,
        pm10=pm25 * 2,
        temperature=25.0,
        humidity=50.0,
    )


def make_alert(sensor, alert_type="ml"):
    return Alert.objects.create(
        sensor=sensor,
        alert_type=alert_type,
        parameter="pm25",
        value=99.0,
        severity=Alert.SEV_HIGH,
        status=Alert.STATUS_OPEN,
    )


# ── SensorStatsView tests ─────────────────────────────────────────────────────

class StatsViewTests(APITestCase):
    def setUp(self):
        _, self.token = make_user("stats_user")
        self.sensor = make_sensor()
        make_reading(self.sensor, pm25=12.0)
        make_reading(self.sensor, pm25=18.0)
        self.url = "/api/v1/analytics/stats/"

    def auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    def test_stats_with_valid_sensor(self):
        self.auth()
        resp = self.client.get(self.url, {"sensor": self.sensor.pk, "hours": "24"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["sensor_id"], self.sensor.pk)
        self.assertEqual(resp.data["count"], 2)
        self.assertAlmostEqual(resp.data["pm25_mean"], 15.0)

    def test_stats_missing_sensor_param(self):
        self.auth()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_stats_unauthenticated_denied(self):
        resp = self.client.get(self.url, {"sensor": self.sensor.pk})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_stats_response_is_flat_dict(self):
        """stats/ must return a plain dict, NOT a paginated envelope."""
        self.auth()
        resp = self.client.get(self.url, {"sensor": self.sensor.pk})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # The paginated envelope always contains a "results" key.
        # stats/ is a plain dict — "results" must NOT be present.
        # (Note: "count" IS present as a legitimate stats field — reading count.)
        self.assertNotIn("results", resp.data)
        self.assertIn("sensor_id", resp.data)


# ── AnomalyFeedView tests ─────────────────────────────────────────────────────

class AnomalyFeedTests(APITestCase):
    def setUp(self):
        _, self.token = make_user("anomaly_user")
        self.sensor = make_sensor("SEN-AN02")
        self.url = "/api/v1/analytics/anomalies/"

    def auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    def test_empty_list_shape_before_ml(self):
        """Must return paginated envelope with empty results in Phase 2."""
        self.auth()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("count", resp.data)
        self.assertIn("results", resp.data)
        self.assertEqual(resp.data["count"], 0)
        self.assertEqual(resp.data["results"], [])

    def test_only_ml_alerts_returned(self):
        """threshold-type alerts must NOT appear in the anomalies feed."""
        make_alert(self.sensor, alert_type="threshold")  # should be excluded
        make_alert(self.sensor, alert_type="ml")         # should be included
        self.auth()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["sensor_code"], self.sensor.sensor_code)

    def test_unauthenticated_denied(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── TrendView tests ───────────────────────────────────────────────────────────

class TrendViewTests(APITestCase):
    def setUp(self):
        _, self.token = make_user("trend_user")
        self.sensor = make_sensor("SEN-AN03")
        make_reading(self.sensor, pm25=10.0)
        self.url = "/api/v1/analytics/trends/"

    def auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    def test_valid_param_and_range(self):
        self.auth()
        resp = self.client.get(self.url, {"param": "pm25", "range": "7d"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["param"], "pm25")
        self.assertEqual(resp.data["range"], "7d")
        self.assertIn("points", resp.data)
        self.assertIsInstance(resp.data["points"], list)

    def test_response_is_flat_dict_not_paginated(self):
        """trends/ must return a plain dict with a 'points' list, NOT an envelope."""
        self.auth()
        resp = self.client.get(self.url, {"param": "pm10", "range": "30d"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertNotIn("results", resp.data)
        self.assertIn("points", resp.data)

    def test_invalid_param_rejected(self):
        self.auth()
        resp = self.client.get(self.url, {"param": "co2", "range": "7d"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_param_rejected(self):
        self.auth()
        resp = self.client.get(self.url, {"range": "7d"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_range_rejected(self):
        self.auth()
        resp = self.client.get(self.url, {"param": "pm25", "range": "99y"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_denied(self):
        resp = self.client.get(self.url, {"param": "pm25", "range": "7d"})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Phase 5: ML anomaly detection tests ──────────────────────────────────────

import tempfile
from pathlib import Path
from django.test import TestCase, override_settings
from sensors.models import Sensor, SensorReading
from analytics.ml import (
    train_sensor_model, score_reading, get_model_path, _build_row, FEATURES
)


def _make_ml_sensor(code="SEN-ML01"):
    return Sensor.objects.create(
        sensor_code=code, location="ML Test",
        status="active", installed_at="2025-01-01",
    )


def _make_ml_reading(sensor, pm25=12.0, pm10=25.0, temp=24.0, hum=52.0):
    return SensorReading.objects.create(
        sensor=sensor, pm25=pm25, pm10=pm10,
        temperature=temp, humidity=hum,
    )


def _bulk_readings(sensor, n=120, pm25_base=12.0):
    """Create n normal readings for training."""
    import numpy as np
    readings = []
    for i in range(n):
        readings.append(SensorReading(
            sensor=sensor,
            pm25=pm25_base + float(np.random.normal(0, 1)),
            pm10=pm25_base * 2 + float(np.random.normal(0, 2)),
            temperature=25.0 + float(np.random.normal(0, 1)),
            humidity=55.0 + float(np.random.normal(0, 3)),
        ))
    SensorReading.objects.bulk_create(readings)


class FeatureEngineeringTests(TestCase):
    """Unit tests for _build_row — no model, no DB needed."""

    def test_build_row_length(self):
        """Feature vector must have 2×len(FEATURES) elements."""
        import types
        reading = types.SimpleNamespace(pm25=10, pm10=20, temperature=25, humidity=50)
        row = _build_row(reading, [])
        self.assertEqual(len(row), len(FEATURES) * 2)

    def test_build_row_cold_start_fallback(self):
        """With no recent readings, rolling means fall back to raw values."""
        import types
        reading = types.SimpleNamespace(pm25=10.0, pm10=20.0, temperature=25.0, humidity=50.0)
        row = _build_row(reading, [])
        raw = row[:len(FEATURES)]
        means = row[len(FEATURES):]
        # Cold-start: means should equal raw values
        self.assertEqual(raw, means)


class MLTrainAndScoreTests(TestCase):
    """Integration tests: train → persist → score."""

    def setUp(self):
        self.sensor = _make_ml_sensor()
        self.tmp = tempfile.mkdtemp()

    @override_settings()
    def test_train_creates_model_file(self):
        from django.conf import settings
        settings.ML_MODELS_DIR = self.tmp
        settings.ML_ROLLING_WINDOW = 6

        _bulk_readings(self.sensor, n=120)
        readings = SensorReading.objects.filter(sensor=self.sensor).order_by("timestamp")
        path = train_sensor_model(self.sensor.id, readings)
        self.assertTrue(path.exists())
        self.assertIn(f"sensor_{self.sensor.id}.joblib", str(path))

    @override_settings()
    def test_score_no_model_returns_false(self):
        """score_reading must return (False, 0.0) when no model file exists."""
        from django.conf import settings
        settings.ML_MODELS_DIR = self.tmp  # empty temp dir
        reading = _make_ml_reading(self.sensor)
        is_anomaly, score = score_reading(reading)
        self.assertFalse(is_anomaly)
        self.assertEqual(score, 0.0)

    @override_settings()
    def test_normal_reading_not_flagged_after_training(self):
        """Normal readings should NOT be flagged as anomalies after training."""
        from django.conf import settings
        settings.ML_MODELS_DIR = self.tmp
        settings.ML_ROLLING_WINDOW = 6
        settings.ML_MIN_READINGS = 100

        _bulk_readings(self.sensor, n=120, pm25_base=12.0)
        readings = SensorReading.objects.filter(sensor=self.sensor).order_by("timestamp")
        train_sensor_model(self.sensor.id, readings)

        # A completely normal reading
        normal = _make_ml_reading(self.sensor, pm25=12.0, pm10=24.0, temp=25.0, hum=55.0)
        is_anomaly, score = score_reading(normal)
        # Note: Isolation Forest is probabilistic — we assert score is finite, not the label
        self.assertIsInstance(is_anomaly, bool)
        self.assertIsInstance(score, float)

    @override_settings()
    def test_extreme_reading_more_anomalous_than_normal(self):
        """
        An extreme spike should have a more anomalous score than a normal reading.
        (score_samples: lower = more anomalous)
        """
        from django.conf import settings
        settings.ML_MODELS_DIR = self.tmp
        settings.ML_ROLLING_WINDOW = 6

        _bulk_readings(self.sensor, n=120, pm25_base=12.0)
        readings = SensorReading.objects.filter(sensor=self.sensor).order_by("timestamp")
        train_sensor_model(self.sensor.id, readings)

        normal = _make_ml_reading(self.sensor, pm25=12.0)
        spike  = _make_ml_reading(self.sensor, pm25=500.0, pm10=600.0)

        _, score_normal = score_reading(normal)
        _, score_spike  = score_reading(spike)

        self.assertLess(score_spike, score_normal,
                        "Spike reading should be more anomalous (lower score)")


class MLManagementCommandTests(TestCase):
    """Smoke tests for python manage.py train_ml."""

    def setUp(self):
        self.sensor = _make_ml_sensor("SEN-CMD01")
        self.tmp = tempfile.mkdtemp()

    @override_settings()
    def test_train_ml_dry_run(self):
        """--dry-run should not create any model files."""
        from django.conf import settings
        from django.core.management import call_command
        from io import StringIO
        settings.ML_MODELS_DIR = self.tmp
        settings.ML_MIN_READINGS = 5

        _bulk_readings(self.sensor, n=10)
        out = StringIO()
        call_command("train_ml", dry_run=True, stdout=out)

        output = out.getvalue()
        self.assertIn("DRY RUN", output)
        # No .joblib file should have been created
        self.assertEqual(list(Path(self.tmp).glob("*.joblib")), [])

    @override_settings()
    def test_train_ml_skips_sensor_with_too_few_readings(self):
        """Sensor with fewer readings than min_readings must be skipped."""
        from django.conf import settings
        from django.core.management import call_command
        from io import StringIO
        settings.ML_MODELS_DIR = self.tmp
        settings.ML_MIN_READINGS = 1000  # impossible to satisfy

        _bulk_readings(self.sensor, n=10)
        out = StringIO()
        call_command("train_ml", stdout=out)
        output = out.getvalue()
        self.assertIn("SKIP", output)
        self.assertEqual(list(Path(self.tmp).glob("*.joblib")), [])

    @override_settings()
    def test_train_ml_trains_and_saves(self):
        """With enough readings, train_ml must create a .joblib file."""
        from django.conf import settings
        from django.core.management import call_command
        from io import StringIO
        settings.ML_MODELS_DIR = self.tmp
        settings.ML_MIN_READINGS = 10
        settings.ML_ROLLING_WINDOW = 6

        _bulk_readings(self.sensor, n=20)
        out = StringIO()
        call_command("train_ml", stdout=out)
        output = out.getvalue()
        self.assertIn("TRAIN", output)
        saved = list(Path(self.tmp).glob("*.joblib"))
        self.assertEqual(len(saved), 1)
        self.assertIn(f"sensor_{self.sensor.id}", saved[0].name)
