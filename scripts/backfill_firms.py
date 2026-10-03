"""FIRMS Historical Backfill Script for NOCTRA.

Fetches historical VIIRS observations for configured regions, windows them
into chunks of at most FIRMS_DAY_RANGE, caches raw CSVs under data/firms_raw/,
and ingests new detections via the incremental real-data ingestion pipeline.

Usage:
    python scripts/backfill_firms.py [--days 30] [--regions jharia,jamnagar] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# Ensure backend root is in python path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from app import db
from app.config import (
    DATA_DIR,
    FIRMS_DAY_RANGE,
    FIRMS_RAW_DIR,
    FIRMS_REGIONS,
    FIRMS_SOURCES,
    FIRMS_SP_CUTOFF_DAYS,
    OSM_GEOJSON,
)
from app.feature_utils import load_polygons
from app.firms_scheduler import get_firms_key, ingest_nrt_rows

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_firms")


def generate_windows(start_date: date, end_date: date, day_range: int = FIRMS_DAY_RANGE) -> list[tuple[date, date]]:
    """Divide a date range [start_date, end_date] into chronological windows
    of at most `day_range` calendar days each."""
    if start_date > end_date:
        return []
    windows = []
    cur = start_date
    while cur <= end_date:
        w_end = min(cur + timedelta(days=day_range - 1), end_date)
        windows.append((cur, w_end))
        cur = w_end + timedelta(days=1)
    return windows


def determine_source_product(base_source: str, window_start: date, cutoff_date: date) -> str:
    """Determine whether to use standard processing (*_SP) or near-real-time (*_NRT).
    Uses *_SP for dates older than cutoff_date, NRT otherwise."""
    if window_start < cutoff_date:
        return base_source.replace("_NRT", "_SP")
    return base_source


def fetch_window_csv(
    key: str,
    source: str,
    bbox: str,
    w_start: date,
    w_end: date,
    cache_path: Path,
) -> str:
    """Fetch window CSV from FIRMS or return cached content.
    Never prints or logs the API key or unredacted URL."""
    if cache_path.exists() and cache_path.stat().st_size > 0:
        logger.info(f"  [CACHE HIT] {cache_path.name}")
        return cache_path.read_text(encoding="utf-8")

    day_span = (w_end - w_start).days + 1
    url = (
        f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"{key}/{source}/{bbox}/{day_span}/{w_start.isoformat()}"
    )
    redacted_url = url.replace(key, "[KEY]")
    logger.info(f"  [FETCH] {redacted_url}")

    try:
        resp = requests.get(url, timeout=60)
    except requests.RequestException as e:
        err = str(e).replace(key, "[KEY]")
        raise RuntimeError(f"FIRMS network request failed for window {w_start} to {w_end}: {err}") from e

    if resp.status_code != 200:
        err_body = resp.text[:200].replace(key, "[KEY]")
        raise RuntimeError(
            f"FIRMS request failed for window {w_start} to {w_end}: HTTP {resp.status_code}: {err_body}"
        )

    text = resp.text.strip()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text


def parse_csv_text(csv_text: str) -> list[dict]:
    """Parse raw FIRMS CSV string into dictionaries with numeric conversions."""
    if not csv_text or not csv_text.strip():
        return []
    lines = csv_text.strip().splitlines()
    if len(lines) < 2:
        return []
    reader = csv.DictReader(lines)
    rows = list(reader)
    for r in rows:
        for k in ("latitude", "longitude", "bright_ti4", "frp", "confidence"):
            try:
                r[k] = float(r[k])
            except (KeyError, TypeError, ValueError):
                r[k] = 0.0
    return rows


def get_region_site_stats(bbox_str: str) -> dict:
    """Query database for site metrics within a region bbox (west,south,east,north)."""
    parts = [float(p.strip()) for p in bbox_str.split(",")]
    west, south, east, north = parts[0], parts[1], parts[2], parts[3]

    site_query = """
        SELECT s.site_id, COUNT(DISTINCT d.acq_date) AS observed_days
        FROM sites s
        JOIN site_detections sd ON s.site_id = sd.site_id
        JOIN detections d ON sd.detection_id = d.id
        WHERE s.lon >= ? AND s.lon <= ? AND s.lat >= ? AND s.lat <= ?
        GROUP BY s.site_id
    """
    rows = db.query(site_query, (west, east, south, north))
    distinct_sites = len(rows)
    ge5 = sum(1 for r in rows if r["observed_days"] >= 5)
    ge15 = sum(1 for r in rows if r["observed_days"] >= 15)
    return {
        "distinct_sites": distinct_sites,
        "sites_ge_5_days": ge5,
        "sites_ge_15_days": ge15,
    }


def run_backfill(
    days: int = 30,
    regions: Optional[list[str]] = None,
    sources: Optional[list[str]] = None,
    dry_run: bool = False,
    end_date: Optional[date] = None,
    sp_cutoff_days: int = FIRMS_SP_CUTOFF_DAYS,
    raw_dir: Optional[Path] = None,
) -> dict:
    """Run historical FIRMS backfill across regions and date windows.

    Returns summary metrics per region.
    """
    if days < 1 or days > 90:
        raise ValueError(f"Days must be between 1 and 90, got {days}")

    target_regions = regions or list(FIRMS_REGIONS.keys())
    target_sources = sources or FIRMS_SOURCES
    raw_cache_dir = raw_dir or FIRMS_RAW_DIR
    raw_cache_dir.mkdir(parents=True, exist_ok=True)

    end_d = end_date or datetime.now(timezone.utc).date()
    start_d = end_d - timedelta(days=days - 1)
    cutoff_d = end_d - timedelta(days=sp_cutoff_days)

    windows = generate_windows(start_d, end_d, FIRMS_DAY_RANGE)

    logger.info(f"=== Starting FIRMS Backfill ({days} days) ===")
    logger.info(f"Date Range: {start_d} to {end_d} ({len(windows)} windows)")
    logger.info(f"Regions: {target_regions}")
    logger.info(f"Sources: {target_sources}")
    logger.info(f"SP Cutoff Date: {cutoff_d} (< cutoff uses *_SP, otherwise NRT)")
    logger.info(f"Dry Run: {dry_run}")
    logger.info(f"Raw Cache Dir: {raw_cache_dir}")

    # Resolve FIRMS key only if needed (not dry-run and uncached windows exist)
    key = ""
    if not dry_run:
        try:
            key = get_firms_key()
        except RuntimeError:
            logger.warning("FIRMS_MAP_KEY not set in environment. Online fetching will fail if uncached.")

    polys = load_polygons(OSM_GEOJSON)
    report_per_region: dict[str, dict] = {}

    for region_name in target_regions:
        bbox = FIRMS_REGIONS.get(region_name)
        if not bbox:
            logger.warning(f"Region '{region_name}' not found in FIRMS_REGIONS. Skipping.")
            continue

        logger.info(f"\n--- Backfilling Region: {region_name} (bbox: {bbox}) ---")
        detections_added_for_region = 0

        # Snapshot detection count prior to backfill
        before_count = db.query(
            "SELECT count(*) as c FROM detections d "
            "JOIN site_detections sd ON d.id = sd.detection_id "
            "JOIN sites s ON sd.site_id = s.site_id "
            "WHERE s.lon >= ? AND s.lon <= ? AND s.lat >= ? AND s.lat <= ?",
            tuple(float(p) for p in [bbox.split(",")[0], bbox.split(",")[2], bbox.split(",")[1], bbox.split(",")[3]])
        )[0]["c"]

        for source in target_sources:
            for w_idx, (w_start, w_end) in enumerate(windows):
                product = determine_source_product(source, w_start, cutoff_d)
                cache_file = raw_cache_dir / f"{region_name}_{product}_{w_start.isoformat()}_{w_end.isoformat()}.csv"
                window_desc = f"{region_name}:{product} [{w_start}..{w_end}]"

                if dry_run:
                    is_cached = cache_file.exists() and cache_file.stat().st_size > 0
                    logger.info(f"  [DRY-RUN] Window {w_idx+1}/{len(windows)}: {window_desc} (Cached: {is_cached})")
                    continue

                try:
                    csv_text = fetch_window_csv(key, product, bbox, w_start, w_end, cache_file)
                    rows = parse_csv_text(csv_text)
                    if rows:
                        pass_dates = sorted({r["acq_date"] for r in rows if r.get("acq_date")})
                        batch_id = f"backfill_{region_name}_{product}_{w_start.strftime('%Y%m%d')}_{w_end.strftime('%Y%m%d')}"
                        summary = ingest_nrt_rows(rows, pass_dates, polys, batch_id)
                        added = summary.get("detections", 0)
                        detections_added_for_region += added
                        logger.info(f"  Window {w_idx+1}/{len(windows)}: {len(rows)} raw rows -> {added} new unique detections ingested")
                    else:
                        logger.info(f"  Window {w_idx+1}/{len(windows)}: 0 detections")
                    time.sleep(0.5)
                except Exception as exc:
                    logger.error(f"  Failed window {window_desc}: {exc}")
                    continue

        after_count = db.query(
            "SELECT count(*) as c FROM detections d "
            "JOIN site_detections sd ON d.id = sd.detection_id "
            "JOIN sites s ON sd.site_id = s.site_id "
            "WHERE s.lon >= ? AND s.lon <= ? AND s.lat >= ? AND s.lat <= ?",
            tuple(float(p) for p in [bbox.split(",")[0], bbox.split(",")[2], bbox.split(",")[1], bbox.split(",")[3]])
        )[0]["c"]

        stats = get_region_site_stats(bbox)
        stats["detections_added"] = max(0, after_count - before_count)
        stats["total_detections"] = after_count
        report_per_region[region_name] = stats

    logger.info("\n=== Final Backfill Summary Per Region ===")
    for reg, st in report_per_region.items():
        logger.info(
            f"Region: {reg:12s} | Detections Added: {st['detections_added']:5d} | "
            f"Distinct Sites: {st['distinct_sites']:4d} | "
            f"Sites >= 5 Days: {st['sites_ge_5_days']:4d} | "
            f"Sites >= 15 Days: {st['sites_ge_15_days']:4d}"
        )

    return report_per_region


def main() -> int:
    parser = argparse.ArgumentParser(description="NOCTRA FIRMS Historical Backfill")
    parser.add_argument("--days", type=int, default=30, help="Days of history to backfill (1 to 90, default 30)")
    parser.add_argument("--regions", type=str, default=None, help="Comma-separated region names (default all)")
    parser.add_argument("--sources", type=str, default=None, help="Comma-separated FIRMS satellite sources")
    parser.add_argument("--dry-run", action="store_true", help="Print plan and cache status without executing")
    parser.add_argument("--sp-cutoff-days", type=int, default=FIRMS_SP_CUTOFF_DAYS, help="Cutoff days for *_SP vs NRT")
    parser.add_argument("--end-date", type=str, default=None, help="End date in YYYY-MM-DD format (default today)")
    args = parser.parse_args()

    reg_list = [r.strip() for r in args.regions.split(",") if r.strip()] if args.regions else None
    src_list = [s.strip() for s in args.sources.split(",") if s.strip()] if args.sources else None
    end_d = datetime.strptime(args.end_date, "%Y-%m-%d").date() if args.end_date else None

    try:
        run_backfill(
            days=args.days,
            regions=reg_list,
            sources=src_list,
            dry_run=args.dry_run,
            end_date=end_d,
            sp_cutoff_days=args.sp_cutoff_days,
        )
        return 0
    except Exception as e:
        logger.exception(f"Backfill failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
