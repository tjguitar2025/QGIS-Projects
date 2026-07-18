"""Fetch an AIFS-single forecast from ECMWF open data.

Usage:
    python fetch_aifs.py --date 20260718 --lead-time 144 --out data/forecasts/aifs_20260718.grib

AIFS is ECMWF's operational AI forecast model (CC BY 4.0 open data, 0.25 deg,
released minutes after each cycle). One GRIB carries everything the app
renders — 2t, msl, 10u/10v, tcw (moisture) and native tp — so AIFS mode needs
neither the local GPU nor the separate IFS precipitation fetch.
"""
import argparse
from pathlib import Path

from ecmwf.opendata import Client

PARAMS = ["2t", "msl", "10u", "10v", "tcw", "tp"]


def fetch(date: str, lead_time: int, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    client = Client(source="ecmwf", model="aifs-single")
    steps = list(range(0, lead_time + 1, 6))
    print(f"requesting AIFS {PARAMS}, init {date} 00z, steps {steps[0]}..{steps[-1]} ...",
          flush=True)
    client.retrieve(
        type="fc", param=PARAMS, step=steps,
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
