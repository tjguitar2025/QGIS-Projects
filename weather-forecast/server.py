"""Local weather app server.

Serves the web app (app/) and lets the browser trigger a new FourCastNetv2
forecast run via the existing run_forecast.ps1 pipeline.

    conda run -n weather python server.py     ->  http://localhost:8050
"""
import subprocess
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
LOG = BASE / "data" / "run_forecast.log"

app = FastAPI(title="Local Weather")
run = {"proc": None, "state": "idle"}   # idle | running | done | failed


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
    detail = ""
    if run["state"] == "running" and LOG.exists():
        lines = LOG.read_text(errors="ignore").strip().splitlines()
        if lines:
            detail = lines[-1][-90:]
    return {"state": run["state"], "detail": detail}


# static app last so /api/* wins
app.mount("/", StaticFiles(directory=BASE / "app", html=True), name="app")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8050)
