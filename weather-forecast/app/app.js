/* Local Weather — Windy-style viewer for FourCastNetv2 forecasts
 * Local layers:  temperature / precip / pressure / moisture PNG frames + wind particle JSON
 *                (precip: IFS open data for forecasts, ERA5 for past days)
 * Live layers:   RainViewer radar tiles, Open-Meteo air quality
 */
"use strict";

const state = {
  timeline: null,      // active timeline (forecast or event)
  dataset: "forecast", // 'forecast' | 'event'
  event: null,         // active event object from events.json
  product: "2t",       // '2t' | 'tp' | 'msl' | 'tcwv' | 'radar' | 'aq'
  windOn: true,
  isobarsOn: false,
  stepIdx: 0,          // forecast step index
  radarIdx: 0,
  playing: false,
  playTimer: null,
};
let forecastTimeline = null;   // kept so Exit history can restore it

function framesBase() {
  return state.dataset === "event" ? "frames_event" : "frames";
}

const map = L.map("map", {
  zoomControl: false,
  worldCopyJump: true,          // re-center across date-line crossings...
  // ...invisibly, because every overlay below is drawn 3x (lng ±360)
  // keep the world tall enough to fill the window - no gray void above the
  // poles - and stop vertical panning at the map edge
  minZoom: Math.max(2, Math.ceil(Math.log2(window.innerHeight / 256))),
  maxBounds: [[-85.06, -Infinity], [85.06, Infinity]],
  maxBoundsViscosity: 1.0,
}).setView([39.1, -94.6], 5);
L.control.zoom({ position: "bottomright" }).addTo(map);
// worldCopyJump only re-centers on drags; catch every other way of drifting a
// world away (inertia, flyTo, keyboard). The snap is invisible: identical
// overlay copies exist at ±360.
map.on("moveend", () => {
  const c = map.getCenter();
  if (Math.abs(c.lng) > 180) {
    map.panTo([c.lat, L.Util.wrapNum(c.lng, [-180, 180], true)], { animate: false });
  }
});
// Base without labels; labels drawn separately in a pane ABOVE the weather
// overlays and brightened to white via CSS (see .labels-pane in style.css) —
// keeps city names readable on top of temperature/precipitation layers.
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; OpenStreetMap &copy; CARTO | forecast: local FourCastNetv2',
  subdomains: "abcd", maxZoom: 19,
}).addTo(map);
map.createPane("labels").classList.add("labels-pane");
map.getPane("labels").style.zIndex = 450;   // above overlays (400), below markers (600)
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png", {
  subdomains: "abcd", maxZoom: 19, pane: "labels",
}).addTo(map);

/* ---------- state/country borders (above overlays, below labels) ---------- */
map.createPane("borders").style.zIndex = 430;
const borderRenderer = L.canvas({ pane: "borders" });
// draw each set at lng -360/0/+360 so borders stay visible while panning
// across the date line (GeoJSON, unlike tiles, doesn't repeat on its own)
function shiftCoords(c, dx) {
  return typeof c[0] === "number" ? [c[0] + dx, c[1]] : c.map(x => shiftCoords(x, dx));
}
async function addBorders(url, style) {
  const gj = await (await fetch(url)).json();
  for (const dx of [-360, 0, 360]) {
    const copy = dx === 0 ? gj : {
      type: "FeatureCollection",
      features: gj.features.map(f => ({
        type: "Feature", properties: {},
        geometry: { type: f.geometry.type,
                    coordinates: shiftCoords(f.geometry.coordinates, dx) },
      })),
    };
    L.geoJSON(copy, { style, renderer: borderRenderer, interactive: false }).addTo(map);
  }
}
addBorders("borders/countries.json", { color: "#ffffff", weight: 1.1, opacity: 0.55 });
addBorders("borders/us_states.json", { color: "#ffffff", weight: 0.8, opacity: 0.4 });

/* ---------- local forecast overlays (PNG frames) ---------- */
// three copies of every frame (lng ±360) make panning across the date line
// seamless - the overlay never runs out and worldCopyJump's re-center is invisible
const scalarOverlays = [-360, 0, 360].map(dx =>
  L.imageOverlay("", [[-90, -180 + dx], [90, 180 + dx]], { opacity: 0.65 }));
const scalarGroup = L.layerGroup(scalarOverlays);
const frameCache = {};            // url -> Image (preload)

function frameUrl(product, idx) {
  const h = String(state.timeline.steps[idx]).padStart(3, "0");
  // ?v= busts stale browser cache: event/day loads reuse the same file names
  // in frames_event/ but hold different data each time
  return `${framesBase()}/${product}/${product}_+${h}h.png?v=${encodeURIComponent(state.timeline.init_time)}`;
}
function preloadFrames(product) {
  state.timeline.steps.forEach((_, i) => {
    const url = frameUrl(product, i);
    if (!frameCache[url]) { const im = new Image(); im.src = url; frameCache[url] = im; }
  });
}

/* ---------- isobar overlay (MSL pressure contour PNGs) ---------- */
// own pane above the color layers (400) and borders (430), below labels (450)
map.createPane("isobars").style.zIndex = 435;
const isobarOverlays = [-360, 0, 360].map(dx =>
  L.imageOverlay("", [[-90, -180 + dx], [90, 180 + dx]],
                 { opacity: 0.9, pane: "isobars" }));
const isobarGroup = L.layerGroup(isobarOverlays);

// isobars are contoured from the same msl field as the pressure layer, so
// they exist exactly when the active timeline rendered msl (forecasts and
// events always; past days loaded before msl was added to the fetch: no)
function isobarsAvailable() {
  return !!(state.timeline && state.timeline.vars.msl);
}
function updateIsobars() {
  isobarBtn.disabled = !isobarsAvailable();
  if (!state.isobarsOn || !isobarsAvailable()) {
    map.removeLayer(isobarGroup);
    return;
  }
  const url = frameUrl("isobars", state.stepIdx);
  isobarOverlays.forEach(o => o.setUrl(url));
  if (!map.hasLayer(isobarGroup)) isobarGroup.addTo(map);
}
const isobarBtn = document.getElementById("isobarToggle");
isobarBtn.addEventListener("click", () => {
  state.isobarsOn = !state.isobarsOn;
  isobarBtn.classList.toggle("active", state.isobarsOn);
  if (state.isobarsOn) preloadFrames("isobars");
  updateIsobars();
});

/* ---------- wind particles ---------- */
let velocityLayer = null;
const windCache = {};

async function windData(idx) {
  const h = String(state.timeline.steps[idx]).padStart(3, "0");
  const url = `${framesBase()}/wind/wind_+${h}h.json?v=${encodeURIComponent(state.timeline.init_time)}`;
  if (!windCache[url]) windCache[url] = await (await fetch(url)).json();
  return windCache[url];
}
async function updateWind() {
  if (!state.windOn || !state.timeline) return;
  const data = await windData(state.stepIdx);
  if (!velocityLayer) {
    velocityLayer = L.velocityLayer({
      data,
      maxVelocity: 25,
      velocityScale: 0.008,
      lineWidth: 1.5,
      colorScale: ["#9db8d8", "#b9d2ea", "#dbeafe", "#ffffff"],
      displayValues: true,
      displayOptions: {
        velocityType: "wind", speedUnit: "m/s", position: "bottomleft",
        emptyString: "move mouse over map for wind speed",
      },
    }).addTo(map);
  } else {
    velocityLayer.setData(data);
    if (!map.hasLayer(velocityLayer)) velocityLayer.addTo(map);
  }
}

/* ---------- RainViewer live radar ---------- */
let radarFrames = [];             // [{time, layer}]
let radarLoaded = false;

async function loadRadar() {
  if (radarLoaded) return;
  const meta = await (await fetch("https://api.rainviewer.com/public/weather-maps.json")).json();
  const frames = [...meta.radar.past, ...meta.radar.nowcast];
  radarFrames = frames.map(f => ({
    time: f.time,
    nowcast: meta.radar.nowcast.includes(f),
    layer: L.tileLayer(`${meta.host}${f.path}/256/{z}/{x}/{y}/2/1_1.png`,
      { opacity: 0, tileSize: 256, zIndex: 400 }),
  }));
  state.radarIdx = meta.radar.past.length - 1;   // most recent observation
  radarLoaded = true;
}
function preloadRadar() {
  // add every frame to the map up front (opacity 0) so all tiles fetch now
  // and play animates smoothly instead of blanking while each frame loads
  radarFrames.forEach(f => { if (!map.hasLayer(f.layer)) f.layer.addTo(map); });
}
function showRadarFrame(idx) {
  radarFrames.forEach((f, i) => f.layer.setOpacity(i === idx ? 0.8 : 0));
}
function hideRadar() {
  radarFrames.forEach(f => { if (map.hasLayer(f.layer)) map.removeLayer(f.layer); });
}

/* ---------- Open-Meteo air quality ---------- */
const aqGroup = L.layerGroup();
let aqTimer = null;

function aqColor(aqi) {
  if (aqi <= 50) return "#4ade80";
  if (aqi <= 100) return "#facc15";
  if (aqi <= 150) return "#fb923c";
  if (aqi <= 200) return "#ef4444";
  if (aqi <= 300) return "#a855f7";
  return "#7f1d1d";
}
async function refreshAQ() {
  const b = map.getBounds();
  const lats = [], lons = [];
  const NX = 8, NY = 5;
  for (let j = 0; j < NY; j++)
    for (let i = 0; i < NX; i++) {
      lats.push((b.getSouth() + (j + 0.5) * (b.getNorth() - b.getSouth()) / NY).toFixed(2));
      lons.push((b.getWest() + (i + 0.5) * (b.getEast() - b.getWest()) / NX).toFixed(2));
    }
  const url = "https://air-quality-api.open-meteo.com/v1/air-quality" +
    `?latitude=${lats.join(",")}&longitude=${lons.join(",")}` +
    "&current=us_aqi,pm2_5,pm10,ozone";
  let results = await (await fetch(url)).json();
  if (!Array.isArray(results)) results = [results];
  aqGroup.clearLayers();
  results.forEach(r => {
    if (!r.current || r.current.us_aqi == null) return;
    const aqi = Math.round(r.current.us_aqi);
    L.marker([r.latitude, r.longitude], {
      icon: L.divIcon({
        className: "aq-marker",
        html: `<div class="aq-marker" style="width:34px;height:34px;line-height:34px;background:${aqColor(aqi)};opacity:.88">${aqi}</div>`,
        iconSize: [34, 34],
      }),
    }).bindPopup(
      `<b>US AQI: ${aqi}</b><br>PM2.5: ${r.current.pm2_5} µg/m³<br>` +
      `PM10: ${r.current.pm10} µg/m³<br>Ozone: ${r.current.ozone} µg/m³`
    ).addTo(aqGroup);
  });
}
map.on("moveend", () => {
  if (state.product !== "aq") return;
  clearTimeout(aqTimer);
  aqTimer = setTimeout(refreshAQ, 600);
});

/* ---------- product switching ---------- */
const slider = document.getElementById("timeSlider");
const timeLabel = document.getElementById("timeLabel");
const legend = document.getElementById("legend");

function fmtValid(iso) {
  const d = new Date(iso + (iso.endsWith("Z") ? "" : "Z"));
  return d.toLocaleString("en-US", {
    weekday: "short", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC",
  }) + " UTC";
}

function renderScalar() {
  const url = frameUrl(state.product, state.stepIdx);
  scalarOverlays.forEach(o => o.setUrl(url));
  if (!map.hasLayer(scalarGroup)) scalarGroup.addTo(map);
}

function updateTimeUI() {
  if (state.product === "radar") {
    slider.max = Math.max(radarFrames.length - 1, 0);
    slider.value = state.radarIdx;
    slider.disabled = false;
    const f = radarFrames[state.radarIdx];
    if (f) timeLabel.textContent =
      (f.nowcast ? "nowcast " : "radar ") + fmtValid(new Date(f.time * 1000).toISOString().slice(0, 16));
  } else if (state.product === "aq") {
    slider.disabled = true;
    timeLabel.textContent = "current conditions";
  } else {
    slider.max = state.timeline.steps.length - 1;
    slider.value = state.stepIdx;
    slider.disabled = false;
    timeLabel.textContent =
      `+${state.timeline.steps[state.stepIdx]}h · ${fmtValid(state.timeline.valid_times[state.stepIdx])}`;
  }
}

function renderLegend() {
  if (state.product === "radar") {
    legend.innerHTML = `<div class="title">Radar reflectivity</div>
      <div class="bar" style="background:linear-gradient(to right,#88f,#0f0,#ff0,#f80,#f00,#f0f)"></div>
      <div class="ticks"><span>light</span><span>heavy</span></div>
      <div style="color:#8fa3c0;margin-top:4px">RainViewer · past 2h + nowcast</div>`;
  } else if (state.product === "aq") {
    legend.innerHTML = `<div class="title">US Air Quality Index</div>
      <div class="bar" style="background:linear-gradient(to right,#4ade80,#facc15,#fb923c,#ef4444,#a855f7)"></div>
      <div class="ticks"><span>0</span><span>150</span><span>300+</span></div>
      <div style="color:#8fa3c0;margin-top:4px">Open-Meteo (CAMS)</div>`;
  } else {
    const v = state.timeline.vars[state.product];
    const grad = v.gradient.join(",");
    const src = state.dataset === "event"
      ? "ERA5 reanalysis · ECMWF/Copernicus" : "FourCastNetv2 · local GPU";
    legend.innerHTML = `<div class="title">${v.label} (${v.units})</div>
      <div class="bar" style="background:linear-gradient(to right,${grad})"></div>
      <div class="ticks">${v.ticks.map(t => `<span>${t}</span>`).join("")}</div>
      <div style="color:#8fa3c0;margin-top:4px">${src}</div>`;
  }
}

// which products the current dataset supports: radar/AQ are live-only, scalar
// layers only exist if the active timeline rendered them (forecast precip
// comes from IFS open data, so an old run without a tp fetch lacks the layer)
function productAvailable(p) {
  if (p === "radar" || p === "aq") return state.dataset === "forecast";
  return !!(state.timeline && state.timeline.vars[p]);
}
function updateProductButtons() {
  document.querySelectorAll("#panel .product").forEach(b => {
    b.disabled = !productAvailable(b.dataset.product);
  });
}

async function setProduct(product) {
  if (!productAvailable(product)) return;
  state.product = product;
  document.querySelectorAll("#panel .product").forEach(b =>
    b.classList.toggle("active", b.dataset.product === product));
  stopPlay();

  map.removeLayer(aqGroup); hideRadar();
  if (product === "radar") {
    map.removeLayer(scalarGroup);
    await loadRadar();
    preloadRadar();
    showRadarFrame(state.radarIdx);
  } else if (product === "aq") {
    map.removeLayer(scalarGroup);
    aqGroup.addTo(map);
    await refreshAQ();
  } else {
    preloadFrames(product);
    renderScalar();
  }
  updateIsobars();   // dataset may have changed under us (event/day/forecast)
  renderLegend();
  updateTimeUI();
}

/* ---------- time control ---------- */
function setStep(idx) {
  if (state.product === "radar") {
    state.radarIdx = idx;
    showRadarFrame(idx);
  } else {
    state.stepIdx = idx;
    renderScalar();
    updateWind();
    updateIsobars();
  }
  updateTimeUI();
}
slider.addEventListener("input", e => setStep(+e.target.value));

/* ---------- layer buttons ---------- */
document.querySelectorAll("#panel .product").forEach(b =>
  b.addEventListener("click", () => setProduct(b.dataset.product)));

const playBtn = document.getElementById("playBtn");
function stopPlay() {
  state.playing = false; playBtn.textContent = "▶";
  clearInterval(state.playTimer);
}
playBtn.addEventListener("click", () => {
  if (state.playing) { stopPlay(); return; }
  if (state.product === "aq") return;
  state.playing = true; playBtn.textContent = "⏸";
  state.playTimer = setInterval(() => {
    const n = +slider.max + 1;
    setStep((+slider.value + 1) % n);
  }, state.product === "radar" ? 450 : 700);
});

/* ---------- wind toggle ---------- */
const windBtn = document.getElementById("windToggle");
windBtn.addEventListener("click", () => {
  state.windOn = !state.windOn;
  windBtn.classList.toggle("active", state.windOn);
  if (state.windOn) updateWind();
  else if (velocityLayer) map.removeLayer(velocityLayer);
});

/* ---------- click popup: Open-Meteo point conditions ---------- */
map.on("click", async e => {
  if (state.product === "aq") return;   // AQ markers have their own popups
  const { lat, lng } = e.latlng;
  const popup = L.popup().setLatLng(e.latlng).setContent("Loading…").openOn(map);
  try {
    const url = "https://api.open-meteo.com/v1/forecast" +
      `?latitude=${lat.toFixed(3)}&longitude=${lng.toFixed(3)}` +
      "&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m,weather_code" +
      "&temperature_unit=fahrenheit&wind_speed_unit=mph";
    const r = await (await fetch(url)).json();
    const c = r.current;
    const dirs = ["N","NE","E","SE","S","SW","W","NW"];
    popup.setContent(
      `<div class="popup-temp">${Math.round(c.temperature_2m)}°F</div>` +
      `Humidity: ${c.relative_humidity_2m}%<br>` +
      `Wind: ${Math.round(c.wind_speed_10m)} mph ${dirs[Math.round(c.wind_direction_10m / 45) % 8]}<br>` +
      `Precip (last hr): ${c.precipitation} mm<br>` +
      `<span style="color:#888">${lat.toFixed(2)}, ${lng.toFixed(2)} · Open-Meteo</span>`
    );
  } catch { popup.setContent("Point data unavailable (offline?)"); }
});

/* ---------- city search + 6-day forecast card ---------- */
const cityInput = document.getElementById("cityInput");
const searchResults = document.getElementById("searchResults");
const cityCard = document.getElementById("cityForecast");
let searchTimer = null;
let cityMarker = null;
let lastCity = null;   // so the card can refresh when entering/exiting a past day

// WMO weather codes -> emoji
function wmoIcon(code) {
  if (code === 0) return "☀️";
  if (code <= 2) return "🌤️";
  if (code === 3) return "☁️";
  if (code <= 48) return "🌫️";
  if (code <= 57) return "🌦️";
  if (code <= 67) return "🌧️";
  if (code <= 77) return "❄️";
  if (code <= 82) return "🌧️";
  if (code <= 86) return "🌨️";
  return "⛈️";
}

async function searchCities(q) {
  const url = "https://geocoding-api.open-meteo.com/v1/search" +
    `?name=${encodeURIComponent(q)}&count=6&language=en`;
  const r = await (await fetch(url)).json();
  return r.results || [];
}

function renderResults(items) {
  searchResults.innerHTML = "";
  items.forEach(c => {
    const div = document.createElement("div");
    div.className = "search-item";
    const sub = [c.admin1, c.country].filter(Boolean).join(", ");
    div.innerHTML = `${c.name} <span class="sub">${sub}</span>`;
    div.addEventListener("click", () => selectCity(c));
    searchResults.appendChild(div);
  });
}

async function selectCity(c) {
  searchResults.innerHTML = "";
  cityInput.value = c.name;
  lastCity = c;
  map.flyTo([c.latitude, c.longitude], 8, { duration: 1.2 });
  if (cityMarker) map.removeLayer(cityMarker);
  cityMarker = L.marker([c.latitude, c.longitude]).addTo(map);
  // while studying a past day, the card shows that day at this city instead
  // of the upcoming 6-day forecast
  if (state.dataset === "event" && state.event?.day) {
    await showCityDayRundown(c, state.event.start);
  } else {
    await showCityForecast(c);
  }
}

/* rundown of the studied past day at a city — Open-Meteo historical archive
   (same ERA5 reanalysis the map layers come from; free, no key) */
async function showCityDayRundown(c, dateStr) {
  const url = "https://archive-api.open-meteo.com/v1/archive" +
    `?latitude=${c.latitude}&longitude=${c.longitude}` +
    `&start_date=${dateStr}&end_date=${dateStr}` +
    "&hourly=temperature_2m,precipitation,weather_code" +
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum" +
    "&temperature_unit=fahrenheit&timezone=auto";
  const r = await (await fetch(url)).json();
  const d = r.daily, h = r.hourly;

  document.getElementById("cityName").textContent = c.name;
  document.getElementById("cityMeta").textContent =
    [c.admin1, c.country].filter(Boolean).join(", ") +
    ` · ${state.event.name} (local time)`;

  const total = d.precipitation_sum[0] ?? 0;
  let html =
    `<div class="city-day-summary">High <b>${Math.round(d.temperature_2m_max[0])}°</b> · ` +
    `Low <b>${Math.round(d.temperature_2m_min[0])}°</b> · 💧 ${total.toFixed(1)} mm total</div>`;
  for (let i = 0; i < h.time.length && i < 24; i += 3) {
    const hourLabel = new Date(h.time[i]).toLocaleTimeString("en-US", { hour: "numeric" });
    const p3 = h.precipitation.slice(i, i + 3).reduce((a, b) => a + (b ?? 0), 0);
    html +=
      `<div class="city-day">` +
      `<span class="dow">${hourLabel}</span>` +
      `<span class="icon">${wmoIcon(h.weather_code[i])}</span>` +
      `<span class="precip">${p3 > 0 ? p3.toFixed(1) + " mm 💧" : ""}</span>` +
      `<span class="temps"><span class="hi">${Math.round(h.temperature_2m[i])}°</span></span>` +
      `</div>`;
  }
  document.getElementById("cityDays").innerHTML = html;
  cityCard.hidden = false;
}

async function showCityForecast(c) {
  const url = "https://api.open-meteo.com/v1/forecast" +
    `?latitude=${c.latitude}&longitude=${c.longitude}` +
    "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max" +
    "&forecast_days=6&timezone=auto&temperature_unit=fahrenheit";
  const r = await (await fetch(url)).json();
  const d = r.daily;

  document.getElementById("cityName").textContent = c.name;
  document.getElementById("cityMeta").textContent =
    [c.admin1, c.country].filter(Boolean).join(", ") +
    ` · ${c.latitude.toFixed(2)}, ${c.longitude.toFixed(2)}`;

  const days = document.getElementById("cityDays");
  days.innerHTML = "";
  d.time.forEach((iso, i) => {
    const dow = i === 0 ? "Today" :
      new Date(iso + "T12:00").toLocaleDateString("en-US", { weekday: "short" });
    const row = document.createElement("div");
    row.className = "city-day";
    row.innerHTML =
      `<span class="dow">${dow}</span>` +
      `<span class="icon">${wmoIcon(d.weather_code[i])}</span>` +
      `<span class="precip">${d.precipitation_probability_max[i] ?? 0}% 💧</span>` +
      `<span class="temps"><span class="hi">${Math.round(d.temperature_2m_max[i])}°</span> / ` +
      `<span class="lo">${Math.round(d.temperature_2m_min[i])}°</span></span>`;
    days.appendChild(row);
  });
  cityCard.hidden = false;
}

cityInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = cityInput.value.trim();
  if (q.length < 2) { searchResults.innerHTML = ""; return; }
  searchTimer = setTimeout(async () => {
    try { renderResults(await searchCities(q)); }
    catch { searchResults.innerHTML = ""; }
  }, 350);
});
cityInput.addEventListener("keydown", e => {
  if (e.key === "Enter") {
    const first = searchResults.querySelector(".search-item");
    if (first) first.click();
  } else if (e.key === "Escape") {
    searchResults.innerHTML = "";
  }
});
document.getElementById("cityClose").addEventListener("click", () => {
  cityCard.hidden = true;
  if (cityMarker) { map.removeLayer(cityMarker); cityMarker = null; }
});

/* ---------- historical events (ERA5 reanalysis playback) ---------- */
const eventSelect = document.getElementById("eventSelect");
const loadEventBtn = document.getElementById("loadEvent");
const eventStatus = document.getElementById("eventStatus");
const eventBanner = document.getElementById("eventBanner");
let eventCatalog = [];
let loadedEventId = null;   // event whose frames are currently in frames_event/

async function loadEventCatalog() {
  try {
    eventCatalog = (await (await fetch("events.json")).json()).events;
    eventCatalog.forEach(ev => {
      const opt = document.createElement("option");
      opt.value = ev.id;
      opt.textContent = `${ev.name} (${ev.start.slice(0, 4)})`;
      eventSelect.appendChild(opt);
    });
  } catch { eventStatus.textContent = "Event catalog unavailable."; }
}

async function enterEventMode(ev) {
  const timeline = await (await fetch(`frames_event/timeline.json?t=${Date.now()}`)).json();
  if (!forecastTimeline) forecastTimeline = state.timeline;
  state.timeline = timeline;
  state.dataset = "event";
  state.event = ev;
  state.stepIdx = 0;
  updateProductButtons();

  document.getElementById("eventTitle").textContent = ev.day
    ? `${ev.name} — hourly ERA5 reanalysis`
    : `${ev.name} — ${ev.start} to ${ev.end} (ERA5 reanalysis)`;
  document.getElementById("eventDesc").textContent = ev.description;
  eventBanner.hidden = false;

  if (ev.lat != null) map.flyTo([ev.lat, ev.lon], ev.zoom || 5, { duration: 1.5 });
  await setProduct(ev.watch || "2t");
  updateWind();
  // an open city card switches to this day's rundown for that city
  if (ev.day && !cityCard.hidden && lastCity) showCityDayRundown(lastCity, ev.start);
}

function exitEventMode() {
  state.dataset = "forecast";
  state.event = null;
  state.stepIdx = 0;
  if (forecastTimeline) state.timeline = forecastTimeline;
  updateProductButtons();
  eventBanner.hidden = true;
  setProduct("2t");
  updateWind();
  // an open city card goes back to the normal 6-day forecast
  if (!cityCard.hidden && lastCity) showCityForecast(lastCity);
}

loadEventBtn.addEventListener("click", async () => {
  const ev = eventCatalog.find(e => e.id === eventSelect.value);
  if (!ev) return;
  if (loadedEventId === ev.id) { await enterEventMode(ev); return; }

  // frames from a previous session may already match this event — check
  // before kicking off a fetch+render cycle
  try {
    const t = await (await fetch(`frames_event/timeline.json?t=${Date.now()}`)).json();
    if (t.init_time && t.init_time.startsWith(ev.start)) {
      loadedEventId = ev.id;
      await enterEventMode(ev);
      return;
    }
  } catch { /* nothing loaded yet */ }

  setHistoryButtons(false);
  eventStatus.textContent = "Requesting ERA5 reanalysis… (first load of an event can take several minutes)";
  try {
    await fetch("/api/load-event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start: ev.start, end: ev.end }),
    });
    await pollEventLoad(ev);
  } catch {
    eventStatus.textContent = "Failed to reach the server.";
    setHistoryButtons(true);
  }
});

function setHistoryButtons(enabled) {
  loadEventBtn.disabled = !enabled;
  loadDayBtn.disabled = !enabled;
}

async function pollEventLoad(ev) {
  const r = await (await fetch("/api/event-status")).json();
  if (r.state === "running") {
    eventStatus.textContent = "Loading… " + (r.detail || "");
    setTimeout(() => pollEventLoad(ev), 4000);
  } else if (r.state === "done") {
    eventStatus.textContent = "";
    setHistoryButtons(true);
    loadedEventId = ev.id;
    await enterEventMode(ev);
  } else {
    eventStatus.textContent = "Load failed — see data\\load_event.log";
    setHistoryButtons(true);
  }
}

document.getElementById("exitEvent").addEventListener("click", exitEventMode);

/* ---------- study any past day (hourly ERA5 reanalysis) ---------- */
const dayInput = document.getElementById("dayInput");
const loadDayBtn = document.getElementById("loadDay");
// ERA5 lags real time by roughly 6 days
dayInput.max = new Date(Date.now() - 6 * 864e5).toISOString().slice(0, 10);

function dayEvent(dateStr) {
  const nice = new Date(dateStr + "T12:00Z").toLocaleDateString("en-US",
    { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
  return {
    id: `day-${dateStr}`, name: nice, start: dateStr, end: dateStr,
    day: true, watch: "2t",
    description: "Temperature, precipitation and wind for this day, hour by hour.",
  };
}

loadDayBtn.addEventListener("click", async () => {
  const dateStr = dayInput.value;
  if (!dateStr) { eventStatus.textContent = "Pick a date first."; return; }
  const ev = dayEvent(dateStr);
  if (loadedEventId === ev.id) { await enterEventMode(ev); return; }

  // day frames from a previous session may already be on disk — a day
  // timeline is recognizable by starting on that date and including precip
  try {
    const t = await (await fetch(`frames_event/timeline.json?t=${Date.now()}`)).json();
    if (t.init_time && t.init_time.startsWith(dateStr) && t.vars.tp) {
      loadedEventId = ev.id;
      await enterEventMode(ev);
      return;
    }
  } catch { /* nothing loaded yet */ }

  setHistoryButtons(false);
  eventStatus.textContent = "Requesting hourly ERA5 for that day… (cached days load in seconds; new days take a few minutes)";
  try {
    const r = await fetch("/api/load-day", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: dateStr }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || "Request rejected.");
    await pollEventLoad(ev);
  } catch (err) {
    eventStatus.textContent = err.message || "Failed to reach the server.";
    setHistoryButtons(true);
  }
});

/* ---------- run-forecast button ---------- */
const runBtn = document.getElementById("runForecast");
const runStatus = document.getElementById("runStatus");
runBtn.addEventListener("click", async () => {
  if (!confirm("Run a new FourCastNetv2 forecast? This takes ~10–20 minutes (download + GPU inference + frame rendering).")) return;
  await fetch("/api/run-forecast", { method: "POST" });
  pollRun();
});
// the server keeps reporting "done" after a run finishes, so only reload when
// THIS page watched the run happen — otherwise every reload sees "done" and
// reloads again, forever
let runWasActive = false;
async function pollRun() {
  const r = await (await fetch("/api/run-status")).json();
  if (r.state === "running") {
    runWasActive = true;
    runBtn.disabled = true;
    runStatus.textContent = "Forecast running… " + (r.detail || "");
    setTimeout(pollRun, 5000);
  } else {
    runBtn.disabled = false;
    if (r.state === "done" && runWasActive) {
      runStatus.textContent = "Done — reloading";
      location.reload();
    } else {
      runStatus.textContent = r.state === "failed" && runWasActive
        ? "Run failed — see server log" : "";
    }
  }
}

/* ---------- init ---------- */
(async function init() {
  try {
    // cache-buster: the server sends no Cache-Control, so a heuristically
    // cached timeline could hide newly added layers after a pipeline run
    state.timeline = await (await fetch(`frames/timeline.json?t=${Date.now()}`)).json();
  } catch {
    document.getElementById("initInfo").textContent =
      "No forecast frames yet — click “Run new forecast” or run run_forecast.ps1.";
    loadEventCatalog();
    updateProductButtons();
    setProduct("radar");
    pollRun();
    return;
  }
  document.getElementById("initInfo").textContent =
    `Model init: ${fmtValid(state.timeline.init_time)} · ${state.timeline.steps.length} steps`;
  windBtn.classList.toggle("active", state.windOn);
  forecastTimeline = state.timeline;
  loadEventCatalog();
  updateProductButtons();
  const want = decodeURIComponent(location.hash.slice(1));
  await setProduct(["2t", "tp", "msl", "tcwv", "radar", "aq"].includes(want) ? want : "2t");
  updateWind();
  pollRun();
})();
