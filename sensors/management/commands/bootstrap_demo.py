"""
sensors/management/commands/bootstrap_demo.py
=============================================
Idempotent bootstrap command for initial environment and demo provisioning.

Provisions:
  1. The 'simulator' service account (role='service') with scoped sensor-creation permissions.
  2. A DRF auth Token for the simulator user (printed as SIMULATOR_TOKEN=<key>).
  3. Pre-creates 5 demo sensors directly via the ORM using preset Indian city coordinates
     so the dashboard displays sensors immediately upon deployment.
  4. Seeds 48 hours of realistic demo readings (one per hour per sensor) so that the
     fleet view and trend charts are populated on first deploy without needing the
     external simulator to run first.

Idempotency:
  Safe to run repeatedly during deployment (e.g. in build.sh). Existing records
  are updated/preserved without duplication.  Readings are only seeded when a
  sensor has fewer than MIN_DEMO_READINGS rows, so repeated deploys do not
  create duplicate data.
"""

import math
import os
import random
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework.authtoken.models import Token

from sensors.models import Sensor, SensorReading

DEMO_LOCATIONS = [
    ("Kolkata Park Street",     22.5535, 88.3519),
    ("Delhi Connaught Place",   28.6315, 77.2167),
    ("Mumbai Bandra",           19.0596, 72.8295),
    ("Bengaluru Indiranagar",   12.9784, 77.6408),
    ("Hyderabad Hitech City",   17.4435, 78.3772),
]

# Realistic baseline AQI values per sensor code (µg/m³)
# Keyed by sensor_code (not location) so the lookup is stable regardless of
# what location string was written to the DB by any previous bootstrap version.
_SENSOR_BASELINES = {
    "SIM-001": {"pm25": 65.0, "pm10": 110.0, "temperature": 30.0, "humidity": 72.0},  # Kolkata
    "SIM-002": {"pm25": 90.0, "pm10": 150.0, "temperature": 32.0, "humidity": 55.0},  # Delhi
    "SIM-003": {"pm25": 45.0, "pm10": 80.0,  "temperature": 29.0, "humidity": 78.0},  # Mumbai
    "SIM-004": {"pm25": 35.0, "pm10": 65.0,  "temperature": 25.0, "humidity": 60.0},  # Bengaluru
    "SIM-005": {"pm25": 50.0, "pm10": 90.0,  "temperature": 31.0, "humidity": 52.0},  # Hyderabad
}

# Seed 48 hourly readings; only insert when sensor has fewer than this many rows
MIN_DEMO_READINGS = 36

# IST is UTC+5:30; we use +5.5 hours offset when converting UTC timestamps to local
# hour-of-day for the diurnal modulation so that readings look realistic
# regardless of what UTC time the deployment runs.
_IST_OFFSET_HOURS = 5.5


def _noisy(base: float, pct: float = 0.15) -> float:
    """Return base ± pct*base with a sinusoidal time-of-day modulation."""
    return max(0.0, base * (1.0 + random.uniform(-pct, pct)))


def _seed_readings(sensor: Sensor, baselines: dict, num_hours: int = 48) -> int:
    """
    Insert `num_hours` hourly SensorReading rows for `sensor`.

    `baselines` must be a dict with keys: pm25, pm10, temperature, humidity.
    Keyed by sensor_code at the call site so the lookup is always correct.

    Each reading uses a realistic sinusoidal diurnal pattern in IST local time
    (UTC+5:30) so the modulation is realistic regardless of deployment timezone.
    The most recent reading (h=1) is pinned to diurnal >= 1.0 (never below the
    raw baseline). All readings are floored at 60% of the city baseline to
    prevent sub-realistic PM values from a trough + negative noise combo.

    Returns the number of rows created.
    """
    now = timezone.now().replace(minute=0, second=0, microsecond=0)
    readings = []
    for h in range(num_hours, 0, -1):
        ts = now - timedelta(hours=h)
        # Convert UTC timestamp to approximate IST hour for the diurnal curve
        ist_hour = (ts.hour + _IST_OFFSET_HOURS) % 24
        # Diurnal modulation: peak pollution at rush hours (8 am, 6 pm IST)
        # Uses a positive-biased sine so the minimum (at 2am IST) is ~0.75×
        # and the maximum (at 2pm IST) is ~1.25× the baseline.
        diurnal = 1.0 + 0.25 * math.sin(math.radians((ist_hour - 8) * 15))

        # Pin the most recent reading to a well-above-zero baseline
        # (diurnal minimum at ~2 AM IST = 0.75×) so the fleet view never
        # shows an unrealistically low AQI from a deployment that ran at
        # midnight IST.
        if h == 1:
            diurnal = max(diurnal, 1.0)   # never dip below the raw baseline

        pm25_val = round(_noisy(baselines["pm25"] * diurnal), 2)
        pm10_val = round(_noisy(baselines["pm10"] * diurnal), 2)

        # Hard floor: never let the reading drop below 60% of the city baseline.
        # This prevents edge cases (deep diurnal trough + negative noise) from
        # producing sub-realistic PM values that map to AQI < 50 for all cities.
        pm25_floor = baselines["pm25"] * 0.60
        pm10_floor = baselines["pm10"] * 0.60

        readings.append(SensorReading(
            sensor=sensor,
            pm25=max(pm25_val, pm25_floor),
            pm10=max(pm10_val, pm10_floor),
            temperature=round(_noisy(baselines["temperature"], pct=0.05), 2),
            humidity=round(_noisy(baselines["humidity"], pct=0.08), 2),
            timestamp=ts,
        ))

    SensorReading.objects.bulk_create(readings, ignore_conflicts=True)
    return len(readings)


class Command(BaseCommand):
    help = "Idempotently provision the simulator service account, DRF auth token, demo sensors, and seed demo readings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force-reseed",
            action="store_true",
            default=False,
            help=(
                "Delete all existing readings for the 5 demo sensors and re-seed "
                "them from scratch. Use when previously seeded readings have bad "
                "values (e.g. wrong diurnal timezone offset)."
            ),
        )

    def handle(self, *args, **options):
        User = get_user_model()

        # 1. Provision simulator user with scoped service role
        target_role = getattr(User, "ROLE_SERVICE", "service")
        user, created = User.objects.get_or_create(
            username="simulator",
            defaults={
                "role": target_role,
                "is_active": True,
            },
        )
        # Update existing user if previously created with legacy role='user'
        if user.role != target_role and not user.is_admin():
            user.role = target_role
            user.save(update_fields=["role"])
            self.stdout.write(self.style.SUCCESS(f"Updated user 'simulator' role to {target_role}"))

        # Set or update password
        env_password = os.environ.get("SIMULATOR_PASSWORD")
        if env_password:
            user.set_password(env_password)
            user.save(update_fields=["password"])
        elif created:
            random_pw = secrets.token_urlsafe(32)
            user.set_password(random_pw)
            user.save(update_fields=["password"])

        # 2. Get or create DRF Auth Token
        token, token_created = Token.objects.get_or_create(user=user)
        self.stdout.write(f"SIMULATOR_TOKEN={token.key}")

        # 3. Pre-create 5 demo sensors
        created_count = 0
        existing_count = 0
        today = timezone.now().date()

        sensors = []
        for idx, (loc, lat, lon) in enumerate(DEMO_LOCATIONS, start=1):
            code = f"SIM-{idx:03d}"
            sensor, s_created = Sensor.objects.get_or_create(
                sensor_code=code,
                defaults={
                    "location": loc,
                    "latitude": lat,
                    "longitude": lon,
                    "status": Sensor.STATUS_ACTIVE,
                    "installed_at": today,
                },
            )
            sensors.append(sensor)
            if s_created:
                created_count += 1
            else:
                existing_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"[bootstrap_demo] Sensors: {created_count} created, "
                f"{existing_count} existing preserved."
            )
        )

        # 4. Seed demo readings
        force = options.get("force_reseed", False)
        if force:
            deleted_total = 0
            for sensor in sensors:
                n, _ = SensorReading.objects.filter(sensor=sensor).delete()
                deleted_total += n
            self.stdout.write(
                self.style.WARNING(
                    f"[bootstrap_demo] --force-reseed: deleted {deleted_total} existing readings."
                )
            )

        total_seeded = 0
        for sensor in sensors:
            current_count = SensorReading.objects.filter(sensor=sensor).count()
            if current_count < MIN_DEMO_READINGS:
                # Look up baseline by sensor_code — always stable regardless of
                # what location string was saved by any previous bootstrap version.
                bl = _SENSOR_BASELINES.get(sensor.sensor_code, {
                    "pm25": 55.0, "pm10": 95.0, "temperature": 28.0, "humidity": 65.0,
                })
                seeded = _seed_readings(sensor, bl, num_hours=48)
                total_seeded += seeded
                self.stdout.write(
                    f"  Seeded {seeded} readings for {sensor.sensor_code} "
                    f"({sensor.location}) pm25_base={bl['pm25']}"
                )
            else:
                self.stdout.write(
                    f"  {sensor.sensor_code} already has {current_count} readings — skipping seed."
                )

        if total_seeded:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[bootstrap_demo] Seeded {total_seeded} demo readings total."
                )
            )
        else:
            self.stdout.write("[bootstrap_demo] All sensors have sufficient readings.")
