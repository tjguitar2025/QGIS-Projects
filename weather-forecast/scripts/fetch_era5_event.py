"""Fetch an ERA5 reanalysis sequence for a historical weather event or day.

Usage:
    python fetch_era5_event.py --start 2005-08-23 --end 2005-08-31 --out data/events/katrina.grib
    python fetch_era5_event.py --start 2025-07-30 --end 2025-07-30 --hourly --vars 2t,tp,wind --out ...

Downloads global 0.25-degree surface fields for the date range, 6-hourly by
default (--hourly for all 24 analysis times). CDS expands year/month/day
requests as a cross-product, so ranges that cross a month boundary are split
into one request per month and the GRIBs are byte-concatenated (valid for GRIB).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import cdsapi

# app variable short names -> CDS request variable names
CDS_VARS = {
    "2t": ["2m_temperature"],
    "msl": ["mean_sea_level_pressure"],
    "tcwv": ["total_column_water_vapour"],
    "wind": ["10m_u_component_of_wind", "10m_v_component_of_wind"],
    "tp": ["total_precipitation"],
}
DEFAULT_VARS = "2t,msl,tcwv,wind"


def month_segments(start: date, end: date):
    """Split [start, end] into per-month (year, month, [days]) segments."""
    segments = []
    d = start
    while d <= end:
        days = []
        month_start = d
        while d <= end and d.month == month_start.month:
            days.append(f"{d.day:02d}")
            d += timedelta(days=1)
        segments.append((f"{month_start.year}", f"{month_start.month:02d}", days))
    return segments


def _var_groups(variables):
    """Split into accumulated (tp, separate CDS stream) vs instantaneous fields.

    Submitting the groups as concurrent CDS requests lets them queue and
    download in parallel, roughly halving wall time vs one combined request.
    """
    accum = [v for v in variables if v == "total_precipitation"]
    inst = [v for v in variables if v != "total_precipitation"]
    return [g for g in (inst, accum) if g]


def _retrieve(part: Path, year, month, days, group, times):
    print(f"requesting {year}-{month} days {days[0]}..{days[-1]}: "
          f"{', '.join(group)} ...", flush=True)
    cdsapi.Client().retrieve(  # one client per request: cdsapi isn't thread-safe
        "reanalysis-era5-single-levels",
        {
            "product_type": ["reanalysis"],
            "variable": group,
            "year": [year],
            "month": [month],
            "day": days,
            "time": times,
            "data_format": "grib",
            "download_format": "unarchived",
        },
        str(part),
    )
    return part


def fetch(start: date, end: date, out: Path, variables, times):
    out.parent.mkdir(parents=True, exist_ok=True)
    jobs = []
    i = 0
    for year, month, days in month_segments(start, end):
        for group in _var_groups(variables):
            jobs.append((out.with_suffix(f".part{i}.grib"), year, month, days,
                         group, times))
            i += 1

    # CDS allows a handful of concurrent requests per user; don't flood it
    with ThreadPoolExecutor(max_workers=min(len(jobs), 4)) as pool:
        parts = list(pool.map(lambda j: _retrieve(*j), jobs))

    # GRIB messages are self-contained; byte order across parts doesn't matter
    with open(out, "wb") as dst:
        for part in parts:
            dst.write(part.read_bytes())
            part.unlink()
    print(f"wrote {out} ({out.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--vars", default=DEFAULT_VARS,
                   help=f"comma list of {'/'.join(CDS_VARS)} (default {DEFAULT_VARS})")
    p.add_argument("--hourly", action="store_true",
                   help="all 24 analysis times per day (default: 00/06/12/18)")
    args = p.parse_args()

    variables = []
    for v in args.vars.split(","):
        variables += CDS_VARS[v.strip()]
    times = ([f"{h:02d}:00" for h in range(24)] if args.hourly
             else ["00:00", "06:00", "12:00", "18:00"])
    fetch(date.fromisoformat(args.start), date.fromisoformat(args.end), args.out,
          variables, times)
