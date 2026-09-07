"""
sensors/geocoding.py — OpenStreetMap Nominatim geocoder
========================================================
Converts a free-text location query into (latitude, longitude).

Design decisions
----------------
* A built-in CITY_COORDS lookup table covers ~100 common Indian cities and
  towns.  Matching is case-insensitive on the stripped query.  A local hit
  skips the Nominatim network call entirely, which is critical on cloud
  deployments (Render, Heroku, etc.) where Nominatim frequently rate-limits
  or blocks requests originating from shared server IP ranges.

* Nominatim is the fallback for queries not in the built-in table.  Its
  usage policy requires a descriptive User-Agent string.  We use "VAYU-AQ/1.0"
  to identify the application.  Nominatim also asks that production apps cache
  results — see external_aqi.py for the 15-minute cache layer applied above this.

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


# ── Built-in city coordinate table ────────────────────────────────────────────
# Covers the most-searched Indian cities and towns.  Keys are lowercase
# stripped city names.  Values are (latitude, longitude) WGS-84 floats.
# A match here bypasses the Nominatim network call entirely, making city
# searches reliable on cloud deployments where Nominatim rate-limits
# requests from shared server IP addresses.
CITY_COORDS: dict[str, tuple[float, float]] = {
    # ── Metros ────────────────────────────────────────────────────────────────
    "delhi":            (28.6139, 77.2090),
    "new delhi":        (28.6139, 77.2090),
    "mumbai":           (19.0760, 72.8777),
    "bombay":           (19.0760, 72.8777),
    "kolkata":          (22.5726, 88.3639),
    "calcutta":         (22.5726, 88.3639),
    "chennai":          (13.0827, 80.2707),
    "madras":           (13.0827, 80.2707),
    "bengaluru":        (12.9716, 77.5946),
    "bangalore":        (12.9716, 77.5946),
    "hyderabad":        (17.3850, 78.4867),
    # ── Tier-2 cities ─────────────────────────────────────────────────────────
    "ahmedabad":        (23.0225, 72.5714),
    "pune":             (18.5204, 73.8567),
    "poona":            (18.5204, 73.8567),
    "surat":            (21.1702, 72.8311),
    "jaipur":           (26.9124, 75.7873),
    "lucknow":          (26.8467, 80.9462),
    "kanpur":           (26.4499, 80.3319),
    "nagpur":           (21.1458, 79.0882),
    "patna":            (25.5941, 85.1376),
    "indore":           (22.7196, 75.8577),
    "thane":            (19.2183, 72.9781),
    "bhopal":           (23.2599, 77.4126),
    "visakhapatnam":    (17.6868, 83.2185),
    "vizag":            (17.6868, 83.2185),
    "pimpri-chinchwad": (18.6279, 73.7997),
    "pimpri":           (18.6279, 73.7997),
    "vadodara":         (22.3072, 73.1812),
    "baroda":           (22.3072, 73.1812),
    "ludhiana":         (30.9010, 75.8573),
    "agra":             (27.1767, 78.0081),
    "nashik":           (19.9975, 73.7898),
    "faridabad":        (28.4089, 77.3178),
    "meerut":           (28.9845, 77.7064),
    "rajkot":           (22.3039, 70.8022),
    "varanasi":         (25.3176, 82.9739),
    "benares":          (25.3176, 82.9739),
    "srinagar":         (34.0836, 74.7973),
    "aurangabad":       (19.8762, 75.3433),
    "amritsar":         (31.6340, 74.8723),
    "allahabad":        (25.4358, 81.8463),
    "prayagraj":        (25.4358, 81.8463),
    "ranchi":           (23.3441, 85.3096),
    "howrah":           (22.5958, 88.2636),
    "coimbatore":       (11.0168, 76.9558),
    "jabalpur":         (23.1815, 79.9864),
    "gwalior":          (26.2183, 78.1828),
    "vijayawada":       (16.5062, 80.6480),
    "jodhpur":          (26.2389, 73.0243),
    "madurai":          (9.9252, 78.1198),
    "raipur":           (21.2514, 81.6296),
    "kota":             (25.2138, 75.8648),
    "guwahati":         (26.1445, 91.7362),
    "chandigarh":       (30.7333, 76.7794),
    "solapur":          (17.6805, 75.9064),
    "hubballi":         (15.3647, 75.1240),
    "hubli":            (15.3647, 75.1240),
    "mysuru":           (12.2958, 76.6394),
    "mysore":           (12.2958, 76.6394),
    "tiruchirappalli":  (10.7905, 78.7047),
    "trichy":           (10.7905, 78.7047),
    "bareilly":         (28.3670, 79.4304),
    "aligarh":          (27.8974, 78.0880),
    "moradabad":        (28.8389, 78.7769),
    "gurgaon":          (28.4595, 77.0266),
    "gurugram":         (28.4595, 77.0266),
    "noida":            (28.5355, 77.3910),
    "jalandhar":        (31.3260, 75.5762),
    "bhubaneswar":      (20.2961, 85.8245),
    "cuttack":          (20.4625, 85.8830),
    "dehradun":         (30.3165, 78.0322),
    "shimla":           (31.1048, 77.1734),
    "simla":            (31.1048, 77.1734),
    "jammu":            (32.7266, 74.8570),
    "mangaluru":        (12.9141, 74.8560),
    "mangalore":        (12.9141, 74.8560),
    "thiruvananthapuram": (8.5241, 76.9366),
    "trivandrum":       (8.5241, 76.9366),
    "kochi":            (9.9312, 76.2673),
    "cochin":           (9.9312, 76.2673),
    "kozhikode":        (11.2588, 75.7804),
    "calicut":          (11.2588, 75.7804),
    "thrissur":         (10.5276, 76.2144),
    "alappuzha":        (9.4981, 76.3388),
    "alleppey":         (9.4981, 76.3388),
    "kollam":           (8.8932, 76.6141),
    "navi mumbai":      (19.0330, 73.0297),
    "puducherry":       (11.9416, 79.8083),
    "pondicherry":      (11.9416, 79.8083),
    "ajmer":            (26.4499, 74.6399),
    "bilaspur":         (22.0796, 82.1391),
    "warangal":         (17.9784, 79.5941),
    "guntur":           (16.3067, 80.4365),
    "nellore":          (14.4426, 79.9865),
    "kakinada":         (16.9891, 82.2475),
    "tirupati":         (13.6288, 79.4192),
    "siliguri":         (26.7271, 88.3953),
    "durgapur":         (23.5204, 87.3119),
    "asansol":          (23.6889, 86.9661),
    "dhanbad":          (23.7957, 86.4304),
    "bokaro":           (23.6693, 86.1511),
    "jamshedpur":       (22.8046, 86.2029),
    "gorakhpur":        (26.7606, 83.3732),
    "agartala":         (23.8315, 91.2868),
    "imphal":           (24.8170, 93.9368),
    "shillong":         (25.5788, 91.8933),
    "aizawl":           (23.7271, 92.7176),
    "itanagar":         (27.0844, 93.6053),
    "kohima":           (25.6751, 94.1086),
    "panaji":           (15.4909, 73.8278),
    "goa":              (15.2993, 74.1240),
    "panjim":           (15.4909, 73.8278),
    "rishikesh":        (30.0869, 78.2676),
    "haridwar":         (29.9457, 78.1642),
    "mathura":          (27.4924, 77.6737),
    "vrindavan":        (27.5794, 77.6964),
    "udaipur":          (24.5854, 73.7125),
    "jaisalmer":        (26.9157, 70.9083),
    "bikaner":          (28.0229, 73.3119),
    "alwar":            (27.5530, 76.6346),
    "bharatpur":        (27.2152, 77.5030),
    "puri":             (19.8135, 85.8312),
    "arambagh":         (22.8810, 87.7855),
    "haldia":           (22.0667, 88.0698),
    "kharagpur":        (22.3460, 87.2320),
    "midnapore":        (22.4222, 87.3197),
    "bardhaman":        (23.2324, 87.8615),
    "burdwan":          (23.2324, 87.8615),
}


def geocode(query: str) -> Optional[tuple[float, float]]:
    """
    Geocode a free-text location name to (latitude, longitude).

    Resolution order
    ----------------
    1. Built-in CITY_COORDS table (case-insensitive exact match on stripped query).
       This is the fast path — no network call, no rate-limit risk.
    2. OpenStreetMap Nominatim API (fallback for queries not in the table).

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
    # ── Step 1: built-in lookup (fast path, no network) ───────────────────────
    key = query.strip().lower()
    if key in CITY_COORDS:
        lat, lon = CITY_COORDS[key]
        logger.debug("geocode %r → built-in table (%.4f, %.4f)", query, lat, lon)
        return lat, lon

    # ── Step 2: Nominatim fallback ────────────────────────────────────────────
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

    logger.debug("Geocoded %r → Nominatim (%.4f, %.4f)", query, lat, lon)
    return lat, lon
