from __future__ import annotations

import csv
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from haversine import Unit, haversine

from app.config import CLUSTER_RADIUS_M, FIRMS_MAP_KEY, OSM_GEOJSON
from app import db
from app.classifier import classify, severity_for_frp
from app.cap import build_cap_alert
from app.feature_utils import load_polygons

load_dotenv()

logger = logging.getLogger(__name__)

# Jharia bbox in FIRMS format: west,south,east,north (lon,lat,lon,lat)
JHARIA_BBOX = "86.2,22.7,86.7,23.9"

# FIRMS NRT API constraints
DAY_RANGE = 5  # max 5 for NRT products (confirm against current official docs
# before changing -- see Phase 3/4B verification history)
SOURCE = "VIIRS_SNPP_NRT"

# State file to track last successful fetch date
STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "firms_last_fetch.txt"

# Rate limit: 5000 transactions / 10 min. Each NRT request = 1 transaction.
# Safe to run every 6 hours (4x/day) = 4 transactions/day, well under limit.
FETCH_INTERVAL_HOURS = 6

M = Unit.METERS


def get_firms_key() -> str:
    """Resolve the FIRMS API key once, in one place. Raises loudly if missing
    rather than silently building a request with an empty/None key."""
    key = os.getenv("FIRMS_MAP_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "FIRMS_MAP_KEY is not set in the environment. Refusing to build "
            "a FIRMS request without a key."
        )
    return key


def get_last_fetch_date() -> Optional[date]:
    """Read the last successful fetch date from state file."""
    if STATE_FILE.exists():
        try:
            content = STATE_FILE.read_text().strip()
            if content:
                return datetime.fromisoformat(content).date()
        except Exception as e:
            logger.warning(f"Failed to read last fetch date: {e}")
    return None


def set_last_fetch_date(d: date) -> None:
    """Write the last successful fetch date to state file."""
    try:
        STATE_FILE.write_text(d.isoformat())
    except Exception as e:
        logger.error(f"Failed to write last fetch date: {e}")


def _site_id(lat: float, lon: float, taken: set[str]) -> str:
    base = f"TG-{int(round(lat * 1000)):05d}-{int(round(lon * 1000)):05d}"
    sid, k = base, 0
    while sid in taken:
        k += 1
        sid = f"{base}-{chr(ord('A') + k)}"
    return sid


def _iso(d: str, t: str) -> str:
    t = (t or "1200").zfill(4)
    return f"{d}T{t[:2]}:{t[2:]}:00Z"


def load_csv(path: Path) -> tuple[list[dict], list[str]]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for key in ("latitude", "longitude", "bright_ti4", "frp", "confidence"):
            try:
                r[key] = float(r[key])
            except (TypeError, ValueError, KeyError):
                r[key] = 0.0
    pass_dates = sorted({r["acq_date"] for r in rows if r.get("acq_date")})
    return rows, pass_dates


def _iso(d: str, t: str) -> str:
    t = (t or "1200").zfill(4)
    return f"{d}T{t[:2]}:{t[2:]}:00Z"


def _ingest_rows(
    rows: list[dict],
    pass_dates: list[str],
    polys: list[dict],
    is_synthetic: int,
    source: str,
    ingestion_batch: str,
) -> dict:
    """Core ingestion logic shared by synthetic and real ingestion.
    Assumes derived tables have already been cleared.
    """
    if not rows:
        return {"error": "no detections provided"}

    # --- detections table with provenance ---
    row_sql = (
        "INSERT INTO detections (latitude, longitude, bright_ti4, scan, track, "
        "acq_date, acq_time, satellite, instrument, confidence, version, bright_ti5, "
        "frp, daynight, is_synthetic, source, ingestion_batch) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    db.executemany(row_sql, [
        (r["latitude"], r["longitude"], r.get("bright_ti4", 0), r.get("scan", 0),
         r.get("track", 0), r["acq_date"], r.get("acq_time"), r.get("satellite"),
         r.get("instrument"), r.get("confidence", 0), r.get("version"),
         r.get("bright_ti5", 0), r.get("frp", 0), r.get("daynight"),
         is_synthetic, source, ingestion_batch)
        for r in rows
    ])

    # --- OSM polygons ---
    polys = load_polygons(OSM_GEOJSON)
    db.executemany(
        "INSERT INTO polygons (kind, name, boundary_json) VALUES (?,?,?)",
        [(p["kind"], p["name"], json.dumps([[lat, lon] for lat, lon in p["ring"]]))
         for p in polys],
    )

    # --- registry: cluster detections within 1km into sites ---
    # Query ALL detections (real + synthetic) for clustering
    all_det_rows = [dict(r) for r in db.query(
        "SELECT id, latitude, longitude, bright_ti4, acq_date, acq_time, frp FROM detections"
    )]
    ordered = sorted(all_det_rows, key=lambda r: (r["acq_date"], str(r.get("acq_time", ""))))

    sites: dict[str, dict] = {}
    taken: set[str] = set()

    det_ids = [row["id"] for row in db.query("SELECT id FROM detections")]
    for idx, r in enumerate(ordered):
        lat, lon = r["latitude"], r["longitude"]
        match_sid: str | None = None
        for sid, s in sites.items():
            if haversine((lat, lon), (s["lat"], s["lon"]), unit=M) <= CLUSTER_RADIUS_M:
                match_sid = sid
                break
        iso = _iso(r["acq_date"], r.get("acq_time"))
        if match_sid is None:
            sid = _site_id(lat, lon, taken)
            taken.add(sid)
            sites[sid] = {
                "site_id": sid, "lat": lat, "lon": lon,
                "first_seen": iso, "last_seen": iso,
                "max_frp": r.get("frp", 0), "brightness": r.get("bright_ti4", 0),
                "det_ids": [r["id"]],
            }
        else:
            s = sites[match_sid]
            s["last_seen"] = max(s["last_seen"], iso)
            s["max_frp"] = max(s["max_frp"], r.get("frp", 0))
            s["brightness"] = max(s["brightness"], r.get("bright_ti4", 0))
            s["det_ids"].append(r["id"])

    site_rows = [(
        s["site_id"], s["lat"], s["lon"], s["first_seen"], s["last_seen"],
        s["max_frp"], s["brightness"],
    ) for s in sites.values()]
    db.executemany(
        "INSERT INTO sites (site_id, lat, lon, first_seen, last_seen, max_frp, brightness) "
        "VALUES (?,?,?,?,?,?,?)",
        site_rows,
    )
    for s in sites.values():
        db.executemany(
            "INSERT OR IGNORE INTO site_detections (site_id, detection_id) VALUES (?,?)",
            [(s["site_id"], did) for did in s["det_ids"]],
        )

    # --- classify each site ---
    created_alerts = 0
    for s in sites.values():
        month = int(s["last_seen"][5:7])
        res = classify(s["lat"], s["lon"], all_det_rows, polys, pass_dates, month,
                       s["max_frp"], s["brightness"])
        severity = severity_for_frp(s["max_frp"])
        anomalous = int(severity in ("severe", "extreme"))
        db.execute(
            "UPDATE sites SET classification=?, confidence=?, explanation=?, severity=?, "
            "is_anomalous=?, persistence=?, consec_days=?, duty_cycle_pct=?, "
            "d_industrial_m=?, d_agri_m=?, d_residential_m=? "
            "WHERE site_id=?",
            (res.classification, res.confidence, res.explanation, severity, anomalous,
             res.features["persistence"], res.features["consec_days"],
             res.features["duty_cycle_pct"], res.features["d_industrial"],
             res.features["d_agri"], res.features["d_residential"], s["site_id"]),
        )
        if anomalous:
            created_alerts += _ensure_alert(s["site_id"], severity)

    return {
        "detections": len(rows),
        "sites": len(sites),
        "pass_dates": pass_dates,
        "polygons": len(polys),
        "alerts_created": created_alerts,
    }


def _ensure_alert(site_id: str, severity: str) -> int:
    """Create an alert_triggered government-console entry if none is active."""
    existing = db.query(
        "SELECT id FROM alerts WHERE site_id=? AND status IN ('alert_triggered','confirmed')",
        (site_id,),
    )
    if existing:
        return 0
    from app.cap import build_cap_alert
    site = dict(db.query("SELECT * FROM sites WHERE site_id=?", (site_id,))[0])
    cap = build_cap_alert(site)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO alerts (site_id, severity, is_anomalous, status, cap_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (site_id, severity, site["is_anomalous"], "alert_triggered",
         json.dumps(cap, indent=2) if isinstance(cap, dict) else cap, now, now),
    )
    return 1


def fetch_new_data(since_date: date, max_date: Optional[date] = None) -> list[dict]:
    """
    Fetch FIRMS NRT data for Jharia from `since_date` up to `max_date` (or today).
    Returns list of detection dicts.

    Any HTTP error or malformed response raises -- the caller (fetch_and_ingest_job)
    must NOT advance the state file if this raises, or a failed window is skipped
    forever. A valid response with zero observations is NOT an error: it continues
    to the next window rather than aborting the whole fetch.
    """
    if max_date is None:
        max_date = datetime.now(timezone.utc).date()

    key = get_firms_key()
    all_rows: list[dict] = []
    current_end = since_date

    while current_end <= max_date:
        url = (
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
            f"{key}/VIIRS_SNPP_NRT/"
            f"{JHARIA_BBOX}/{DAY_RANGE}/{current_end.isoformat()}"
        )
        redacted_url = url.replace(key, "[KEY]")
        logger.info(f"Fetching {current_end} (day_range={DAY_RANGE}) url={url.replace(key, '[KEY]')}")

        try:
            resp = requests.get(url, timeout=60)
        except requests.RequestException as e:
            raise RuntimeError(f"FIRMS request failed for window ending {current_end}: {e}") from e

        if resp.status_code != 200:
            raise RuntimeError(
                f"FIRMS request failed for window ending {current_end}: "
                f"HTTP {resp.status_code}: {resp.text[:200]}"
            )

        text = resp.text.strip()
        if not text:
            raise RuntimeError(f"Empty response body for window ending {current_end} (HTTP 200)")

        lines = text.splitlines()
        if len(lines) < 2:
            # Valid header-only CSV: zero observations for this window.
            # This is a SUCCESS, not a failure -- continue to the next window.
            logger.info(f"Valid FIRMS CSV, zero observations for window ending {current_end}")
        else:
            header = lines[0].lower()
            if "latitude" not in header or "longitude" not in header or "acq_date" not in header:
                raise RuntimeError(
                    f"Malformed CSV for window ending {current_end}: "
                    f"unexpected header: {lines[0][:200]}"
                )
            reader = csv.DictReader(lines)
            rows = list(reader)
            logger.info(f"  Fetched {len(rows)} detections")
            all_rows.extend(rows)

        current_end += timedelta(days=DAY_RANGE)
        time.sleep(2)

    return all_rows


def ingest_nrt_rows(rows: list[dict], pass_dates: list[str], polys: list[dict],
                    ingestion_batch: str) -> dict:
    """Ingest NRT rows with real provenance (is_synthetic=0, source='firms'),
    using the incremental-safe path so repeated scheduler runs don't crash
    or duplicate sites."""
    return _ingest_incremental(rows, pass_dates, polys, is_synthetic=0, source="firms",
                               ingestion_batch=ingestion_batch)


def fetch_and_ingest_job() -> None:
    """Main scheduled job: fetch new data since last run and ingest."""
    logger.info("Starting scheduled FIRMS ingestion job")

    last_fetch = get_last_fetch_date()
    if last_fetch is None:
        since_date = datetime.now(timezone.utc).date() - timedelta(days=5)
        logger.info(f"No previous fetch recorded. Fetching last 5 days from {since_date}")
    else:
        since_date = last_fetch + timedelta(days=1)
        logger.info(f"Last fetch was {last_fetch}. Fetching from {since_date}")

    max_date = datetime.now(timezone.utc).date()
    if since_date > max_date:
        logger.info("No new data to fetch")
        return

    try:
        rows = fetch_new_data(since_date, max_date)
        if not rows:
            logger.info("No new detections found")
            # Still advance the state file on a valid empty fetch to avoid re-fetching
            set_last_fetch_date(max_date)
            return

        pass_dates = sorted({r["acq_date"] for r in rows})
        polys = load_polygons()
        batch_id = f"firms_nrt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        summary = ingest_nrt_rows(rows, pass_dates, polys, batch_id)
        logger.info(f"Ingestion summary: {summary}")

        # Only advance the state file AFTER the entire fetch range succeeds
        set_last_fetch_date(max_date)
        logger.info(f"Updated last fetch date to {max_date}")

    except Exception as e:
        logger.exception(f"Scheduled job failed: {e}")
        # Don't re-raise -- let scheduler continue to the next interval.
        # Do NOT advance the state file on failure.


def create_scheduler() -> BackgroundScheduler:
    """Create and configure the background scheduler."""
    scheduler = BackgroundScheduler(timezone="UTC")

    # Add the periodic job
    scheduler.add_job(
        fetch_and_ingest_job,
        trigger=IntervalTrigger(hours=FETCH_INTERVAL_HOURS),
        id="firms_nrt_ingestion",
        name="FIRMS NRT Jharia Ingestion",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,  # 1 hour grace
    )

    return scheduler


# Module-level scheduler instance (created on import)
_scheduler: Optional[BackgroundScheduler] = None


def get_scheduler() -> BackgroundScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = create_scheduler()
    return _scheduler


def start_scheduler() -> None:
    """Start the background scheduler. Not called automatically anywhere --
    must be invoked explicitly (e.g. from a FastAPI startup hook) once you
    are ready for it to run unattended."""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("FIRMS NRT ingestion scheduler started")


def stop_scheduler() -> None:
    """Stop the background scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=True)
        _scheduler = None
        logger.info("FIRMS NRT ingestion scheduler stopped")


def run_once() -> dict:
    """Run the fetch/ingest job once manually. Returns summary."""
    logger.info("Running manual FIRMS ingestion")
    fetch_and_ingest_job()
    return {"status": "completed"}


def main() -> None:
    """CLI entry point for manual runs."""
    run_once()


if __name__ == "__main__":
    main()