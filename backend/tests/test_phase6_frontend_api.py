"""Phase 6 regression tests: imagery panel endpoints and human classification review feedback."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import execute, get_conn, query
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_phase6_test_data():
    """Ensure test imagery, sites, and alerts are cleaned up before and after each test."""
    _do_cleanup()
    yield
    _do_cleanup()


def _do_cleanup():
    execute("DELETE FROM alert_reviews WHERE site_id LIKE 'SITE_P6_TEST%'")
    execute("DELETE FROM alerts WHERE site_id LIKE 'SITE_P6_TEST%'")
    execute("DELETE FROM imagery WHERE site_id LIKE 'SITE_P6_TEST%'")
    execute("DELETE FROM sites WHERE site_id LIKE 'SITE_P6_TEST%'")


def test_site_imagery_endpoint_placeholder_and_active():
    """Verify GET /api/sites/{site_id}/imagery returns empty list when no imagery exists, and populates when present."""
    # Create test site
    execute(
        "INSERT OR REPLACE INTO sites (site_id, lat, lon, classification, confidence, explanation, severity, is_anomalous, status, first_seen, last_seen, d_industrial_m, d_agri_m, d_residential_m) "
        "VALUES ('SITE_P6_TEST_1', 23.75, 86.40, 'industrial_fire', 0.95, 'Test site', 'severe', 1, 'alert_triggered', datetime('now'), datetime('now'), 100.0, 5000.0, 5000.0)"
    )

    # 1. No imagery present -> returns 200 with empty list []
    res_empty = client.get("/api/sites/SITE_P6_TEST_1/imagery")
    assert res_empty.status_code == 200
    assert res_empty.json() == []

    # 2. Insert mock satellite chip in imagery table
    execute(
        "INSERT INTO imagery (site_id, acquired_date, source, cloud_cover_pct, file_path, is_synthetic, status, created_at) "
        "VALUES ('SITE_P6_TEST_1', '2026-09-22', 'sentinel2-l2a', 2.5, 'data/imagery/SITE_P6_TEST_1/20260922.tif', 0, 'available', datetime('now'))"
    )

    # 3. Query again -> returns populated list
    res_populated = client.get("/api/sites/SITE_P6_TEST_1/imagery")
    assert res_populated.status_code == 200
    data = res_populated.json()
    assert len(data) == 1
    assert data[0]["site_id"] == "SITE_P6_TEST_1"
    assert data[0]["source"] == "sentinel2-l2a"
    assert data[0]["cloud_cover_pct"] == 2.5
    assert data[0]["file_path"] == "data/imagery/SITE_P6_TEST_1/20260922.tif"


def test_classification_feedback_submission_and_audit():
    """Verify POST /api/alerts/{id}/feedback updates feedback_label and writes append-only audit row."""
    execute(
        "INSERT OR REPLACE INTO sites (site_id, lat, lon, classification, confidence, explanation, severity, is_anomalous, status, first_seen, last_seen, d_industrial_m, d_agri_m, d_residential_m) "
        "VALUES ('SITE_P6_TEST_2', 23.76, 86.41, 'agricultural_burn', 0.85, 'Test site 2', 'moderate', 1, 'alert_triggered', datetime('now'), datetime('now'), 5000.0, 100.0, 5000.0)"
    )
    execute(
        "INSERT INTO alerts (site_id, severity, is_anomalous, status, created_at, updated_at) "
        "VALUES ('SITE_P6_TEST_2', 'moderate', 1, 'alert_triggered', datetime('now'), datetime('now'))"
    )
    alert_row = query("SELECT id FROM alerts WHERE site_id='SITE_P6_TEST_2' ORDER BY id DESC LIMIT 1")[0]
    alert_id = alert_row["id"]

    feedback_payload = {
        "feedback": "correct",
        "analyst_note": "Visual plume matches thermal signature.",
        "reviewed_by": "analyst_beta",
    }

    res = client.post(f"/api/alerts/{alert_id}/feedback", json=feedback_payload)
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["feedback"] == "correct"
    assert res_data["alert"]["feedback_label"] == "correct"

    # Check database state
    db_alert = query("SELECT * FROM alerts WHERE id=?", (alert_id,))[0]
    assert db_alert["feedback_label"] == "correct"

    # Check append-only audit trail
    reviews = query("SELECT * FROM alert_reviews WHERE alert_id=? AND action='feedback'", (alert_id,))
    assert len(reviews) == 1
    assert reviews[0]["feedback_label"] == "correct"
    assert reviews[0]["reviewed_by"] == "analyst_beta"
    assert reviews[0]["analyst_note"] == "Visual plume matches thermal signature."
