"""Convert an AI-model forecast GRIB into frames for the web app.

Usage (one variable per invocation — a fresh process per variable keeps
ecCodes/cfgrib memory use bounded on large multi-variable GRIBs):
    python grib_to_frames.py <forecast.grib> --var 2t|msl|tcwv|wind
    python grib_to_frames.py <forecast.grib> --timeline

Outputs, per 6h forecast step:
  app/frames/<var>/<var>_+NNNh.png   colorized transparent overlays (2t, msl, tcwv)
  app/frames/wind/wind_+NNNh.json    u10/v10 grid in leaflet-velocity format (1 deg)
  app/frames/timeline.json           steps, valid times, bounds, legend metadata
"""
import argparse
import json
from pathlib import Path

import numpy as np
import xarray as xr
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image

# value stops -> colors, matching the ramps used in the old QGIS project
VARS = {
    "2t": {
        "label": "2m temperature",
        "units": "°C",
        "min": 233.15, "max": 313.15,
        "stops": [
            (233.15, (48, 18, 227), "-40"),
            (273.15, (240, 240, 240), "0"),
            (313.15, (200, 30, 30), "+40"),
        ],
    },
    "msl": {
        "label": "Sea-level pressure",
        "units": "hPa",
        "min": 95000.0, "max": 105000.0,
        "stops": [
            (95000.0, (120, 30, 160), "950"),
            (100000.0, (240, 240, 240), "1000"),
            (105000.0, (230, 140, 30), "1050"),
        ],
    },
    "tcwv": {
        "label": "Moisture (total column water vapor)",
        "units": "kg/m²",
        "min": 0.0, "max": 70.0,
        "stops": [
            (0.0, (255, 255, 255), "0"),
            (35.0, (90, 180, 200), "35"),
            (70.0, (20, 60, 150), "70"),
        ],
    },
}
WIND_SUBSAMPLE = 4  # 0.25 deg grid -> 1 deg for leaflet-velocity


def _open_var(grib_path: Path, short_name: str) -> xr.DataArray:
    ds = xr.open_dataset(
        grib_path, engine="cfgrib",
        backend_kwargs={"filter_by_keys": {"shortName": short_name}},
    )
    return ds[list(ds.data_vars)[0]]


def _cmap(spec):
    lo, hi = spec["min"], spec["max"]
    anchors = [((v - lo) / (hi - lo), tuple(c / 255 for c in rgb))
               for v, rgb, _ in spec["stops"]]
    return LinearSegmentedColormap.from_list("ramp", anchors)


def _shift_to_180(da: xr.DataArray) -> xr.DataArray:
    # Longitude 0..360 -> -180..180 so overlays fit a normal Leaflet world map
    if float(da.longitude.max()) > 180:
        da = da.assign_coords(longitude=(((da.longitude + 180) % 360) - 180))
        da = da.sortby("longitude")
    return da


def _north_up(frame: xr.DataArray) -> np.ndarray:
    data = frame.values
    lat = frame.latitude.values
    if lat[0] < lat[-1]:
        data = data[::-1, :]
    return data


def write_scalar_frames(grib_path: Path, var: str, outdir: Path, steps_meta: dict):
    spec = VARS[var]
    da = _shift_to_180(_open_var(grib_path, var))
    cmap = _cmap(spec)
    vardir = outdir / var
    vardir.mkdir(parents=True, exist_ok=True)

    steps = da.step.values if "step" in da.dims else [da.step.values]
    for step in steps:
        frame = da.sel(step=step)
        hours = int(step / np.timedelta64(1, "h"))
        norm = np.clip((_north_up(frame) - spec["min"]) / (spec["max"] - spec["min"]), 0, 1)
        rgba = (cmap(norm) * 255).astype(np.uint8)
        Image.fromarray(rgba, "RGBA").save(vardir / f"{var}_+{hours:03d}h.png", optimize=True)
        steps_meta.setdefault(hours, np.datetime_as_string(frame.valid_time.values, unit="m"))
    print(f"{var}: {len(steps)} PNG frames")


def write_wind_frames(grib_path: Path, outdir: Path, steps_meta: dict):
    # keep native 0..360 ordering; leaflet-velocity handles the wrap itself
    u = _open_var(grib_path, "10u")
    v = _open_var(grib_path, "10v")
    winddir = outdir / "wind"
    winddir.mkdir(parents=True, exist_ok=True)
    ref_time = np.datetime_as_string(u.time.values, unit="s") + "Z"

    s = WIND_SUBSAMPLE
    lat = u.latitude.values[::s]
    lon = u.longitude.values[::s]
    header_base = {
        "parameterCategory": 2,
        "lo1": float(lon[0]), "la1": float(lat[0]),
        "lo2": float(lon[-1]), "la2": float(lat[-1]),
        "dx": abs(float(lon[1] - lon[0])), "dy": abs(float(lat[1] - lat[0])),
        "nx": len(lon), "ny": len(lat),
        "refTime": ref_time,
    }

    steps = u.step.values if "step" in u.dims else [u.step.values]
    for step in steps:
        hours = int(step / np.timedelta64(1, "h"))
        records = []
        for num, da in ((2, u), (3, v)):  # GRIB parameterNumber: 2=U, 3=V
            data = da.sel(step=step).values[::s, ::s]
            if da.latitude.values[0] < da.latitude.values[-1]:
                data = data[::-1, :]
            header = dict(header_base, parameterNumber=num, forecastTime=hours)
            records.append({
                "header": header,
                "data": [round(float(x), 2) for x in data.ravel()],
            })
        with open(winddir / f"wind_+{hours:03d}h.json", "w") as f:
            json.dump(records, f, separators=(",", ":"))
    print(f"wind: {len(steps)} JSON frames")


def write_timeline(grib_path: Path, outdir: Path):
    da = _open_var(grib_path, "2t")
    steps = da.step.values if "step" in da.dims else [da.step.values]
    steps_meta = {
        int(s / np.timedelta64(1, "h")):
            np.datetime_as_string(da.sel(step=s).valid_time.values, unit="m")
        for s in steps
    }
    hours = sorted(steps_meta)
    timeline = {
        "init_time": np.datetime_as_string(da.time.values, unit="m"),
        "steps": hours,
        "valid_times": [steps_meta[h] for h in hours],
        "bounds": [[-90, -180], [90, 180]],
        "vars": {
            var: {
                "label": spec["label"],
                "units": spec["units"],
                "legend": [
                    {"value": lbl, "color": f"rgb({c[0]},{c[1]},{c[2]})"}
                    for _, c, lbl in spec["stops"]
                ],
            }
            for var, spec in VARS.items()
        },
    }
    with open(outdir / "timeline.json", "w") as f:
        json.dump(timeline, f, indent=1)
    print(f"timeline.json: {len(hours)} steps, init {timeline['init_time']}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("grib", type=Path)
    p.add_argument("--var", choices=[*VARS, "wind"])
    p.add_argument("--timeline", action="store_true")
    p.add_argument("--outdir", type=Path,
                   default=Path(__file__).parent.parent / "app" / "frames")
    args = p.parse_args()

    if args.timeline:
        write_timeline(args.grib, args.outdir)
    elif args.var == "wind":
        write_wind_frames(args.grib, args.outdir, {})
    elif args.var:
        write_scalar_frames(args.grib, args.var, args.outdir, {})
    else:
        p.error("pass --var <name> or --timeline")


if __name__ == "__main__":
    main()
