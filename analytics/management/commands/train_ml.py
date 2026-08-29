"""
analytics/management/commands/train_ml.py
==========================================
Management command: python manage.py train_ml

Trains one Isolation Forest model per active sensor using recent readings
from the database.  Models are saved to ML_MODELS_DIR (see settings.py).

Usage
-----
    # Train all active sensors (default)
    python manage.py train_ml

    # Train a specific sensor only
    python manage.py train_ml --sensor-id 3

    # Override the minimum-readings guard
    python manage.py train_ml --min-readings 50

    # Dry run — show what would be trained without writing files
    python manage.py train_ml --dry-run

Requirements
------------
  - The sensor simulator (Phase 3) must have posted at least ML_MIN_READINGS
    readings per sensor before a model can be trained.
  - scikit-learn and joblib must be installed (see requirements.txt).

Output
------
  Training each sensor prints a progress line.  The final summary reports
  how many models were trained vs skipped.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from analytics.ml import get_model_path, train_sensor_model
from sensors.models import Sensor, SensorReading


class Command(BaseCommand):
    help = "Train Isolation Forest ML anomaly-detection models, one per active sensor."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sensor-id",
            type=int,
            default=None,
            metavar="ID",
            help="Only train the model for this sensor ID.",
        )
        parser.add_argument(
            "--min-readings",
            type=int,
            default=None,
            metavar="N",
            help=(
                "Minimum number of readings required to train a model. "
                f"Defaults to settings.ML_MIN_READINGS ({settings.ML_MIN_READINGS})."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be done without actually training or saving models.",
        )

    def handle(self, *args, **options):
        min_readings: int = options["min_readings"] or settings.ML_MIN_READINGS
        sensor_id: int | None = options["sensor_id"]
        dry_run: bool = options["dry_run"]

        # ── Select sensors ────────────────────────────────────────────────────
        if sensor_id:
            sensors = Sensor.objects.filter(pk=sensor_id, status="active")
            if not sensors.exists():
                raise CommandError(
                    f"No active sensor found with id={sensor_id}."
                )
        else:
            sensors = Sensor.objects.filter(status="active").order_by("id")

        if not sensors.exists():
            self.stdout.write(self.style.WARNING("No active sensors found. Nothing to train."))
            return

        trained, skipped = 0, 0

        for sensor in sensors:
            count = SensorReading.objects.filter(sensor=sensor).count()

            if count < min_readings:
                self.stdout.write(
                    f"  SKIP  {sensor.sensor_code} (id={sensor.id}) — "
                    f"{count}/{min_readings} readings"
                )
                skipped += 1
                continue

            model_path = get_model_path(sensor.id)
            self.stdout.write(
                f"  TRAIN {sensor.sensor_code} (id={sensor.id}) — "
                f"{count} readings → {model_path}"
            )

            if dry_run:
                trained += 1
                continue

            readings = (
                SensorReading.objects
                .filter(sensor=sensor)
                .order_by("timestamp")
            )
            try:
                train_sensor_model(sensor.id, readings)
                trained += 1
                self.stdout.write(
                    self.style.SUCCESS(f"         ✓ saved {model_path.name}")
                )
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(
                    self.style.ERROR(f"         ✗ ERROR: {exc}")
                )
                skipped += 1

        # ── Summary ───────────────────────────────────────────────────────────
        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{prefix}Done: {trained} model(s) trained, {skipped} skipped."
            )
        )
