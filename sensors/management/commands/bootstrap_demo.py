"""
sensors/management/commands/bootstrap_demo.py
=============================================
Idempotent bootstrap command for initial environment and demo provisioning.

Provisions:
  1. The 'simulator' service account (role='service') with scoped sensor-creation permissions.
  2. A DRF auth Token for the simulator user (printed as SIMULATOR_TOKEN=<key>).
  3. Pre-creates 5 demo sensors directly via the ORM using preset Indian city coordinates
     so the dashboard displays sensors immediately upon deployment.

Idempotency:
  Safe to run repeatedly during deployment (e.g. in build.sh). Existing records
  are updated/preserved without duplication.
"""

import os
import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework.authtoken.models import Token

from sensors.models import Sensor

DEMO_LOCATIONS = [
    ("Kolkata Park Street", 22.5535, 88.3519),
    ("Delhi Connaught Place", 28.6315, 77.2167),
    ("Mumbai Bandra", 19.0596, 72.8295),
    ("Bengaluru Indiranagar", 12.9784, 77.6408),
    ("Hyderabad Hitech City", 17.4435, 78.3772),
]


class Command(BaseCommand):
    help = "Idempotently provision the simulator service account, DRF auth token, and demo sensors."

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
            if s_created:
                created_count += 1
            else:
                existing_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"[bootstrap_demo] Completed: {created_count} sensors created, "
                f"{existing_count} existing sensors preserved."
            )
        )
