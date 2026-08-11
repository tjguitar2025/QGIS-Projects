/* SpaceWeather — Earth cloud imagery (NASA GIBS) + space-weather dashboards (NOAA SWPC / NASA DONKI / SDO). */
"use strict";

const $ = (id) => document.getElementById(id);
const CSSVAR = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const COLORS = {
  s1: CSSVAR("--series-1"), s2: CSSVAR("--series-2"), s3: CSSVAR("--series-3"),
  good: CSSVAR("--good"), warning: CSSVAR("--warning"),
  serious: CSSVAR("--serious"), critical: CSSVAR("--critical"),
  ink2: CSSVAR("--ink-2"), muted: CSSVAR("--muted"),
  grid: CSSVAR("--grid"), baseline: CSSVAR("--baseline"), surface: CSSVAR("--surface"),
};

/* ================= map + GIBS imagery ================= */

const map = L.map("map", { center: [30, -40], zoom: 3, minZoom: 2, worldCopyJump: true });
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: "&copy; OpenStreetMap &copy; CARTO",
  maxZoom: 12,
}).addTo(map);

const GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{layer}/default/{time}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg";

function utcDateStr(offsetDays = 0) {
  const d = new Date(Date.now() + offsetDays * 864e5);
  return d.toISOString().slice(0, 10);
}

let gibsLayer = null;
function setGibs() {
  const layer = $("layerSelect").value;
  const time = $("dateInput").value;
  if (gibsLayer) map.removeLayer(gibsLayer);
  gibsLayer = L.tileLayer(GIBS, {
    layer, time,
    tileSize: 256, maxNativeZoom: 9, maxZoom: 12,
    opacity: 0.9,
    attribution: "Imagery: NASA GIBS / Worldview",
  }).addTo(map);
  if (auroraOverlay) auroraOverlay.bringToFront();
}

const dateInput = $("dateInput");
dateInput.max = utcDateStr(0);
dateInput.value = utcDateStr(-1); // today's polar-orbiter mosaic is usually incomplete
dateInput.addEventListener("change", setGibs);
$("layerSelect").addEventListener("change", setGibs);
$("datePrev").addEventListener("click", () => stepDate(-1));
$("dateNext").addEventListener("click", () => stepDate(1));
function stepDate(days) {
  const d = new Date(dateInput.value + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  const s = d.toISOString().slice(0, 10);
  if (s > dateInput.max) return;
  dateInput.value = s;
  setGibs();
}

/* ================= aurora overlay (SWPC OVATION) ================= */

let auroraOverlay = null;
async function loadAurora() {
  try {
    const data = await getJSON("/api/swpc/json/ovation_aurora_latest.json");
    // 1° grid: lon 0..359 (shift to -180..179), lat -90..90
    const grid = new Float32Array(181 * 360);
    for (const [lon, lat, val] of data.coordinates) {
      grid[(lat + 90) * 360 + ((lon + 180) % 360)] = val;
    }
    // draw into Mercator-projected rows so latitudes land where the basemap has them
    const LATMAX = 85.051;
    const W = 720, H = 720;
    const canvas = document.createElement("canvas");
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext("2d");
    const img = ctx.createImageData(W, H);
    const yMax = Math.log(Math.tan(Math.PI / 4 + (LATMAX * Math.PI) / 360));
    for (let y = 0; y < H; y++) {
      const my = yMax * (1 - (2 * y) / H); // mercator y, top -> bottom
      const lat = ((2 * Math.atan(Math.exp(my)) - Math.PI / 2) * 180) / Math.PI;
      const li = Math.round(lat + 90);
      for (let x = 0; x < W; x++) {
        const lon = Math.round((x / W) * 360); // 0..360 across -180..180
        const val = grid[li * 360 + (lon % 360)];
        if (val < 5) continue; // sub-5% probability is noise
        const i = (y * W + x) * 4;
        // aurora convention: green -> yellow -> red with probability
        const t = Math.min(val, 100) / 100;
        img.data[i]     = t < 0.35 ? 40 : Math.min(255, (t - 0.35) * 700);
        img.data[i + 1] = t < 0.7 ? 220 : Math.max(60, 220 - (t - 0.7) * 500);
        img.data[i + 2] = 60;
        img.data[i + 3] = Math.min(230, 30 + t * 320);
      }
    }
    ctx.putImageData(img, 0, 0);
    const url = canvas.toDataURL();
    if (auroraOverlay) map.removeLayer(auroraOverlay);
    auroraOverlay = L.imageOverlay(url, [[-LATMAX, -180], [LATMAX, 180]], {
      opacity: 0.62, interactive: false,
    });
    if ($("auroraToggle").checked) auroraOverlay.addTo(map);
  } catch (e) { console.warn("aurora load failed", e); }
}
$("auroraToggle").addEventListener("change", (e) => {
  if (!auroraOverlay) return;
  e.target.checked ? auroraOverlay.addTo(map) : map.removeLayer(auroraOverlay);
});

/* ================= data helpers ================= */

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}
const fmtClock = (d) => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const fmtDay = (d) => d.toLocaleDateString([], { month: "short", day: "numeric" });
const fmtWhen = (d) => `${fmtDay(d)} ${fmtClock(d)}`;

/* ================= tooltip (shared) ================= */

const tip = document.createElement("div");
tip.id = "tooltip";
document.body.appendChild(tip);
function showTip(x, y, timeText, rows) {
  tip.replaceChildren();
  const t = document.createElement("div");
  t.className = "tt-time";
  t.textContent = timeText;
  tip.appendChild(t);
  for (const r of rows) {
    const row = document.createElement("div");
    row.className = "tt-row";
    const key = document.createElement("span");
    key.className = "tt-key";
    key.style.background = r.color;
    const val = document.createElement("span");
    val.className = "tt-val";
    val.textContent = r.value;
    const name = document.createElement("span");
    name.className = "tt-name";
    name.textContent = r.name;
    row.append(key, val, name);
    tip.appendChild(row);
  }
  tip.style.display = "block";
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(x + 14, innerWidth - w - 8) + "px";
  tip.style.top = Math.max(8, Math.min(y - h - 10, innerHeight - h - 8)) + "px";
}
const hideTip = () => (tip.style.display = "none");

/* ================= SVG chart builders ================= */

const NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs) {
  const el = document.createElementNS(NS, tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}
const PAD = { l: 42, r: 10, t: 16, b: 20 };

function niceTicks(min, max, n = 4) {
  const span = max - min || 1;
  const step0 = span / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) ticks.push(v);
  return ticks;
}

/* Multi/single-series line chart with crosshair tooltip.
   series: [{name, color, points: [[Date, value], ...]}]  */
function lineChart(el, { series, caption, unit = "", height = 140, yFmt = (v) => String(Math.round(v)), yLog = false, yDomain = null, zeroLine = false, bands = null }) {
  const W = 380, H = height;
  el.replaceChildren();
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` });
  el.appendChild(svg);

  const all = series.flatMap((s) => s.points).filter((p) => Number.isFinite(p[1]));
  if (!all.length) { emptyNote(el, svg, W, H, caption); return; }
  const tMin = Math.min(...all.map((p) => +p[0])), tMax = Math.max(...all.map((p) => +p[0]));
  const tf = yLog ? Math.log10 : (v) => v;
  let vMin = yDomain ? yDomain[0] : Math.min(...all.map((p) => p[1]));
  let vMax = yDomain ? yDomain[1] : Math.max(...all.map((p) => p[1]));
  if (!yDomain) { const pad = (vMax - vMin) * 0.12 || 1; vMin -= pad; vMax += pad; }
  if (zeroLine) { vMin = Math.min(vMin, -1); vMax = Math.max(vMax, 1); }
  const X = (t) => PAD.l + ((t - tMin) / (tMax - tMin || 1)) * (W - PAD.l - PAD.r);
  const Y = (v) => PAD.t + (1 - (tf(v) - tf(vMin)) / (tf(vMax) - tf(vMin) || 1)) * (H - PAD.t - PAD.b);

  // caption (chart-local subtitle, muted ink)
  svg.appendChild(text(PAD.l, 11, caption, { fill: COLORS.muted, "font-size": 10 }));

  // y grid + labels
  const yTicks = yLog
    ? Array.from({ length: Math.floor(tf(vMax)) - Math.ceil(tf(vMin)) + 1 }, (_, i) => 10 ** (Math.ceil(tf(vMin)) + i))
    : niceTicks(vMin, vMax, 3);
  for (const v of yTicks) {
    const y = Y(v);
    if (y < PAD.t - 1 || y > H - PAD.b + 1) continue;
    svg.appendChild(svgEl("line", { x1: PAD.l, x2: W - PAD.r, y1: y, y2: y, stroke: COLORS.grid, "stroke-width": 1 }));
    svg.appendChild(text(PAD.l - 6, y + 3, yFmt(v), { fill: COLORS.muted, "font-size": 9, "text-anchor": "end" }));
  }
  // flare-class bands (x-ray chart)
  if (bands) for (const b of bands) {
    const y = Y(b.v);
    if (y < PAD.t || y > H - PAD.b) continue;
    svg.appendChild(text(W - PAD.r - 2, y - 3, b.label, { fill: COLORS.muted, "font-size": 9, "text-anchor": "end" }));
  }
  if (zeroLine) {
    const y0 = Y(0);
    svg.appendChild(svgEl("line", { x1: PAD.l, x2: W - PAD.r, y1: y0, y2: y0, stroke: COLORS.baseline, "stroke-width": 1.5 }));
  }
  // x labels
  for (const frac of [0, 0.5, 1]) {
    const t = tMin + frac * (tMax - tMin);
    svg.appendChild(text(X(t), H - 6, fmtClock(new Date(t)), { fill: COLORS.muted, "font-size": 9, "text-anchor": frac === 0 ? "start" : frac === 1 ? "end" : "middle" }));
  }

  // series lines (2px, round joins)
  for (const s of series) {
    const pts = s.points.filter((p) => Number.isFinite(p[1]));
    const d = pts.map((p, i) => `${i ? "L" : "M"}${X(+p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    svg.appendChild(svgEl("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  }

  // crosshair + hover layer
  const cross = svgEl("line", { y1: PAD.t, y2: H - PAD.b, stroke: COLORS.baseline, "stroke-width": 1, visibility: "hidden" });
  svg.appendChild(cross);
  const dots = series.map((s) => {
    const g = svgEl("circle", { r: 4.5, fill: s.color, stroke: COLORS.surface, "stroke-width": 2, visibility: "hidden" });
    svg.appendChild(g);
    return g;
  });
  const hit = svgEl("rect", { x: PAD.l, y: PAD.t, width: W - PAD.l - PAD.r, height: H - PAD.t - PAD.b, fill: "transparent" });
  svg.appendChild(hit);
  const ref = series[0].points;
  hit.addEventListener("pointermove", (ev) => {
    const box = svg.getBoundingClientRect();
    const t = tMin + ((ev.clientX - box.left) * (W / box.width) - PAD.l) / (W - PAD.l - PAD.r) * (tMax - tMin);
    let idx = 0, best = Infinity;
    ref.forEach((p, i) => { const d = Math.abs(+p[0] - t); if (d < best) { best = d; idx = i; } });
    const tx = X(+ref[idx][0]);
    cross.setAttribute("x1", tx); cross.setAttribute("x2", tx);
    cross.setAttribute("visibility", "visible");
    const rows = series.map((s, si) => {
      const p = s.points[idx] || s.points[s.points.length - 1];
      if (p && Number.isFinite(p[1])) {
        dots[si].setAttribute("cx", X(+p[0])); dots[si].setAttribute("cy", Y(p[1]));
        dots[si].setAttribute("visibility", "visible");
      } else dots[si].setAttribute("visibility", "hidden");
      return { color: s.color, name: s.name, value: p && Number.isFinite(p[1]) ? yFmt(p[1]) + (unit ? " " + unit : "") : "—" };
    });
    showTip(ev.clientX, ev.clientY, fmtWhen(new Date(+ref[idx][0])), rows);
  });
  hit.addEventListener("pointerleave", () => {
    cross.setAttribute("visibility", "hidden");
    dots.forEach((d) => d.setAttribute("visibility", "hidden"));
    hideTip();
  });
}

/* Kp bar chart — per-bar hover, status colors, rounded data-end/square baseline. */
function kpBarChart(el, points) {
  const W = 380, H = 130;
  el.replaceChildren();
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` });
  el.appendChild(svg);
  if (!points.length) { emptyNote(el, svg, W, H, "no data"); return; }
  const yMax = 9;
  const Y = (v) => PAD.t + (1 - v / yMax) * (H - PAD.t - PAD.b);
  for (const v of [0, 3, 6, 9]) {
    svg.appendChild(svgEl("line", { x1: PAD.l, x2: W - PAD.r, y1: Y(v), y2: Y(v), stroke: v === 0 ? COLORS.baseline : COLORS.grid, "stroke-width": 1 }));
    svg.appendChild(text(PAD.l - 6, Y(v) + 3, String(v), { fill: COLORS.muted, "font-size": 9, "text-anchor": "end" }));
  }
  const span = W - PAD.l - PAD.r;
  const slot = span / points.length;
  const bw = Math.min(24, Math.max(3, slot - 2)); // ≤24px, 2px surface gap
  points.forEach((p, i) => {
    const [t, v] = p;
    const x = PAD.l + i * slot + (slot - bw) / 2;
    const y = Y(v), y0 = Y(0);
    const c = v < 4 ? COLORS.good : v < 5 ? COLORS.warning : v < 7 ? COLORS.serious : COLORS.critical;
    const r = Math.min(4, bw / 2, Math.max(0, y0 - y));
    // rounded top, square baseline
    const d = `M${x},${y0} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + bw - r},${y} Q${x + bw},${y} ${x + bw},${y + r} L${x + bw},${y0} Z`;
    const bar = svgEl("path", { d, fill: c });
    svg.appendChild(bar);
    const hit = svgEl("rect", { x: PAD.l + i * slot, y: PAD.t, width: slot, height: H - PAD.t - PAD.b, fill: "transparent" });
    svg.appendChild(hit);
    const label = v < 4 ? "quiet" : v < 5 ? "active" : v < 6 ? "G1 minor storm" : v < 7 ? "G2 moderate storm" : v < 8 ? "G3 strong storm" : v < 9 ? "G4 severe storm" : "G5 extreme storm";
    hit.addEventListener("pointermove", (ev) => {
      bar.setAttribute("opacity", "0.8");
      showTip(ev.clientX, ev.clientY, fmtWhen(t), [{ color: c, name: label, value: "Kp " + v.toFixed(2).replace(/\.?0+$/, "") }]);
    });
    hit.addEventListener("pointerleave", () => { bar.setAttribute("opacity", "1"); hideTip(); });
  });
  // day labels on x
  let lastDay = "";
  points.forEach((p, i) => {
    const day = fmtDay(p[0]);
    if (day !== lastDay) {
      lastDay = day;
      svg.appendChild(text(PAD.l + i * slot + 2, H - 6, day, { fill: COLORS.muted, "font-size": 9 }));
    }
  });
}

function text(x, y, str, attrs) {
  const t = svgEl("text", { x, y, ...attrs });
  t.textContent = str;
  return t;
}
function emptyNote(el, svg, W, H, caption) {
  svg.appendChild(text(W / 2, H / 2, `${caption || "chart"}: no data`, { fill: COLORS.muted, "font-size": 11, "text-anchor": "middle" }));
}

/* ================= dashboard loaders ================= */

function latestFinite(rows, key) {
  for (const r of rows) { // rows are newest-first
    const v = parseFloat(r[key]);
    if (Number.isFinite(v)) return { v, row: r };
  }
  return null;
}
const downsample = (arr, n) => (arr.length <= n ? arr : arr.filter((_, i) => i % Math.ceil(arr.length / n) === 0));

async function loadSolarWind() {
  // RTSW feeds: array of objects, newest first; `active` marks the operational spacecraft
  const [windAll, magAll] = await Promise.all([
    getJSON("/api/swpc/json/rtsw/rtsw_wind_1m.json"),
    getJSON("/api/swpc/json/rtsw/rtsw_mag_1m.json"),
  ]);
  const active = (rows) => { const a = rows.filter((r) => r.active); return a.length ? a : rows; };
  const wind = active(windAll), mag = active(magAll);
  const sp = latestFinite(wind, "proton_speed"), de = latestFinite(wind, "proton_density"), bz = latestFinite(mag, "bz_gsm");
  if (sp) { $("t-speed").textContent = Math.round(sp.v); $("t-sat").textContent = sp.row.source || "—"; }
  if (de) $("t-density").textContent = de.v.toFixed(1);
  if (bz) {
    $("t-bz").textContent = (bz.v > 0 ? "+" : "") + bz.v.toFixed(1);
    $("t-bz").style.color = bz.v <= -5 ? COLORS.serious : "";
  }

  const pts = (rows, key) => rows.slice().reverse()
    .map((r) => [new Date(r.time_tag + "Z"), parseFloat(r[key])]);
  lineChart($("speed-chart"), {
    caption: "speed · km/s",
    series: [{ name: "speed", color: COLORS.s1, points: downsample(pts(wind, "proton_speed"), 240) }],
    unit: "km/s",
  });
  lineChart($("bz-chart"), {
    caption: "Bz (interplanetary magnetic field) · nT",
    series: [{ name: "Bz", color: COLORS.s3, points: downsample(pts(mag, "bz_gsm"), 240) }],
    unit: "nT", zeroLine: true, yFmt: (v) => v.toFixed(0),
  });
}

async function loadKp() {
  const rows = await getJSON("/api/swpc/products/noaa-planetary-k-index.json");
  const cutoff = Date.now() - 3 * 864e5;
  const pts = rows.map((r) => [new Date(r.time_tag + "Z"), parseFloat(r.Kp)])
    .filter((p) => Number.isFinite(p[1]) && +p[0] > cutoff);
  kpBarChart($("kp-chart"), pts);
  if (pts.length) {
    const kp = pts[pts.length - 1][1];
    $("t-kp").textContent = kp.toFixed(2).replace(/\.?0+$/, "");
    const g = kp < 5 ? "" : kp < 6 ? " · G1" : kp < 7 ? " · G2" : kp < 8 ? " · G3" : kp < 9 ? " · G4" : " · G5";
    $("t-kp-sub").textContent = "planetary, 3-h" + g;
    $("t-kp").style.color = kp < 4 ? "" : kp < 5 ? COLORS.warning : kp < 7 ? COLORS.serious : COLORS.critical;
  }
}

function flareClass(flux) {
  if (!Number.isFinite(flux) || flux <= 0) return "—";
  const bands = [["X", 1e-4], ["M", 1e-5], ["C", 1e-6], ["B", 1e-7], ["A", 1e-8]];
  for (const [cls, base] of bands) if (flux >= base) return cls + (flux / base).toFixed(1);
  return "A<1";
}

async function loadXray() {
  const rows = await getJSON("/api/swpc/json/goes/primary/xrays-1-day.json");
  const long = rows.filter((r) => r.energy === "0.1-0.8nm");
  const pts = downsample(long.map((r) => [new Date(r.time_tag), r.flux]), 280).filter((p) => p[1] > 0);
  lineChart($("xray-chart"), {
    caption: "GOES long-band flux · W/m²  (C/M/X = flare class)",
    series: [{ name: "0.1–0.8 nm", color: COLORS.s2, points: pts }],
    yLog: true, yDomain: [1e-9, 1e-3],
    yFmt: (v) => v.toExponential(0).replace("e-", "e-"),
    bands: [{ v: 1e-8, label: "A" }, { v: 1e-7, label: "B" }, { v: 1e-6, label: "C" }, { v: 1e-5, label: "M" }, { v: 1e-4, label: "X" }],
    height: 150,
  });
  if (long.length) {
    const f = long[long.length - 1].flux;
    $("t-xray").textContent = flareClass(f);
    $("t-xray").style.color = f >= 1e-5 ? COLORS.serious : "";
    $("t-xray-sub").textContent = `GOES-${long[long.length - 1].satellite || "?"} 0.1–0.8 nm`;
  }
}

function sevClass(text) {
  const t = text.toUpperCase();
  if (/(G[45]|X\d|EXTREME|SEVERE)/.test(t)) return "sev-critical";
  if (/(G[23]|M\d|STRONG|MODERATE STORM|WARNING)/.test(t)) return "sev-serious";
  if (/(G1|ALERT|WATCH|MINOR)/.test(t)) return "sev-warning";
  return "";
}

function feedItem(title, when, body, sev) {
  const li = document.createElement("li");
  if (sev) li.className = sev;
  const t = document.createElement("div");
  t.className = "f-title";
  t.textContent = title;
  const w = document.createElement("div");
  w.className = "f-time";
  w.textContent = when;
  li.append(t, w);
  if (body) {
    const b = document.createElement("div");
    b.className = "f-body";
    b.textContent = body;
    li.appendChild(b);
  }
  return li;
}
function emptyItem(msg) {
  const li = document.createElement("li");
  li.className = "empty";
  li.textContent = msg;
  return li;
}

async function loadAlerts() {
  const list = $("alerts");
  list.replaceChildren();
  try {
    const alerts = await getJSON("/api/swpc/products/alerts.json");
    const cutoff = Date.now() - 3 * 864e5;
    const recent = alerts.filter((a) => new Date(a.issue_datetime + "Z") > cutoff).slice(0, 8);
    if (!recent.length) { list.appendChild(emptyItem("No alerts in the last 3 days — quiet conditions.")); return; }
    for (const a of recent) {
      const first = (a.message || "").split("\n").find((l) => /^(ALERT|WARNING|WATCH|SUMMARY|EXTENDED)/.test(l)) || (a.message || "").split("\n")[0] || a.product_id;
      list.appendChild(feedItem(first.slice(0, 90), fmtWhen(new Date(a.issue_datetime + "Z")), "", sevClass(first)));
    }
  } catch { list.appendChild(emptyItem("Alerts unavailable.")); }
}

async function loadDonki() {
  const list = $("events");
  list.replaceChildren();
  const end = utcDateStr(0), start = utcDateStr(-7);
  const q = `?startDate=${start}&endDate=${end}`;
  try {
    const [flares, cmes] = await Promise.all([
      getJSON("/api/donki/FLR" + q).catch(() => []),
      getJSON("/api/donki/CME" + q).catch(() => []),
    ]);
    const items = [];
    for (const f of flares || []) {
      items.push({
        t: new Date(f.peakTime || f.beginTime),
        title: `Solar flare ${f.classType || ""}`.trim(),
        body: f.sourceLocation ? `from region ${f.activeRegionNum || "?"} at ${f.sourceLocation}` : "",
        sev: /^X/.test(f.classType || "") ? "sev-critical" : /^M/.test(f.classType || "") ? "sev-serious" : "sev-warning",
      });
    }
    for (const c of cmes || []) {
      const a = (c.cmeAnalyses || [])[0];
      items.push({
        t: new Date(c.startTime),
        title: "Coronal mass ejection" + (a && a.speed ? ` · ${Math.round(a.speed)} km/s` : ""),
        body: a && a.isMostAccurate === false ? "" : (c.note || "").slice(0, 110),
        sev: a && a.speed > 1000 ? "sev-serious" : "",
      });
    }
    items.sort((x, y) => y.t - x.t);
    if (!items.length) { list.appendChild(emptyItem("No flares or CMEs catalogued in the last 7 days.")); return; }
    for (const it of items.slice(0, 10)) list.appendChild(feedItem(it.title, fmtWhen(it.t), it.body, it.sev));
  } catch { list.appendChild(emptyItem("DONKI unavailable (rate limit?) — try again in a minute.")); }
}

function loadSun() {
  const bust = "?t=" + Math.floor(Date.now() / 6e5); // refresh every 10 min
  $("sun-193").src = "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0193.jpg" + bust;
  $("sun-304").src = "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0304.jpg" + bust;
  $("sun-hmi").src = "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_HMIIF.jpg" + bust;
}

/* ================= boot + refresh ================= */

function refreshAll() {
  loadSolarWind().catch((e) => console.warn(e));
  loadKp().catch((e) => console.warn(e));
  loadXray().catch((e) => console.warn(e));
  loadAurora();
  loadAlerts();
  loadDonki();
  loadSun();
}
setGibs();
refreshAll();
setInterval(refreshAll, 5 * 60 * 1000);
