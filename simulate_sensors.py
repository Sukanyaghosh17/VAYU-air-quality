#!/usr/bin/env python
"""
simulate_sensors.py — VAYU Air-Quality Sensor Simulator
=========================================================
Standalone script (no Django import) that impersonates physical air-quality
sensors by POSTing realistic readings to the VAYU REST API.

Usage
-----
    python simulate_sensors.py [OPTIONS]

    # Quickstart (reads token from SIMULATOR_TOKEN env var):
    python simulate_sensors.py --sensors 3 --interval 3 --spike-rate 0.05

    # Explicit token + custom server:
    python simulate_sensors.py --token abc123 --url http://127.0.0.1:8000 \\
        --sensors 5 --interval 2 --spike-rate 0.1

    # Run against specific existing sensor IDs:
    python simulate_sensors.py --sensor-ids 1,2,3 --interval 5

Options
-------
    --url           Base URL of the VAYU server  (default: http://127.0.0.1:8000)
    --token         API token for the simulator user.
                    Falls back to SIMULATOR_TOKEN env var.
    --sensors N     Number of sensors to simulate. If fewer active sensors exist
                    in the DB, new ones are created automatically. (default: 3)
    --sensor-ids    Comma-separated list of specific sensor IDs to simulate.
                    Overrides --sensors.
    --interval SEC  Seconds between reading batches. (default: 3)
    --spike-rate F  Probability [0–1] that any individual reading is a spike.
                    (default: 0.05 = 5 %)
    --duration SEC  Run for this many seconds then exit. Omit to run forever.
    --no-create     Do not create new sensors; fail if fewer than --sensors exist.

Data Generation
---------------
Readings are sampled from Gaussian distributions around real-world baselines:

  Parameter   Baseline (mean ± std)   Spike multiplier / delta
  ─────────   ────────────────────    ────────────────────────
  PM2.5       15 ± 5  µg/m³           ×(6–14)  → 90–210 µg/m³
  PM10        30 ± 10 µg/m³           ×(5–12)  → 150–360 µg/m³
  Temperature 25 ± 3  °C              +(10–20) °C
  Humidity    55 ± 10 %               push to 88–99 %

Spikes are injected independently per parameter so mixed anomalies
(only PM25 spiking while temperature is normal) are possible.

Authentication
--------------
Uses DRF Token auth.  Set up the simulator user once:

    python manage.py shell -c "
    import environ; from pathlib import Path
    from django.contrib.auth import get_user_model
    from rest_framework.authtoken.models import Token
    env = environ.Env(); environ.Env.read_env(Path('.env'))
    User = get_user_model()
    u, _ = User.objects.get_or_create(username='simulator', defaults={'role': 'user'})
    u.set_password(env('SIMULATOR_PASSWORD')); u.save()
    t, _ = Token.objects.get_or_create(user=u)
    print('Token:', t.key)
    "

Then set SIMULATOR_TOKEN=<key> in .env or pass --token <key>.
"""

import argparse
import os
import random
import signal
import sys
import time
from datetime import date

import numpy as np
import requests

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_URL = "http://127.0.0.1:8000"
DEFAULT_SENSORS = 3
DEFAULT_INTERVAL = 3
DEFAULT_SPIKE_RATE = 0.05

# Baseline distributions: (mean, std, hard_min, hard_max)
BASELINES = {
    "pm25":        (15.0,  5.0,  0.0,   500.0),
    "pm10":        (30.0, 10.0,  0.0,   600.0),
    "temperature": (25.0,  3.0, -20.0,   60.0),
    "humidity":    (55.0, 10.0,  0.0,   100.0),
}

# Spike injection: callables that take the baseline sample and return spiked value
SPIKE_FN = {
    "pm25":        lambda v: v * random.uniform(6.0, 14.0),
    "pm10":        lambda v: v * random.uniform(5.0, 12.0),
    "temperature": lambda v: v + random.uniform(10.0, 20.0),
    "humidity":    lambda _: random.uniform(88.0, 99.0),
}

# ── Signal handling ────────────────────────────────────────────────────────────

_running = True


def _handle_sigint(signum, frame):  # noqa: ARG001
    global _running
    print("\n[simulator] Ctrl+C received — shutting down gracefully …")
    _running = False


signal.signal(signal.SIGINT, _handle_sigint)

# ── Data generation ────────────────────────────────────────────────────────────


def generate_reading(spike_rate: float) -> dict:
    """
    Generate one set of air-quality measurements.

    Each parameter is sampled independently, so a single reading can have
    any combination of normal / spiked values.  This produces realistic
    partial-anomaly scenarios for testing the alert engine and ML scorer.
    """
    reading = {}
    for param, (mean, std, hard_min, hard_max) in BASELINES.items():
        # Sample from Gaussian baseline
        value = float(np.random.normal(mean, std))
        # Inject spike with probability spike_rate
        if random.random() < spike_rate:
            value = SPIKE_FN[param](value)
        # Clamp to physical limits
        value = max(hard_min, min(hard_max, value))
        reading[param] = round(value, 2)
    return reading


# ── API client ─────────────────────────────────────────────────────────────────


class VayuClient:
    """Thin HTTP client for the VAYU API using Token auth."""

    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Token {token}"})

    def _url(self, path: str) -> str:
        return f"{self.base}{path}"

    def list_sensors(self) -> list[dict]:
        """Return all active sensors."""
        resp = self.session.get(self._url("/api/v1/sensors/"), params={"page_size": 200})
        resp.raise_for_status()
        data = resp.json()
        # Handle both paginated (DRF default) and bare list responses
        sensors = data.get("results", data) if isinstance(data, dict) else data
        return [s for s in sensors if s.get("status") == "active"]

    def create_sensor(self, code: str, location: str) -> dict:
        payload = {
            "sensor_code": code,
            "location": location,
            "status": "active",
            "installed_at": date.today().isoformat(),
        }
        resp = self.session.post(self._url("/api/v1/sensors/"), json=payload)
        resp.raise_for_status()
        return resp.json()

    def post_reading(self, sensor_id: int, reading: dict) -> dict:
        payload = {"sensor": sensor_id, **reading}
        resp = self.session.post(self._url("/api/v1/readings/"), json=payload)
        resp.raise_for_status()
        return resp.json()


# ── Sensor provisioning ────────────────────────────────────────────────────────


def get_or_create_sensors(
    client: VayuClient,
    target_count: int,
    sensor_ids: list[int] | None,
    no_create: bool,
) -> list[dict]:
    """
    Return a list of sensor dicts to simulate.

    If --sensor-ids was passed, fetch only those sensors.
    Otherwise, ensure at least target_count active sensors exist,
    creating new ones if needed (unless --no-create).
    """
    if sensor_ids:
        all_sensors = client.list_sensors()
        id_set = set(sensor_ids)
        matched = [s for s in all_sensors if s["id"] in id_set]
        missing = id_set - {s["id"] for s in matched}
        if missing:
            print(f"[simulator] WARNING: sensor IDs not found or inactive: {missing}")
        return matched

    existing = client.list_sensors()
    if len(existing) >= target_count:
        return existing[:target_count]

    if no_create:
        print(
            f"[simulator] ERROR: only {len(existing)} active sensors exist "
            f"but --sensors={target_count} and --no-create is set."
        )
        sys.exit(1)

    needed = target_count - len(existing)
    print(f"[simulator] Creating {needed} new sensor(s) …")
    for i in range(needed):
        idx = len(existing) + i + 1
        code = f"SIM-{idx:03d}"
        loc = f"Simulated Location {idx}"
        new = client.create_sensor(code, loc)
        existing.append(new)
        print(f"[simulator]   Created {code} (id={new['id']})")

    return existing[:target_count]


# ── Main loop ─────────────────────────────────────────────────────────────────


def run(args: argparse.Namespace) -> None:
    token = args.token or os.environ.get("SIMULATOR_TOKEN", "")
    if not token:
        print(
            "[simulator] ERROR: No API token found.\n"
            "  Pass --token <key>  or  set SIMULATOR_TOKEN in .env\n"
            "  See README.md § Token Auth / Simulator User for setup steps."
        )
        sys.exit(1)

    client = VayuClient(base_url=args.url, token=token)

    # Verify connectivity
    try:
        sensors = get_or_create_sensors(
            client,
            target_count=args.sensors,
            sensor_ids=args.sensor_ids,
            no_create=args.no_create,
        )
    except requests.exceptions.ConnectionError:
        print(
            f"[simulator] ERROR: Cannot connect to {args.url}\n"
            "  Is the Django dev server running?  (python manage.py runserver)"
        )
        sys.exit(1)
    except requests.exceptions.HTTPError as exc:
        print(f"[simulator] ERROR: API returned {exc.response.status_code}: {exc.response.text}")
        sys.exit(1)

    if not sensors:
        print("[simulator] ERROR: No sensors to simulate. Create at least one sensor first.")
        sys.exit(1)

    print(
        f"[simulator] Starting — {len(sensors)} sensor(s), "
        f"interval={args.interval}s, spike_rate={args.spike_rate:.0%}"
    )
    for s in sensors:
        print(f"  • {s['sensor_code']} (id={s['id']}) — {s['location']}")
    print("[simulator] Press Ctrl+C to stop.\n")

    start_time = time.monotonic()
    cycle = 0

    while _running:
        # Check --duration limit
        if args.duration and (time.monotonic() - start_time) >= args.duration:
            print(f"[simulator] Duration limit ({args.duration}s) reached — stopping.")
            break

        cycle += 1
        batch_start = time.monotonic()
        spike_count = 0

        for sensor in sensors:
            reading = generate_reading(args.spike_rate)
            is_spike = any(
                reading[p] > BASELINES[p][0] * 3  # >3× baseline mean = spike indicator
                for p in ("pm25", "pm10")
            )
            if is_spike:
                spike_count += 1

            try:
                result = client.post_reading(sensor["id"], reading)
                flag = " ⚡SPIKE" if is_spike else ""
                print(
                    f"[cycle {cycle:04d}] {sensor['sensor_code']:10s} "
                    f"PM2.5={reading['pm25']:6.1f}  PM10={reading['pm10']:6.1f}  "
                    f"T={reading['temperature']:5.1f}°C  "
                    f"RH={reading['humidity']:5.1f}%  "
                    f"id={result['id']}{flag}"
                )
            except requests.exceptions.HTTPError as exc:
                print(
                    f"[cycle {cycle:04d}] {sensor['sensor_code']:10s} "
                    f"ERROR {exc.response.status_code}: {exc.response.text[:120]}"
                )
            except requests.exceptions.ConnectionError:
                print(f"[cycle {cycle:04d}] {sensor['sensor_code']:10s} ERROR: connection lost")

        # Sleep for the remainder of the interval
        elapsed = time.monotonic() - batch_start
        sleep_for = max(0.0, args.interval - elapsed)
        if sleep_for > 0 and _running:
            time.sleep(sleep_for)

    print(f"\n[simulator] Stopped after {cycle} cycle(s).")


# ── CLI ───────────────────────────────────────────────────────────────────────


def parse_sensor_ids(value: str) -> list[int]:
    try:
        return [int(x.strip()) for x in value.split(",") if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--sensor-ids must be comma-separated integers, got: {value!r}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VAYU sensor simulator — POSTs realistic air-quality readings to the API.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Base URL of the VAYU server.",
    )
    parser.add_argument(
        "--token",
        default="",
        help="DRF Token for the simulator user. Falls back to SIMULATOR_TOKEN env var.",
    )
    parser.add_argument(
        "--sensors",
        type=int,
        default=DEFAULT_SENSORS,
        metavar="N",
        help="Number of sensors to simulate (creates new ones if needed).",
    )
    parser.add_argument(
        "--sensor-ids",
        type=parse_sensor_ids,
        default=None,
        metavar="1,2,3",
        help="Comma-separated sensor IDs. Overrides --sensors.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        metavar="SEC",
        help="Seconds between reading batches.",
    )
    parser.add_argument(
        "--spike-rate",
        type=float,
        default=DEFAULT_SPIKE_RATE,
        metavar="F",
        help="Probability [0–1] that a reading is anomalous.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        metavar="SEC",
        help="Stop after this many seconds (omit to run forever).",
    )
    parser.add_argument(
        "--no-create",
        action="store_true",
        help="Do not create new sensors; fail if fewer than --sensors exist.",
    )

    args = parser.parse_args()

    if not (0.0 <= args.spike_rate <= 1.0):
        parser.error("--spike-rate must be between 0.0 and 1.0")
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.sensors < 1:
        parser.error("--sensors must be at least 1")

    run(args)


if __name__ == "__main__":
    main()
