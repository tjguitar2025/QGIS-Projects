"""Fetch IFS total-precipitation forecast from ECMWF open data.

Usage:
    python fetch_opendata_tp.py --date 20260714 --lead-time 144 --out data/forecasts/tp_20260714.grib

FourCastNetv2 does not output precipitation, so the app's forecast precip
layer comes from the physics-based IFS forecast of the same 00z cycle
(ECMWF open data, CC BY 4.0). tp is accumulated from forecast start;
grib_to_frames.py differences consecutive steps into per-6h amounts.
"""
import argparse
from pathlib import Path

from ecmwf.opendata import Client


def fetch(date: str, lead_time: int, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    client = Client(source="ecmwf")
    steps = list(range(0, lead_time + 1, 6))
    print(f"requesting IFS tp, init {date} 00z, steps {steps[0]}..{steps[-1]} ...", flush=True)
    client.retrieve(
        type="fc", param="tp", step=steps,
        date=date, time=0,
        target=str(out),
    )
    print(f"wrote {out} ({out.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="init date YYYYMMDD")
    p.add_argument("--lead-time", type=int, default=144)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    fetch(args.date, args.lead_time, args.out)
