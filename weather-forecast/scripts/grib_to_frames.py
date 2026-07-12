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

# Per-variable color scales. `colors` are (value_in_native_units, rgb) anchors
# for a smooth colormap; `ticks` are the few labels shown under the legend bar
# (evenly spaced, so they line up with a value grid).
VARS = {
    "2t": {
        "label": "Temperature",
        "units": "°F",
        # -40 °F .. 120 °F in Kelvin — US TV-weather range with a freezing break
        "min": 233.15, "max": 322.039,
        # Weather Channel / NWS-style temperature rainbow, one anchor per 10 °F:
        # violet (extreme cold) -> blue -> cyan -> green -> yellow -> orange ->
        # red -> magenta (extreme heat). Cyan->green transition sits near 32 °F.
        "colors": [
            (233.150, (179, 157, 219)),  # -40 °F
            (238.706, (126,  87, 194)),  # -30
            (244.261, ( 94,  53, 177)),  # -20
            (249.817, ( 57,  73, 171)),  # -10
            (255.372, ( 30,  95, 208)),  #   0
            (260.928, ( 46, 134, 224)),  #  10
            (266.483, ( 86, 176, 232)),  #  20
            (272.039, (143, 211, 240)),  #  30  (~freezing)
            (277.594, (124, 201, 143)),  #  40
            (283.150, ( 70, 180,  90)),  #  50
            (288.706, (159, 210,  78)),  #  60
            (294.261, (242, 225,  75)),  #  70
            (299.817, (246, 185,  59)),  #  80
            (305.372, (239, 125,  42)),  #  90
            (310.928, (226,  59,  32)),  # 100
            (316.483, (183,  28,  28)),  # 110
            (322.039, (122,  31, 107)),  # 120
        ],
        "ticks": ["-40°", "0°", "40°", "80°", "120°"],
    },
    "msl": {
        "label": "Sea-level pressure",
        "units": "hPa",
        "min": 95000.0, "max": 105000.0,
        "colors": [
            ( 95000.0, (120,  30, 160)),
            (100000.0, (240, 240, 240)),
            (105000.0, (230, 140,  30)),
        ],
        "ticks": ["950", "1000", "1050"],
    },
    "tcwv": {
        "label": "Moisture (total column water vapor)",
        "units": "kg/m²",
        "min": 0.0, "max": 70.0,
        "colors": [
            ( 0.0, (255, 255, 255)),
            (35.0, ( 90, 180, 200)),
            (70.0, ( 20,  60, 150)),
        ],
        "ticks": ["0", "35", "70"],
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
               for v, rgb in spec["colors"]]
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
                "gradient": [f"rgb({c[0]},{c[1]},{c[2]})" for _, c in spec["colors"]],
                "ticks": spec["ticks"],
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
