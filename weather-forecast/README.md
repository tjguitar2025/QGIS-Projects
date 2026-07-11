# Local Weather — an AI-powered weather app

A Weather Channel / Windy-style weather app that runs entirely on your own
machine: a pretrained AI model (FourCastNetv2-small via
[ECMWF ai-models](https://github.com/ecmwf-lab/ai-models)) generates real
multi-day forecasts on your GPU, and a local web app shows them as animated
maps — wind particles, temperature, pressure, moisture — alongside live radar
and air quality.

## Features

- **💨 Wind particles** — Windy-style animated particle flow from your own model's u/v fields ([leaflet-velocity](https://github.com/onaci/leaflet-velocity))
- **🌡️ Temperature / 🌀 Pressure / 💧 Moisture maps** — colorized forecast frames animated with a time slider (up to 10 days)
- **🌧️ Live radar** — observed + nowcast precipitation tiles from [RainViewer](https://www.rainviewer.com/api.html) (free for personal use)
- **😷 Air quality** — US AQI grid over the visible map from the [Open-Meteo Air Quality API](https://open-meteo.com/en/docs/air-quality-api) (free, no key)
- **📍 Click anywhere** — current conditions popup (Open-Meteo)
- **▶ Run new forecast** — one button in the UI triggers a fresh model run on your GPU

## Pipeline

```
ERA5 initial state (Copernicus CDS)
  → FourCastNetv2-small inference on GPU (~2 min for 6 days on an RTX 4050)
  → forecast GRIB (73 variables)
  → scripts/grib_to_frames.py → PNG frames + leaflet-velocity wind JSON
  → server.py (FastAPI) serves app/ at http://localhost:8050
```

## Setup

1. Install [Miniconda](https://docs.conda.io/en/latest/miniconda.html)
2. `conda env create -f environment.yml`
3. Install CUDA PyTorch: `conda run -n weather pip install torch --index-url https://download.pytorch.org/whl/cu128`
   and `conda run -n weather pip install onnxruntime-gpu`
4. Create a free [Copernicus CDS](https://cds.climate.copernicus.eu) account and put your
   key in `~/.cdsapirc`:
   ```
   url: https://cds.climate.copernicus.eu/api
   key: <your-uuid-key>
   ```
5. Verify: `conda run -n weather python scripts/check_gpu.py`

**Known issue:** with PyTorch ≥ 2.6 the FourCastNetv2 checkpoint fails to load
(`weights_only` default change). Patch `ai_models_fourcastnetv2/model.py` in your
env to pass `weights_only=False` to `torch.load` — the checkpoint comes from
ECMWF's official asset store.

## Run

```powershell
.\run_forecast.ps1                        # generate a forecast (latest ERA5, 144h)
.\run_forecast.ps1 -Date 20260704 -LeadTime 240
.\start_app.ps1                           # start the app -> http://localhost:8050
```

ERA5 lags real time by ~6 days, so the default init date is 6 days back —
the forecast still covers today and beyond. Radar and air quality layers are
live regardless.

## Skew-T soundings

```powershell
conda run -n weather python scripts/skewt_at_point.py data/forecasts/<run>.grib --lat 39.1 --lon -94.6 --step 24
```

## Layout

| Path | Purpose |
|---|---|
| `app/` | Web app (Leaflet + leaflet-velocity), served by `server.py` |
| `app/frames/` | Generated forecast frames (not committed) |
| `server.py` | FastAPI server + run-forecast trigger API |
| `scripts/grib_to_frames.py` | Forecast GRIB → PNG frames + wind JSON |
| `scripts/check_gpu.py` | Verify env: CUDA torch, ONNX-GPU, ecCodes, cfgrib, cdsapi |
| `scripts/skewt_at_point.py` | Skew-T log-P sounding at any lat/lon and forecast hour |

> **Note:** this project previously visualized forecasts through QGIS.
> That pipeline was replaced by the interactive web app in this version.

Forecast data (GRIB/frames) is not committed — regenerate with `run_forecast.ps1`.
