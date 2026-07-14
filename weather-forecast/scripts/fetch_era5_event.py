"""Fetch an ERA5 reanalysis sequence for a historical weather event.

Usage:
    python fetch_era5_event.py --start 2005-08-23 --end 2005-08-31 --out data/events/katrina.grib

Downloads global 0.25-degree surface fields at 6-hourly steps for the date
range: 2m temperature, MSL pressure, total column water vapour, 10m u/v wind
(the five fields the app renders). CDS expands year/month/day requests as a
cross-product, so ranges that cross a month boundary are split into one
request per month and the GRIBs are byte-concatenated (valid for GRIB).
"""
import argparse
from datetime import date, timedelta
from pathlib import Path

import cdsapi

VARIABLES = [
    "2m_temperature",
    "mean_sea_level_pressure",
    "total_column_water_vapour",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
]
TIMES = ["00:00", "06:00", "12:00", "18:00"]


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


def fetch(start: date, end: date, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    client = cdsapi.Client()
    parts = []
    for i, (year, month, days) in enumerate(month_segments(start, end)):
        part = out.with_suffix(f".part{i}.grib")
        print(f"requesting {year}-{month} days {days[0]}..{days[-1]} ...", flush=True)
        client.retrieve(
            "reanalysis-era5-single-levels",
            {
                "product_type": ["reanalysis"],
                "variable": VARIABLES,
                "year": [year],
                "month": [month],
                "day": days,
                "time": TIMES,
                "data_format": "grib",
                "download_format": "unarchived",
            },
            str(part),
        )
        parts.append(part)

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
    args = p.parse_args()
    fetch(date.fromisoformat(args.start), date.fromisoformat(args.end), args.out)
