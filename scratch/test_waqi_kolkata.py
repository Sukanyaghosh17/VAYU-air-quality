import urllib.request
import json

token = 'fe43f246243baecb0342468d7a92519767b3e57d'
urls = [
    f'https://api.waqi.info/feed/kolkata/?token={token}',
    f'https://api.waqi.info/search/?keyword=kolkata&token={token}',
    f'https://api.waqi.info/feed/geo:22.5726;88.3639/?token={token}',
    f'https://api.waqi.info/feed/geo:22.57;88.36/?token={token}'
]

for u in urls:
    req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            payload = json.loads(r.read().decode('utf-8'))
            print('=' * 60)
            print('URL:', u)
            print('Status:', payload.get('status'))
            if payload.get('status') == 'ok':
                d = payload.get('data')
                if isinstance(d, dict):
                    print('City / Station:', d.get('city', {}).get('name'))
                    print('AQI:', d.get('aqi'))
                    print('IAQI:', d.get('iaqi'))
                elif isinstance(d, list):
                    print(f'Search found {len(d)} stations:')
                    for s in d[:3]:
                        print('  -', s.get('station', {}).get('name'), '| uid:', s.get('uid'))
            else:
                print('Raw payload:', payload)
    except Exception as e:
        print('Error calling', u, ':', e)
