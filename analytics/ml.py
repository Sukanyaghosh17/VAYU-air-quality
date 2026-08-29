"""
analytics/ml.py — Isolation Forest anomaly detection
=====================================================
Two public functions:

  train_sensor_model(sensor_id, readings)
    Builds a feature matrix from a queryset of SensorReading rows, fits an
    Isolation Forest, and persists it to disk at ML_MODELS_DIR/sensor_<id>.joblib.
    Called by: `python manage.py train_ml`

  score_reading(reading) -> (is_anomaly: bool, score: float)
    Loads the saved model for the reading's sensor, engineers features for
    the single reading (with rolling context from the DB), and returns
    whether the reading is flagged as an anomaly together with the raw
    decision-function score (lower = more anomalous).
    Called by: SensorReadingViewSet.perform_create()

Feature engineering
-------------------
For each reading we build an 8-dimensional vector:

  [pm25, pm10, temperature, humidity,                ← raw values (4)
   pm25_roll_mean, pm10_roll_mean,                   ← rolling means (4)
   temperature_roll_mean, humidity_roll_mean]

Rolling stats use the previous ML_ROLLING_WINDOW readings for that sensor,
ordered by timestamp descending (newest first, then reversed for the mean).
For the very first readings (cold start) the rolling mean falls back to the
raw value, so the feature vector is always complete.

Model persistence
-----------------
One file per sensor: <ML_MODELS_DIR>/sensor_<id>.joblib
ML_MODELS_DIR is configured in vayu/settings.py.
The directory is created automatically on first save.

Cold-start guard
----------------
score_reading() returns (False, 0.0) immediately when no model file exists
for the sensor.  This is the expected state for Phase 2–4 and is fine.
Phase 5 scoring only kicks in after `python manage.py train_ml` has been run.
"""

import logging
from pathlib import Path

import joblib
import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)

# ── Feature definition ────────────────────────────────────────────────────────

FEATURES = ("pm25", "pm10", "temperature", "humidity")
N_FEATURES = len(FEATURES) * 2  # raw + rolling mean = 8


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_model_path(sensor_id: int) -> Path:
    """Return the joblib file path for a given sensor."""
    return Path(settings.ML_MODELS_DIR) / f"sensor_{sensor_id}.joblib"


def _rolling_means(readings: list, window: int) -> list[float]:
    """
    Compute per-feature rolling means from a list of SensorReading objects.
    Readings should be ordered oldest→newest (training) or newest→oldest (scoring).
    If the list is empty, returns zeros — the caller should substitute raw values.
    """
    if not readings:
        return [0.0] * len(FEATURES)
    tail = readings[-window:] if len(readings) > window else readings
    return [float(np.mean([getattr(r, f) for r in tail])) for f in FEATURES]


def _build_row(reading, recent_readings: list) -> list[float]:
    """
    Build one 8-feature row for `reading`, given a list of preceding readings
    (used to compute rolling means).  Falls back to raw value when no
    preceding readings exist (handles cold-start cleanly).
    """
    raw = [float(getattr(reading, f)) for f in FEATURES]
    window = getattr(settings, "ML_ROLLING_WINDOW", 6)
    # Cold-start: no preceding readings → use raw values as rolling means too.
    # _rolling_means() always returns a list (never raises), so we must guard
    # on recent_readings being empty rather than on the returned list.
    if not recent_readings:
        means = raw[:]
    else:
        means = _rolling_means(recent_readings, window)
    return raw + means


# ── Training ──────────────────────────────────────────────────────────────────

def train_sensor_model(sensor_id: int, readings) -> Path:
    """
    Train and persist an Isolation Forest model for one sensor.

    Parameters
    ----------
    sensor_id : int
    readings  : iterable of SensorReading, ordered by timestamp ascending

    Returns
    -------
    Path  — path to the saved model file
    """
    from sklearn.ensemble import IsolationForest  # lazy import — not needed at startup

    reading_list = list(readings)
    if not reading_list:
        raise ValueError(f"No readings provided for sensor {sensor_id}")

    window = getattr(settings, "ML_ROLLING_WINDOW", 6)
    X = []
    for i, reading in enumerate(reading_list):
        recent = reading_list[max(0, i - window): i]
        X.append(_build_row(reading, recent))

    X_arr = np.array(X, dtype=float)
    model = IsolationForest(
        n_estimators=100,
        contamination=0.05,   # assume 5 % of training data are anomalies
        random_state=42,
    )
    model.fit(X_arr)

    model_path = get_model_path(sensor_id)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    logger.info(
        "ML model trained for sensor %d (%d readings) → %s",
        sensor_id, len(reading_list), model_path,
    )
    return model_path


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_reading(reading) -> tuple[bool, float]:
    """
    Score a single SensorReading using the sensor's Isolation Forest.

    Returns
    -------
    (is_anomaly: bool, score: float)
      is_anomaly — True when Isolation Forest predicts -1 (outlier)
      score      — raw decision_function value; more negative = more anomalous.
                   0.0 when no model exists (cold-start).

    Behaviour when no model exists
    --------------------------------
    Returns (False, 0.0) immediately.  This is the correct no-op behaviour
    before `train_ml` has been run for this sensor.
    """
    model_path = get_model_path(reading.sensor_id)
    if not model_path.exists():
        logger.debug("No ML model for sensor %d — skipping scoring.", reading.sensor_id)
        return False, 0.0

    model = joblib.load(model_path)

    # Fetch recent readings for rolling context (exclude the current reading)
    from sensors.models import SensorReading  # local to avoid circular import
    window = getattr(settings, "ML_ROLLING_WINDOW", 6)
    recent = list(
        SensorReading.objects
        .filter(sensor_id=reading.sensor_id)
        .exclude(pk=reading.pk)
        .order_by("-timestamp")[:window]
    )
    recent.reverse()  # oldest → newest for _rolling_means

    X = np.array([_build_row(reading, recent)], dtype=float)
    prediction = int(model.predict(X)[0])          # -1 anomaly, +1 normal
    score = float(model.score_samples(X)[0])       # lower = more anomalous

    return prediction == -1, score
