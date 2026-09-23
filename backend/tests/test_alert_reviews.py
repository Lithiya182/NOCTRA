"""Phase 5 regression tests: alert status transitions, analyst notes, and append-only audit trail."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import execute, get_conn, query
from app.main import app

from app.config import API_KEY

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": API_KEY}


def test_existing_alerts_migration_and_structure():
    """Verify schema migration adds analyst_note and reviewed_by without breaking existing alerts."""
    conn = get_conn()
    table_info = conn.execute("PRAGMA table_info(alerts)").fetchall()
    col_names = [col["name"] for col in table_info]
    assert "analyst_note" in col_names
    assert "reviewed_by" in col_names

    # Check alert_reviews table exists
    tables = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "alert_reviews" in tables

    # Query alerts endpoint
    response = client.get("/api/alerts")
    assert response.status_code == 200
    alerts = response.json()
    assert isinstance(alerts, list)


def test_transition_confirm_with_note():
    """Test confirming an alert with an analyst note and reviewer ID."""
    execute(
        "INSERT OR REPLACE INTO sites (site_id, lat, lon, classification, confidence, explanation, severity, is_anomalous, status, first_seen, last_seen, d_industrial_m, d_agri_m, d_residential_m) "
        "VALUES ('SITE_P5_TEST_1', 23.75, 86.40, 'industrial_fire', 0.95, 'Test site', 'severe', 1, 'alert_triggered', datetime('now'), datetime('now'), 100.0, 5000.0, 5000.0)"
    )
    execute(
        "INSERT INTO alerts (site_id, severity, is_anomalous, status, created_at, updated_at) "
        "VALUES ('SITE_P5_TEST_1', 'severe', 1, 'alert_triggered', datetime('now'), datetime('now'))"
    )
    alert_row = query("SELECT id FROM alerts WHERE site_id='SITE_P5_TEST_1' ORDER BY id DESC LIMIT 1")[0]
    alert_id = alert_row["id"]

    note_text = "Verified industrial smoke plume via thermal sensor reading."
    reviewer = "operator_alpha"

    payload = {
        "action": "confirm",
        "analyst_note": note_text,
        "reviewed_by": reviewer,
    }

    res = client.post(f"/api/alerts/{alert_id}/transition", json=payload, headers=AUTH_HEADERS)
    assert res.status_code == 200
    data = res.json()

    assert data["alert"]["status"] == "confirmed"
    assert data["alert"]["analyst_note"] == note_text
    assert data["alert"]["reviewed_by"] == reviewer

    # Verify database state in alerts table
    db_alert = query("SELECT * FROM alerts WHERE id=?", (alert_id,))[0]
    assert db_alert["status"] == "confirmed"
    assert db_alert["analyst_note"] == note_text
    assert db_alert["reviewed_by"] == reviewer

    # Verify append-only record in alert_reviews audit table
    reviews = query("SELECT * FROM alert_reviews WHERE alert_id=? ORDER BY id DESC", (alert_id,))
    assert len(reviews) >= 1
    latest_review = reviews[0]
    assert latest_review["action"] == "confirm"
    assert latest_review["new_status"] == "confirmed"
    assert latest_review["analyst_note"] == note_text
    assert latest_review["reviewed_by"] == reviewer


def test_transition_dismiss_with_note():
    """Test dismissing an alert with an analyst note."""
    execute(
        "INSERT OR REPLACE INTO sites (site_id, lat, lon, classification, confidence, explanation, severity, is_anomalous, status, first_seen, last_seen, d_industrial_m, d_agri_m, d_residential_m) "
        "VALUES ('SITE_P5_TEST_2', 23.76, 86.41, 'agricultural_burn', 0.85, 'Test site 2', 'moderate', 1, 'alert_triggered', datetime('now'), datetime('now'), 5000.0, 100.0, 5000.0)"
    )
    execute(
        "INSERT INTO alerts (site_id, severity, is_anomalous, status, created_at, updated_at) "
        "VALUES ('SITE_P5_TEST_2', 'moderate', 1, 'alert_triggered', datetime('now'), datetime('now'))"
    )
    alert_row = query("SELECT id FROM alerts WHERE site_id='SITE_P5_TEST_2' ORDER BY id DESC LIMIT 1")[0]
    alert_id = alert_row["id"]

    note_text = "False positive: controlled stack burn authorized under permit #402."

    payload = {
        "action": "dismiss",
        "analyst_note": note_text,
    }

    res = client.post(f"/api/alerts/{alert_id}/transition", json=payload, headers=AUTH_HEADERS)
    assert res.status_code == 200
    data = res.json()

    assert data["alert"]["status"] == "dismissed"
    assert data["alert"]["analyst_note"] == note_text
    assert data["alert"]["reviewed_by"] == "analyst"

    # Verify audit endpoint
    reviews_res = client.get(f"/api/alerts/{alert_id}/reviews")
    assert reviews_res.status_code == 200
    reviews_list = reviews_res.json()
    assert len(reviews_list) >= 1
    assert reviews_list[-1]["action"] == "dismiss"
    assert reviews_list[-1]["analyst_note"] == note_text
    assert reviews_list[-1]["new_status"] == "dismissed"


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Ensure test sites and alerts are cleaned up before and after each test."""
    _do_cleanup()
    yield
    _do_cleanup()


def _do_cleanup():
    execute("DELETE FROM alert_reviews WHERE site_id LIKE 'SITE_P5_TEST%'")
    execute("DELETE FROM alerts WHERE site_id LIKE 'SITE_P5_TEST%'")
    execute("DELETE FROM sites WHERE site_id LIKE 'SITE_P5_TEST%'")


def test_global_reviews_endpoint():
    """Test GET /api/alerts/reviews endpoint."""
    res = client.get("/api/alerts/reviews")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
