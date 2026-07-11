"""Phase 3: Convert an AI-model forecast GRIB into per-timestep GeoTIFFs for QGIS.

Usage:
    python grib_to_geotiff.py <forecast.grib> [--var 2t] [--outdir ../data/geotiffs]

Each output file is named  <var>_<YYYYMMDDHH>+<step>h.tif  and carries the
valid time in its filename so QGIS's Temporal Controller can animate them.
"""
import argparse
from pathlib import Path

import numpy as np
import xarray as xr
import rasterio
from rasterio.transform import from_origin


def _open_var(grib_path: Path, short_name: str) -> xr.DataArray:
    ds = xr.open_dataset(
        grib_path, engine="cfgrib",
        backend_kwargs={"filter_by_keys": {"shortName": short_name}},
    )
    return ds[list(ds.data_vars)[0]]


def convert(grib_path: Path, var: str, outdir: Path) -> list[Path]:
    # cfgrib splits GRIB into datasets by level type; filter to the surface var
    if var == "wind":
        # 10m wind speed from u/v components
        u = _open_var(grib_path, "10u")
        v = _open_var(grib_path, "10v")
        da = np.hypot(u, v)
        da = da.assign_coords(u.coords)
    else:
        da = _open_var(grib_path, var)

    # Longitude 0..360 -> -180..180 so QGIS displays a normal world map
    if float(da.longitude.max()) > 180:
        da = da.assign_coords(longitude=(((da.longitude + 180) % 360) - 180))
        da = da.sortby("longitude")

    lon = da.longitude.values
    lat = da.latitude.values
    res_x = abs(float(lon[1] - lon[0]))
    res_y = abs(float(lat[1] - lat[0]))
    transform = from_origin(lon.min() - res_x / 2, lat.max() + res_y / 2, res_x, res_y)

    outdir.mkdir(parents=True, exist_ok=True)
    base_time = np.datetime_as_string(da.time.values, unit="h").replace("-", "").replace("T", "")

    steps = da.step.values if "step" in da.dims else [da.step.values]
    written = []
    for step in steps:
        frame = da.sel(step=step)
        hours = int(step / np.timedelta64(1, "h"))
        # north-up ordering for GeoTIFF
        data = frame.values
        if lat[0] < lat[-1]:
            data = data[::-1, :]

        out = outdir / f"{var}_{base_time}+{hours:03d}h.tif"
        with rasterio.open(
            out, "w", driver="GTiff",
            height=data.shape[0], width=data.shape[1], count=1,
            dtype=data.dtype, crs="EPSG:4326", transform=transform,
            compress="deflate",
        ) as dst:
            dst.write(data, 1)
            valid = np.datetime_as_string(frame.valid_time.values, unit="m")
            dst.update_tags(VALID_TIME=valid, FORECAST_STEP_HOURS=hours)
        written.append(out)
        print(f"wrote {out.name}  (valid {valid})")

    return written


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("grib", type=Path)
    p.add_argument("--var", default="2t", help="GRIB shortName, e.g. 2t, 10u, 10v, msl, tp")
    p.add_argument("--outdir", type=Path, default=Path(__file__).parent.parent / "data" / "geotiffs")
    args = p.parse_args()
    files = convert(args.grib, args.var, args.outdir)
    print(f"\n{len(files)} GeoTIFFs ready — load the folder in QGIS and enable temporal navigation.")
