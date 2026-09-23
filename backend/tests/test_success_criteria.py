"""Section 5 success-criteria tests, executable via `pytest`."""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, ml_model  # noqa: E402
from app.config import FIRMS_CSV  # noqa: E402
from app.ingest import ingest  # noqa: E402
from app.main import app  # noqa: E402

CONTRACT_FIELDS = [
    "site_id", "lat", "lon", "classification", "confidence", "explanation",
    "severity", "is_anomalous", "status", "first_seen", "last_seen",
]


def _client():
    from app.config import API_KEY
    with TestClient(app) as client:  # triggers startup ingest
        client.headers["X-API-Key"] = API_KEY
        return client


def test_data_ingestion_matches_csv():
    c = _client()
    n_db = db.query("SELECT COUNT(*) AS c FROM detections")[0]["c"]
    n_syn = db.query("SELECT COUNT(*) AS c FROM detections WHERE is_synthetic = 1")[0]["c"]
    n_seed = db.query("SELECT COUNT(*) AS c FROM detections WHERE ingestion_batch = 'seed_20251110_20251114'")[0]["c"]
    with open(FIRMS_CSV, newline="", encoding="utf-8") as f:
        n_csv = sum(1 for _ in csv.DictReader(f))
    assert n_csv == 424
    assert n_seed >= n_csv
    assert n_syn >= n_csv
    assert n_db >= n_csv
    assert c.get("/api/health").json()["counts"]["detections"] == n_db


def test_sites_endpoint_contract():
    c = _client()
    sites = c.get("/api/sites").json()
    assert isinstance(sites, list) and sites
    for s in sites:
        assert set(CONTRACT_FIELDS).issubset(set(s.keys()))
        assert s["classification"] in {
            "industrial_fire", "agricultural_burn", "wildfire", "other"}
        assert s["severity"] in {"minor", "moderate", "severe", "extreme"}
        assert s["is_anomalous"] in (True, False)


def test_region_dominant_labels():
    c = _client()
    sites = c.get("/api/sites").json()
    from collections import Counter

    def dominant(box):
        pts = [s for s in sites if box[0] <= s["lat"] <= box[1] and box[2] <= s["lon"] <= box[3]]
        return Counter(s["classification"] for s in pts).most_common(1)[0][0]

    assert dominant((23.70, 23.84, 86.30, 86.48)) == "industrial_fire"   # Jharia
    assert dominant((22.35, 22.55, 69.90, 70.25)) == "industrial_fire"   # Jamnagar
    assert dominant((30.20, 31.35, 74.70, 76.80)) == "agricultural_burn"  # Punjab
    assert dominant((29.95, 30.16, 79.00, 79.35)) == "wildfire"           # Uttarakhand


def test_registry_deduplicates_sites():
    c = _client()
    c.post("/api/dev/ingest")
    sites = c.get("/api/sites").json()
    sites_by_id = {s["site_id"]: s for s in sites}
    assert len(sites) == len(sites_by_id)
    for s in sites:
        assert s["first_seen"] <= s["last_seen"]
    # Rester detection with multiple passes maps onto a single site: re-ingest
    # must produce the same site_id count (deterministic id + cluster).
    ids1 = {s["site_id"] for s in sites}
    c.post("/api/dev/ingest")
    ids2 = {s["site_id"] for s in c.get("/api/sites").json()}
    assert ids1 == ids2


def test_alert_lifecycle_and_gating():
    c = _client()
    alerts = c.get("/api/alerts").json()
    assert alerts, "anomalous sites should auto-create government-console alerts"
    severe_alerts = [a for a in alerts if a["severity"] in ("severe", "extreme")]
    assert severe_alerts, "severe/extreme alerts exist"

    target = severe_alerts[0]
    assert target["status"] == "alert_triggered"
    assert target["is_anomalous"], "severe => anomalous"
    cap = target["cap"]
    for field in ("identifier", "sent", "status", "info"):
        assert field in cap
    info = cap["info"][0]
    for field in ("category", "severity", "urgency", "area", "headline", "description"):
        assert field in info

    # Confirm on a SEVERE alert should fire the public tier (SMS/push) - here
    # unconfigured, so dispatch must still report the graceful offline path.
    res = c.post(f"/api/alerts/{target['id']}/transition", json={"action": "confirm"}).json()
    assert res["alert"]["status"] == "confirmed"
    assert "dispatched" in res
    assert res["dispatched"]["sms"]["sent"] is False


def test_runtime_detection_live_alert():
    c = _client()
    before = {a["id"] for a in c.get("/api/alerts").json()}
    res = c.post("/api/dev/detection",
                 json={"lat": 22.430, "lon": 69.985, "frp": 130.0}).json()
    assert res["alert_created"] == 1
    assert res["classification"] == "industrial_fire"
    assert res["severity"] == "extreme"
    after = {a["id"] for a in c.get("/api/alerts").json()}
    new_alerts = after - before
    assert new_alerts, "runtime detection appears as a new alert without page refresh"


def test_needs_writeback():
    c = _client()
    resp = c.post("/api/needs",
                  json={"kind": "help", "lat": 23.74, "lon": 86.33,
                        "message": "Need evacuation assistance"}).json()
    assert resp["id"] > 0
    needs = c.get("/api/needs").json()
    assert any(n["id"] == resp["id"] for n in needs)
    assert needs[0]["message"] == "Need evacuation assistance"


def test_polygons_and_filters():
    c = _client()
    polys = c.get("/api/polygons").json()
    kinds = {p["kind"] for p in polys}
    assert {"industrial", "agricultural", "residential"} <= kinds

    ind = c.get("/api/sites", params={"classification": "industrial_fire"}).json()
    assert ind and all(s["classification"] == "industrial_fire" for s in ind)
    wild = c.get("/api/sites", params={"classification": "wildfire"}).json()
    assert all(s["classification"] == "wildfire" for s in wild)
    assert len(ind) + len(wild) < len(c.get("/api/sites").json()), \
        "filtering to industrial hides non-industrial points"


def test_ml_weak_label_layer():
    ml_model.load()
    sites = [dict(r) for r in db.query("SELECT * FROM sites")]
    preds = ml_model.predict(sites[0])
    assert preds in {"industrial_fire", "agricultural_burn", "wildfire", "other"}


def test_synthetic_reset_preserves_real_rows():
    """Regression test: synthetic reset must preserve real FIRMS rows.
    Simulates the critical failure mode: real data disappearing after backend restart.
    """
    # A. Start with existing dataset (TestClient triggers ingest on startup)
    c = _client()
    n_dets_before = db.query("SELECT COUNT(*) AS c FROM detections")[0]["c"]
    n_real_before = db.query("SELECT COUNT(*) AS c FROM detections WHERE is_synthetic = 0")[0]["c"]
    n_syn_before = db.query("SELECT COUNT(*) AS c FROM detections WHERE is_synthetic = 1")[0]["c"]
    assert n_syn_before > 0, "synthetic seed data should exist"

    # B. Insert one clearly identifiable test detection with is_synthetic=0
    test_lat, test_lon = 12.34567, 98.76543  # unique coordinate not in seed data
    test_batch = "test_real_reset"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.execute(
        """INSERT INTO detections (latitude, longitude, bright_ti4, scan, track, acq_date,
           acq_time, satellite, instrument, confidence, version, bright_ti5, frp, daynight,
           is_synthetic, source, ingestion_batch)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (test_lat, test_lon, 300.0, 0.4, 0.4, "2025-11-10", "1200",
         "NOAA-20", "VIIRS", 90.0, "10.1.1_NRT", 290.0, 50.0, "D",
         0, "firms", test_batch),
    )

    # Verify real row count increased by 1
    n_real_after_insert = db.query("SELECT COUNT(*) AS c FROM detections WHERE is_synthetic = 0")[0]["c"]
    assert n_real_after_insert == n_real_before + 1

    # C. Run synthetic reset path
    summary = ingest(reset=True)

    # D. Confirm real detections preserved
    n_real_after_reset = db.query("SELECT COUNT(*) AS c FROM detections WHERE is_synthetic = 0")[0]["c"]
    assert n_real_after_reset == n_real_before + 1, f"real detection lost after reset (count={n_real_after_reset})"

    real_row = db.query(
        "SELECT * FROM detections WHERE is_synthetic = 0 AND ingestion_batch = ?",
        (test_batch,),
    )
    assert len(real_row) == 1
    assert real_row[0]["latitude"] == test_lat
    assert real_row[0]["longitude"] == test_lon

    # E. Clean up test row
    db.execute("DELETE FROM detections WHERE ingestion_batch = ?", (test_batch,))
    db.execute("DELETE FROM site_detections WHERE site_id IN (SELECT site_id FROM sites WHERE lat = ? AND lon = ?)",
               (test_lat, test_lon))
    db.execute("DELETE FROM sites WHERE lat = ? AND lon = ?", (test_lat, test_lon))
    db.execute("DELETE FROM alerts WHERE site_id IN (SELECT site_id FROM sites WHERE lat = ? AND lon = ?)",
               (test_lat, test_lon))

    # Verify state restored
    n_real_final = db.query("SELECT COUNT(*) AS c FROM detections WHERE is_synthetic = 0")[0]["c"]
    assert n_real_final == n_real_before, "database not restored to initial real row count"

    print("RESET SAFETY TEST PASSED: real rows survive synthetic reset")