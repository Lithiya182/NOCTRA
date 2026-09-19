"""Pre-fetch real FIRMS VIIRS detections for the four demo regions and cache to CSV.

Usage:  python scripts/fetch_firms.py
Requires FIRMS_MAP_KEY in .env. See https://firms.modaps.eosdis.nasa.gov/api/area/csv/
"""
from __future__ import annotations

import csv
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

DATA = Path(__file__).resolve().parent.parent / "data"

REGIONS = {
    "jharia": "22.7,86.2,23.9,86.7",       # minlat,minlon,maxlat,maxlon
    "jamnagar": "22.3,69.8,22.6,70.3",
    "punjab": "30.15,74.7,31.3,76.8",
    "uttarakhand": "29.9,78.9,30.2,79.4",
}
DATE_RANGE = 10  # days of historical data

HEADERS = [
    "latitude", "longitude", "bright_ti4", "scan", "track", "acq_date", "acq_time",
    "satellite", "instrument", "confidence", "version", "bright_ti5", "frp", "daynight",
]


def fetch_region(name: str, bbox: str, key: str) -> list[dict]:
    url = (
        f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/"
        f"{bbox}/{DATE_RANGE}"
    )
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    reader = csv.DictReader(resp.text.splitlines())
    rows = list(reader)
    print(f"  {name}: {len(rows)} detections")
    return rows


def main() -> None:
    key = os.getenv("FIRMS_MAP_KEY", "")
    if not key or key.startswith("YOUR_") or key == "":
        print("FIRMS_MAP_KEY not set in .env - skipping. Use scripts/generate_seed_data.py "
              "for offline seed data instead.")
        return
    all_rows: list[dict] = []
    for name, bbox in REGIONS.items():
        try:
            all_rows.extend(fetch_region(name, bbox, key))
        except Exception as exc:  # noqa: BLE001
            print(f"  {name}: FAILED ({exc})")
        time.sleep(3)
    if not all_rows:
        print("No data fetched.")
        return
    out = DATA / "firms_real.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"Wrote {len(all_rows)} rows -> {out}")


if __name__ == "__main__":
    main()