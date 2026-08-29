/**
 * dashboard.js — VAYU Phase 6 frontend
 * ======================================
 * Polls the DRF API using session cookies (no token needed in the browser).
 * All API calls use fetch() with credentials: 'same-origin'.
 *
 * Polling intervals:
 *   Latest readings + alert feed → every 10 seconds
 *   Trend charts                 → every 60 seconds
 *
 * Chart.js is loaded via CDN in the base template.
 */

/* ── State ──────────────────────────────────────────────────── */
const state = {
  sensors: [],
  latestReadings: [],
  pm25Range: '24h',
  pm10Range: '24h',
  pm25Chart: null,
  pm10Chart: null,
  selectedSensorId: null,
};

/* ── API helpers ─────────────────────────────────────────────── */
const API = {
  get: (path) => fetch(path, { credentials: 'same-origin' }).then(r => {
    if (!r.ok) throw new Error(`API ${path} → ${r.status}`);
    return r.json();
  }),
};

async function apiGetAll(path) {
  /** Fetch first page; return results array (handles paginated DRF responses) */
  const data = await API.get(path);
  return Array.isArray(data) ? data : (data.results ?? []);
}

/* ── AQI helpers ─────────────────────────────────────────────── */
function pm25Aqi(val) {
  if (val <= 12)  return { label: 'Good',        color: '#68d391' };
  if (val <= 35)  return { label: 'Moderate',     color: '#f6e05e' };
  if (val <= 55)  return { label: 'Unhealthy·S',  color: '#ed8936' };
  if (val <= 150) return { label: 'Unhealthy',    color: '#fc8181' };
  return               { label: 'Hazardous',     color: '#e53e3e' };
}
function pm10Aqi(val) {
  if (val <= 54)  return { label: 'Good',        color: '#68d391' };
  if (val <= 154) return { label: 'Moderate',    color: '#f6e05e' };
  if (val <= 254) return { label: 'Unhealthy',   color: '#fc8181' };
  return               { label: 'Hazardous',    color: '#e53e3e' };
}
function unitForParam(param) {
  return { pm25: 'µg/m³', pm10: 'µg/m³', temperature: '°C', humidity: '%' }[param] ?? '';
}
function labelForParam(param) {
  return { pm25: 'PM2.5', pm10: 'PM10', temperature: 'Temp', humidity: 'Humidity' }[param] ?? param;
}

/* ── SVG ring ───────────────────────────────────────────────── */
function makeRing(value, max, color, size = 56) {
  const r = 22, cx = size / 2, cy = size / 2;
  const circ = 2 * Math.PI * r;
  const pct = Math.min(value / max, 1);
  const dash = pct * circ;
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="rgba(255,255,255,0.07)" stroke-width="4"/>
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="4"
      stroke-dasharray="${dash} ${circ}" stroke-dashoffset="${circ / 4}"
      stroke-linecap="round" transform="rotate(-90 ${cx} ${cy})"/>
  </svg>`;
}

/* ── Stat cards ─────────────────────────────────────────────── */
function renderStatCards(readings) {
  if (!readings.length) return;
  // Average across all sensors for global overview
  const avg = (key) => readings.reduce((s, r) => s + parseFloat(r[key] ?? 0), 0) / readings.length;
  const pm25  = avg('pm25');
  const pm10  = avg('pm10');
  const temp  = avg('temperature');
  const hum   = avg('humidity');

  const aqiPm25 = pm25Aqi(pm25);
  const aqiPm10 = pm10Aqi(pm10);

  setCard('stat-pm25', pm25.toFixed(1), 'µg/m³', makeRing(pm25, 150, aqiPm25.color),
    `<span class="stat-aqi-label" style="color:${aqiPm25.color}">${aqiPm25.label}</span>`);
  setCard('stat-pm10', pm10.toFixed(1), 'µg/m³', makeRing(pm10, 300, aqiPm10.color),
    `<span class="stat-aqi-label" style="color:${aqiPm10.color}">${aqiPm10.label}</span>`);
  setCard('stat-temp', temp.toFixed(1), '°C', makeRing(temp, 50, '#fc8181'), '');
  setCard('stat-hum',  hum.toFixed(1),  '%',   makeRing(hum, 100, '#38b2ac'), '');
}

function setCard(id, value, unit, ring, extra) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = `
    <div class="stat-label">${el.dataset.label}</div>
    <div class="stat-value-row">
      <div>
        <span class="stat-value">${value}</span><span class="stat-unit">${unit}</span>
        ${extra}
      </div>
      <div class="stat-ring">${ring}</div>
    </div>`;
}

/* ── Sidebar sensor list ─────────────────────────────────────── */
function renderSidebar(sensors) {
  const list = document.getElementById('sensor-list');
  if (!list) return;
  if (!sensors.length) {
    list.innerHTML = '<div class="sensor-item"><span class="text-muted" style="font-size:12px">No sensors yet</span></div>';
    return;
  }
  list.innerHTML = sensors.map(s => `
    <div class="sensor-item ${state.selectedSensorId === s.id ? 'active' : ''}"
         data-id="${s.id}" onclick="selectSensor(${s.id})">
      <div class="sensor-status-dot ${s.status}"></div>
      <div class="sensor-info">
        <div class="sensor-code">${s.sensor_code}</div>
        <div class="sensor-loc">${s.location}</div>
      </div>
      <div class="sensor-count">${s.reading_count ?? ''}</div>
    </div>`).join('');
}

window.selectSensor = function(id) {
  state.selectedSensorId = (state.selectedSensorId === id) ? null : id;
  renderSidebar(state.sensors);
};

/* ── Trend charts ────────────────────────────────────────────── */
function buildGradient(ctx, colorHex) {
  const gradient = ctx.createLinearGradient(0, 0, 0, 200);
  gradient.addColorStop(0, colorHex + '55');
  gradient.addColorStop(1, colorHex + '00');
  return gradient;
}

function createChart(canvasId, label, colorHex) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return null;
  const ctx = canvas.getContext('2d');
  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label,
        data: [],
        borderColor: colorHex,
        backgroundColor: buildGradient(ctx, colorHex),
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHoverBackgroundColor: colorHex,
        tension: 0.4,
        fill: true,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 600 },
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: {
          ticks: {
            color: '#4a5568', maxTicksLimit: 8,
            font: { size: 10, family: 'Inter' },
          },
          grid: { color: 'rgba(255,255,255,0.04)' },
        },
        y: {
          ticks: {
            color: '#4a5568',
            font: { size: 10, family: 'Inter' },
          },
          grid: { color: 'rgba(255,255,255,0.06)' },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(10,14,26,0.9)',
          borderColor: 'rgba(255,255,255,0.1)',
          borderWidth: 1,
          titleFont: { family: 'Inter', size: 12 },
          bodyFont: { family: 'Inter', size: 12 },
          padding: 10,
        },
      },
    },
  });
}

function updateChart(chart, points, unit) {
  if (!chart || !points) return;
  chart.data.labels = points.map(p => {
    const d = new Date(p.bucket);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  });
  chart.data.datasets[0].data = points.map(p => parseFloat(p.avg_value).toFixed(2));
  chart.data.datasets[0].label += ` (${unit})`;
  chart.update('active');
}

async function loadTrend(param, range, chart) {
  try {
    const sensorParam = state.selectedSensorId ? `&sensor=${state.selectedSensorId}` : '';
    const data = await API.get(`/api/v1/analytics/trends/?param=${param}&range=${range}${sensorParam}`);
    updateChart(chart, data.points, unitForParam(param));
  } catch (e) {
    console.warn('Trend load failed:', e);
  }
}

/* ── Alert feed ─────────────────────────────────────────────── */
function severityBadge(sev, type) {
  const cls = type === 'ml' ? 'ml' : sev;
  const label = type === 'ml' ? `🤖 ML` : sev.toUpperCase();
  return `<span class="badge badge-${cls}">${label}</span>`;
}

function relativeTime(ts) {
  const diff = Date.now() - new Date(ts);
  const mins = Math.floor(diff / 60000);
  if (mins < 1)  return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function renderAlertFeed(alerts) {
  const tbody = document.getElementById('alert-tbody');
  const counter = document.getElementById('alert-count');
  if (!tbody) return;

  if (counter) counter.textContent = alerts.length;

  if (!alerts.length) {
    tbody.innerHTML = `<tr><td colspan="6">
      <div class="empty-state">
        <div class="empty-state-icon">✅</div>
        <div>No open alerts — air quality is nominal</div>
      </div>
    </td></tr>`;
    return;
  }

  tbody.innerHTML = alerts.map(a => `
    <tr>
      <td>${severityBadge(a.severity, a.alert_type)}</td>
      <td class="alert-sensor">${a.sensor_code ?? a.sensor ?? '—'}</td>
      <td><span class="alert-param">${labelForParam(a.parameter)}</span></td>
      <td class="alert-value">${parseFloat(a.value).toFixed(2)} ${unitForParam(a.parameter)}</td>
      <td><span class="alert-type-icon">${a.alert_type === 'ml' ? '🤖' : '⚡'}</span></td>
      <td class="alert-time" title="${a.created_at}">${relativeTime(a.created_at)}</td>
    </tr>`).join('');
}

/* ── Fetch cycle ─────────────────────────────────────────────── */
async function refreshReadings() {
  try {
    const data = await apiGetAll('/api/v1/readings/latest/');
    state.latestReadings = data;
    renderStatCards(data);
  } catch (e) { console.warn('Readings refresh failed:', e); }
}

async function refreshAlerts() {
  try {
    // Fetch open + investigating alerts, newest first, max 50
    const data = await apiGetAll('/api/v1/alerts/?status=open&page_size=50');
    renderAlertFeed(data);
  } catch (e) { console.warn('Alerts refresh failed:', e); }
}

async function refreshCharts() {
  await loadTrend('pm25', state.pm25Range, state.pm25Chart);
  await loadTrend('pm10', state.pm10Range, state.pm10Chart);
}

async function refreshSensors() {
  try {
    const data = await apiGetAll('/api/v1/sensors/?page_size=100');
    state.sensors = data;
    renderSidebar(data);
  } catch (e) { console.warn('Sensor list failed:', e); }
}

/* ── Range buttons ───────────────────────────────────────────── */
window.setRange = function(param, range, btn) {
  if (param === 'pm25') state.pm25Range = range;
  else state.pm10Range = range;
  // Update active button within the same group
  btn.closest('.chart-range-btns').querySelectorAll('.chart-range-btn')
     .forEach(b => b.classList.toggle('active', b === btn));
  loadTrend(param, range, param === 'pm25' ? state.pm25Chart : state.pm10Chart);
};

/* ── Timestamp ───────────────────────────────────────────────── */
function updateTimestamp() {
  const el = document.getElementById('last-updated');
  if (el) el.textContent = new Date().toLocaleTimeString();
}

/* ── Init ────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', async () => {
  // Create charts
  state.pm25Chart = createChart('pm25-chart', 'PM2.5', '#4299e1');
  state.pm10Chart = createChart('pm10-chart', 'PM10',  '#ed8936');

  // Initial load
  await refreshSensors();
  await refreshReadings();
  await refreshAlerts();
  await refreshCharts();
  updateTimestamp();

  // Polling
  setInterval(async () => {
    await refreshReadings();
    await refreshAlerts();
    updateTimestamp();
  }, 10_000);

  setInterval(async () => {
    await refreshCharts();
  }, 60_000);
});
