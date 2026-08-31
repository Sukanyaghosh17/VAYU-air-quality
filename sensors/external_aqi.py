"""
sensors/external_aqi.py — Robust Multi-Step WAQI (World Air Quality Index) Client
==================================================================================
Fetches real-time AQI, PM2.5, and PM10 from public monitoring stations using a
resilient multi-step fallback chain:

Fallback Chain
--------------
1. Step A (Geo): Query WAQI geo:<lat>;<lon> endpoint directly.
2. Step B (Keyword): Query WAQI search API with the city name. Selects closest
   station name match or nearest geographical coordinate within 80km.
3. Step C (Keyword + Country): Query WAQI search API with "<query>, India" suffix.
   Validates name substring or proximity (<= 75km).
4. Step D (Regional Geo Proximity): Tests nearby regional coordinates (<= 75km)
   to discover regional monitoring stations for towns lacking local sensors.
5. Step E (Exhausted): Returns None if no station exists within range.

Design decisions
----------------
* Normalised response format across all fallback steps.
* 15-minute Django cache TTL keyed by normalised query or rounded coordinates.
* Server-side logging of which fallback step succeeded for analytics/observability.
* Network timeouts capped at 5 seconds per call.
"""

from __future__ import annotations

import json
import logging
import math
import urllib.parse
import urllib.request
from typing import Optional

from django.conf import settings
from django.core.cache import cache

from .aqi import compute_aqi

logger = logging.getLogger(__name__)

WAQI_GEO_URL = "https://api.waqi.info/feed/geo:{lat};{lon}/?token={token}"
WAQI_SEARCH_URL = "https://api.waqi.info/search/?keyword={keyword}&token={token}"
WAQI_FEED_UID_URL = "https://api.waqi.info/feed/@{uid}/?token={token}"

TIMEOUT_SECONDS = 5
CACHE_TTL = 60 * 15  # 15 minutes


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers between two coordinates."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _safe_float(data: dict, key: str) -> Optional[float]:
    """Extract a float from a WAQI iaqi sub-dict, or None."""
    try:
        return float(data[key]["v"])
    except (KeyError, TypeError, ValueError):
        return None


def _fetch_waqi_json(url: str) -> Optional[dict]:
    """Perform HTTP GET against WAQI API and return json payload if status is ok."""
    req = urllib.request.Request(url, headers={"User-Agent": "VAYU-AirQuality/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("status") == "ok":
                return payload.get("data")
            logger.debug("WAQI non-ok response for %s: %s", url, payload.get("data"))
    except Exception as exc:
        logger.warning("WAQI API request failed for %s: %s", url, exc)
    return None


def _parse_waqi_feed(
    data: dict,
    fallback_step: str,
    distance_km: Optional[float] = None,
) -> Optional[dict]:
    """Convert raw WAQI feed data into standardized dictionary response."""
    if not isinstance(data, dict):
        return None

    # Sentinel check: WAQI uses "-" as dominant pollutant when no nearby station
    if data.get("dominentpol") == "-":
        return None

    iaqi = data.get("iaqi", {})
    pm25 = _safe_float(iaqi, "pm25")
    pm10 = _safe_float(iaqi, "pm10")
    temperature = _safe_float(iaqi, "t")
    humidity = _safe_float(iaqi, "h")

    aqi_data = compute_aqi(pm25, pm10)
    aqi_value = aqi_data["aqi"]
    category = aqi_data["category"]

    if aqi_value is None:
        raw_aqi = data.get("aqi")
        if isinstance(raw_aqi, (int, float)):
            aqi_value = int(raw_aqi)
            category = aqi_data["category"]

    station_name = (
        data.get("city", {}).get("name")
        or data.get("station", {}).get("name")
        or "Unknown station"
    )

    updated_at = data.get("time", {}).get("iso", "")

    # Extract station coordinates from city.geo or station.geo
    geo = data.get("city", {}).get("geo") or data.get("station", {}).get("geo") or []
    stn_lat: Optional[float] = None
    stn_lon: Optional[float] = None
    if len(geo) >= 2:
        try:
            stn_lat = float(geo[0])
            stn_lon = float(geo[1])
        except (TypeError, ValueError):
            pass

    return {
        "source": "external_waqi",
        "station_name": station_name,
        "aqi": aqi_value,
        "category": category,
        "pm25": pm25,
        "pm10": pm10,
        "temperature": temperature,
        "humidity": humidity,
        "dominant_pollutant": data.get("dominentpol"),
        "updated_at": updated_at,
        "latitude": stn_lat,
        "longitude": stn_lon,
        "distance_km": round(distance_km, 1) if distance_km is not None else None,
        "fallback_step": fallback_step,
    }



def fetch_external_aqi(
    lat: Optional[float],
    lon: Optional[float],
    cache_key: str,
    query: str = "",
) -> Optional[dict]:
    """
    Fetch air quality data for a location or coordinate pair with multi-step fallback.

    Parameters
    ----------
    lat, lon   : Coordinates (float) or None if search is purely text-based.
    cache_key  : Normalised cache key for Django cache storage.
    query      : Search query string (e.g. city name) for keyword fallbacks.

    Returns
    -------
    Standardized result dict on success, or None if no station was found.
    """
    token = getattr(settings, "WAQI_API_TOKEN", "")
    if not token:
        logger.warning("WAQI_API_TOKEN is not configured — external AQI lookup skipped.")
        return None

    # ── Check Cache First ─────────────────────────────────────────────────────
    cached = cache.get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for location key %r", cache_key)
        return cached

    clean_query = query.strip() if query else ""

    # ── Step A: Direct geo:<lat>;<lon> Lookup ─────────────────────────────────
    if lat is not None and lon is not None:
        url_geo = WAQI_GEO_URL.format(lat=lat, lon=lon, token=urllib.parse.quote(token))
        geo_data = _fetch_waqi_json(url_geo)
        if geo_data:
            stn_geo = geo_data.get("city", {}).get("geo", [])
            dist = None
            if len(stn_geo) >= 2:
                try:
                    dist = haversine_km(lat, lon, float(stn_geo[0]), float(stn_geo[1]))
                except (TypeError, ValueError):
                    dist = None

            # Only accept if station is reasonably close (<= 80km) or coordinates unverified
            if dist is None or dist <= 80.0:
                result = _parse_waqi_feed(geo_data, fallback_step="geo", distance_km=dist)
                if result:
                    cache.set(cache_key, result, CACHE_TTL)
                    logger.info(
                        "WAQI lookup for %r (%.4f, %.4f) succeeded via step 'geo' -> %s (AQI: %s)",
                        clean_query, lat, lon, result["station_name"], result["aqi"],
                    )
                    return result

    # ── Step B: Keyword Search ────────────────────────────────────────────────
    if clean_query:
        search_url = WAQI_SEARCH_URL.format(
            keyword=urllib.parse.quote(clean_query),
            token=urllib.parse.quote(token),
        )
        sdata = _fetch_waqi_json(search_url)
        if isinstance(sdata, list) and len(sdata) > 0:
            best_item = None
            best_dist = None

            # Find matching station
            for item in sdata:
                sname = item.get("station", {}).get("name", "")
                sgeo = item.get("station", {}).get("geo", [])
                dist = None
                if lat is not None and lon is not None and len(sgeo) >= 2:
                    try:
                        dist = haversine_km(lat, lon, float(sgeo[0]), float(sgeo[1]))
                    except (TypeError, ValueError):
                        dist = None

                # Exact or substring match in name
                if clean_query.lower() in sname.lower():
                    best_item = item
                    best_dist = dist
                    break
                elif dist is not None and dist <= 100.0:
                    if best_dist is None or dist < best_dist:
                        best_item = item
                        best_dist = dist

            if best_item is None and (lat is None or lon is None):
                # If no coords to verify distance, take top keyword match
                best_item = sdata[0]

            if best_item:
                uid = best_item.get("uid")
                feed_data = None
                if uid:
                    feed_url = WAQI_FEED_UID_URL.format(uid=uid, token=urllib.parse.quote(token))
                    feed_data = _fetch_waqi_json(feed_url)

                result = _parse_waqi_feed(
                    feed_data if feed_data else best_item,
                    fallback_step="keyword",
                    distance_km=best_dist,
                )
                if result:
                    cache.set(cache_key, result, CACHE_TTL)
                    logger.info(
                        "WAQI lookup for %r succeeded via step 'keyword' -> %s (AQI: %s)",
                        clean_query, result["station_name"], result["aqi"],
                    )
                    return result

    # ── Step C: Keyword Search with ", India" Suffix ──────────────────────────
    if clean_query and "india" not in clean_query.lower():
        india_query = f"{clean_query}, India"
        search_india_url = WAQI_SEARCH_URL.format(
            keyword=urllib.parse.quote(india_query),
            token=urllib.parse.quote(token),
        )
        sdata_india = _fetch_waqi_json(search_india_url)
        if isinstance(sdata_india, list) and len(sdata_india) > 0:
            candidates = []
            for item in sdata_india:
                sname = item.get("station", {}).get("name", "")
                sgeo = item.get("station", {}).get("geo", [])
                dist = None
                if lat is not None and lon is not None and len(sgeo) >= 2:
                    try:
                        dist = haversine_km(lat, lon, float(sgeo[0]), float(sgeo[1]))
                    except (TypeError, ValueError):
                        dist = None

                if clean_query.lower() in sname.lower():
                    candidates.append((0, dist or 0.0, item))
                elif dist is not None and dist <= 75.0:
                    candidates.append((1, dist, item))

            if candidates:
                candidates.sort(key=lambda x: (x[0], x[1]))
                best_item = candidates[0][2]
                best_dist = candidates[0][1]
                uid = best_item.get("uid")
                feed_data = None
                if uid:
                    feed_url = WAQI_FEED_UID_URL.format(uid=uid, token=urllib.parse.quote(token))
                    feed_data = _fetch_waqi_json(feed_url)

                result = _parse_waqi_feed(
                    feed_data if feed_data else best_item,
                    fallback_step="keyword_india",
                    distance_km=best_dist if best_dist > 0 else None,
                )
                if result:
                    cache.set(cache_key, result, CACHE_TTL)
                    logger.info(
                        "WAQI lookup for %r succeeded via step 'keyword_india' -> %s (AQI: %s)",
                        clean_query, result["station_name"], result["aqi"],
                    )
                    return result

    # ── Step D: Regional Proximity Geo Probing (<= 75km) ──────────────────────
    if lat is not None and lon is not None:
        offsets = [(0.25, 0.0), (-0.25, 0.0), (0.0, 0.25), (0.0, -0.25), (0.25, 0.25), (-0.25, -0.25)]
        for dlat, dlon in offsets:
            nlat, nlon = round(lat + dlat, 3), round(lon + dlon, 3)
            url_offset = WAQI_GEO_URL.format(lat=nlat, lon=nlon, token=urllib.parse.quote(token))
            offset_data = _fetch_waqi_json(url_offset)
            if offset_data:
                stn_geo = offset_data.get("city", {}).get("geo", [])
                if len(stn_geo) >= 2:
                    try:
                        dist = haversine_km(lat, lon, float(stn_geo[0]), float(stn_geo[1]))
                        if dist <= 75.0:
                            result = _parse_waqi_feed(
                                offset_data,
                                fallback_step="regional_geo",
                                distance_km=dist,
                            )
                            if result:
                                cache.set(cache_key, result, CACHE_TTL)
                                logger.info(
                                    "WAQI lookup for %r (%.4f, %.4f) succeeded via step 'regional_geo' -> %s (dist: %.1f km, AQI: %s)",
                                    clean_query, lat, lon, result["station_name"], dist, result["aqi"],
                                )
                                return result
                    except (TypeError, ValueError):
                        pass

    # ── Step E: No Station Found Near Location ────────────────────────────────
    logger.info("WAQI lookup for %r (coords: %s, %s) failed all fallback steps.", clean_query, lat, lon)
    return None
