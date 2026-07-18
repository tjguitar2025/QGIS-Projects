"""Convert an AI-model forecast GRIB into frames for the web app.

Usage (one variable per invocation — a fresh process per variable keeps
ecCodes/cfgrib memory use bounded on large multi-variable GRIBs):
    python grib_to_frames.py <forecast.grib> --var 2t|msl|tcwv|tp|wind|isobars
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
    "tp": {
        # ERA5 hourly total precipitation: metres accumulated over the hour up
        # to the analysis time -> mm/h after x1000. Radar-style ramp, sqrt
        # scale so light rain gets most of the color range, transparent where
        # dry. Only available in --analysis (ERA5) datasets — FourCastNetv2
        # does not output precipitation.
        "label": "Precipitation (1h)",
        "units": "mm",
        "min": 0.0, "max": 16.0,
        "factor": 1000.0,          # m -> mm
        "scale": "sqrt",
        "alpha_ramp": (0.05, 0.5, 230),   # fade in between 0.05 and 0.5 mm
        "colors": [
            ( 0.0, (110, 170, 240)),
            ( 0.5, ( 80, 160, 245)),
            ( 1.0, ( 60, 150, 235)),
            ( 2.5, ( 60, 200, 130)),
            ( 4.0, (150, 215,  80)),
            ( 6.5, (240, 220,  70)),
            ( 9.0, (245, 160,  50)),
            (12.0, (235,  85,  45)),
            (16.0, (190,  30, 100)),
        ],
        # legend positions follow the sqrt scale: 0,1,4,9,16 are evenly spaced
        "ticks": ["0", "1", "4", "9", "16"],
    },
}
WIND_SUBSAMPLE = 4  # 0.25 deg grid -> 1 deg for leaflet-velocity

# Isobars: contour lines of MSL pressure every 4 hPa (synoptic-chart standard),
# heavier line every 20 hPa. Range covers record extremes (870 Wilma .. 1084 Agata).
ISOBAR_LEVELS = np.arange(872, 1088, 4)
ISOBAR_WRAP = 24  # columns repeated past the date line so lines stay continuous

# Terrain sharpening: redraw 2t on a 0.1 deg DEM grid with a fixed-lapse-rate
# correction for the elevation the 0.25 deg model terrain can't resolve
# (build the dataset once with build_topo.py; without it, frames stay 0.25 deg)
TOPO_PATH = Path(__file__).parent.parent / "data" / "static" / "topo_0p1.npz"
LAPSE_K_PER_M = 0.0065


def _var_spec(var: str, analysis: bool) -> dict:
    """Per-mode variable spec. tp differs: reanalysis days are 1h amounts,
    forecasts (IFS open data) are differenced into 6h amounts, so the
    forecast variant stretches the same ramp over a 0..64 mm range."""
    spec = VARS[var]
    if var == "tp" and not analysis:
        return {
            **spec,
            "label": "Precipitation (6h)",
            "max": 64.0,
            "colors": [(v * 4, c) for v, c in spec["colors"]],
            "ticks": ["0", "4", "16", "36", "64"],
            "alpha_ramp": (0.2, 2.0, 230),
        }
    return spec


def _open_var(grib_path: Path, short_name: str) -> xr.DataArray:
    ds = xr.open_dataset(
        grib_path, engine="cfgrib",
        backend_kwargs={"filter_by_keys": {"shortName": short_name}},
    )
    if not ds.data_vars and short_name == "tcwv":
        # AIFS publishes total column water (tcw) instead of water vapor;
        # near-identical field, rendered on the same moisture scale
        return _open_var(grib_path, "tcw")
    return ds[list(ds.data_vars)[0]]


def _anchor_pos(spec, value):
    """Normalized 0..1 position of a value on the (possibly sqrt) color scale."""
    p = (value - spec["min"]) / (spec["max"] - spec["min"])
    return p ** 0.5 if spec.get("scale") == "sqrt" else p


def _cmap(spec):
    anchors = [(_anchor_pos(spec, v), tuple(c / 255 for c in rgb))
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


def _iter_frames(da: xr.DataArray, analysis: bool):
    """Yield (hours, frame) pairs.

    Forecast GRIBs (ai-models output) have a `step` dimension from one init
    time; reanalysis GRIBs (ERA5 event sequences) have a `time` dimension of
    analysis times — hours are counted from the first one.
    """
    if analysis:
        if "step" in da.dims:
            # accumulated ERA5 vars (tp) come as forecast runs x hourly steps;
            # only the requested validity hours hold data — the rest of the
            # time x step hypercube is NaN padding. Flatten by valid time.
            frames = []
            for t in da.time.values:
                for s in da.step.values:
                    f = da.sel(time=t, step=s)
                    if np.isfinite(f.values).any():
                        frames.append((f.valid_time.values, f))
            frames.sort(key=lambda x: x[0])
            t0 = frames[0][0]
            for vt, f in frames:
                yield int((vt - t0) / np.timedelta64(1, "h")), f
            return
        times = da.time.values
        t0 = times[0]
        for t in times:
            yield int((t - t0) / np.timedelta64(1, "h")), da.sel(time=t)
    else:
        steps = da.step.values if "step" in da.dims else [da.step.values]
        for step in steps:
            yield int(step / np.timedelta64(1, "h")), da.sel(step=step)


def _interp_wrap(da2d: xr.DataArray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Bilinear-interpolate a lat/lon field to a finer grid, wrapping the last
    longitude interval so the +180 edge doesn't come out NaN."""
    first = da2d.isel(longitude=0)
    first = first.assign_coords(longitude=float(da2d.longitude.values[0]) + 360.0)
    ext = xr.concat([da2d, first], dim="longitude")
    return ext.interp(latitude=lat, longitude=lon).values.astype(np.float32)


def _topo_correction():
    """(dem_lat, dem_lon, correction) for terrain-sharpened 2t, or None.

    correction = lapse * (model_terrain - real_terrain) on the 0.1 deg grid:
    positive (warmer) in valleys the model terrain floats above, negative
    (colder) on peaks it smooths away."""
    if not TOPO_PATH.exists():
        return None
    t = np.load(TOPO_PATH)
    zm = xr.DataArray(
        t["zmodel"], dims=("latitude", "longitude"),
        coords={"latitude": t["zmodel_lat"], "longitude": t["zmodel_lon"]},
    )
    zm_hi = _interp_wrap(zm, t["dem_lat"], t["dem_lon"])
    return t["dem_lat"], t["dem_lon"], LAPSE_K_PER_M * (zm_hi - t["dem"])


def write_scalar_frames(grib_path: Path, var: str, outdir: Path, steps_meta: dict,
                        analysis: bool = False):
    spec = _var_spec(var, analysis)
    da = _shift_to_180(_open_var(grib_path, var))
    cmap = _cmap(spec)
    vardir = outdir / var
    vardir.mkdir(parents=True, exist_ok=True)
    topo = _topo_correction() if var == "2t" else None
    if topo is not None:
        print("2t: terrain sharpening on (0.1 deg DEM + lapse-rate correction)")

    count = 0
    prev = None
    for hours, frame in _iter_frames(da, analysis):
        if topo is not None:
            dem_lat, dem_lon, corr = topo
            # interp target lat runs 90..-90, so the result is already north-up
            vals = _interp_wrap(frame, dem_lat, dem_lon) + corr
        else:
            vals = np.nan_to_num(_north_up(frame)) * spec.get("factor", 1.0)
        if var == "tp" and not analysis:
            # forecast tp accumulates from init; difference into per-step amounts
            vals, prev = (vals - prev if prev is not None else vals), vals
        norm = np.clip((vals - spec["min"]) / (spec["max"] - spec["min"]), 0, 1)
        if spec.get("scale") == "sqrt":
            norm = np.sqrt(norm)
        rgba = (cmap(norm) * 255).astype(np.uint8)
        if "alpha_ramp" in spec:  # transparent where (nearly) zero, e.g. no rain
            v0, v1, amax = spec["alpha_ramp"]
            rgba[..., 3] = (np.clip((vals - v0) / (v1 - v0), 0, 1) * amax).astype(np.uint8)
        Image.fromarray(rgba, "RGBA").save(vardir / f"{var}_+{hours:03d}h.png", optimize=True)
        steps_meta.setdefault(hours, np.datetime_as_string(frame.valid_time.values, unit="m"))
        count += 1
    print(f"{var}: {count} PNG frames")


def write_isobar_frames(grib_path: Path, outdir: Path, analysis: bool = False):
    """Contour the MSL pressure field into transparent label-annotated PNGs.

    Drawn oversized (5760x2880 for a 0.25-deg grid) so the thin lines and the
    inline hPa labels stay crisp when Leaflet stretches the overlay.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import patheffects

    da = _shift_to_180(_open_var(grib_path, "msl"))
    lat = da.latitude.values
    lon = da.longitude.values
    # matplotlib contour wants ascending coords; ERA5/FCN lat runs 90..-90
    flip = lat[0] > lat[-1]
    if flip:
        lat = lat[::-1]
    # repeat the first columns past +180 so contours run through the date line
    # instead of ending at the image edge (the axes clip them at x=180)
    lon_ext = np.r_[lon, lon[:ISOBAR_WRAP] + 360.0]
    halo = [patheffects.withStroke(linewidth=1.4, foreground="#0b1524")]
    widths = [1.3 if lv % 20 == 0 else 0.65 for lv in ISOBAR_LEVELS]
    vardir = outdir / "isobars"
    vardir.mkdir(parents=True, exist_ok=True)

    count = 0
    for hours, frame in _iter_frames(da, analysis):
        hpa = frame.values / 100.0
        if flip:
            hpa = hpa[::-1, :]
        hpa = np.c_[hpa, hpa[:, :ISOBAR_WRAP]]
        fig = plt.figure(figsize=(28.8, 14.4), dpi=200)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()
        ax.set_xlim(-180, 180)
        ax.set_ylim(-90, 90)
        cs = ax.contour(lon_ext, lat, hpa, levels=ISOBAR_LEVELS,
                        colors="white", linewidths=widths, alpha=0.75)
        for t in ax.clabel(cs, fontsize=4.5, fmt="%d", inline=True, inline_spacing=3):
            t.set_color("white")
            t.set_path_effects(halo)
        fig.savefig(vardir / f"isobars_+{hours:03d}h.png", transparent=True)
        plt.close(fig)
        count += 1
    print(f"isobars: {count} PNG frames")


def write_wind_frames(grib_path: Path, outdir: Path, steps_meta: dict,
                      analysis: bool = False):
    # keep native 0..360 ordering; leaflet-velocity handles the wrap itself
    u = _open_var(grib_path, "10u")
    v = _open_var(grib_path, "10v")
    winddir = outdir / "wind"
    winddir.mkdir(parents=True, exist_ok=True)
    t0 = u.time.values[0] if analysis else u.time.values
    ref_time = np.datetime_as_string(t0, unit="s") + "Z"

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

    count = 0
    for (hours, u_frame), (_, v_frame) in zip(_iter_frames(u, analysis),
                                              _iter_frames(v, analysis)):
        records = []
        for num, frame in ((2, u_frame), (3, v_frame)):  # GRIB parameterNumber: 2=U, 3=V
            data = frame.values[::s, ::s]
            if frame.latitude.values[0] < frame.latitude.values[-1]:
                data = data[::-1, :]
            header = dict(header_base, parameterNumber=num, forecastTime=hours)
            records.append({
                "header": header,
                "data": [round(float(x), 2) for x in data.ravel()],
            })
        with open(winddir / f"wind_+{hours:03d}h.json", "w") as f:
            json.dump(records, f, separators=(",", ":"))
        count += 1
    print(f"wind: {count} JSON frames")


def write_timeline(grib_path: Path, outdir: Path, analysis: bool = False,
                   var_list: list | None = None, model: str = "FourCastNetv2 · local GPU"):
    da = _open_var(grib_path, "2t")
    steps_meta = {
        h: np.datetime_as_string(frame.valid_time.values, unit="m")
        for h, frame in _iter_frames(da, analysis)
    }
    hours = sorted(steps_meta)
    t0 = da.time.values[0] if analysis else da.time.values
    var_list = var_list or ["2t", "msl", "tcwv"]
    timeline = {
        "model": model,
        "init_time": np.datetime_as_string(t0, unit="m"),
        "steps": hours,
        "valid_times": [steps_meta[h] for h in hours],
        "bounds": [[-90, -180], [90, 180]],
        "vars": {
            var: {
                "label": spec["label"],
                "units": spec["units"],
                # (spec comes from _var_spec so tp gets its per-mode variant)
                # CSS gradient stops at each anchor's true scale position
                "gradient": [
                    f"rgb({c[0]},{c[1]},{c[2]}) {_anchor_pos(spec, v) * 100:.0f}%"
                    for v, c in spec["colors"]
                ],
                "ticks": spec["ticks"],
            }
            for var, spec in ((v, _var_spec(v, analysis)) for v in var_list)
        },
    }
    with open(outdir / "timeline.json", "w") as f:
        json.dump(timeline, f, indent=1)
    print(f"timeline.json: {len(hours)} steps, init {timeline['init_time']}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("grib", type=Path)
    p.add_argument("--var", choices=[*VARS, "wind", "isobars"])
    p.add_argument("--timeline", action="store_true")
    p.add_argument("--vars", help="comma list of vars to describe in timeline.json "
                                  "(default: 2t,msl,tcwv)")
    p.add_argument("--model", default="FourCastNetv2 · local GPU",
                   help="model label shown in the app legend")
    p.add_argument("--analysis", action="store_true",
                   help="input is a reanalysis time sequence (ERA5 event), not a forecast")
    p.add_argument("--outdir", type=Path,
                   default=Path(__file__).parent.parent / "app" / "frames")
    args = p.parse_args()

    if args.timeline:
        var_list = [v.strip() for v in args.vars.split(",")] if args.vars else None
        write_timeline(args.grib, args.outdir, analysis=args.analysis,
                       var_list=var_list, model=args.model)
    elif args.var == "wind":
        write_wind_frames(args.grib, args.outdir, {}, analysis=args.analysis)
    elif args.var == "isobars":
        write_isobar_frames(args.grib, args.outdir, analysis=args.analysis)
    elif args.var:
        write_scalar_frames(args.grib, args.var, args.outdir, {}, analysis=args.analysis)
    else:
        p.error("pass --var <name> or --timeline")


if __name__ == "__main__":
    main()
