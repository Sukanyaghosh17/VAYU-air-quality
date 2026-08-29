# VAYU — Air Quality Anomaly & Alert Platform

A full-stack Django + ML platform that ingests real-time air-quality sensor readings,
detects anomalies via rule-based thresholds and Isolation Forest ML, and presents
a live dashboard with charts and alert management.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14, Django 6.1, Django REST Framework 3.18 |
| Database | MySQL 8 |
| Frontend | Django templates, Vanilla CSS/JS, Chart.js |
| ML | scikit-learn Isolation Forest, joblib |
| Data | Pandas, NumPy |

---

## Quick Start

### 1. Prerequisites
- Python 3.12+
- MySQL 8 running locally

### 2. Clone & install
```bash
git clone <repo-url>
cd vayu-air-quality
pip install -r requirements.txt
```

### 3. Create the MySQL database
```sql
CREATE DATABASE vayu_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 4. Configure environment
```bash
cp .env.example .env
# Edit .env — set SECRET_KEY and your MySQL credentials
```

Generate a secret key:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 5. Migrate & create superuser
```bash
python manage.py migrate
python manage.py createsuperuser
```

### 6. Run the dev server
```bash
python manage.py runserver
```

Visit `http://127.0.0.1:8000/admin/` to confirm the admin panel loads.

---

## Running the Sensor Simulator

The simulator is a standalone script (`simulate_sensors.py`) — no Django
process required, just the dev server running in another terminal.

### 1. Set up the simulator user (once)

```bash
# Add to .env:
# SIMULATOR_PASSWORD=choose-a-strong-password

python manage.py shell -c "
import environ; from pathlib import Path
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
env = environ.Env(); environ.Env.read_env(Path('.env'))
User = get_user_model()
u, _ = User.objects.get_or_create(username='simulator', defaults={'role': 'user'})
u.set_password(env('SIMULATOR_PASSWORD')); u.save()
t, _ = Token.objects.get_or_create(user=u)
print('SIMULATOR_TOKEN=' + t.key)
"
# Copy the printed token into .env:
# SIMULATOR_TOKEN=<printed key>
```

### 2. Run the simulator

```bash
# Quickstart — 3 sensors, 3-second interval, 5 % spike rate
python simulate_sensors.py --sensors 3 --interval 3 --spike-rate 0.05

# 5 sensors, faster (1 s), higher spike rate for alert testing
python simulate_sensors.py --sensors 5 --interval 1 --spike-rate 0.15

# Target specific sensor IDs already in the DB
python simulate_sensors.py --sensor-ids 1,2,3 --interval 3

# Run for exactly 60 seconds then stop
python simulate_sensors.py --sensors 3 --duration 60

# Against a remote server with explicit token
python simulate_sensors.py --url http://myserver:8000 --token <key> --sensors 5
```

### 3. What you'll see

```
[simulator] Starting — 3 sensor(s), interval=3s, spike_rate=5%
  • SIM-001 (id=1) — Simulated Location 1
  • SIM-002 (id=2) — Simulated Location 2
  • SIM-003 (id=3) — Simulated Location 3
[simulator] Press Ctrl+C to stop.

[cycle 0001] SIM-001     PM2.5=  13.4  PM10=  27.8  T= 24.2°C  RH= 52.1%  id=1
[cycle 0001] SIM-002     PM2.5= 142.0  PM10= 198.5  T= 26.1°C  RH= 54.8%  id=2  ⚡SPIKE
[cycle 0001] SIM-003     PM2.5=  17.2  PM10=  31.0  T= 23.8°C  RH= 48.6%  id=3
```

### 4. Spike behaviour

Each parameter is spiked independently at `--spike-rate` probability:

| Parameter | Normal range | Spike range |
|---|---|---|
| PM2.5 | 5–25 µg/m³ | 90–210 µg/m³ |
| PM10 | 10–50 µg/m³ | 150–360 µg/m³ |
| Temperature | 19–31 °C | 35–45 °C |
| Humidity | 35–75 % | 88–99 % |

Spikes are what trigger the threshold alerts (Phase 4) and train the
ML anomaly detector (Phase 5).

---

## Retraining the ML Model

_(Added in Phase 5)_

```bash
python manage.py retrain_models
```

---

## MVP Design Notes & Known Limitations

### Threshold is global per parameter (not per-sensor)
**This is a deliberate MVP simplification.**
`Threshold` rows are keyed only by `parameter` (pm25, pm10, temperature, humidity).
Every sensor is checked against the same global limits. In a production system,
thresholds would carry a nullable FK to `Sensor` (or a `Location`), allowing
location-specific limits (e.g., a station near a highway may have higher acceptable
PM2.5 baselines). This is called out explicitly in `alerts/models.py` and in
`ARCHITECTURE.md` as a planned next iteration.

---

## Token Auth / Simulator User

The Phase 3 sensor simulator is a standalone script that uses **Token auth**
(not browser sessions).  Run this once after `python manage.py migrate` to
create the simulator service account and print its API token:

```bash
# 1. Add SIMULATOR_PASSWORD to .env (see .env.example for the key name)

# 2. Create the user and print the token
python manage.py shell -c "
import environ
from pathlib import Path
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token

env = environ.Env()
environ.Env.read_env(Path('.env'))

User = get_user_model()
u, created = User.objects.get_or_create(
    username='simulator',
    defaults={'role': 'user'},
)
u.set_password(env('SIMULATOR_PASSWORD'))
u.save()
t, _ = Token.objects.get_or_create(user=u)
print('Simulator token:', t.key)
"
```

The simulator script sends this token in every request header:
```
Authorization: Token <key>
```

---

## Architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full data-flow diagram and design
decision Q&A (why Isolation Forest, why per-sensor models, how rule-based and ML
alerts coexist, scalability roadmap).
