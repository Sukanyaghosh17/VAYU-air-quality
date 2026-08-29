"""
sensors/tests.py — DRF APITestCase suite for sensors and readings
=================================================================
Tests use Django's test database (separate from vayu_db) so they are safe
to run in any environment without touching production data.

Fixtures are created inline via the ORM — no JSON fixtures so the tests
remain refactor-friendly.

Token auth is used throughout (not session) because that is the auth path
the Phase 3 simulator will use — ensuring tests cover the real code path.
"""

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from rest_framework import status
from django.utils import timezone
from datetime import timedelta

from sensors.models import Sensor, SensorReading

User = get_user_model()


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_user(username, role="user", password="testpass123"):
    u = User.objects.create_user(username=username, password=password, role=role)
    token, _ = Token.objects.get_or_create(user=u)
    return u, token.key


def make_sensor(code="SEN-T01", location="Test Lab", status_="active"):
    return Sensor.objects.create(
        sensor_code=code,
        location=location,
        status=status_,
        installed_at="2025-01-01",
    )


def make_reading(sensor, pm25=10.0, pm10=20.0, temperature=25.0, humidity=50.0):
    return SensorReading.objects.create(
        sensor=sensor,
        pm25=pm25,
        pm10=pm10,
        temperature=temperature,
        humidity=humidity,
    )


# ── SensorViewSet tests ───────────────────────────────────────────────────────

class SensorAPITests(APITestCase):
    def setUp(self):
        self.admin, self.admin_token = make_user("admin_user", role="admin")
        self.user, self.user_token = make_user("regular_user", role="user")
        self.sensor = make_sensor()
        self.list_url = "/api/v1/sensors/"

    def auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def test_list_authenticated(self):
        self.auth(self.user_token)
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_list_unauthenticated_denied(self):
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_as_admin(self):
        self.auth(self.admin_token)
        payload = {
            "sensor_code": "SEN-T02",
            "location": "Roof",
            "status": "active",
            "installed_at": "2025-06-01",
        }
        resp = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["sensor_code"], "SEN-T02")

    def test_create_as_non_admin_forbidden(self):
        self.auth(self.user_token)
        payload = {
            "sensor_code": "SEN-T03",
            "location": "Basement",
            "status": "active",
            "installed_at": "2025-06-01",
        }
        resp = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_retrieve(self):
        self.auth(self.user_token)
        resp = self.client.get(f"{self.list_url}{self.sensor.pk}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["sensor_code"], self.sensor.sensor_code)

    def test_reading_count_annotated(self):
        make_reading(self.sensor)
        make_reading(self.sensor)
        self.auth(self.user_token)
        resp = self.client.get(f"{self.list_url}{self.sensor.pk}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["reading_count"], 2)


# ── SensorReadingViewSet tests ────────────────────────────────────────────────

class SensorReadingAPITests(APITestCase):
    def setUp(self):
        self.admin, self.admin_token = make_user("admin2", role="admin")
        self.simulator, self.sim_token = make_user("simulator", role="user")
        self.sensor = make_sensor("SEN-R01")
        self.list_url = "/api/v1/readings/"

    def auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def test_create_as_simulator_user(self):
        """Non-admin simulator user must be able to POST readings."""
        self.auth(self.sim_token)
        payload = {
            "sensor": self.sensor.pk,
            "pm25": 12.5,
            "pm10": 25.0,
            "temperature": 28.0,
            "humidity": 60.0,
        }
        resp = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["sensor_code"], self.sensor.sensor_code)

    def test_create_unauthenticated_denied(self):
        payload = {
            "sensor": self.sensor.pk,
            "pm25": 12.5,
            "pm10": 25.0,
            "temperature": 28.0,
            "humidity": 60.0,
        }
        resp = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_returns_200(self):
        make_reading(self.sensor)
        self.auth(self.sim_token)
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_filter_by_sensor(self):
        other_sensor = make_sensor("SEN-R02")
        make_reading(self.sensor, pm25=5.0)
        make_reading(other_sensor, pm25=99.0)
        self.auth(self.sim_token)
        resp = self.client.get(self.list_url, {"sensor": self.sensor.pk})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [r["sensor"] for r in resp.data["results"]]
        self.assertTrue(all(i == self.sensor.pk for i in ids))

    def test_put_returns_405(self):
        """
        Readings are immutable — PUT must be rejected with 405.

        We authenticate as admin to ensure DRF reaches the method-not-allowed
        check rather than short-circuiting with a permission 403 first.
        """
        reading = make_reading(self.sensor)
        self.auth(self.admin_token)  # admin bypasses permission gate → hits method gate
        resp = self.client.put(f"{self.list_url}{reading.pk}/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_latest_returns_one_per_sensor(self):
        sensor2 = make_sensor("SEN-R03")
        make_reading(self.sensor)
        make_reading(self.sensor, pm25=99.0)  # newer
        make_reading(sensor2)
        self.auth(self.sim_token)
        resp = self.client.get(f"{self.list_url}latest/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # One row per sensor
        sensor_codes = [r["sensor_code"] for r in resp.data]
        self.assertEqual(len(sensor_codes), len(set(sensor_codes)))

    def test_history_24h(self):
        make_reading(self.sensor)
        self.auth(self.sim_token)
        resp = self.client.get(
            f"{self.list_url}history/",
            {"sensor": self.sensor.pk, "range": "24h"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsInstance(resp.data, list)

    def test_history_7d(self):
        make_reading(self.sensor)
        self.auth(self.sim_token)
        resp = self.client.get(
            f"{self.list_url}history/",
            {"sensor": self.sensor.pk, "range": "7d"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_history_30d(self):
        make_reading(self.sensor)
        self.auth(self.sim_token)
        resp = self.client.get(
            f"{self.list_url}history/",
            {"sensor": self.sensor.pk, "range": "30d"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_history_missing_sensor_param(self):
        self.auth(self.sim_token)
        resp = self.client.get(f"{self.list_url}history/", {"range": "24h"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_history_invalid_range(self):
        self.auth(self.sim_token)
        resp = self.client.get(
            f"{self.list_url}history/",
            {"sensor": self.sensor.pk, "range": "99y"},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pagination_page_size(self):
        """With >50 readings, a second page must exist."""
        for i in range(55):
            make_reading(self.sensor, pm25=float(i))
        self.auth(self.sim_token)
        resp = self.client.get(self.list_url, {"sensor": self.sensor.pk})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 50)
        self.assertIsNotNone(resp.data["next"])
