# 🍃 VAYU — Air Quality Monitoring & ML Anomaly Platform

![Python](https://img.shields.io/badge/Python-3.12%2B-blue?style=flat-square&logo=python)
![Django](https://img.shields.io/badge/Django-6.1-green?style=flat-square&logo=django)
![Django REST Framework](https://img.shields.io/badge/DRF-3.18-red?style=flat-square)
![scikit-learn](https://img.shields.io/badge/scikit--learn-Isolation%20Forest-orange?style=flat-square&logo=scikit-learn)
![Chart.js](https://img.shields.io/badge/Chart.js-4.4-yellow?style=flat-square&logo=chartdotjs)
![Leaflet](https://img.shields.io/badge/Leaflet-1.9-brightgreen?style=flat-square&logo=leaflet)

**VAYU** is an open, end-to-end Air Quality Monitoring, Analytics, and Anomaly Detection platform. It ingests high-frequency IoT sensor telemetry, computes standardized CPCB Air Quality Index (AQI) values, flags abnormal spikes via rule-based thresholds and unsupervised machine learning (Isolation Forest), and delivers a real-time, glassmorphic monitoring dashboard with interactive map views and trend analysis.

---

## 🌟 Key Features

- 🖥️ **Instant Public Dashboard**: Zero-friction, publicly accessible live dashboard with a modern dark-mode aesthetic, live pulse updates, and city quick-select tiles.
- 🗺️ **Interactive Station Map**: Leaflet-powered geospatial map rendering color-coded AQI pins for monitored stations.
- 🔍 **Dual-Source Location Search**:
  - **Internal Network**: Instant subquery search across deployed VAYU hardware stations with Indian city aliases (e.g., *Bangalore* ↔ *Bengaluru*).
  - **Global Fallback**: Geocodes unfamiliar locations via Nominatim and fetches nearest public monitoring station data from the **World Air Quality Index (WAQI)** API with 15-minute caching.
- 📊 **CPCB AQI Engine**: Official Central Pollution Control Board (India) breakpoint formulas calculating sub-indices and overall AQI categories (*Good*, *Satisfactory*, *Moderate*, *Poor*, *Very Poor*, *Severe*).
- 🧠 **ML Anomaly Detection**: Per-sensor **Isolation Forest** models trained on multi-feature rolling averages and deviations to detect subtle, non-threshold-crossing anomalies.
- 🚨 **Automated Alerting**: System-generated alerts categorized by threshold violations and ML anomalies, complete with configurable alert cooldowns.
- 📡 **High-Throughput REST API**: Fully documented DRF endpoints for sensor management, latest readings, time-bucketed history, statistics, alerts, and map data.
- 🧪 **IoT Simulator CLI**: Standalone Python simulator (`simulate_sensors.py`) simulating concurrent sensors, realistic Gaussian telemetry, and configurable anomaly spike rates.

---

## 🏗️ Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| **Backend** | Python 3.12+, Django 6.1, DRF 3.18 | Core framework, API routing, and ORM |
| **Database** | SQLite (Dev) / MySQL 8+ / PostgreSQL (Prod) | Relational storage for sensors, readings, alerts |
| **Machine Learning** | scikit-learn, joblib, NumPy, Pandas | Unsupervised Isolation Forest anomaly scoring |
| **Frontend** | Django Templates, Vanilla JavaScript, CSS3 | Glassmorphic, responsive dashboard UI |
| **Visualizations** | Chart.js 4.4, Leaflet.js 1.9, OpenStreetMap | Time-series trend charts and geospatial station map |
| **External Data** | WAQI API & OpenStreetMap Nominatim | Worldwide air quality fallback & geocoding |

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.12 or newer
- Virtual environment tool (`venv`)
- (Optional) MySQL 8+ or SQLite (default)

### 2. Clone and Setup Environment

```bash
# Clone the repository
git clone https://github.com/Sukanyaghosh17/VAYU-air-quality.git
cd "VAYU - air - Quality"

# Create and activate virtual environment
python -m venv .venv

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure `.env`

Copy the example environment file:
```bash
cp .env.example .env
```

Edit `.env` with your settings:
```env
SECRET_KEY=your-secure-secret-key
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

# (Optional) Database URL - defaults to SQLite if omitted
# DATABASE_URL=mysql://root:password@127.0.0.1:3306/vayu_db

# (Optional) World Air Quality Index token for global search fallback
# Get a free token at https://aqicn.org/data-platform/token/
WAQI_API_TOKEN=your-waqi-token-here

# Simulator service credentials
SIMULATOR_PASSWORD=simulator-strong-password
```

### 4. Database Migrations & Static Files

```bash
# Run database migrations
python manage.py migrate

# (Optional) Create superuser for Django Admin (/admin/)
python manage.py createsuperuser

# Collect static assets
python manage.py collectstatic --noinput
```

### 5. Launch the Development Server

```bash
python manage.py runserver
```

Open your browser and navigate to:
- 🌐 **Live Dashboard**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- ⚙️ **Django Admin**: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

---

## 🧪 Running the IoT Sensor Simulator

The platform includes a multi-featured simulator (`simulate_sensors.py`) to stream realistic air-quality telemetry directly into the ingest API.

### Step 1: Generate Simulator API Token
Run this one-line command to initialize the simulator user and output its authentication token:

```bash
python manage.py shell -c "
import environ; from pathlib import Path; from django.contrib.auth import get_user_model; from rest_framework.authtoken.models import Token
env = environ.Env(); environ.Env.read_env(Path('.env'))
User = get_user_model()
u, _ = User.objects.get_or_create(username='simulator', defaults={'role': 'user'})
u.set_password(env('SIMULATOR_PASSWORD')); u.save()
t, _ = Token.objects.get_or_create(user=u)
print('SIMULATOR_TOKEN=' + t.key)
"
```

Copy the output token and paste it into `.env` as `SIMULATOR_TOKEN=<token>`.

### Step 2: Run the Simulator

```bash
# Basic simulation with 3 sensors, publishing every 3 seconds:
python simulate_sensors.py --sensors 3 --interval 3 --spike-rate 0.05

# High-frequency testing with 5 sensors and higher spike rates:
python simulate_sensors.py --sensors 5 --interval 1 --spike-rate 0.15

# Target specific sensor IDs already in the database:
python simulate_sensors.py --sensor-ids 1,2,3 --interval 2

# Run for a fixed duration (e.g., 60 seconds) then stop:
python simulate_sensors.py --sensors 3 --duration 60
```

#### Simulator Telemetry Baseline:
| Parameter | Baseline Range | Anomaly Spike Range | Unit |
|---|---|---|---|
| **PM2.5** | 15 ± 5 | 90 – 210 | µg/m³ |
| **PM10** | 30 ± 10 | 150 – 360 | µg/m³ |
| **Temperature** | 25 ± 3 | 35 – 45 | °C |
| **Humidity** | 55 ± 10 | 88 – 99 | % |

---

## 🧠 Machine Learning Anomaly Detection

VAYU utilizes an **Isolation Forest** algorithm per sensor to detect subtle, multivariate anomalies in air quality streams.

### Training the Models
When sensors have accumulated at least 100 readings, train the anomaly detection models:

```bash
python manage.py train_ml
```

- Models are serialized to `.joblib` files under `ml_models/sensor_<id>.joblib`.
- Ingestion pipelines evaluate incoming sensor readings against these models in real time to generate `alert_type='ml'` alerts.

---

## 📡 REST API Reference

All API routes are served under `/api/v1/`:

### Sensors & Readings
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/sensors/` | List all sensors with reading counts |
| `POST` | `/api/v1/sensors/` | Create a new sensor (Admin only) |
| `GET` | `/api/v1/sensors/<id>/` | Retrieve details for a specific sensor |
| `GET` | `/api/v1/sensors/search/?location=<city>` | Search sensor stations or external WAQI stations |
| `GET` | `/api/v1/sensors/search/?lat=<lat>&lon=<lon>` | Coordinate-based nearest AQI search |
| `GET` | `/api/v1/sensors/map/` | Geocoded sensors with latest AQI status for map view |
| `GET` | `/api/v1/readings/` | Paginated raw readings feed |
| `POST` | `/api/v1/readings/` | Ingest new sensor reading |
| `GET` | `/api/v1/readings/latest/` | Most recent reading for every sensor |
| `GET` | `/api/v1/readings/history/?sensor=<id>&range=24h\|7d\|30d` | Time-bucketed averages for trends |

### Analytics & Alerts
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/analytics/stats/?sensor=<id>&hours=24` | Aggregated statistical summary for a sensor |
| `GET` | `/api/v1/analytics/trends/?param=<pm25\|pm10...>&range=7d` | Time-bucketed trend points |
| `GET` | `/api/v1/analytics/anomalies/` | Feed of ML-flagged anomaly alerts |
| `GET` | `/api/v1/alerts/?status=open` | List active alerts |
| `PATCH`| `/api/v1/alerts/<id>/` | Update alert status (*open*, *investigating*, *resolved*) (Admin only) |
| `GET` | `/api/v1/thresholds/` | List rule-based threshold parameters |

---

## 📁 Project Structure

```
VAYU - air - Quality/
├── accounts/            # Custom User model, roles, and administrative auth
├── alerts/              # Threshold configurations, rule-based & ML alert models
├── analytics/           # Analytics endpoints, statistics aggregation, ML trainer
├── dashboard/           # Public dashboard view routing & templates
├── sensors/             # Sensor CRUD, reading ingest, AQI formulas, geocoding & WAQI
├── static/
│   ├── css/             # Glassmorphic dashboard stylesheets
│   └── js/              # Client-side API fetchers, polling, Chart.js & Leaflet logic
├── templates/
│   ├── base.html        # HTML5 layout shell with fonts & CDNs
│   └── dashboard/       # Main dashboard HTML template
├── vayu/                # Django project settings, WSGI, ASGI, and root URLs
├── ml_models/           # Serialized scikit-learn Isolation Forest model files
├── simulate_sensors.py  # Standalone IoT sensor telemetry simulator CLI
├── manage.py            # Django management CLI
├── requirements.txt     # Python project dependencies
└── render.yaml          # Cloud deployment specification
```

---

## 🧪 Running Tests

Execute the automated test suite covering all modules:

```bash
python manage.py test
```

---

## 📄 License

This project is licensed under the MIT License — feel free to use and extend it.
