import urllib.request
import json

token = 'fe43f246243baecb0342468d7a92519767b3e57d'
geo_urls = [
    ("Kolkata", f"https://api.waqi.info/feed/geo:22.5726;88.3639/?token={token}"),
    ("Delhi", f"https://api.waqi.info/feed/geo:28.6139;77.2090/?token={token}"),
    ("Mumbai", f"https://api.waqi.info/feed/geo:19.0760;72.8777/?token={token}"),
    ("London", f"https://api.waqi.info/feed/geo:51.5074;-0.1278/?token={token}"),
    ("New York", f"https://api.waqi.info/feed/geo:40.7128;-74.0060/?token={token}"),
    ("Kolkata direct feed", f"https://api.waqi.info/feed/kolkata/?token={token}"),
    ("Kolkata search", f"https://api.waqi.info/search/?keyword=Kolkata&token={token}"),
]

for name, u in geo_urls:
    req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            payload = json.loads(r.read().decode('utf-8'))
            status = payload.get('status')
            data = payload.get('data')
            if status == 'ok':
                if isinstance(data, dict):
                    stn = data.get('city', {}).get('name', 'Unknown')
                    aqi = data.get('aqi')
                    print(f"{name:20} -> OK | Station: {stn[:35]} | AQI: {aqi}")
                else:
                    print(f"{name:20} -> OK | Search count: {len(data)}")
            else:
                print(f"{name:20} -> STATUS: {status} | DATA: {data}")
    except Exception as e:
        print(f"{name:20} -> Error: {e}")
