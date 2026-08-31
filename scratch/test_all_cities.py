import os
import sys
from pathlib import Path
import math
import urllib.request
import urllib.parse
import json

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vayu.settings")
import django
django.setup()

from django.conf import settings
from sensors.geocoding import geocode

token = getattr(settings, "WAQI_API_TOKEN", "")

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def fetch_feed_data(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("status") == "ok" and payload.get("data"):
                return payload.get("data")
    except Exception:
        pass
    return None

def robust_waqi_lookup(query):
    coords = geocode(query)
    lat, lon = coords if coords else (None, None)
    
    # ── Step A: geo:<lat>;<lon> ──
    if lat is not None and lon is not None:
        geo_url = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={token}"
        data = fetch_feed_data(geo_url)
        if data and data.get("dominentpol") != "-" and (data.get("city") or data.get("iaqi")):
            # Check geographic distance if station geo is returned
            stn_geo = data.get("city", {}).get("geo", [])
            valid_geo = True
            if len(stn_geo) >= 2:
                try:
                    dist = haversine_km(lat, lon, float(stn_geo[0]), float(stn_geo[1]))
                    if dist > 80.0:  # If WAQI returned a station > 80km away, reject and try keyword
                        valid_geo = False
                except Exception:
                    pass
            if valid_geo:
                stn_name = data.get("city", {}).get("name") or data.get("station", {}).get("name")
                return "a (geo)", stn_name, data.get("aqi")

    # ── Step B: keyword search ──
    if query:
        search_url = f"https://api.waqi.info/search/?keyword={urllib.parse.quote(query)}&token={token}"
        sdata = fetch_feed_data(search_url)
        if isinstance(sdata, list) and len(sdata) > 0:
            # Pick best match containing query or closest
            best = None
            for item in sdata:
                sname = item.get("station", {}).get("name", "")
                if query.lower() in sname.lower():
                    best = item
                    break
            if not best:
                best = sdata[0]
            
            uid = best.get("uid")
            if uid:
                feed = fetch_feed_data(f"https://api.waqi.info/feed/@{uid}/?token={token}")
                if feed:
                    stn_name = feed.get("city", {}).get("name") or best.get("station", {}).get("name")
                    return "b (keyword)", stn_name, feed.get("aqi")
                return "b (keyword)", best.get("station", {}).get("name"), best.get("aqi")

    # ── Step C: keyword search with ", India" ──
    if query and "india" not in query.lower():
        search_url_in = f"https://api.waqi.info/search/?keyword={urllib.parse.quote(query + ', India')}&token={token}"
        sdata = fetch_feed_data(search_url_in)
        if isinstance(sdata, list) and len(sdata) > 0:
            candidates = []
            for item in sdata:
                sname = item.get("station", {}).get("name", "")
                sgeo = item.get("station", {}).get("geo", [])
                dist = None
                if lat is not None and lon is not None and len(sgeo) >= 2:
                    try:
                        dist = haversine_km(lat, lon, float(sgeo[0]), float(sgeo[1]))
                    except Exception:
                        pass
                if query.lower() in sname.lower():
                    candidates.append((0, dist or 9999, item))
                elif dist is not None and dist <= 75:
                    candidates.append((1, dist, item))

            if candidates:
                candidates.sort(key=lambda x: (x[0], x[1]))
                best = candidates[0][2]
                uid = best.get("uid")
                feed = fetch_feed_data(f"https://api.waqi.info/feed/@{uid}/?token={token}") if uid else None
                name = (feed.get("city", {}).get("name") if feed else None) or best.get("station", {}).get("name")
                aqi = (feed.get("aqi") if feed else None) or best.get("aqi")
                return "c (keyword_india)", name, aqi

    # ── Step D: regional proximity search (~50-70km) ──
    if lat is not None and lon is not None:
        for dlat, dlon in [(0.25, 0), (-0.25, 0), (0, 0.25), (0, -0.25)]:
            nlat, nlon = round(lat + dlat, 3), round(lon + dlon, 3)
            data = fetch_feed_data(f"https://api.waqi.info/feed/geo:{nlat};{nlon}/?token={token}")
            if data and data.get("dominentpol") != "-" and (data.get("city") or data.get("iaqi")):
                stn_geo = data.get("city", {}).get("geo", [])
                if len(stn_geo) >= 2:
                    try:
                        dist = haversine_km(lat, lon, float(stn_geo[0]), float(stn_geo[1]))
                        if dist <= 75.0:
                            stn_name = data.get("city", {}).get("name") or data.get("station", {}).get("name")
                            return "d (regional_geo)", stn_name, data.get("aqi")
                    except Exception:
                        pass

    return "e (failed)", None, None

cities = [
    # Metros
    "Delhi", "Mumbai", "Kolkata", "Chennai", "Bangalore", "Hyderabad",
    # Tier-2
    "Lucknow", "Bhopal", "Patna", "Guwahati", "Coimbatore", "Nagpur",
    # Small towns
    "Arambagh", "Siliguri", "Rishikesh", "Puri", "Alappuzha"
]

print(f"{'City / Town':15} | {'Step':18} | {'AQI':5} | {'Station Name'}")
print("-" * 80)
for city in cities:
    step, stn, aqi = robust_waqi_lookup(city)
    stn_display = (stn[:40] + "...") if stn and len(stn) > 40 else (stn or "No station found (404)")
    # Encode safe for console
    safe_display = stn_display.encode("ascii", "replace").decode("ascii")
    print(f"{city:15} | {step:18} | {str(aqi):5} | {safe_display}")
