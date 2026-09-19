"""Detection pipeline: load FIRMS CSV -> detections table -> site registry ->
rule-based classification -> alerts. Runs at startup and on demand."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from haversine import haversine, Unit

from . import db
from .classifier import classify, severity_for_frp
from .config import CLUSTER_RADIUS_M, DATA_DIR, FIRMS_CSV, FIRMS_REAL_CSV, OSM_GEOJSON
from .feature_utils import load_polygons

M = Unit.METERS


def _site_id(lat: float, lon: float, taken: set[str]) -> str:
    base = f"TG-{int(round(lat * 1000)):05d}-{int(round(lon * 1000)):05d}"
    sid, k = base, 0
    while sid in taken:
        k += 1
        sid = f"{base}-{chr(ord('A') + k)}"
    return sid


def load_csv(path: Path = FIRMS_CSV) -> tuple[list[dict], list[str]]:
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

    # --- registry: cluster detections within 1km into sites ---
    # Query ALL detections (real + synthetic) for clustering
    all_det_rows = [dict(r) for r in db.query(
        "SELECT id, latitude, longitude, bright_ti4, acq_date, acq_time, frp FROM detections"
    )]
    ordered = sorted(all_det_rows, key=lambda r: (r["acq_date"], str(r.get("acq_time", ""))))

    sites: dict[str, dict] = {}
    taken: set[str] = set()

    for r in ordered:
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


def ingest(reset: bool = True, *, real_csv: Path | None = None) -> dict:
    """Main ingestion entry point.

    Synthetic (demo) path (default): reset synthetic data, ingest seed CSV.
    Real FIRMS path: real_csv=FIRMS_REAL_CSV, no reset of real data.
    """
    if real_csv is not None:
        # Real FIRMS ingestion: append to existing data, no reset
        rows, pass_dates = load_csv(real_csv)
        polys = load_polygons(OSM_GEOJSON)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return _ingest_rows(rows, pass_dates, polys, is_synthetic=0, source="firms",
                            ingestion_batch=f"firms_{ts}")

    # Synthetic demo path
    rows, pass_dates = load_csv(FIRMS_CSV)
    polys = load_polygons(OSM_GEOJSON)

    if reset:
        # Provenance-safe reset: delete synthetic detections + derived tables,
        # preserve real detections
        db.reset_synthetic_only()
    else:
        db.reset_derived_tables()

    return _ingest_rows(rows, pass_dates, polys, is_synthetic=1, source="synthetic",
                        ingestion_batch="seed_20251110_20251114")


def _ensure_alert(site_id: str, severity: str) -> int:
    """Create an alert_triggered government-console entry if none is active."""
    existing = db.query(
        "SELECT id FROM alerts WHERE site_id=? AND status IN ('alert_triggered','confirmed')",
        (site_id,),
    )
    if existing:
        return 0
    from .cap import build_cap_alert
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


def trigger_runtime_detection(lat: float, lon: float, frp: float = 120.0,
                              brightness: float = 360.0) -> dict:
    """Dev/demo helper: inject a LIVE detection plus its recent history at runtime,
    classify it, and produce a new government-console alert. Demonstrates the
    end-to-end path without using any live external API."""
    # Use synthetic seed dates for history simulation
    _, pass_dates = load_csv(FIRMS_CSV)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_t = datetime.now(timezone.utc).strftime("%H%M")

    # Simulate the site having been active on previous satellite passes too.
    history_dates = pass_dates[-4:]
    inserted = []
    for hd in history_dates:
        inserted.append((lat, lon, brightness, 0.4, 0.4, hd, now_t, "NOAA-20",
                         "VIIRS", 98.0, "10.1.1_NRT", 305.0, frp, "D",
                         1, "synthetic", "seed_20251110_20251114"))
    inserted.append((lat, lon, brightness, 0.4, 0.4, today, now_t, "NOAA-20",
                     "VIIRS", 98.0, "10.1.1_NRT", 305.0, frp, "D",
                     1, "synthetic", "seed_20251110_20251114"))
    db.executemany(
        "INSERT INTO detections (latitude, longitude, bright_ti4, scan, track, acq_date, "
        "acq_time, satellite, instrument, confidence, version, bright_ti5, frp, daynight, "
        "is_synthetic, source, ingestion_batch) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", inserted)

    # Build detection dicts for the classifier straight from the DB (sources of truth).
    det_rows = [dict(r) for r in db.query(
        "SELECT latitude, longitude, bright_ti4, acq_date, frp FROM detections")]
    all_pass_dates = sorted({r["acq_date"] for r in det_rows})

    sid = _site_id(lat, lon, set())
    existing = db.query("SELECT * FROM sites WHERE site_id=?", (sid,))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if existing:
        site = dict(existing[0])
        db.execute("UPDATE sites SET last_seen=?, max_frp=MAX(max_frp,?), brightness=MAX(brightness,?) "
                   "WHERE site_id=?", (now, frp, brightness, sid))
    else:
        db.execute(
            "INSERT INTO sites (site_id, lat, lon, first_seen, last_seen, max_frp, brightness, status) "
            "VALUES (?,?,?,?,?,?,?,'alert_triggered')",
            (sid, lat, lon, now, now, frp, brightness),
        )
        site = dict(db.query("SELECT * FROM sites WHERE site_id=?", (sid,))[0])
    month = int(today[5:7])
    res = classify(lat, lon, det_rows, load_polygons(), all_pass_dates, month, frp, brightness)
    severity = severity_for_frp(frp)
    anomalous = int(severity in ("severe", "extreme"))
    db.execute(
        "UPDATE sites SET classification=?, confidence=?, explanation=?, severity=?, "
        "is_anomalous=?, duty_cycle_pct=?, d_industrial_m=?, d_agri_m=?, d_residential_m=? "
        "WHERE site_id=?",
        (res.classification, res.confidence, res.explanation, severity, anomalous,
         res.features["duty_cycle_pct"], res.features["d_industrial"],
         res.features["d_agri"], res.features["d_residential"], sid),
    )
    created = _ensure_alert(sid, severity)
    if created and severity == "extreme":
        from .alert_engine import dispatch_public
        alert = dict(db.query("SELECT * FROM alerts WHERE site_id=? AND status='alert_triggered' "
                              "ORDER BY id DESC LIMIT 1", (sid,))[0])
        dispatch_public(alert, site)
    return {"site_id": sid, "classification": res.classification, "severity": severity,
            "alert_created": created, "explanation": res.explanation}