# SpaceWeather — space weather tracking + Earth cloud imagery

A local web app that pairs **daily satellite imagery of Earth** (cloud cover from
NASA's polar-orbiting imagers) with a **live space-weather dashboard** (solar wind,
geomagnetic activity, solar flares, aurora forecast, and the Sun itself).

Companion project to `..\WeatherForecast` (the AI weather-forecast platform) —
same stack, same conda env, different port.

## Features

- **🛰️ Satellite cloud imagery** — global true-color mosaics from VIIRS
  (Suomi-NPP / NOAA-20) and MODIS (Terra / Aqua) via **NASA GIBS** WMTS tiles;
  step through any date (imagery is daily, complete ~1 day behind real time)
- **🌌 Aurora forecast overlay** — NOAA SWPC **OVATION** 30-minute aurora
  probability, reprojected onto the Mercator map (green → yellow → red)
- **🌬️ Solar wind panel** — live speed / density / Bz from the operational L1
  spacecraft (`json/rtsw/` feeds), 24-hour charts with crosshair tooltips
- **🧲 Planetary K-index** — 3 days of 3-hour bars, colored by NOAA G-scale
- **☀️ X-ray flux** — GOES long-band on a log scale with A/B/C/M/X flare classes
- **🖼️ The Sun right now** — SDO AIA 193 / AIA 304 / HMI latest images
- **🚨 Active alerts** — NOAA SWPC watches / warnings / alerts (last 3 days)
- **📋 Recent events** — NASA DONKI flare + CME catalog (last 7 days)

## Data sources (all free)

| Source | What | Access |
|---|---|---|
| NASA GIBS | daily satellite imagery tiles | WMTS, no key |
| NOAA SWPC | solar wind, Kp, X-ray, aurora, alerts | JSON, no key (proxied) |
| NASA DONKI | flare/CME event catalog | api.nasa.gov (`DEMO_KEY`; set `NASA_API_KEY` for higher limits) |
| NASA SDO | latest Sun images | direct JPG |
| CARTO/OSM | basemap | tiles |

The FastAPI server proxies SWPC and DONKI with a short cache (and sanitizes the
`NaN` values SWPC embeds in its JSON), so the browser talks to one origin and
upstream rate limits are respected.

## Run

```powershell
.\start_app.ps1        # -> http://localhost:8060
```

Uses the existing `weather` conda env (fastapi + uvicorn). Optional: set
`NASA_API_KEY` in your environment for a personal api.nasa.gov key.

## Gotchas learned building this

- SWPC retired `products/solar-wind/*.json` — real-time solar wind now lives at
  `json/rtsw/rtsw_wind_1m.json` / `rtsw_mag_1m.json` (array of objects, newest
  first, `active: true` marks the operational spacecraft).
- SWPC JSON can contain literal `NaN` — invalid JSON; the proxy nulls them.
- OVATION's grid is 1° equirectangular (lon 0–359) — draw it into
  Mercator-projected rows or the oval lands at the wrong latitudes.
- Today's GIBS polar-orbiter mosaic is incomplete until ~late in the day;
  default the date picker to yesterday.
