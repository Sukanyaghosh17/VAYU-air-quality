"""
alerts/tests.py — DRF APITestCase suite for alerts and thresholds
=================================================================
Key cases verified:
  - Alert list/retrieve open to any auth user
  - Alert PATCH status: admin → 200, regular user → 403
  - Alert PATCH with invalid status value → 400
  - Threshold create: admin → 201, regular user → 403
  - Threshold create with warning_limit >= critical_limit → 400
"""

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from alerts.models import Alert, Threshold
from sensors.models import Sensor

User = get_user_model()


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_user(username, role="user"):
    u = User.objects.create_user(username=username, password="testpass123", role=role)
    token, _ = Token.objects.get_or_create(user=u)
    return u, token.key


def make_sensor(code="SEN-A01"):
    return Sensor.objects.create(
        sensor_code=code,
        location="Test",
        status="active",
        installed_at="2025-01-01",
    )


def make_alert(sensor, alert_type="threshold", param="pm25", value=80.0, sev="high"):
    return Alert.objects.create(
        sensor=sensor,
        alert_type=alert_type,
        parameter=param,
        value=value,
        severity=sev,
        status=Alert.STATUS_OPEN,
    )


# ── AlertViewSet tests ────────────────────────────────────────────────────────

class AlertAPITests(APITestCase):
    def setUp(self):
        self.admin, self.admin_token = make_user("alert_admin", role="admin")
        self.user, self.user_token = make_user("alert_user", role="user")
        self.sensor = make_sensor()
        self.alert = make_alert(self.sensor)
        self.list_url = "/api/v1/alerts/"
        self.detail_url = f"{self.list_url}{self.alert.pk}/"

    def auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def test_list_as_regular_user(self):
        self.auth(self.user_token)
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_list_unauthenticated_allowed(self):
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_filter_by_status(self):
        self.auth(self.user_token)
        resp = self.client.get(self.list_url, {"status": "open"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        for item in resp.data["results"]:
            self.assertEqual(item["status"], "open")

    def test_retrieve_as_regular_user(self):
        self.auth(self.user_token)
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_patch_status_as_admin(self):
        self.auth(self.admin_token)
        resp = self.client.patch(
            self.detail_url, {"status": "investigating"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "investigating")

    def test_patch_status_as_regular_user_forbidden(self):
        """Regular users must not be able to update alert status."""
        self.auth(self.user_token)
        resp = self.client.patch(
            self.detail_url, {"status": "resolved"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_invalid_status_value(self):
        self.auth(self.admin_token)
        resp = self.client.patch(
            self.detail_url, {"status": "banana"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_not_allowed(self):
        """Alerts are system-generated — POST must be rejected."""
        self.auth(self.admin_token)
        resp = self.client.post(self.list_url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_not_allowed(self):
        self.auth(self.admin_token)
        resp = self.client.delete(self.detail_url)
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


# ── ThresholdViewSet tests ────────────────────────────────────────────────────

class ThresholdAPITests(APITestCase):
    def setUp(self):
        self.admin, self.admin_token = make_user("thr_admin", role="admin")
        self.user, self.user_token = make_user("thr_user", role="user")
        self.list_url = "/api/v1/thresholds/"

    def auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def test_list_as_regular_user(self):
        self.auth(self.user_token)
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_as_admin(self):
        self.auth(self.admin_token)
        payload = {
            "parameter": "pm25",
            "warning_limit": 35.5,
            "critical_limit": 75.0,
        }
        resp = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_create_as_regular_user_forbidden(self):
        self.auth(self.user_token)
        payload = {
            "parameter": "pm10",
            "warning_limit": 50.0,
            "critical_limit": 100.0,
        }
        resp = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_warning_equal_to_critical_rejected(self):
        self.auth(self.admin_token)
        payload = {
            "parameter": "temperature",
            "warning_limit": 40.0,
            "critical_limit": 40.0,  # equal — should fail
        }
        resp = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_warning_greater_than_critical_rejected(self):
        self.auth(self.admin_token)
        payload = {
            "parameter": "humidity",
            "warning_limit": 90.0,
            "critical_limit": 80.0,  # reversed — should fail
        }
        resp = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ── Phase 4: ThresholdCheckService tests ─────────────────────────────────────

from django.test import TestCase, override_settings
from alerts.services import check_thresholds
from sensors.models import Sensor, SensorReading


def make_threshold(param, warning, critical):
    return Threshold.objects.create(
        parameter=param,
        warning_limit=warning,
        critical_limit=critical,
    )


def make_fresh_sensor(code="SEN-SVC01"):
    return Sensor.objects.create(
        sensor_code=code,
        location="Service Test",
        status="active",
        installed_at="2025-01-01",
    )


def make_fresh_reading(sensor, pm25=10.0, pm10=20.0, temperature=25.0, humidity=50.0):
    return SensorReading.objects.create(
        sensor=sensor,
        pm25=pm25,
        pm10=pm10,
        temperature=temperature,
        humidity=humidity,
    )


@override_settings(ALERT_COOLDOWN_SECONDS=300)
class ThresholdCheckServiceTests(TestCase):
    """
    Unit tests for alerts.services.check_thresholds().
    Tests run directly against the service function — no HTTP layer.
    """

    def setUp(self):
        self.sensor = make_fresh_sensor("SEN-SVC01")
        # Standard WHO-adjacent thresholds
        self.pm25_threshold = make_threshold("pm25", warning=35.0, critical=75.0)
        self.pm10_threshold = make_threshold("pm10", warning=50.0, critical=100.0)

    # ── Normal readings ───────────────────────────────────────────────────────

    def test_normal_reading_creates_no_alerts(self):
        reading = make_fresh_reading(self.sensor, pm25=10.0, pm10=20.0)
        alerts = check_thresholds(reading)
        self.assertEqual(alerts, [])
        self.assertEqual(Alert.objects.count(), 0)

    # ── Warning level (MEDIUM severity) ──────────────────────────────────────

    def test_pm25_above_warning_creates_medium_alert(self):
        reading = make_fresh_reading(self.sensor, pm25=50.0)  # > 35 (warning), < 75 (critical)
        alerts = check_thresholds(reading)
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.severity, Alert.SEV_MEDIUM)
        self.assertEqual(alert.parameter, "pm25")
        self.assertEqual(alert.alert_type, Alert.TYPE_THRESHOLD)
        self.assertEqual(alert.status, Alert.STATUS_OPEN)
        self.assertEqual(alert.reading, reading)
        self.assertEqual(alert.sensor, self.sensor)

    # ── Critical level (HIGH severity) ───────────────────────────────────────

    def test_pm25_above_critical_creates_high_alert(self):
        reading = make_fresh_reading(self.sensor, pm25=150.0)  # > 75 (critical)
        alerts = check_thresholds(reading)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, Alert.SEV_HIGH)

    def test_pm10_above_critical_creates_high_alert(self):
        reading = make_fresh_reading(self.sensor, pm10=250.0)  # > 100 (critical)
        alerts = check_thresholds(reading)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, Alert.SEV_HIGH)
        self.assertEqual(alerts[0].parameter, "pm10")

    # ── Multiple parameters breached simultaneously ───────────────────────────

    def test_multiple_params_breached_creates_multiple_alerts(self):
        """Both PM2.5 and PM10 above warning → 2 alerts in one call."""
        reading = make_fresh_reading(self.sensor, pm25=50.0, pm10=80.0)
        alerts = check_thresholds(reading)
        self.assertEqual(len(alerts), 2)
        params = {a.parameter for a in alerts}
        self.assertIn("pm25", params)
        self.assertIn("pm10", params)

    # ── Deduplication ─────────────────────────────────────────────────────────

    @override_settings(ALERT_COOLDOWN_SECONDS=300)
    def test_duplicate_alert_suppressed_within_cooldown(self):
        """
        Two consecutive spike readings → only 1 alert (not 2).
        Second call is within the 300s cooldown window.
        """
        r1 = make_fresh_reading(self.sensor, pm25=150.0)
        alerts_1 = check_thresholds(r1)
        self.assertEqual(len(alerts_1), 1)

        r2 = make_fresh_reading(self.sensor, pm25=160.0)
        alerts_2 = check_thresholds(r2)
        self.assertEqual(len(alerts_2), 0)  # suppressed

        self.assertEqual(Alert.objects.count(), 1)

    @override_settings(ALERT_COOLDOWN_SECONDS=0)
    def test_cooldown_zero_allows_consecutive_alerts(self):
        """With cooldown=0, every breach creates an alert."""
        r1 = make_fresh_reading(self.sensor, pm25=150.0)
        check_thresholds(r1)
        r2 = make_fresh_reading(self.sensor, pm25=160.0)
        check_thresholds(r2)
        self.assertEqual(Alert.objects.count(), 2)

    # ── No threshold configured ───────────────────────────────────────────────

    def test_no_threshold_for_param_creates_no_alert(self):
        """Temperature spiking with no Threshold configured → no alert."""
        reading = make_fresh_reading(self.sensor, temperature=60.0)  # extreme heat
        alerts = check_thresholds(reading)
        # Only pm25/pm10 thresholds are configured in setUp.
        # Temperature has no threshold → engine should skip it.
        temp_alerts = [a for a in alerts if a.parameter == "temperature"]
        self.assertEqual(temp_alerts, [])

    def test_no_thresholds_at_all_returns_empty(self):
        """If Threshold table is empty, check_thresholds returns []."""
        Threshold.objects.all().delete()
        reading = make_fresh_reading(self.sensor, pm25=500.0)
        alerts = check_thresholds(reading)
        self.assertEqual(alerts, [])

    # ── API integration: POST reading → alerts auto-created ──────────────────

    def test_post_reading_via_api_triggers_alert(self):
        """
        Integration test: POST /readings/ with spiked PM2.5 →
        the reading is saved AND an alert is auto-created in the same request.
        """
        from django.contrib.auth import get_user_model
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient

        User = get_user_model()
        user = User.objects.create_user(
            username="svc_int", password="testpass", role="user"
        )
        token, _ = Token.objects.get_or_create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        payload = {
            "sensor": self.sensor.pk,
            "pm25": 200.0,   # >> critical_limit=75
            "pm10": 20.0,
            "temperature": 25.0,
            "humidity": 50.0,
        }
        resp = client.post("/api/v1/readings/", payload, format="json")
        self.assertEqual(resp.status_code, 201)

        # Alert must have been created automatically
        self.assertEqual(Alert.objects.count(), 1)
        alert = Alert.objects.first()
        self.assertEqual(alert.parameter, "pm25")
        self.assertEqual(alert.severity, Alert.SEV_HIGH)
        self.assertEqual(alert.alert_type, Alert.TYPE_THRESHOLD)
