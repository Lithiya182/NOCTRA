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

from app.config import (
    CLUSTER_RADIUS_M,
    DATA_DIR,
    FIRMS_DAY_RANGE,
    FIRMS_MAP_KEY,
    FIRMS_REGIONS,
    FIRMS_SOURCES,
    OSM_GEOJSON,
)
from app import db
from app.classifier import classify, severity_for_frp
from app.cap import build_cap_alert
from app.feature_utils import load_polygons

load_dotenv()

logger = logging.getLogger(__name__)

# Constants and backward compatibility exports
DAY_RANGE = FIRMS_DAY_RANGE
JHARIA_BBOX = FIRMS_REGIONS.get("jharia", "86.2,22.7,86.7,23.9")
SOURCE = FIRMS_SOURCES[0] if FIRMS_SOURCES else "VIIRS_SNPP_NRT"

# State file to track per-region and per-source fetch dates (stored as JSON)
STATE_FILE = DATA_DIR / "firms_last_fetch.txt"

# Rate limit: 5000 transactions / 10 min.
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


def _read_state_dict() -> dict[str, str]:
    """Internal helper to load the state dictionary from STATE_FILE."""
    if STATE_FILE.exists():
        try:
            content = STATE_FILE.read_text(encoding="utf-8").strip()
            if content:
                if content.startswith("{"):
                    return json.loads(content)
                # Legacy single-date string
                return {"_legacy": content}
        except Exception as e:
            logger.warning(f"Failed to read state file: {e}")
    return {}


def get_last_fetch_date(region: str = "jharia", source: str = "VIIRS_SNPP_NRT") -> Optional[date]:
    """Read the last successful fetch date for a given region and source."""
    state = _read_state_dict()
    key = f"{region}:{source}"
    val = state.get(key) or state.get(region) or state.get("_legacy")
    if val:
        try:
            return datetime.fromisoformat(val).date()
        except Exception:
            return None
    return None


def set_last_fetch_date(d: date, region: str = "jharia", source: str = "VIIRS_SNPP_NRT") -> None:
    """Write the last successful fetch date for a given region and source.
    Persists as JSON in STATE_FILE to maintain per-region/source isolation.
    """
    state = _read_state_dict()
    state[f"{region}:{source}"] = d.isoformat()
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
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
    """Create an alert_triggered government-console entry if none is active.
    NEVER sends notifications or calls any dispatch functions.
    Alerts strictly remain in 'alert_triggered' until human confirmation.
    """
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


def fetch_new_data(
    since_date: date,
    max_date: Optional[date] = None,
    region: str = "jharia",
    bbox: Optional[str] = None,
    source: str = "VIIRS_SNPP_NRT",
) -> list[dict]:
    """
    Fetch FIRMS NRT data for a region/bbox and satellite source from `since_date` up to `max_date`.
    Returns list of detection dicts.

    Any HTTP error or malformed response raises -- the caller (fetch_and_ingest_job)
    must NOT advance the state file if this raises, or a failed window is skipped
    forever. A valid response with zero observations is NOT an error: it continues
    to the next window rather than aborting the whole fetch.
    Key is ALWAYS redacted in logs and error messages.
    """
    if max_date is None:
        max_date = datetime.now(timezone.utc).date()

    if bbox is None:
        bbox = FIRMS_REGIONS.get(region, JHARIA_BBOX)

    key = get_firms_key()
    all_rows: list[dict] = []
    current_end = since_date

    while current_end <= max_date:
        url = (
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
            f"{key}/{source}/"
            f"{bbox}/{DAY_RANGE}/{current_end.isoformat()}"
        )
        redacted_url = url.replace(key, "[KEY]")
        logger.info(f"Fetching {current_end} (day_range={DAY_RANGE}) url={redacted_url}")

        try:
            resp = requests.get(url, timeout=60)
        except requests.RequestException as e:
            err_msg = str(e).replace(key, "[KEY]")
            raise RuntimeError(f"FIRMS request failed for window ending {current_end}: {err_msg}") from e

        if resp.status_code != 200:
            err_body = resp.text[:200].replace(key, "[KEY]")
            raise RuntimeError(
                f"FIRMS request failed for window ending {current_end}: "
                f"HTTP {resp.status_code}: {err_body}"
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
                sample = lines[0][:200].replace(key, "[KEY]")
                raise RuntimeError(
                    f"Malformed CSV for window ending {current_end}: "
                    f"unexpected header: {sample}"
                )
            reader = csv.DictReader(lines)
            rows = list(reader)
            logger.info(f"  Fetched {len(rows)} detections for {region} ({source})")
            all_rows.extend(rows)

        current_end += timedelta(days=DAY_RANGE)
        time.sleep(1)

    return all_rows


def _ingest_incremental(
    rows: list[dict],
    pass_dates: list[str],
    polys: list[dict],
    is_synthetic: int,
    source: str,
    ingestion_batch: str,
) -> dict:
    """Incremental ingestion: add new detections, update/merge sites, reclassify affected.
    Does NOT clear derived tables - updates them in place.
    NEVER calls any notification or dispatch functions.
    """
    if not rows:
        return {"detections": 0, "sites": 0, "pass_dates": pass_dates, "polygons": len(polys), "alerts_created": 0}

    # --- 1. Insert new detections with natural-key dedup ---
    row_sql = (
        "INSERT OR IGNORE INTO detections (latitude, longitude, bright_ti4, scan, track, "
        "acq_date, acq_time, satellite, instrument, confidence, version, bright_ti5, "
        "frp, daynight, is_synthetic, source, ingestion_batch) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    det_rows = [
        (r["latitude"], r["longitude"], r.get("bright_ti4", 0), r.get("scan", 0),
         r.get("track", 0), r["acq_date"], r.get("acq_time"), r.get("satellite"),
         r.get("instrument"), r.get("confidence", 0), r.get("version"),
         r.get("bright_ti5", 0), r.get("frp", 0), r.get("daynight"),
         is_synthetic, source, ingestion_batch)
        for r in rows
    ]
    db.executemany(row_sql, det_rows)

    # Get IDs of newly inserted detections
    new_det_ids = [r["id"] for r in db.query(
        "SELECT id FROM detections WHERE ingestion_batch=?", (ingestion_batch,))]

    if not new_det_ids:
        return {"detections": 0, "sites": 0, "pass_dates": pass_dates, "polygons": len(polys), "alerts_created": 0}

    # --- 2. Load new detections with full data for clustering ---
    new_dets = [dict(r) for r in db.query(
        "SELECT id, latitude, longitude, bright_ti4, acq_date, acq_time, frp FROM detections "
        "WHERE id IN ({})".format(",".join("?" * len(new_det_ids))), tuple(new_det_ids))]

    # --- 3. For each new detection, find or create site (incremental clustering) ---
    existing_sites = [dict(r) for r in db.query(
        "SELECT site_id, lat, lon FROM sites")]

    affected_site_ids = set()

    for det in new_dets:
        lat, lon = det["latitude"], det["longitude"]
        det_id = det["id"]

        # Find existing site within cluster radius
        match_sid = None
        for s in existing_sites:
            if haversine((lat, lon), (s["lat"], s["lon"]), unit=M) <= CLUSTER_RADIUS_M:
                match_sid = s["site_id"]
                break

        if match_sid is None:
            # Create new site
            taken = {s["site_id"] for s in existing_sites}
            sid = _site_id(lat, lon, taken)
            existing_sites.append({"site_id": sid, "lat": lat, "lon": lon})
            iso = _iso(det["acq_date"], det.get("acq_time"))
            db.execute(
                "INSERT INTO sites (site_id, lat, lon, first_seen, last_seen, max_frp, brightness) "
                "VALUES (?,?,?,?,?,?,?)",
                (sid, lat, lon, iso, iso, det.get("frp", 0), det.get("bright_ti4", 0)),
            )
            match_sid = sid
        else:
            # Update existing site
            iso = _iso(det["acq_date"], det.get("acq_time"))
            db.execute(
                "UPDATE sites SET last_seen=MAX(last_seen,?), max_frp=MAX(max_frp,?), brightness=MAX(brightness,?) "
                "WHERE site_id=?",
                (iso, det.get("frp", 0), det.get("bright_ti4", 0), match_sid),
            )

        # Link detection to site
        db.execute(
            "INSERT OR IGNORE INTO site_detections (site_id, detection_id) VALUES (?,?)",
            (match_sid, det_id),
        )
        affected_site_ids.add(match_sid)

    # --- 4. Re-classify only affected sites ---
    all_det_rows = [dict(r) for r in db.query(
        "SELECT latitude, longitude, bright_ti4, acq_date, frp FROM detections")]

    created_alerts = 0
    for sid in affected_site_ids:
        site = dict(db.query("SELECT * FROM sites WHERE site_id=?", (sid,))[0])
        month = int(site["last_seen"][5:7])
        res = classify(site["lat"], site["lon"], all_det_rows, polys, pass_dates, month,
                       site["max_frp"], site["brightness"])
        severity = severity_for_frp(site["max_frp"])
        anomalous = int(severity in ("severe", "extreme"))
        db.execute(
            "UPDATE sites SET classification=?, confidence=?, explanation=?, severity=?, "
            "is_anomalous=?, persistence=?, consec_days=?, duty_cycle_pct=?, "
            "d_industrial_m=?, d_agri_m=?, d_residential_m=? "
            "WHERE site_id=?",
            (res.classification, res.confidence, res.explanation, severity, anomalous,
             res.features["persistence"], res.features["consec_days"],
             res.features["duty_cycle_pct"], res.features["d_industrial"],
             res.features["d_agri"], res.features["d_residential"], sid),
        )
        if anomalous:
            created_alerts += _ensure_alert(sid, severity)

    return {
        "detections": len(new_det_ids),
        "sites": len(affected_site_ids),
        "pass_dates": pass_dates,
        "polygons": len(polys),
        "alerts_created": created_alerts,
    }


def ingest_nrt_rows(rows: list[dict], pass_dates: list[str], polys: list[dict],
                    ingestion_batch: str) -> dict:
    """Ingest NRT rows with real provenance (is_synthetic=0, source='firms'),
    using the incremental-safe path so repeated scheduler runs don't crash
    or duplicate sites."""
    return _ingest_incremental(rows, pass_dates, polys, is_synthetic=0, source="firms",
                               ingestion_batch=ingestion_batch)


def fetch_and_ingest_job() -> dict:
    """Main scheduled job: loop over all regions and sources.
    Keeps per-region/source state.
    Never marks today as fetched: after a successful run sets the state to yesterday,
    and on every run re-fetches the last 2 days (unique natural key index dedups).
    A failure in one region does not block other regions.
    """
    logger.info("Starting scheduled FIRMS ingestion job across regions and sources")
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    total_detections = 0
    total_sites_affected = 0
    regions_succeeded: list[str] = []
    regions_failed: list[tuple[str, str]] = []

    polys = load_polygons(OSM_GEOJSON)

    for region_name, bbox in FIRMS_REGIONS.items():
        for source in FIRMS_SOURCES:
            job_key = f"{region_name}:{source}"
            last_fetch = get_last_fetch_date(region_name, source)

            if last_fetch is None:
                since_date = today - timedelta(days=DAY_RANGE)
                logger.info(f"No previous fetch recorded for {job_key}. Fetching last {DAY_RANGE} days from {since_date}")
            else:
                two_days_ago = today - timedelta(days=1)
                since_date = min(last_fetch, two_days_ago)
                logger.info(f"Last fetch for {job_key} was {last_fetch}. Fetching from {since_date}")

            if since_date > today:
                logger.info(f"No new data needed for {job_key}")
                continue

            try:
                rows = fetch_new_data(
                    since_date=since_date,
                    max_date=today,
                    region=region_name,
                    bbox=bbox,
                    source=source,
                )
                if rows:
                    pass_dates = sorted({r["acq_date"] for r in rows if r.get("acq_date")})
                    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    batch_id = f"firms_nrt_{region_name}_{source}_{ts}"
                    summary = ingest_nrt_rows(rows, pass_dates, polys, batch_id)
                    total_detections += summary.get("detections", 0)
                    total_sites_affected += summary.get("sites", 0)
                    logger.info(f"Ingestion summary for {job_key}: {summary}")
                else:
                    logger.info(f"No new detections found for {job_key}")

                # After successful fetch/ingest, set state to yesterday (never today)
                set_last_fetch_date(yesterday, region_name, source)
                regions_succeeded.append(job_key)

            except Exception as e:
                logger.exception(f"Scheduled job failed for {job_key}: {e}")
                regions_failed.append((job_key, str(e)))
                # A failure in one region does NOT block the others!
                continue

    return {
        "status": "completed" if not regions_failed else "partial",
        "succeeded": regions_succeeded,
        "failed": regions_failed,
        "total_detections": total_detections,
        "total_sites": total_sites_affected,
    }


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