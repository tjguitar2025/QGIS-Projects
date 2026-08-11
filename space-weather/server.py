"""SpaceWeather — local server.

Serves the web app and proxies the upstream data services (NOAA SWPC, NASA
DONKI) with a short in-memory cache, so the browser talks to one origin and
upstream rate limits are respected.

Run:  conda run -n weather uvicorn server:app --port 8060
"""
import json
import os
import time
import urllib.request
import urllib.parse
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
NASA_API_KEY = os.environ.get("NASA_API_KEY", "DEMO_KEY")

SWPC_BASE = "https://services.swpc.noaa.gov"
DONKI_BASE = "https://api.nasa.gov/DONKI"

# Only these SWPC paths may be proxied (path-prefix safelist).
SWPC_ALLOWED = (
    "products/",
    "json/",
)
DONKI_ALLOWED = {"FLR", "CME", "GST", "IPS", "HSS", "SEP", "notifications"}

# path -> (fetched_at, payload)
_cache: dict[str, tuple[float, object]] = {}

app = FastAPI(title="SpaceWeather")


def _sanitize(o):
    """NaN/Infinity appear in SWPC feeds; they are not valid JSON — null them."""
    if isinstance(o, float):
        return o if o == o and abs(o) != float("inf") else None
    if isinstance(o, list):
        return [_sanitize(v) for v in o]
    if isinstance(o, dict):
        return {k: _sanitize(v) for k, v in o.items()}
    return o


def _fetch_json(url: str, ttl: int, cache_key: str):
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": "SpaceWeather-local/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = _sanitize(json.loads(r.read().decode("utf-8")))
    except Exception as e:  # upstream hiccup: serve stale if we have it
        if hit:
            return hit[1]
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")
    _cache[cache_key] = (now, data)
    return data


@app.get("/api/swpc/{path:path}")
def swpc(path: str):
    if not any(path.startswith(p) for p in SWPC_ALLOWED) or ".." in path:
        raise HTTPException(status_code=404, detail="not an allowed SWPC product")
    # OVATION aurora grid is big and refreshes ~5 min; everything else 60 s.
    ttl = 300 if "ovation" in path else 60
    return JSONResponse(_fetch_json(f"{SWPC_BASE}/{path}", ttl, f"swpc:{path}"))


@app.get("/api/donki/{event}")
def donki(event: str, startDate: str = "", endDate: str = ""):
    if event not in DONKI_ALLOWED:
        raise HTTPException(status_code=404, detail="not an allowed DONKI event type")
    q = {"api_key": NASA_API_KEY}
    if startDate:
        q["startDate"] = startDate
    if endDate:
        q["endDate"] = endDate
    if event == "notifications":
        q["type"] = "all"
    url = f"{DONKI_BASE}/{event}?{urllib.parse.urlencode(q)}"
    # DONKI events update slowly and DEMO_KEY is rate-limited: cache 30 min.
    return JSONResponse(_fetch_json(url, 1800, f"donki:{event}:{startDate}:{endDate}"))


app.mount("/", StaticFiles(directory=BASE / "app", html=True), name="app")
