"""End-to-end smoke test for Section 5 success criteria (backend side)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.ingest import ingest
from app import db, ml_model

summary = ingest(reset=True)
print("INGEST:", summary)

n_det = db.query("SELECT COUNT(*) c FROM detections")[0]["c"]
n_csv = sum(1 for _ in open(ROOT / "data/firms_seed.csv", encoding="utf-8")) - 1
print(f"detections rows: db={n_det} csv={n_csv} match={n_det == n_csv}")

from collections import Counter
n_sites = db.query("SELECT COUNT(*) c FROM sites")[0]["c"]
print("sites:", n_sites)

rows = [dict(r) for r in db.query(
    "SELECT site_id, lat, lon, classification, severity, is_anomalous, max_frp, "
    "confidence, explanation FROM sites")]
print("classification counts:", Counter(r["classification"] for r in rows))
print("severity counts:", Counter(r["severity"] for r in rows))

region_checks = {
    "Jharia (23.70-23.84, 86.30-86.48)": [r for r in rows if 23.70 <= r["lat"] <= 23.84 and 86.30 <= r["lon"] <= 86.48],
    "Jamnagar (22.35-22.55, 69.90-70.25)": [r for r in rows if 22.35 <= r["lat"] <= 22.55 and 69.90 <= r["lon"] <= 70.25],
    "Punjab (30.2-31.3, 74.7-76.7)": [r for r in rows if 30.20 <= r["lat"] <= 31.35 and 74.70 <= r["lon"] <= 76.80],
    "Uttarakhand (29.95-30.16, 79.00-79.32)": [r for r in rows if 29.95 <= r["lat"] <= 30.16 and 79.00 <= r["lon"] <= 79.32],
}
for name, region in region_checks.items():
    c = Counter(r["classification"] for r in region)
    print(f"{name}: {len(region)} sites -> {dict(c)}")

ml_result = ml_model.train()
print("ML:", ml_result)
ml_rows = [dict(r) for r in db.query("SELECT * FROM sites")]
preds = Counter(ml_model.predict(s) for s in ml_rows)
print("ML prediction distribution:", dict(preds))
