import urllib.request
import urllib.parse
import json

token = 'fe43f246243baecb0342468d7a92519767b3e57d'

def test_keyword(kw):
    url = f"https://api.waqi.info/search/?keyword={urllib.parse.quote(kw)}&token={token}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.loads(r.read().decode('utf-8'))
        print(f"Keyword: {kw} -> status: {data.get('status')}, results count: {len(data.get('data', []))}")
        if data.get('status') == 'ok' and data.get('data'):
            top = data['data'][0]
            print(f"  Top: {top.get('station', {}).get('name')} | uid: {top.get('uid')} | aqi: {top.get('aqi')}")
            # Fetch detailed feed for this uid
            uid = top.get('uid')
            feed_url = f"https://api.waqi.info/feed/@{uid}/?token={token}"
            req2 = urllib.request.Request(feed_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req2, timeout=5) as r2:
                d2 = json.loads(r2.read().decode('utf-8'))
                if d2.get('status') == 'ok':
                    iaqi = d2.get('data', {}).get('iaqi', {})
                    print(f"  Feed @{uid} -> PM2.5: {iaqi.get('pm25', {}).get('v')}, PM10: {iaqi.get('pm10', {}).get('v')}, T: {iaqi.get('t', {}).get('v')}, H: {iaqi.get('h', {}).get('v')}")

test_keyword("Kolkata")
test_keyword("Arambagh")
test_keyword("Arambagh, India")
test_keyword("Siliguri")
