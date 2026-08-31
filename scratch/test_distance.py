import math
import urllib.request
import urllib.parse
import json

token = 'fe43f246243baecb0342468d7a92519767b3e57d'

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0 # km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

print("Haversine check Kolkata to Howrah:", haversine(22.5726, 88.3639, 22.5958, 88.2636), "km")
