"""
sensors/geocoding.py — OpenStreetMap Nominatim geocoder
========================================================
Converts a free-text location query into (latitude, longitude).

Design decisions
----------------
* Nominatim is free and requires no API key, but its usage policy requires
  a descriptive User-Agent string.  We use "VAYU-AQ/1.0" to identify the
  application.  Nominatim also asks that production apps cache results —
  see external_aqi.py for the 15-minute cache layer applied above this.

* Timeout is hard-capped at 5 seconds.  A slow Nominatim response must
  never hang the user's dashboard search.

* On any error (network, timeout, bad JSON, empty result) this module
  returns None rather than raising.  The caller decides whether to show
  a 404 or continue with cached data.

Public API
----------
  geocode(query: str) -> tuple[float, float] | None
    Returns (lat, lon) as floats, or None on any failure.

  GeocodingError — raised only by internal helpers; caught here before
    being converted to a None return value.
"""

from __future__ import annotations

import logging
from typing import Optional

import urllib.request
import urllib.parse
import json

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "VAYU-AQ/1.0 (air-quality-monitoring; contact=admin@vayu.local)"
TIMEOUT_SECONDS = 5


def geocode(query: str) -> Optional[tuple[float, float]]:
    """
    Geocode a free-text location name via OpenStreetMap Nominatim.

    Parameters
    ----------
    query : str
        City/town name or any address fragment (e.g. "Kolkata", "Arambagh").

    Returns
    -------
    (lat, lon) tuple of floats, or None if:
    - The query returned no results.
    - Any network error, timeout, or JSON parse error occurred.

    Caching
    -------
    This function does NOT cache internally.  Caching is done by the
    caller (external_aqi.py / LocationSearchView) to keep this module
    pure and testable.
    """
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "limit": 1,
    })
    url = f"{NOMINATIM_URL}?{params}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("Nominatim geocode failed for %r: %s", query, exc)
        return None

    if not data:
        logger.debug("Nominatim returned no results for %r", query)
        return None

    try:
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
    except (KeyError, ValueError, IndexError) as exc:
        logger.warning("Nominatim response parse error for %r: %s", query, exc)
        return None

    logger.debug("Geocoded %r → (%.4f, %.4f)", query, lat, lon)
    return lat, lon
