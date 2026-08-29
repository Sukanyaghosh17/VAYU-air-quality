"""
sensors/external_aqi.py — WAQI (World Air Quality Index) API client
====================================================================
Fetches real-time AQI, PM2.5, and PM10 from the nearest monitoring station
to a given (lat, lon) coordinate pair.

Design decisions
----------------
* Uses Django's cache framework (configured in settings.py) to store results
  for 15 minutes per normalised location string.  This prevents hammering
  WAQI on repeated searches for the same city.

* All network calls are wrapped in try/except with a 5-second timeout.
  A failing or slow WAQI API must never crash the endpoint or block the UI.

* The WAQI token is read from settings.WAQI_API_TOKEN (set via env var).
  If the token is empty, fetch_external_aqi() returns None immediately with
  a log warning — never crashes.

* The "geo:<lat>;<lon>" feed endpoint returns the nearest monitoring station.
  The response data.iaqi contains individual pollutant sub-indices; we
  extract pm25.v and pm10.v when available.

Public API
----------
  fetch_external_aqi(lat, lon, cache_key) -> dict | None

  Return dict shape (on success):
  {
    "source":       "external_waqi",
    "station_name": str,
    "aqi":          int | None,
    "category":     str,
    "pm25":         float | None,
    "pm10":         float | None,
    "temperature":  float | None,
    "humidity":     float | None,
    "dominant_pollutant": str | None,
    "updated_at":   str  (ISO timestamp from WAQI)
  }

  Returns None if:
  - WAQI_API_TOKEN is not configured.
  - The API call fails (network error, timeout).
  - The API response status != "ok".
  - No station is nearby (dominant_pollutant is sentinel "-").
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Optional

from django.conf import settings
from django.core.cache import cache

from .aqi import compute_aqi

logger = logging.getLogger(__name__)

WAQI_URL = "https://api.waqi.info/feed/geo:{lat};{lon}/?token={token}"
TIMEOUT_SECONDS = 5
CACHE_TTL = 60 * 15  # 15 minutes


def _safe_float(data: dict, key: str) -> Optional[float]:
    """Extract a float from a WAQI iaqi sub-dict, or None."""
    try:
        return float(data[key]["v"])
    except (KeyError, TypeError, ValueError):
        return None


def fetch_external_aqi(
    lat: float,
    lon: float,
    cache_key: str,
) -> Optional[dict]:
    """
    Fetch AQI data for (lat, lon) from WAQI, with 15-minute caching.

    Parameters
    ----------
    lat, lon   : Coordinates from Nominatim geocoding.
    cache_key  : Normalised string used as the Django cache key (e.g. the
                 lowercased, stripped location query).  The caller must
                 supply this so it matches the key used to check the cache
                 before calling this function.

    Returns
    -------
    dict (see module docstring) on success, None on any failure.
    """
    token = getattr(settings, "WAQI_API_TOKEN", "")
    if not token:
        logger.warning(
            "WAQI_API_TOKEN is not configured — external AQI lookup skipped. "
            "Set it in .env (see .env.example for instructions)."
        )
        return None

    # ── Check cache first ─────────────────────────────────────────────────────
    cached = cache.get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for location key %r", cache_key)
        return cached

    # ── Call WAQI API ─────────────────────────────────────────────────────────
    url = WAQI_URL.format(lat=lat, lon=lon, token=urllib.parse.quote(token))
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("WAQI API call failed for (%.4f, %.4f): %s", lat, lon, exc)
        return None

    if payload.get("status") != "ok":
        logger.info(
            "WAQI returned non-ok status for (%.4f, %.4f): %s",
            lat, lon, payload.get("status"),
        )
        return None

    data = payload.get("data", {})

    # Sentinel check: WAQI uses "-" as dominant pollutant when no nearby station
    if data.get("dominentpol") == "-" or not data:
        logger.info("WAQI: no nearby station for (%.4f, %.4f)", lat, lon)
        return None

    iaqi = data.get("iaqi", {})

    pm25 = _safe_float(iaqi, "pm25")
    pm10 = _safe_float(iaqi, "pm10")
    temperature = _safe_float(iaqi, "t")
    humidity = _safe_float(iaqi, "h")

    # Use our CPCB AQI calculator for consistency; fall back to WAQI's own value
    aqi_data = compute_aqi(pm25, pm10)
    aqi_value = aqi_data["aqi"]
    category = aqi_data["category"]

    # If our CPCB calc couldn't produce an AQI (both pm25/pm10 missing),
    # use WAQI's reported AQI directly
    if aqi_value is None:
        raw_aqi = data.get("aqi")
        if isinstance(raw_aqi, (int, float)):
            aqi_value = int(raw_aqi)
            category = aqi_data["category"]  # already "N/A"

    # Station name: WAQI nests it in city.name or station.name
    station_name = (
        data.get("city", {}).get("name")
        or data.get("station", {}).get("name")
        or "Unknown station"
    )

    # Updated timestamp
    updated_at = data.get("time", {}).get("iso", "")

    result = {
        "source":               "external_waqi",
        "station_name":         station_name,
        "aqi":                  aqi_value,
        "category":             category,
        "pm25":                 pm25,
        "pm10":                 pm10,
        "temperature":          temperature,
        "humidity":             humidity,
        "dominant_pollutant":   data.get("dominentpol"),
        "updated_at":           updated_at,
    }

    # ── Store in cache ────────────────────────────────────────────────────────
    cache.set(cache_key, result, CACHE_TTL)
    logger.debug("Cached WAQI result for key %r (TTL=%ds)", cache_key, CACHE_TTL)

    return result
