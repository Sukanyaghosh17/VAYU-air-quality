/**
 * map.js — VAYU Interactive Map View (Leaflet + CartoDB Dark)
 * ===========================================================
 * Manages the "Map View" tab independently from dashboard.js.
 *
 * Public API consumed by dashboard.js:
 *   window.switchView(mode)             — tab toggle
 *   window.mapDropExternalMarker(r, q)  — drop WAQI pin after external search
 *   window.mapClearExternalMarker()     — remove WAQI pin
 *   window.mapFocusVayuSensor(id)       — pan + open popup for a VAYU sensor
 *   window._mapViewDetails(id)          — switch back to dashboard + select sensor
 *   window.mapToggleLayer(layer)        — toggle 'pins' or 'heatmap' layer
 *
 * Features:
 *   • AQI colour-coded sensor pin markers
 *   • Semi-transparent AQI heatmap circle overlays (radius ∝ AQI)
 *   • Sidebar: fleet overview (active count, avg AQI, best/worst city)
 *   • Sidebar: clickable sensor station list with AQI pills
 *   • Sidebar: selected station info panel (PM2.5, PM10, Temp, Humidity)
 *   • AQI legend overlay (bottom-left of map)
 *   • Layer controls (top-right of map): toggle Pins / Heatmap
 *   • Auto-fit bounds to all visible markers
 *   • 30-second live refresh while map tab is active
 */

/* ── Map state ────────────────────────────────────────────────── */
const mapState = {
  map: null,
  vayu_markers: [],         // L.Marker[]    — VAYU sensor pins
  heatmap_circles: [],      // L.Circle[]    — AQI heatmap overlays
  external_marker: null,    // L.Marker      — searched WAQI location pin
  sensor_data: null,        // cached /api/v1/sensors/map/ response
  sensor_data_ts: 0,        // timestamp of last fetch (ms)
  CACHE_TTL: 30_000,        // 30 s refresh while map is open
  refresh_timer: null,      // setInterval handle
  active: false,            // is map tab currently visible?
  layers: { pins: true, heatmap: true },  // visibility flags
  lastExternalResult: null,
};

/* ── AQI colour palette ────────────────────────────────────────── */
const MAP_AQI_COLORS = {
  'Good':        '#68d391',
  'Satisfactory':'#b7eb8f',
  'Moderate':    '#f6e05e',
  'Poor':        '#ed8936',
  'Very Poor':   '#fc8181',
  'Severe':      '#e53e3e',
  'N/A':         '#94a3b8',
  'Unavailable': '#94a3b8',
};

function mapAqiColor(category) {
  return MAP_AQI_COLORS[category] ?? '#94a3b8';
}

/* ── SVG pin icon ──────────────────────────────────────────────── */
function makeSensorIcon(category, status) {
  const color = mapAqiColor(category);
  const opacity = status === 'active' ? 1 : 0.55;
  const filterId = `drop-shadow-${encodeURIComponent(category)}`;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 32 40">
      <defs>
        <filter id="${filterId}" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="${color}" flood-opacity="0.5"/>
        </filter>
      </defs>
      <path d="M16 2C9.37 2 4 7.37 4 14c0 9.33 12 24 12 24s12-14.67 12-24C28 7.37 22.63 2 16 2z"
            fill="${color}" opacity="${opacity}"
            filter="url(#${filterId})"/>
      <circle cx="16" cy="14" r="5" fill="white" opacity="0.9"/>
    </svg>`;
  return L.divIcon({
    html: svg,
    className: '',
    iconSize: [32, 40],
    iconAnchor: [16, 40],
    popupAnchor: [0, -42],
  });
}

function makeExternalIcon() {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 32 40">
      <defs>
        <filter id="shadow-ext" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#64748b" flood-opacity="0.6"/>
        </filter>
      </defs>
      <path d="M16 2C9.37 2 4 7.37 4 14c0 9.33 12 24 12 24s12-14.67 12-24C28 7.37 22.63 2 16 2z"
            fill="#64748b" filter="url(#shadow-ext)"/>
      <text x="16" y="19" text-anchor="middle" font-family="Inter,sans-serif"
            font-size="10" font-weight="700" fill="white">W</text>
    </svg>`;
  return L.divIcon({
    html: svg,
    className: '',
    iconSize: [32, 40],
    iconAnchor: [16, 40],
    popupAnchor: [0, -42],
  });
}

/* ── Popup HTML builders ───────────────────────────────────────── */
function sensorPopupHtml(s) {
  const aqi   = s.aqi ?? '—';
  const cat   = s.aqi_category ?? 'N/A';
  const color = mapAqiColor(cat);
  const pm25  = s.pm25  != null ? parseFloat(s.pm25).toFixed(1)        : '—';
  const pm10  = s.pm10  != null ? parseFloat(s.pm10).toFixed(1)        : '—';
  const temp  = s.temperature != null ? parseFloat(s.temperature).toFixed(1) : '—';
  const hum   = s.humidity   != null ? parseFloat(s.humidity).toFixed(1)   : '—';
  const ts    = s.timestamp  ? new Date(s.timestamp).toLocaleString()   : '—';
  const dot   = `<span class="map-status-dot map-status-dot--${s.status}"></span>`;
  const isLive = s.data_source === 'live';
  const badgeClass = isLive ? 'map-popup-badge--live' : 'map-popup-badge--vayu';
  const badgeText = isLive ? 'Live WAQI Feed' : 'Simulated Demo';

  return `
    <div class="vayu-map-popup">
      <div class="map-popup-header">
        <div>
          <div class="map-popup-code">${dot}${s.sensor_code}</div>
          <div class="map-popup-loc">${s.location}</div>
        </div>
        <span class="map-popup-badge ${badgeClass}">${badgeText}</span>
      </div>
      <div class="map-popup-aqi" style="color:${color}">
        AQI <strong>${aqi}</strong>
        <span class="map-popup-cat" style="color:${color}">${cat}</span>
      </div>
      <div class="map-popup-grid">
        <div class="map-popup-metric"><span class="map-popup-mkey">PM2.5</span><span class="map-popup-mval">${pm25} <em>µg/m³</em></span></div>
        <div class="map-popup-metric"><span class="map-popup-mkey">PM10</span><span class="map-popup-mval">${pm10} <em>µg/m³</em></span></div>
        <div class="map-popup-metric"><span class="map-popup-mkey">Temp</span><span class="map-popup-mval">${temp} <em>°C</em></span></div>
        <div class="map-popup-metric"><span class="map-popup-mkey">Humidity</span><span class="map-popup-mval">${hum}<em>%</em></span></div>
      </div>
      <div class="map-popup-ts">Updated: ${ts}</div>
      <button class="map-popup-link" onclick="window._mapViewDetails(${s.id})">
        View Details →
      </button>
    </div>`;
}

function externalPopupHtml(result, query) {
  const aqi   = result.aqi  ?? '—';
  const cat   = result.category ?? 'N/A';
  const color = mapAqiColor(cat);
  const pm25  = result.pm25 != null ? parseFloat(result.pm25).toFixed(1)        : '—';
  const pm10  = result.pm10 != null ? parseFloat(result.pm10).toFixed(1)        : '—';
  const temp  = result.temperature != null ? parseFloat(result.temperature).toFixed(1) : '—';
  const station = result.station_name ?? query;
  const ts    = result.updated_at ? new Date(result.updated_at).toLocaleString() : '—';

  return `
    <div class="vayu-map-popup">
      <div class="map-popup-header">
        <div>
          <div class="map-popup-code">${station}</div>
          <div class="map-popup-loc">${query}</div>
        </div>
        <span class="map-popup-badge map-popup-badge--public">Public Data · WAQI</span>
      </div>
      <div class="map-popup-aqi" style="color:${color}">
        AQI <strong>${aqi}</strong>
        <span class="map-popup-cat" style="color:${color}">${cat}</span>
      </div>
      <div class="map-popup-grid">
        <div class="map-popup-metric"><span class="map-popup-mkey">PM2.5</span><span class="map-popup-mval">${pm25} <em>µg/m³</em></span></div>
        <div class="map-popup-metric"><span class="map-popup-mkey">PM10</span><span class="map-popup-mval">${pm10} <em>µg/m³</em></span></div>
        <div class="map-popup-metric"><span class="map-popup-mkey">Temp</span><span class="map-popup-mval">${temp} <em>°C</em></span></div>
      </div>
      <div class="map-popup-ts">Station data: ${ts}</div>
      <div class="map-popup-note">ⓘ Nearest public monitoring station</div>
    </div>`;
}

/* ── Map initialisation ────────────────────────────────────────── */
function initMap() {
  if (mapState.map) return;

  mapState.map = L.map('vayu-map', {
    center: [20.5937, 78.9629],
    zoom: 5,
    zoomControl: true,
    attributionControl: true,
  });

  L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    }
  ).addTo(mapState.map);
}

/* ── Fetch + render VAYU sensor markers + sidebar ─────────────── */
async function loadAndRenderSensors(force = false) {
  const now   = Date.now();
  const stale = now - mapState.sensor_data_ts > mapState.CACHE_TTL;

  if (!force && mapState.sensor_data && !stale) {
    renderSensorMarkers(mapState.sensor_data);
    renderMapSidebar(mapState.sensor_data);
    return;
  }

  try {
    const resp = await fetch(`/api/v1/sensors/map/?_t=${Date.now()}`, {
      credentials: 'same-origin',
      cache: 'no-cache',
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    mapState.sensor_data     = data;
    mapState.sensor_data_ts  = Date.now();
    renderSensorMarkers(data);
    renderMapSidebar(data);
  } catch (e) {
    console.warn('[VAYU Map] Failed to load sensor locations:', e);
  }
}

/* ── Render sensor pin markers + heatmap circles ──────────────── */
function renderSensorMarkers(sensors) {
  if (!mapState.map) return;

  // Remove existing layers
  mapState.vayu_markers.forEach(m => m.remove());
  mapState.heatmap_circles.forEach(c => c.remove());
  mapState.vayu_markers    = [];
  mapState.heatmap_circles = [];

  if (!sensors.length) return;

  sensors.forEach(s => {
    const color = mapAqiColor(s.aqi_category);
    const aqi   = s.aqi ?? 0;

    // ── Heatmap circle ─────────────────────────────────────────
    // Radius scaled by AQI: 0→25km, 500→90km (capped), 70% opacity fill
    const radiusM = Math.min(25000 + aqi * 130, 90000);
    const circle  = L.circle([s.latitude, s.longitude], {
      radius:      radiusM,
      color:       color,
      fillColor:   color,
      fillOpacity: 0.13,
      weight:      1.5,
      opacity:     0.35,
    }).addTo(mapState.map);
    circle.setStyle({ display: mapState.layers.heatmap ? '' : 'none' });
    if (!mapState.layers.heatmap) circle.remove();
    mapState.heatmap_circles.push(circle);

    // ── Pin marker ─────────────────────────────────────────────
    const icon   = makeSensorIcon(s.aqi_category, s.status);
    const marker = L.marker([s.latitude, s.longitude], { icon })
      .bindPopup(sensorPopupHtml(s), { maxWidth: 280, className: 'vayu-popup' })
      .addTo(mapState.map);

    // On popup open → update sidebar info panel
    marker.on('popupopen', () => showMapInfoPanel(s));
    marker.on('popupclose', () => clearMapInfoPanel());

    if (!mapState.layers.pins) marker.remove();
    mapState.vayu_markers.push(marker);
  });

  fitMapBounds();
  applyLayerVisibility();
}

/* ── Layer toggle ──────────────────────────────────────────────── */
window.mapToggleLayer = function(layer) {
  mapState.layers[layer] = !mapState.layers[layer];

  // Update button active state
  const btn = document.getElementById(`map-layer-${layer}`);
  if (btn) btn.classList.toggle('active', mapState.layers[layer]);

  applyLayerVisibility();
};

function applyLayerVisibility() {
  if (!mapState.map) return;
  mapState.vayu_markers.forEach(m => {
    if (mapState.layers.pins) {
      if (!mapState.map.hasLayer(m)) m.addTo(mapState.map);
    } else {
      if (mapState.map.hasLayer(m)) m.remove();
    }
  });
  mapState.heatmap_circles.forEach(c => {
    if (mapState.layers.heatmap) {
      if (!mapState.map.hasLayer(c)) c.addTo(mapState.map);
    } else {
      if (mapState.map.hasLayer(c)) c.remove();
    }
  });
}

/* ── Sidebar: fleet stats + sensor list ───────────────────────── */
function renderMapSidebar(sensors) {
  renderFleetStats(sensors);
  renderSensorList(sensors);
}

function renderFleetStats(sensors) {
  const active = sensors.filter(s => s.status === 'active');
  const withAqi = sensors.filter(s => s.aqi != null);

  const el = id => document.getElementById(id);

  // Active sensor count
  if (el('ms-active')) el('ms-active').textContent = active.length;

  // Fleet avg AQI
  if (el('ms-avg-aqi')) {
    if (withAqi.length) {
      const avg = Math.round(withAqi.reduce((sum, s) => sum + s.aqi, 0) / withAqi.length);
      el('ms-avg-aqi').textContent = avg;
      el('ms-avg-aqi').style.color = mapAqiColor(aqiCategory(avg));
    } else {
      el('ms-avg-aqi').textContent = '—';
    }
  }

  // Worst city (highest AQI)
  if (el('ms-worst') && withAqi.length) {
    const worst = withAqi.reduce((a, b) => (b.aqi > a.aqi ? b : a));
    el('ms-worst').textContent = shortLoc(worst.location);
    el('ms-worst').style.color = mapAqiColor(worst.aqi_category);
  }

  // Best city (lowest AQI)
  if (el('ms-best') && withAqi.length) {
    const best = withAqi.reduce((a, b) => (b.aqi < a.aqi ? b : a));
    el('ms-best').textContent = shortLoc(best.location);
    el('ms-best').style.color = mapAqiColor(best.aqi_category);
  }
}

function shortLoc(location) {
  // Trim long location strings: "Kolkata Park Street" → "Kolkata"
  return location ? location.split(',')[0].split(' ').slice(0, 2).join(' ') : '—';
}

function aqiCategory(aqi) {
  if (aqi <= 50)  return 'Good';
  if (aqi <= 100) return 'Satisfactory';
  if (aqi <= 200) return 'Moderate';
  if (aqi <= 300) return 'Poor';
  if (aqi <= 400) return 'Very Poor';
  return 'Severe';
}

function renderSensorList(sensors) {
  const list = document.getElementById('map-sensor-list');
  if (!list) return;

  if (!sensors.length) {
    list.innerHTML = `<div class="map-info-empty"><span>No sensors found</span></div>`;
    return;
  }

  list.innerHTML = sensors.map(s => {
    const color = mapAqiColor(s.aqi_category);
    const aqi   = s.aqi ?? '—';
    const isLive = s.data_source === 'live';
    const tagHtml = isLive
      ? `<span class="source-tag live">LIVE</span>`
      : `<span class="source-tag demo">DEMO</span>`;
    return `
      <div class="map-sensor-row" data-sensor-id="${s.id}"
           onclick="mapSidebarSelectSensor(${s.id})">
        <span class="map-sensor-dot map-sensor-dot--${s.status}"></span>
        <div class="map-sensor-info">
          <div class="map-sensor-code">${s.sensor_code}${tagHtml}</div>
          <div class="map-sensor-loc">${s.location}</div>
        </div>
        <span class="map-sensor-aqi-pill"
              style="color:${color};border-color:${color}40;background:${color}18">
          ${aqi}
        </span>
      </div>`;
  }).join('');
}

window.mapSidebarSelectSensor = function(id) {
  // Highlight the row
  document.querySelectorAll('.map-sensor-row').forEach(r =>
    r.classList.toggle('active', parseInt(r.dataset.sensorId) === id)
  );
  // Focus the map and open popup
  window.mapFocusVayuSensor(id);
};

/* ── Info panel (right sidebar bottom) ────────────────────────── */
function showMapInfoPanel(s) {
  const color = mapAqiColor(s.aqi_category);
  window._mapInfoSensorId = s.id;

  document.getElementById('map-info-empty').style.display  = 'none';
  document.getElementById('map-info-detail').style.display = '';

  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  const tag = s.data_source === 'live' ? ' [LIVE]' : ' [DEMO]';
  set('mi-code', `${s.sensor_code}${tag}`);
  set('mi-loc',  s.location);
  set('mi-aqi',  s.aqi ?? '—');
  set('mi-cat',  s.aqi_category ?? 'N/A');
  set('mi-pm25', s.pm25  != null ? parseFloat(s.pm25).toFixed(1)  : '—');
  set('mi-pm10', s.pm10  != null ? parseFloat(s.pm10).toFixed(1)  : '—');
  set('mi-temp', s.temperature != null ? parseFloat(s.temperature).toFixed(1) : '—');
  set('mi-hum',  s.humidity   != null ? parseFloat(s.humidity).toFixed(1)   : '—');
  set('mi-ts',   s.timestamp  ? `Updated: ${new Date(s.timestamp).toLocaleString()}` : '');

  const aqiEl = document.getElementById('mi-aqi');
  const catEl = document.getElementById('mi-cat');
  if (aqiEl) aqiEl.style.color = color;
  if (catEl) catEl.style.color = color;

  // Highlight matching sidebar row
  if (s.id != null) {
    document.querySelectorAll('.map-sensor-row').forEach(r =>
      r.classList.toggle('active', parseInt(r.dataset.sensorId) === s.id)
    );
  }
}

function clearMapInfoPanel() {
  document.getElementById('map-info-empty').style.display  = '';
  document.getElementById('map-info-detail').style.display = 'none';
  window._mapInfoSensorId = null;
  document.querySelectorAll('.map-sensor-row').forEach(r => r.classList.remove('active'));
}

/* ── Auto-fit bounds ───────────────────────────────────────────── */
function fitMapBounds() {
  if (!mapState.map) return;

  const allMarkers = [
    ...mapState.vayu_markers,
    ...(mapState.external_marker ? [mapState.external_marker] : []),
  ];

  if (!allMarkers.length) return;

  if (allMarkers.length === 1) {
    const ll = allMarkers[0].getLatLng();
    mapState.map.setView(ll, 12);
  } else {
    const group = L.featureGroup(allMarkers);
    mapState.map.fitBounds(group.getBounds().pad(0.15));
  }
}

/* ── External (WAQI) marker ────────────────────────────────────── */
window.mapDropExternalMarker = function(result, query) {
  mapState.lastExternalResult = { result, query };
  if (!mapState.map) return;

  if (mapState.external_marker) {
    mapState.external_marker.remove();
    mapState.external_marker = null;
  }

  const lat = result.latitude ?? result.lat;
  const lon = result.longitude ?? result.lon;
  if (lat == null || lon == null) return;

  mapState.external_marker = L.marker([lat, lon], { icon: makeExternalIcon() })
    .bindPopup(externalPopupHtml(result, query), { maxWidth: 280, className: 'vayu-popup' })
    .addTo(mapState.map);

  mapState.map.setView([lat, lon], 12);
  mapState.external_marker.openPopup();
};

window.mapClearExternalMarker = function() {
  mapState.lastExternalResult = null;
  if (mapState.external_marker) {
    mapState.external_marker.remove();
    mapState.external_marker = null;
  }
  fitMapBounds();
};

window.mapFocusVayuSensor = function(sensorId) {
  if (!mapState.map || !mapState.sensor_data) return;
  const match = mapState.sensor_data.find(s => s.id === sensorId);
  if (!match || match.latitude == null || match.longitude == null) return;
  mapState.map.setView([match.latitude, match.longitude], 12);
  const m = mapState.vayu_markers.find(marker => {
    const ll = marker.getLatLng();
    return Math.abs(ll.lat - match.latitude) < 0.0001 &&
           Math.abs(ll.lng - match.longitude) < 0.0001;
  });
  if (m) {
    if (!mapState.map.hasLayer(m)) m.addTo(mapState.map);
    m.openPopup();
  }
};

/* ── "View Details" — back to dashboard + select sensor ───────── */
window._mapViewDetails = function(sensorId) {
  switchView('dashboard');
  if (typeof window.selectSensor === 'function') {
    window.selectSensor(sensorId);
  }
};

/* ── View switcher (tab toggle) ────────────────────────────────── */
window.switchView = function(mode) {
  const dashPanel = document.getElementById('dashboard-view-panel');
  const mapPanel  = document.getElementById('map-view-panel');
  const btnDash   = document.getElementById('btn-dashboard-view');
  const btnMap    = document.getElementById('btn-map-view');

  if (mode === 'map') {
    dashPanel.style.display = 'none';
    mapPanel.style.display  = '';
    btnDash.classList.remove('active');
    btnMap.classList.add('active');
    mapState.active = true;

    initMap();
    setTimeout(() => { if (mapState.map) mapState.map.invalidateSize(); }, 50);

    loadAndRenderSensors().then(() => {
      if (mapState.lastExternalResult && !mapState.external_marker) {
        window.mapDropExternalMarker(
          mapState.lastExternalResult.result,
          mapState.lastExternalResult.query
        );
      }
    });

    if (!mapState.refresh_timer) {
      mapState.refresh_timer = setInterval(() => {
        if (mapState.active) loadAndRenderSensors(true);
      }, mapState.CACHE_TTL);
    }
  } else {
    mapPanel.style.display  = 'none';
    dashPanel.style.display = '';
    btnMap.classList.remove('active');
    btnDash.classList.add('active');
    mapState.active = false;
  }
};

/* ── Inject popup + toggle styles (self-contained) ────────────── */
(function injectMapStyles() {
  const style = document.createElement('style');
  style.textContent = `
    /* ── View-mode toggle ──────────────────────────────────────── */
    .view-mode-toggle {
      display: flex;
      gap: 6px;
      margin-bottom: 18px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 10px;
      padding: 4px;
      width: fit-content;
    }
    .view-mode-btn {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 7px 16px;
      border-radius: 7px;
      border: none;
      background: transparent;
      color: #94a3b8;
      font-family: 'Inter', sans-serif;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.18s, color 0.18s;
    }
    .view-mode-btn:hover { background: rgba(255,255,255,0.06); color: #e2e8f0; }
    .view-mode-btn.active { background: rgba(66,153,225,0.18); color: #63b3ed; }
    .view-mode-btn svg { flex-shrink: 0; }

    /* ── Leaflet popup — dark glassmorphism ─────────────────────── */
    .vayu-popup .leaflet-popup-content-wrapper {
      background: rgba(10,14,26,0.95) !important;
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255,255,255,0.10);
      border-radius: 12px !important;
      box-shadow: 0 8px 32px rgba(0,0,0,0.6) !important;
      padding: 0 !important;
    }
    .vayu-popup .leaflet-popup-content { margin: 0 !important; }
    .vayu-popup .leaflet-popup-tip-container { display: none !important; }
    .vayu-popup .leaflet-popup-close-button { color: #94a3b8 !important; font-size: 18px !important; top: 8px !important; right: 10px !important; }
    .vayu-popup .leaflet-popup-close-button:hover { color: #e2e8f0 !important; }

    /* ── Popup inner ─────────────────────────────────────────────── */
    .vayu-map-popup { font-family: 'Inter', sans-serif; color: #e2e8f0; padding: 14px 16px 12px; min-width: 220px; }
    .map-popup-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 10px; }
    .map-popup-code { font-size: 14px; font-weight: 700; color: #f1f5f9; display: flex; align-items: center; gap: 6px; }
    .map-popup-loc { font-size: 11px; color: #94a3b8; margin-top: 2px; }
    .map-popup-badge { font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 20px; white-space: nowrap; flex-shrink: 0; }
    .map-popup-badge--vayu   { background: rgba(72,199,131,0.15); color: #48c783; border: 1px solid rgba(72,199,131,0.3); }
    .map-popup-badge--public { background: rgba(99,179,237,0.12); color: #63b3ed; border: 1px solid rgba(99,179,237,0.25); }
    .map-popup-aqi { font-size: 22px; font-weight: 800; margin-bottom: 10px; display: flex; align-items: baseline; gap: 10px; }
    .map-popup-cat { font-size: 12px; font-weight: 600; }
    .map-popup-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 8px; margin-bottom: 8px; }
    .map-popup-metric { display: flex; flex-direction: column; gap: 1px; }
    .map-popup-mkey { font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
    .map-popup-mval { font-size: 13px; font-weight: 600; color: #e2e8f0; }
    .map-popup-mval em { font-style: normal; font-size: 10px; color: #94a3b8; margin-left: 2px; }
    .map-popup-ts   { font-size: 10px; color: #475569; margin-bottom: 10px; }
    .map-popup-note { font-size: 10px; color: #475569; margin-top: -4px; margin-bottom: 4px; }
    .map-popup-link { width: 100%; padding: 8px 0; background: rgba(66,153,225,0.15); border: 1px solid rgba(66,153,225,0.3); border-radius: 8px; color: #63b3ed; font-family: 'Inter', sans-serif; font-size: 12px; font-weight: 600; cursor: pointer; transition: background 0.18s; }
    .map-popup-link:hover { background: rgba(66,153,225,0.28); }

    /* ── Status dot in popup ─────────────────────────────────────── */
    .map-status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
    .map-status-dot--active      { background: #68d391; box-shadow: 0 0 6px #68d391; }
    .map-status-dot--inactive    { background: #718096; }
    .map-status-dot--maintenance { background: #ecc94b; }
  `;
  document.head.appendChild(style);
})();
