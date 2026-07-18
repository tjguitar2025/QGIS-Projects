"""Local weather app server.

Serves the web app (app/) and lets the browser trigger a new FourCastNetv2
forecast run via the existing run_forecast.ps1 pipeline.

    conda run -n weather python server.py     ->  http://localhost:8050
"""
import json
import re
import subprocess
import threading
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
LOG = BASE / "data" / "run_forecast.log"
EVENT_LOG = BASE / "data" / "load_event.log"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

app = FastAPI(title="Local Weather")
run = {"proc": None, "state": "idle"}          # idle | running | done | failed
event_run = {"proc": None, "state": "idle"}    # same states


def _tail(log: Path) -> str:
    if not log.exists():
        return ""
    lines = log.read_text(errors="ignore").strip().splitlines()
    return lines[-1][-90:] if lines else ""


def _watch(proc: subprocess.Popen):
    proc.wait()
    run["state"] = "done" if proc.returncode == 0 else "failed"


@app.post("/api/run-forecast")
def run_forecast():
    if run["proc"] and run["proc"].poll() is None:
        return {"state": "running"}
    LOG.parent.mkdir(exist_ok=True)
    logf = open(LOG, "w")
    # -ExecutionPolicy Bypass: scoped to this child only — default Restricted
    # policy would refuse to run the pipeline script at all
    run["proc"] = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(BASE / "run_forecast.ps1")],
        stdout=logf, stderr=subprocess.STDOUT, cwd=BASE,
    )
    run["state"] = "running"
    threading.Thread(target=_watch, args=(run["proc"],), daemon=True).start()
    return {"state": "running"}


@app.get("/api/run-status")
def run_status():
    detail = _tail(LOG) if run["state"] == "running" else ""
    return {"state": run["state"], "detail": detail}


@app.post("/api/load-event")
def load_event(payload: dict):
    start, end = payload.get("start", ""), payload.get("end", "")
    if not (DATE_RE.match(start) and DATE_RE.match(end)):
        raise HTTPException(400, "start/end must be YYYY-MM-DD")
    if event_run["proc"] and event_run["proc"].poll() is None:
        return {"state": "running"}
    EVENT_LOG.parent.mkdir(exist_ok=True)
    logf = open(EVENT_LOG, "w")
    event_run["proc"] = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(BASE / "load_event.ps1"), "-Start", start, "-End", end],
        stdout=logf, stderr=subprocess.STDOUT, cwd=BASE,
    )
    event_run["state"] = "running"

    def _watch_event(proc):
        proc.wait()
        event_run["state"] = "done" if proc.returncode == 0 else "failed"

    threading.Thread(target=_watch_event, args=(event_run["proc"],), daemon=True).start()
    return {"state": "running"}


@app.post("/api/load-day")
def load_day(payload: dict):
    """Load one past day (hourly ERA5: temperature + precipitation + wind)."""
    day = payload.get("date", "")
    if not DATE_RE.match(day):
        raise HTTPException(400, "date must be YYYY-MM-DD")
    d = date.fromisoformat(day)
    if d < date(1940, 1, 1) or d > date.today() - timedelta(days=6):
        raise HTTPException(400, "ERA5 covers 1940 up to ~6 days ago")
    # shares event_run: day frames and event frames both live in frames_event/
    if event_run["proc"] and event_run["proc"].poll() is None:
        return {"state": "running"}
    EVENT_LOG.parent.mkdir(exist_ok=True)
    logf = open(EVENT_LOG, "w")
    event_run["proc"] = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(BASE / "load_day.ps1"), "-Date", day],
        stdout=logf, stderr=subprocess.STDOUT, cwd=BASE,
    )
    event_run["state"] = "running"

    def _watch_day(proc):
        proc.wait()
        event_run["state"] = "done" if proc.returncode == 0 else "failed"

    threading.Thread(target=_watch_day, args=(event_run["proc"],), daemon=True).start()
    return {"state": "running"}


@app.get("/api/geolocate")
def geolocate():
    """Approximate location of this machine from its public IP (ip-api.com,
    free, no key). Done server-side so the browser needs no CORS or https.
    Fallback for when the browser's own network-based geolocation is denied."""
    try:
        with urllib.request.urlopen(
            "http://ip-api.com/json/?fields=status,lat,lon,city,regionName,country",
            timeout=6,
        ) as r:
            info = json.load(r)
    except OSError as e:
        raise HTTPException(502, f"IP geolocation unreachable: {e}")
    if info.get("status") != "success":
        raise HTTPException(502, "IP geolocation failed")
    label = ", ".join(x for x in (info.get("city"), info.get("regionName"),
                                  info.get("country")) if x)
    return {"lat": info["lat"], "lon": info["lon"], "label": label}


@app.get("/api/event-status")
def event_status():
    detail = _tail(EVENT_LOG) if event_run["state"] == "running" else ""
    return {"state": event_run["state"], "detail": detail}


# static app last so /api/* wins
app.mount("/", StaticFiles(directory=BASE / "app", html=True), name="app")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8050)
