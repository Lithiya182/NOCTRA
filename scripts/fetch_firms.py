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
    "jharia": "86.2,22.7,86.7,23.9",       # west,south,east,north
    "jamnagar": "69.8,22.3,70.3,22.6",
    "punjab": "74.7,30.15,76.8,31.3",
    "uttarakhand": "78.9,29.9,79.4,30.2",
}
DATE_RANGE = 5  # days of historical data (max 5 for NRT)

HEADERS = [
    "latitude", "longitude", "bright_ti4", "scan", "track", "acq_date", "acq_time",
    "satellite", "instrument", "confidence", "version", "bright_ti5", "frp", "daynight",
]


def fetch_region(name: str, bbox: str, key: str) -> list[dict]:
    url = (
        f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/"
        f"{bbox}/{DATE_RANGE}"
    )
    print(f"  Requesting: {url.replace(key, '[KEY]')}")
    resp = requests.get(url, timeout=60)

    # Check for empty response or error content
    if resp.status_code != 200:
        print(f"  {name}: HTTP {resp.status_code}")
        return []

    if not resp.text.strip():
        print(f"  {name}: Empty response")
        return []

    lines = resp.text.strip().splitlines()
    if len(lines) < 2:
        # Only header line, zero observations
        print(f"  {name}: Valid CSV, zero observations")
        return []

    reader = csv.DictReader(lines)
    rows = list(reader)
    print(f"  {name}: {len(rows)} detections")
    return rows


def main() -> None:
    key = os.getenv("FIRMS_MAP_KEY", "")
    if not key or key.startswith("YOUR_") or key == "":
        print("FIRMS_MAP_KEY not set in .env - skipping. Use scripts/generate_seed_data.py "
              "for offline seed data instead.")
        return

    # Only query Jharia for this controlled smoke test
    name = "jharia"
    bbox = REGIONS["jharia"]
    print(f"=== FIRMS Smoke Test ===")
    print(f"Region: {name}")
    print(f"BBox: {bbox}")
    print(f"Product: VIIRS_SNPP_NRT")
    print(f"Day Range: {DATE_RANGE}")
    print()

    try:
        rows = fetch_region(name, bbox, key)
    except Exception as exc:  # noqa: BLE001
        print(f"  {name}: FAILED ({exc})")
        return

    if not rows:
        print("Result: Valid FIRMS CSV, zero observations")
        return

    print(f"Rows returned: {len(rows)}")

    out = DATA / "firms_real.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written to: {out}")

    # Show sample
    print("Sample (first 3 rows):")
    for i, r in enumerate(rows[:3]):
        print(f"  [{i}] lat={r['latitude']} lon={r['longitude']} date={r['acq_date']} "
              f"time={r['acq_time']} sat={r['satellite']} inst={r['instrument']} "
              f"conf={r['confidence']} frp={r['frp']} daynight={r['daynight']} ver={r['version']}")


if __name__ == "__main__":
    main()
