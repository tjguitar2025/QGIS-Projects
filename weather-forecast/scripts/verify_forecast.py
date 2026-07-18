"""Continuous forecast verification (skill score-keeping).

Run after each forecast (non-fatal pipeline stage) or by hand:
    python verify_forecast.py

Does two things:
 1. Archives today's 00z IFS analysis (2t + msl, step-0 fields from ECMWF
    open data) into data/verif/ — small, a few MB per day.
 2. Scores every forecast GRIB in data/forecasts/ against every archived
    analysis at matching valid times: global latitude-weighted RMSE and mean
    bias, appended once per (model, init, lead, var) to data/verif/scores.csv.

The CSV is the model-health record: if skill ever drifts (e.g. an upstream
analysis-cycle change), the day-1/2/3 RMSE trend shows it immediately.
"""
import csv
import re
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

BASE = Path(__file__).parent.parent
FORECASTS = BASE / "data" / "forecasts"
VERIF = BASE / "data" / "verif"
SCORES = VERIF / "scores.csv"
COLS = ["model", "init", "lead_h", "valid", "var", "bias", "rmse", "scored_at"]
VARS = {"2t": ("K", 1.0), "msl": ("hPa", 0.01)}
FC_RE = re.compile(r"^(fcnv2|aifs)_(\d{8})\.grib$")


def fetch_todays_analysis():
    """Save today's 00z step-0 IFS fields as verification truth (if not yet)."""
    day = date.today().strftime("%Y%m%d")
    out = VERIF / f"analysis_{day}.grib"
    if out.exists():
        return
    from ecmwf.opendata import Client
    VERIF.mkdir(parents=True, exist_ok=True)
    try:
        Client(source="ecmwf").retrieve(
            type="fc", param=["2t", "msl"], step=0,
            date=day, time=0, target=str(out),
        )
        print(f"archived analysis {out.name} ({out.stat().st_size / 1e6:.1f} MB)")
    except Exception as e:  # today's cycle not out yet, or offline — try next run
        print(f"analysis fetch skipped: {e}")
        out.unlink(missing_ok=True)


def _open(path, short):
    ds = xr.open_dataset(path, engine="cfgrib",
                         backend_kwargs={"filter_by_keys": {"shortName": short}})
    da = ds[list(ds.data_vars)[0]]
    # normalize grid conventions so forecast and analysis subtract cell-for-cell
    # (ai-models GRIBs use lon 0..360, IFS open data uses -180..180)
    da = da.assign_coords(longitude=(((da.longitude + 180) % 360) - 180))
    da = da.sortby("longitude")
    if da.latitude.values[0] < da.latitude.values[-1]:
        da = da.sortby("latitude", ascending=False)
    return da


def _score(f, o, lat):
    w = np.cos(np.deg2rad(lat))[:, None]
    d = f - o
    bias = float((d * w).sum() / (w.sum() * d.shape[1]))
    rmse = float(np.sqrt((d * d * w).sum() / (w.sum() * d.shape[1])))
    return bias, rmse


def score_forecasts():
    truths = {}  # valid datetime64 -> {var: (values, lat)}
    for ap in sorted(VERIF.glob("analysis_*.grib")):
        for var in VARS:
            da = _open(ap, var)
            vt = np.datetime64(str(da.valid_time.values), "h")
            truths.setdefault(vt, {})[var] = (da.values, da.latitude.values)
    if not truths:
        print("no archived analyses yet — nothing to score")
        return

    done = set()
    if SCORES.exists():
        with open(SCORES, newline="") as fh:
            for row in csv.DictReader(fh):
                done.add((row["model"], row["init"], row["lead_h"], row["var"]))

    new_rows = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    for fp in sorted(FORECASTS.glob("*.grib")):
        m = FC_RE.match(fp.name)
        if not m:
            continue
        model = m.group(1)
        for var, (unit, scale) in VARS.items():
            try:
                fc = _open(fp, var)
            except Exception as e:
                print(f"{fp.name}: cannot open {var}: {e}")
                continue
            init = np.datetime64(str(fc.time.values), "h")
            for st in np.atleast_1d(fc.step.values):
                lead = int(st / np.timedelta64(1, "h"))
                vt = init + st.astype("timedelta64[h]")
                key = (model, str(init), str(lead), var)
                if lead == 0 or vt not in truths or key in done:
                    continue
                # single-step GRIBs carry step as a scalar coord, not a dim
                f = (fc.sel(step=st) if "step" in fc.dims else fc).values * scale
                if not np.isfinite(f).all() or (var == "2t" and f.mean() < 100 * scale):
                    print(f"{fp.name} +{lead}h {var}: corrupt/empty field, skipped")
                    continue
                o, lat = truths[vt][var]
                bias, rmse = _score(f, o * scale, lat)
                new_rows.append(dict(zip(COLS, [model, str(init), lead, str(vt),
                                               var, f"{bias:.4f}", f"{rmse:.4f}", now])))
                done.add(key)

    if new_rows:
        write_header = not SCORES.exists()
        with open(SCORES, "a", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=COLS)
            if write_header:
                wr.writeheader()
            wr.writerows(new_rows)
    print(f"scored {len(new_rows)} new (model, lead, var) combinations -> {SCORES.name}")
    for r in new_rows:
        print(f"  {r['model']} init {r['init']} +{r['lead_h']:>3}h {r['var']:<3}"
              f"  bias {float(r['bias']):+7.2f}  rmse {float(r['rmse']):6.2f}")


if __name__ == "__main__":
    fetch_todays_analysis()
    score_forecasts()
