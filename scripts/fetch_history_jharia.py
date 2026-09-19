"""Fetch 30-day historical VIIRS_SNPP_SP data for Jharia.

Uses explicit DATE windows with DAY_RANGE=5 (max for standard products).
Works backward from the latest available SP date (2026-06-30 per data_availability API).
"""

import csv
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Jharia bbox: west,south,east,north
JHARIA_BBOX = "86.2,22.7,86.7,23.9"

# VIIRS_SNPP_SP data availability: 2012-01-20 to 2026-06-30
# Latest available date: 2026-06-30
# Day range limit for standard products: 5
DAY_RANGE = 5
WINDOW_DAYS = DAY_RANGE

# Latest available date for VIIRS_SNPP_SP
LATEST_SP_DATE = datetime(2026, 6, 30).date()

# Target ~30 days
TARGET_DAYS = 30
NUM_WINDOWS = (TARGET_DAYS + DAY_RANGE - 1) // DAY_RANGE  # ceil division

HEADERS = [
    "latitude", "longitude", "bright_ti4", "scan", "track", "acq_date", "acq_time",
    "satellite", "instrument", "confidence", "version", "bright_ti5", "frp", "daynight",
    "type",
]

SOURCE = "VIIRS_SNPP_SP"


def fetch_window(name: str, bbox: str, key: str, start_date: datetime.date, end_date: datetime.date) -> list[dict]:
    """Fetch a single date window using explicit DATE parameter."""
    # Format: /api/area/csv/{key}/{SOURCE}/{AREA}/{DAY_RANGE}/{DATE}
    # where DATE is the start date of the window
    url = (
        f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_SP/"
        f"{bbox}/{DAY_RANGE}/{start_date.isoformat()}"
    )
    print(f"  [{name}] Requesting: {url.replace(key, '[KEY]')}")
    resp = requests.get(url, timeout=60)

    if resp.status_code != 200:
        print(f"  [{name}] HTTP {resp.status_code}: {resp.text[:200]}")
        return []

    if not resp.text.strip():
        print(f"  [{name}] Empty response")
        return []

    lines = resp.text.strip().splitlines()
    if len(lines) < 2:
        print(f"  [{name}] Valid CSV, zero observations")
        return []

    reader = csv.DictReader(lines)
    rows = list(reader)
    print(f"  [{name}] {len(rows)} detections ({start_date} to {end_date})")
    return rows


def main() -> int:
    key = os.getenv("FIRMS_MAP_KEY", "")
    if not key or key.startswith("YOUR_") or key == "":
        print("FIRMS_MAP_KEY not set in .env")
        return 1

    print(f"=== FIRMS 30-Day Historical Fetch ===")
    print(f"Region: Jharia")
    print(f"BBox: {JHARIA_BBOX}")
    print(f"Product: VIIRS_SNPP_SP (Standard Processing)")
    print(f"Day Range: {DAY_RANGE}")
    print(f"Latest SP available: {LATEST_SP_DATE}")
    print(f"Target window: ~30 days ending {LATEST_SP_DATE}")
    print(f"Planned windows: {NUM_WINDOWS}")
    print()

    # Generate windows working backward from LATEST_SP_DATE
    windows = []
    current_end = LATEST_SP_DATE
    for i in range(NUM_WINDOWS):
        start = current_end - timedelta(days=DAY_RANGE - 1)
        windows.append((start, current_end))
        current_end = start - timedelta(days=1)

    # Reverse to process chronologically (oldest first)
    windows.reverse()

    print("Planned windows:")
    for i, (start, end) in enumerate(windows):
        print(f"  Window {i+1}: {start} to {end}")
    print()

    all_rows = []
    seen_keys = set()

    for i, (start_date, end_date) in enumerate(windows):
        window_name = f"Window {i+1} ({start_date} to {end_date})"
        try:
            rows = fetch_window(window_name, JHARIA_BBOX, os.getenv("FIRMS_MAP_KEY", ""), start_date, end_date)
        except Exception as exc:
            print(f"  Window {i+1}: FAILED ({exc})")
            return 1

        if not rows:
            print(f"  Window {i+1}: Valid CSV, zero observations")
        else:
            # Deduplicate using natural key
            for r in rows:
                key = (r['latitude'], r['longitude'], r['acq_date'], r['acq_time'], r['satellite'])
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_rows.append(r)
            print(f"  Window {i+1}: {len(rows)} rows, {len([k for k in seen_keys if k not in seen_keys])} new unique")

        if i < len(windows) - 1:
            time.sleep(3)

    if not all_rows:
        print("No data fetched across all windows.")
        return 1

    # Final deduplication check
    print(f"\nTotal raw rows: {len(all_rows)}")
    final_keys = set()
    final_rows = []
    for r in all_rows:
        key = (r['latitude'], r['longitude'], r['acq_date'], r['acq_time'], r['satellite'])
        if key not in final_keys:
            final_keys.add(key)
            final_rows.append(r)
    print(f"Unique rows after dedup: {len(final_rows)}")

    # Write output
    out = DATA / "firms_history_jharia.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(final_rows)
    print(f"Written to: {out}")

    # Summary
    print(f"\n=== Summary ===")
    print(f"Total unique rows: {len(final_rows)}")
    print(f"Date range: {min(r['acq_date'] for r in final_rows)} to {max(r['acq_date'] for r in final_rows)}")
    dates = set(r['acq_date'] for r in final_rows)
    print(f"Unique dates: {len(dates)} ({min(dates)} to {max(dates)})")
    daynight = {}
    for r in final_rows:
        daynight[r['daynight']] = daynight.get(r['daynight'], 0) + 1
    print(f"Day/night: {daynight}")
    sats = {}
    for r in final_rows:
        sats[r['satellite']] = sats.get(r['satellite'], 0) + 1
    print(f"Satellites: {sats}")
    confs = {}
    for r in final_rows:
        confs[r['confidence']] = confs.get(r['confidence'], 0) + 1
    print(f"Confidence: {confs}")

    # Verify dedup
    nat_keys = [(r['latitude'], r['longitude'], r['acq_date'], r['acq_time'], r['satellite']) for r in final_rows]
    from collections import Counter
    dupes = {k: v for k, v in Counter(nat_keys).items() if v > 1}
    print(f"Duplicate natural keys: {len(dupes)}")

    return 0


if __name__ == "__main__":
    import os
    sys.exit(main())
