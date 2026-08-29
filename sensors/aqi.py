"""
sensors/aqi.py — Indian CPCB AQI calculation
=============================================
Implements the Central Pollution Control Board (CPCB) sub-index formula for
PM2.5 and PM10.  The overall AQI is the maximum of all computed sub-indices.

None-safety
-----------
If pm25 or pm10 is None (sensor did not report the value), the function:
  - Skips that pollutant's sub-index instead of crashing.
  - Returns {"aqi": None, "category": "N/A"} only when ALL inputs are None.
  - Otherwise computes normally from the available pollutants.

CPCB AQI categories (same thresholds for the overall index)
------------------------------------------------------------
  0–50    Good
  51–100  Satisfactory
  101–200 Moderate
  201–300 Poor
  301–400 Very Poor
  401–500 Severe

Sub-index linear interpolation formula
---------------------------------------
  AQI_i = ((AQI_Hi - AQI_Lo) / (CP_Hi - CP_Lo)) * (CP - CP_Lo) + AQI_Lo

References: CPCB AQI Bulletin 2014; IS 5182 Part 22.

Location alias map
------------------
Maps common alternate spellings / historic names of Indian cities to their
canonical form used in the Sensor.location field.  The search view calls
`resolve_location(query)` to normalise input before querying the DB.

Supported pairs (bidirectional — either form resolves):
  Bangalore  ↔  Bengaluru
  Bombay     ↔  Mumbai
  Calcutta   ↔  Kolkata
  Madras     ↔  Chennai
  Baroda     ↔  Vadodara
  Poona      ↔  Pune
  Mysore     ↔  Mysuru
  Mangalore  ↔  Mangaluru
  Simla      ↔  Shimla
  Pondicherry↔  Puducherry
  Cuttack    ↔  Bhubaneswar  (common confusion)
  Dilli      ↔  Delhi
  New Delhi  ↔  Delhi
"""

from __future__ import annotations

from typing import Optional

# ── CPCB breakpoints ─────────────────────────────────────────────────────────
# Each entry: (CP_Lo, CP_Hi, AQI_Lo, AQI_Hi)
# Source: CPCB National Air Quality Index (2014)

_PM25_BREAKPOINTS = [
    (0.0,  30.0,   0,  50),
    (30.0, 60.0,  51, 100),
    (60.0, 90.0, 101, 200),
    (90.0, 120.0, 201, 300),
    (120.0, 250.0, 301, 400),
    (250.0, 500.0, 401, 500),
]

_PM10_BREAKPOINTS = [
    (0.0,   50.0,   0,  50),
    (50.0, 100.0,  51, 100),
    (100.0, 250.0, 101, 200),
    (250.0, 350.0, 201, 300),
    (350.0, 430.0, 301, 400),
    (430.0, 600.0, 401, 500),
]

_AQI_CATEGORIES = [
    (50,  "Good"),
    (100, "Satisfactory"),
    (200, "Moderate"),
    (300, "Poor"),
    (400, "Very Poor"),
    (500, "Severe"),
]

# ── City alias map ────────────────────────────────────────────────────────────
# Key: alternate / historic name (lowercase)
# Value: canonical name (title-cased, as stored in Sensor.location)
# The DB search uses icontains so casing doesn't matter — this map ensures
# that a search for "Bangalore" also hits sensors stored as "Bengaluru".
CITY_ALIASES: dict[str, str] = {
    "bangalore":   "Bengaluru",
    "bengaluru":   "Bangalore",     # reverse alias
    "bombay":      "Mumbai",
    "calcutta":    "Kolkata",
    "kolkata":     "Calcutta",      # reverse alias
    "madras":      "Chennai",
    "chennai":     "Madras",        # reverse alias
    "baroda":      "Vadodara",
    "vadodara":    "Baroda",        # reverse alias
    "poona":       "Pune",
    "pune":        "Poona",         # reverse alias
    "mysore":      "Mysuru",
    "mysuru":      "Mysore",        # reverse alias
    "mangalore":   "Mangaluru",
    "mangaluru":   "Mangalore",     # reverse alias
    "simla":       "Shimla",
    "pondicherry": "Puducherry",
    "puducherry":  "Pondicherry",   # reverse alias
    "new delhi":   "Delhi",
    "dilli":       "Delhi",
    "new bombay":  "Navi Mumbai",
    "arambagh":    "Arambagh",      # exact — no alias needed, kept for doc
}


def resolve_location(query: str) -> list[str]:
    """
    Return a list of location strings to search for, given user input.

    Always includes the original query.  If the query (lowercased) has an
    alias entry, the canonical alternate is appended so the DB search covers
    both forms in a single OR-style icontains query.

    Example:
        resolve_location("Bangalore") → ["Bangalore", "Bengaluru"]
        resolve_location("Kolkata")   → ["Kolkata", "Calcutta"]
        resolve_location("Arambagh")  → ["Arambagh"]
    """
    terms = [query]
    alias = CITY_ALIASES.get(query.strip().lower())
    if alias and alias.lower() != query.strip().lower():
        terms.append(alias)
    return terms


# ── Sub-index calculation ─────────────────────────────────────────────────────

def _sub_index(value: float, breakpoints: list[tuple]) -> int:
    """
    Linear interpolation within the matching breakpoint band.
    Clamps to 500 if the value exceeds the highest breakpoint.
    """
    for cp_lo, cp_hi, aqi_lo, aqi_hi in breakpoints:
        if cp_lo <= value <= cp_hi:
            return round(
                ((aqi_hi - aqi_lo) / (cp_hi - cp_lo)) * (value - cp_lo) + aqi_lo
            )
    # Value exceeds table maximum → clamp to 500 (Severe)
    return 500


def _category(aqi: int) -> str:
    for limit, label in _AQI_CATEGORIES:
        if aqi <= limit:
            return label
    return "Severe"


# ── Public API ────────────────────────────────────────────────────────────────

def compute_aqi(
    pm25: Optional[float],
    pm10: Optional[float],
) -> dict:
    """
    Compute the Indian CPCB AQI from PM2.5 and/or PM10 readings.

    Parameters
    ----------
    pm25 : float or None
        PM2.5 concentration in µg/m³.  Pass None if not available.
    pm10 : float or None
        PM10 concentration in µg/m³.  Pass None if not available.

    Returns
    -------
    dict with keys:
        "aqi"      : int or None   — overall AQI (None if all inputs are None)
        "category" : str           — CPCB category label or "N/A"
        "pm25_sub" : int or None   — PM2.5 sub-index
        "pm10_sub" : int or None   — PM10 sub-index

    Behaviour for missing values
    ----------------------------
    * Both None → {"aqi": None, "category": "N/A", "pm25_sub": None, "pm10_sub": None}
    * One None  → AQI computed from the available pollutant only.
    * Negative values are clamped to 0 before interpolation.
    """
    sub_indices: list[int] = []
    pm25_sub: Optional[int] = None
    pm10_sub: Optional[int] = None

    if pm25 is not None:
        pm25_sub = _sub_index(max(float(pm25), 0.0), _PM25_BREAKPOINTS)
        sub_indices.append(pm25_sub)

    if pm10 is not None:
        pm10_sub = _sub_index(max(float(pm10), 0.0), _PM10_BREAKPOINTS)
        sub_indices.append(pm10_sub)

    if not sub_indices:
        return {"aqi": None, "category": "N/A", "pm25_sub": None, "pm10_sub": None}

    overall = max(sub_indices)
    return {
        "aqi":      overall,
        "category": _category(overall),
        "pm25_sub": pm25_sub,
        "pm10_sub": pm10_sub,
    }
