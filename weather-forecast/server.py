"""Local weather app server.

Serves the web app (app/) and lets the browser trigger a new FourCastNetv2
forecast run via the existing run_forecast.ps1 pipeline.

    conda run -n weather python server.py     ->  http://localhost:8050
"""
import re
import subprocess
import threading
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


@app.get("/api/event-status")
def event_status():
    detail = _tail(EVENT_LOG) if event_run["state"] == "running" else ""
    return {"state": event_run["state"], "detail": detail}


# static app last so /api/* wins
app.mount("/", StaticFiles(directory=BASE / "app", html=True), name="app")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8050)
