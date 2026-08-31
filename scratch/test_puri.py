import urllib.request
import urllib.parse
import json
import math

token = 'fe43f246243baecb0342468d7a92519767b3e57d'

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# Puri coordinates: 19.8135, 85.8312
lat, lon = 19.8135, 85.8312

url = f"https://api.waqi.info/search/?keyword=Puri,%20India&token={token}"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=5) as r:
    data = json.loads(r.read().decode('utf-8'))
    print("Puri, India search results count:", len(data.get('data', [])))
    for item in data.get('data', []):
        sgeo = item.get('station', {}).get('geo', [])
        dist = haversine_km(lat, lon, float(sgeo[0]), float(sgeo[1])) if len(sgeo) >= 2 else None
        print(" ", item.get('station', {}).get('name'), "| dist:", f"{dist:.1f} km" if dist else "N/A")
