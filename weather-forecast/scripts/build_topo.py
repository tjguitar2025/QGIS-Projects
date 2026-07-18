"""One-time build of the terrain dataset used to sharpen temperature frames.

    python build_topo.py        ->  data/static/topo_0p1.npz

Two grids, both on lon -180..180 / lat 90..-90:
  dem     0.1 deg (1800x3600)  real surface elevation, ETOPO 2022 (NOAA),
                               strided server-side via OPeNDAP; ocean clamped to 0
  zmodel  0.25 deg (721x1440)  the forecast model's smoothed terrain,
                               ERA5 invariant geopotential / g (CDS)

grib_to_frames.py uses them to redraw 2t on the 0.1 deg grid with a
0.65 K / 100 m lapse-rate correction for the elevation the model can't see.
"""
from pathlib import Path

import numpy as np
import xarray as xr

OUT = Path(__file__).parent.parent / "data" / "static" / "topo_0p1.npz"
ETOPO = ("https://www.ngdc.noaa.gov/thredds/dodsC/global/ETOPO2022/60s/"
         "60s_surface_elev_netcdf/ETOPO_2022_v1_60s_N90W180_surface.nc")


def fetch_dem():
    print("fetching ETOPO 2022 (strided to 0.1 deg via OPeNDAP) ...", flush=True)
    ds = xr.open_dataset(ETOPO)
    z = ds.z[::6, ::6].load()          # 60 arc-sec -> 0.1 deg, server-side stride
    z = z.sortby("lat", ascending=False)
    dem = np.maximum(z.values.astype(np.float32), 0.0)   # ocean -> sea level
    return dem, z.lat.values.astype(np.float32), z.lon.values.astype(np.float32)


def fetch_model_orography():
    print("fetching ERA5 invariant orography (CDS) ...", flush=True)
    import cdsapi
    tmp = OUT.parent / "era5_orog.grib"
    if not tmp.exists():
        cdsapi.Client().retrieve(
            "reanalysis-era5-single-levels",
            {"product_type": "reanalysis", "variable": "geopotential",
             "date": "2026-01-01", "time": "00:00",
             "grid": [0.25, 0.25], "format": "grib"},
            str(tmp),
        )
    da = xr.open_dataset(tmp, engine="cfgrib")["z"]
    da = da.assign_coords(longitude=(((da.longitude + 180) % 360) - 180))
    da = da.sortby("longitude").sortby("latitude", ascending=False)
    zmodel = np.maximum(da.values.astype(np.float32) / 9.80665, 0.0)
    return zmodel, da.latitude.values.astype(np.float32), da.longitude.values.astype(np.float32)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    dem, dlat, dlon = fetch_dem()
    zmodel, mlat, mlon = fetch_model_orography()
    np.savez_compressed(OUT, dem=dem, dem_lat=dlat, dem_lon=dlon,
                        zmodel=zmodel, zmodel_lat=mlat, zmodel_lon=mlon)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)  "
          f"dem {dem.shape}  zmodel {zmodel.shape}")
