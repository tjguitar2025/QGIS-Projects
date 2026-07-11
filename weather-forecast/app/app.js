/* Local Weather — Windy-style viewer for FourCastNetv2 forecasts
 * Local layers:  temperature / pressure / moisture PNG frames + wind particle JSON
 * Live layers:   RainViewer radar tiles, Open-Meteo air quality
 */
"use strict";

const state = {
  timeline: null,      // frames/timeline.json
  product: "2t",       // '2t' | 'msl' | 'tcwv' | 'radar' | 'aq'
  windOn: true,
  stepIdx: 0,          // forecast step index
  radarIdx: 0,
  playing: false,
  playTimer: null,
};

const map = L.map("map", { zoomControl: false, minZoom: 2, worldCopyJump: true })
  .setView([39.1, -94.6], 5);
L.control.zoom({ position: "bottomright" }).addTo(map);
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; OpenStreetMap &copy; CARTO | forecast: local FourCastNetv2',
  subdomains: "abcd", maxZoom: 19,
}).addTo(map);

/* ---------- local forecast overlays (PNG frames) ---------- */
const scalarOverlay = L.imageOverlay("", [[-90, -180], [90, 180]], { opacity: 0.65 });
const frameCache = {};            // url -> Image (preload)

function frameUrl(product, idx) {
  const h = String(state.timeline.steps[idx]).padStart(3, "0");
  return `frames/${product}/${product}_+${h}h.png`;
}
function preloadFrames(product) {
  state.timeline.steps.forEach((_, i) => {
    const url = frameUrl(product, i);
    if (!frameCache[url]) { const im = new Image(); im.src = url; frameCache[url] = im; }
  });
}

/* ---------- wind particles ---------- */
let velocityLayer = null;
const windCache = {};

async function windData(idx) {
  const h = String(state.timeline.steps[idx]).padStart(3, "0");
  const url = `frames/wind/wind_+${h}h.json`;
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
      displayOptions: { velocityType: "wind", speedUnit: "m/s", position: "bottomleft" },
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
function showRadarFrame(idx) {
  radarFrames.forEach((f, i) => {
    if (i === idx) { if (!map.hasLayer(f.layer)) f.layer.addTo(map); f.layer.setOpacity(0.75); }
    else f.layer.setOpacity(0);
  });
}
function hideRadar() { radarFrames.forEach(f => f.layer.setOpacity(0)); }

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
  scalarOverlay.setUrl(url);
  if (!map.hasLayer(scalarOverlay)) scalarOverlay.addTo(map);
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
    const grad = v.legend.map(s => s.color).join(",");
    legend.innerHTML = `<div class="title">${v.label} (${v.units})</div>
      <div class="bar" style="background:linear-gradient(to right,${grad})"></div>
      <div class="ticks">${v.legend.map(s => `<span>${s.value}</span>`).join("")}</div>
      <div style="color:#8fa3c0;margin-top:4px">FourCastNetv2 · local GPU</div>`;
  }
}

async function setProduct(product) {
  state.product = product;
  document.querySelectorAll("#panel .product").forEach(b =>
    b.classList.toggle("active", b.dataset.product === product));
  stopPlay();

  map.removeLayer(aqGroup); hideRadar();
  if (product === "radar") {
    map.removeLayer(scalarOverlay);
    await loadRadar();
    showRadarFrame(state.radarIdx);
  } else if (product === "aq") {
    map.removeLayer(scalarOverlay);
    aqGroup.addTo(map);
    await refreshAQ();
  } else {
    preloadFrames(product);
    renderScalar();
  }
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
  }
  updateTimeUI();
}
slider.addEventListener("input", e => setStep(+e.target.value));

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

/* ---------- run-forecast button ---------- */
const runBtn = document.getElementById("runForecast");
const runStatus = document.getElementById("runStatus");
runBtn.addEventListener("click", async () => {
  if (!confirm("Run a new FourCastNetv2 forecast? This takes ~10–20 minutes (download + GPU inference + frame rendering).")) return;
  await fetch("/api/run-forecast", { method: "POST" });
  pollRun();
});
async function pollRun() {
  const r = await (await fetch("/api/run-status")).json();
  if (r.state === "running") {
    runBtn.disabled = true;
    runStatus.textContent = "Forecast running… " + (r.detail || "");
    setTimeout(pollRun, 5000);
  } else {
    runBtn.disabled = false;
    if (r.state === "done") { runStatus.textContent = "Done — reloading"; location.reload(); }
    else runStatus.textContent = r.state === "failed" ? "Run failed — see server log" : "";
  }
}

/* ---------- init ---------- */
(async function init() {
  try {
    state.timeline = await (await fetch("frames/timeline.json")).json();
  } catch {
    document.getElementById("initInfo").textContent =
      "No forecast frames yet — click “Run new forecast” or run run_forecast.ps1.";
    setProduct("radar");
    pollRun();
    return;
  }
  document.getElementById("initInfo").textContent =
    `Model init: ${fmtValid(state.timeline.init_time)} · ${state.timeline.steps.length} steps`;
  windBtn.classList.toggle("active", state.windOn);
  await setProduct("2t");
  updateWind();
  pollRun();
})();
