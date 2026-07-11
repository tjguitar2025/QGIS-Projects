"""Plot a Skew-T log-P sounding from a FourCastNetv2 forecast GRIB at a point.

Usage:
    python skewt_at_point.py <forecast.grib> --lat 39.1 --lon -94.6 --step 24
    (step = forecast hour: 0, 6, 12, ... 144)

Writes  skewt_<lat>_<lon>_+<step>h.png  next to the GRIB file.
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from metpy.plots import SkewT
from metpy.units import units
import metpy.calc as mpcalc


def open_level_var(grib: Path, short_name: str, step_h: int) -> xr.DataArray:
    ds = xr.open_dataset(
        grib, engine="cfgrib",
        backend_kwargs={"filter_by_keys": {
            "shortName": short_name, "typeOfLevel": "isobaricInhPa"}},
    )
    da = ds[list(ds.data_vars)[0]]
    return da.sel(step=np.timedelta64(step_h, "h"))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("grib", type=Path)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--step", type=int, default=0, help="forecast hour (multiple of 6)")
    args = p.parse_args()

    lon360 = args.lon % 360  # model grid is 0..360

    t = open_level_var(args.grib, "t", args.step)
    u = open_level_var(args.grib, "u", args.step)
    v = open_level_var(args.grib, "v", args.step)
    r = open_level_var(args.grib, "r", args.step)

    sel = dict(latitude=args.lat, longitude=lon360, method="nearest")
    levels = t.isobaricInhPa.values * units.hPa
    T = t.sel(**sel).values * units.K
    U = (u.sel(**sel).values * units("m/s")).to("knots")
    V = (v.sel(**sel).values * units("m/s")).to("knots")
    RH = np.clip(r.sel(**sel).values, 0.5, 100.0) * units.percent
    Td = mpcalc.dewpoint_from_relative_humidity(T, RH)

    # sort surface -> top (descending pressure)
    order = np.argsort(levels.m)[::-1]
    levels, T, Td, U, V = levels[order], T[order], Td[order], U[order], V[order]

    valid = np.datetime_as_string(t.sel(**sel).valid_time.values, unit="m")
    fig = plt.figure(figsize=(8, 9))
    skew = SkewT(fig, rotation=45)
    skew.plot(levels, T.to("degC"), "r", lw=2, label="Temperature")
    skew.plot(levels, Td, "g", lw=2, label="Dewpoint")
    skew.plot_barbs(levels, U, V)
    skew.plot_dry_adiabats(alpha=0.25)
    skew.plot_moist_adiabats(alpha=0.25)
    skew.plot_mixing_lines(alpha=0.25)
    skew.ax.set_ylim(1000, 100)
    skew.ax.set_xlim(-45, 45)
    skew.ax.legend(loc="upper left")
    plt.title(f"FourCastNetv2 sounding  {args.lat:.2f}, {args.lon:.2f}\n"
              f"valid {valid}Z (+{args.step}h)")

    out = args.grib.parent / f"skewt_{args.lat:.2f}_{args.lon:.2f}_+{args.step:03d}h.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
