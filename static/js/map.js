/**
 * map.js — VAYU Interactive Map View (Leaflet + OpenStreetMap/CartoDB)
 * ====================================================================
 * Manages the "Map View" tab independently from dashboard.js.
 * Communicates with dashboard.js only via:
 *   - window.switchView(mode)  — exported by this file, called from HTML onclick
 *   - mapState.lastExternalResult — set by dashboard.js hook to push searched
 *     external WAQI results onto the map
 *
 * Data flows:
 *   1. On first map-tab open: fetch /api/v1/sensors/map/ → place VAYU markers
 *   2. Cache result session-side; refresh every 30s while map tab is active
 *   3. When dashboard.js resolves an external search, call
 *      window.mapDropExternalMarker(result, query) to add the WAQI pin
 *
 * No API key required:
 *   CartoDB Dark tiles → https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png
 */

/* ── Map state ────────────────────────────────────────────────── */
const mapState = {
  map: null,
  vayu_markers: [],         // L.Marker[]  — VAYU sensor pins
  external_marker: null,    // L.Marker    — searched WAQI location pin
  sensor_data: null,        // cached /api/v1/sensors/map/ response
  sensor_data_ts: 0,        // timestamp of last fetch (ms)
  CACHE_TTL: 30_000,        // 30 s refresh while map is open
  refresh_timer: null,      // setInterval handle
  active: false,            // is map tab currently visible?
};

/* ── AQI color palette (mirrors CPCB_COLORS in dashboard.js) ─── */
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

/* ── SVG circle marker icon factory ──────────────────────────── */
function makeSensorIcon(category, status) {
  const color = mapAqiColor(category);
  // dim inactive/maintenance sensors slightly
  const opacity = status === 'active' ? 1 : 0.55;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 32 40">
      <defs>
        <filter id="drop-shadow-${encodeURIComponent(category)}" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="${color}" flood-opacity="0.5"/>
        </filter>
      </defs>
      <!-- Pin shape -->
      <path d="M16 2C9.37 2 4 7.37 4 14c0 9.33 12 24 12 24s12-14.67 12-24C28 7.37 22.63 2 16 2z"
            fill="${color}" opacity="${opacity}"
            filter="url(#drop-shadow-${encodeURIComponent(category)})"/>
      <!-- Inner white circle -->
      <circle cx="16" cy="14" r="5" fill="white" opacity="0.9"/>
    </svg>`;
  return L.divIcon({
    html: svg,
    className: '',  // suppress default Leaflet classes
    iconSize: [32, 40],
    iconAnchor: [16, 40],
    popupAnchor: [0, -42],
  });
}

function makeExternalIcon() {
  // Gray pin with a search-glass icon for WAQI external results
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 32 40">
      <defs>
        <filter id="shadow-ext" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#64748b" flood-opacity="0.6"/>
        </filter>
      </defs>
      <path d="M16 2C9.37 2 4 7.37 4 14c0 9.33 12 24 12 24s12-14.67 12-24C28 7.37 22.63 2 16 2z"
            fill="#64748b" filter="url(#shadow-ext)"/>
      <!-- W letter for WAQI -->
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
  const aqi = s.aqi ?? '—';
  const cat = s.aqi_category ?? 'N/A';
  const color = mapAqiColor(cat);
  const pm25 = s.pm25 != null ? parseFloat(s.pm25).toFixed(1) : '—';
  const pm10 = s.pm10 != null ? parseFloat(s.pm10).toFixed(1) : '—';
  const temp = s.temperature != null ? parseFloat(s.temperature).toFixed(1) : '—';
  const hum  = s.humidity != null ? parseFloat(s.humidity).toFixed(1) : '—';
  const ts   = s.timestamp ? new Date(s.timestamp).toLocaleString() : '—';
  const statusDot = `<span class="map-status-dot map-status-dot--${s.status}"></span>`;

  return `
    <div class="vayu-map-popup">
      <div class="map-popup-header">
        <div>
          <div class="map-popup-code">${statusDot}${s.sensor_code}</div>
          <div class="map-popup-loc">${s.location}</div>
        </div>
        <span class="map-popup-badge map-popup-badge--vayu">VAYU Sensor</span>
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
  const aqi  = result.aqi ?? '—';
  const cat  = result.category ?? 'N/A';
  const color = mapAqiColor(cat);
  const pm25 = result.pm25 != null ? parseFloat(result.pm25).toFixed(1) : '—';
  const pm10 = result.pm10 != null ? parseFloat(result.pm10).toFixed(1) : '—';
  const temp = result.temperature != null ? parseFloat(result.temperature).toFixed(1) : '—';
  const station = result.station_name ?? query;
  const ts = result.updated_at ? new Date(result.updated_at).toLocaleString() : '—';

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
  if (mapState.map) return;   // already initialised

  mapState.map = L.map('vayu-map', {
    center: [20.5937, 78.9629],   // centre of India
    zoom: 5,
    zoomControl: true,
    attributionControl: true,
  });

  // CartoDB Dark (matches VAYU glassmorphism dark theme)
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

/* ── Fetch + render VAYU sensor markers ──────────────────────── */
async function loadAndRenderSensors(force = false) {
  const now = Date.now();
  const stale = now - mapState.sensor_data_ts > mapState.CACHE_TTL;

  if (!force && mapState.sensor_data && !stale) {
    // Already fresh — just re-render (e.g. tab revisit)
    renderSensorMarkers(mapState.sensor_data);
    return;
  }

  try {
    const resp = await fetch('/api/v1/sensors/map/', {
      credentials: 'same-origin',
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    mapState.sensor_data = data;
    mapState.sensor_data_ts = Date.now();
    renderSensorMarkers(data);
  } catch (e) {
    console.warn('[VAYU Map] Failed to load sensor locations:', e);
  }
}

function renderSensorMarkers(sensors) {
  if (!mapState.map) return;

  // Remove existing VAYU markers
  mapState.vayu_markers.forEach(m => m.remove());
  mapState.vayu_markers = [];

  if (!sensors.length) return;

  sensors.forEach(s => {
    const icon = makeSensorIcon(s.aqi_category, s.status);
    const marker = L.marker([s.latitude, s.longitude], { icon })
      .bindPopup(sensorPopupHtml(s), { maxWidth: 280, className: 'vayu-popup' })
      .addTo(mapState.map);
    mapState.vayu_markers.push(marker);
  });

  fitMapBounds();
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

/* ── External (WAQI) marker ─────────────────────────────────────
   Called by dashboard.js after a successful external search.     */
window.mapDropExternalMarker = function(result, query) {
  mapState.lastExternalResult = { result, query };
  if (!mapState.map) return;    // map not initialised yet — will be rendered in switchView

  // Remove previous external pin if any
  if (mapState.external_marker) {
    mapState.external_marker.remove();
    mapState.external_marker = null;
  }

  // External results may carry latitude/longitude from WAQI uid feed
  const lat = result.latitude ?? result.lat;
  const lon = result.longitude ?? result.lon;
  if (lat == null || lon == null) return;   // no coordinates — can't place pin

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
    return Math.abs(ll.lat - match.latitude) < 0.0001 && Math.abs(ll.lng - match.longitude) < 0.0001;
  });
  if (m) m.openPopup();
};

/* ── "View Details" button from popup ───────────────────────────
   Switches back to dashboard tab and selects that sensor.        */
window._mapViewDetails = function(sensorId) {
  switchView('dashboard');
  if (typeof window.selectSensor === 'function') {
    window.selectSensor(sensorId);
  }
};

/* ── View switcher (tab toggle) ─────────────────────────────── */
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

    // Initialise Leaflet lazily on first open (avoids 0-size tile glitch)
    initMap();
    // Force Leaflet to recalculate size after the container becomes visible
    setTimeout(() => {
      if (mapState.map) mapState.map.invalidateSize();
    }, 50);

    // Load (or refresh) sensor data
    loadAndRenderSensors().then(() => {
      // If an external search result was pending, drop it onto the map now
      if (mapState.lastExternalResult && !mapState.external_marker) {
        window.mapDropExternalMarker(
          mapState.lastExternalResult.result,
          mapState.lastExternalResult.query
        );
      }
    });

    // Start periodic refresh while map is open
    if (!mapState.refresh_timer) {
      mapState.refresh_timer = setInterval(() => {
        if (mapState.active) loadAndRenderSensors(true);
      }, mapState.CACHE_TTL);
    }
  } else {
    // Back to dashboard
    mapPanel.style.display  = 'none';
    dashPanel.style.display = '';
    btnMap.classList.remove('active');
    btnDash.classList.add('active');
    mapState.active = false;

    // Don't clear the refresh timer — pause it via the mapState.active guard above
  }
};

/* ── Inject popup + toggle styles ───────────────────────────────
   We add CSS here (not a separate file) to keep the map feature
   fully self-contained in one file.                              */
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
    .view-mode-btn:hover {
      background: rgba(255,255,255,0.06);
      color: #e2e8f0;
    }
    .view-mode-btn.active {
      background: rgba(66,153,225,0.18);
      color: #63b3ed;
    }
    .view-mode-btn svg {
      flex-shrink: 0;
    }

    /* ── Leaflet popup override — dark glassmorphism ─────────────── */
    .vayu-popup .leaflet-popup-content-wrapper {
      background: rgba(10, 14, 26, 0.95) !important;
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255,255,255,0.10);
      border-radius: 12px !important;
      box-shadow: 0 8px 32px rgba(0,0,0,0.6) !important;
      padding: 0 !important;
    }
    .vayu-popup .leaflet-popup-content {
      margin: 0 !important;
    }
    .vayu-popup .leaflet-popup-tip-container {
      display: none !important;
    }
    .vayu-popup .leaflet-popup-close-button {
      color: #94a3b8 !important;
      font-size: 18px !important;
      top: 8px !important;
      right: 10px !important;
    }
    .vayu-popup .leaflet-popup-close-button:hover {
      color: #e2e8f0 !important;
    }

    /* ── Popup inner layout ─────────────────────────────────────── */
    .vayu-map-popup {
      font-family: 'Inter', sans-serif;
      color: #e2e8f0;
      padding: 14px 16px 12px;
      min-width: 220px;
    }
    .map-popup-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
      margin-bottom: 10px;
    }
    .map-popup-code {
      font-size: 14px;
      font-weight: 700;
      color: #f1f5f9;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .map-popup-loc {
      font-size: 11px;
      color: #94a3b8;
      margin-top: 2px;
    }
    .map-popup-badge {
      font-size: 10px;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 20px;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .map-popup-badge--vayu {
      background: rgba(72,199,131,0.15);
      color: #48c783;
      border: 1px solid rgba(72,199,131,0.3);
    }
    .map-popup-badge--public {
      background: rgba(99,179,237,0.12);
      color: #63b3ed;
      border: 1px solid rgba(99,179,237,0.25);
    }
    .map-popup-aqi {
      font-size: 22px;
      font-weight: 800;
      margin-bottom: 10px;
      display: flex;
      align-items: baseline;
      gap: 10px;
    }
    .map-popup-cat {
      font-size: 12px;
      font-weight: 600;
    }
    .map-popup-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px 8px;
      margin-bottom: 8px;
    }
    .map-popup-metric {
      display: flex;
      flex-direction: column;
      gap: 1px;
    }
    .map-popup-mkey {
      font-size: 10px;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .map-popup-mval {
      font-size: 13px;
      font-weight: 600;
      color: #e2e8f0;
    }
    .map-popup-mval em {
      font-style: normal;
      font-size: 10px;
      color: #94a3b8;
      margin-left: 2px;
    }
    .map-popup-ts {
      font-size: 10px;
      color: #475569;
      margin-bottom: 10px;
    }
    .map-popup-note {
      font-size: 10px;
      color: #475569;
      margin-top: -4px;
      margin-bottom: 4px;
    }
    .map-popup-link {
      width: 100%;
      padding: 8px 0;
      background: rgba(66,153,225,0.15);
      border: 1px solid rgba(66,153,225,0.3);
      border-radius: 8px;
      color: #63b3ed;
      font-family: 'Inter', sans-serif;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.18s;
    }
    .map-popup-link:hover {
      background: rgba(66,153,225,0.28);
    }

    /* ── Sensor status dot in popup ─────────────────────────────── */
    .map-status-dot {
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .map-status-dot--active      { background: #68d391; box-shadow: 0 0 6px #68d391; }
    .map-status-dot--inactive    { background: #718096; }
    .map-status-dot--maintenance { background: #ecc94b; }
  `;
  document.head.appendChild(style);
})();
