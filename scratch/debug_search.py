import os
import sys
from pathlib import Path
import json
import urllib.request
import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vayu.settings")
django.setup()

from django.conf import settings
from django.db.models import Q
from sensors.models import Sensor
from sensors.aqi import resolve_location
from sensors.geocoding import geocode, NOMINATIM_URL, USER_AGENT
from sensors.external_aqi import fetch_external_aqi, WAQI_URL

print("=" * 60)
print("STEP 1: Checking Sensor table (Internal Path)")
print("=" * 60)
query = "Kolkata"
search_terms = resolve_location(query)
q_filter = Q()
for term in search_terms:
    q_filter |= Q(location__icontains=term)
matched = list(Sensor.objects.filter(q_filter).values('id', 'sensor_code', 'location'))
print(f"Matched sensors for '{query}': {matched}")

print("\n" + "=" * 60)
print("STEP 2: Testing Nominatim Geocoding Step")
print("=" * 60)
# Also test raw nominatim call to see any error if any
nominatim_url = f"{NOMINATIM_URL}?q={urllib.parse.quote(query)}&format=json&limit=1"
print(f"Nominatim Request URL: {nominatim_url}")
try:
    req = urllib.request.Request(nominatim_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=5) as resp:
        nom_raw = resp.read().decode('utf-8')
        print(f"Nominatim raw response: {nom_raw}")
except Exception as e:
    print(f"Nominatim raw exception: {type(e)} - {e}")

coords = geocode(query)
print(f"geocode('{query}') return value: {coords}")

print("\n" + "=" * 60)
print("STEP 5: Checking WAQI_API_TOKEN in settings.py")
print("=" * 60)
token = getattr(settings, "WAQI_API_TOKEN", "")
if token:
    masked = token[:4] + "..." + token[-4:] if len(token) >= 8 else token[:2] + "..."
    print(f"settings.WAQI_API_TOKEN is present: {masked} (length: {len(token)})")
else:
    print("settings.WAQI_API_TOKEN is EMPTY or NONE!")

if coords:
    lat, lon = coords
    print("\n" + "=" * 60)
    print("STEP 6: Constructed WAQI URL")
    print("=" * 60)
    full_url = WAQI_URL.format(lat=lat, lon=lon, token=token)
    print(f"Full WAQI URL: {full_url}")

    print("\n" + "=" * 60)
    print("STEP 3 & 4: Testing WAQI Call & Raw Response")
    print("=" * 60)
    try:
        req = urllib.request.Request(full_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            status_code = resp.getcode()
            raw_body = resp.read().decode('utf-8')
            print(f"HTTP Status Code: {status_code}")
            print(f"Raw Response Body: {raw_body}")
            parsed = json.loads(raw_body)
            print(f"Parsed status: {parsed.get('status')}")
            if parsed.get('status') == 'ok':
                data = parsed.get('data', {})
                print(f"Station name: {data.get('city', {}).get('name')}")
                print(f"AQI: {data.get('aqi')}")
                print(f"IAQI keys: {list(data.get('iaqi', {}).keys())}")
    except Exception as exc:
        print(f"Exception during raw WAQI call: {type(exc)} - {exc}")

    print("\n" + "=" * 60)
    print("fetch_external_aqi() function execution")
    print("=" * 60)
    from django.core.cache import cache
    cache_key = f"vayu_waqi_debug_{query.lower()}"
    cache.delete(cache_key)
    res = fetch_external_aqi(lat, lon, cache_key)
    print(f"fetch_external_aqi({lat}, {lon}) returned: {json.dumps(res, indent=2)}")
