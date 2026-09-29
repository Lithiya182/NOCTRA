"""NOCTRA Phase 1 Reviewer Security & Human-Gated Dispatch Tests.

Verifies:
1. Ingest of an extreme-FRP detection sends nothing (alert stays 'alert_triggered').
2. POST /api/alerts/{id}/notify on unconfirmed alert is rejected (400).
3. Missing or invalid Bearer token -> 401 Unauthorized.
4. Viewer role -> 403 Forbidden on confirm/transition/notify.
5. reviewed_by in alert_reviews strictly matches authenticated reviewer name, ignoring payload defaults.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import create_reviewer
from app.config import API_KEY
from app.db import execute, query
from app.main import app

client = TestClient(app)

DEV_HEADER = {"X-API-Key": API_KEY}
TEST_REV_TOKEN = "noctra-rev-sec-reviewer-xyz"
TEST_VIEW_TOKEN = "noctra-rev-sec-viewer-xyz"


@pytest.fixture(autouse=True)
def setup_and_teardown_security_test():
    """Setup test reviewers and clean up test rows."""
    create_reviewer("Officer Jane Doe", "reviewer", TEST_REV_TOKEN)
    create_reviewer("Safety Observer Tim", "viewer", TEST_VIEW_TOKEN)
    _cleanup()
    yield
    _cleanup()


def _cleanup():
    execute("DELETE FROM alert_reviews WHERE site_id LIKE 'SITE_GATING_TEST%' OR site_id = 'TG-26543-83211'")
    execute("DELETE FROM alerts WHERE site_id LIKE 'SITE_GATING_TEST%' OR site_id = 'TG-26543-83211'")
    execute("DELETE FROM sites WHERE site_id LIKE 'SITE_GATING_TEST%' OR site_id = 'TG-26543-83211'")
    execute("DELETE FROM detections WHERE latitude = 26.5432 AND longitude = 83.2109")


def _create_test_site_and_alert(site_id: str = "SITE_GATING_TEST_1", status: str = "alert_triggered") -> int:
    execute(
        "INSERT OR REPLACE INTO sites (site_id, lat, lon, classification, confidence, explanation, severity, is_anomalous, status, first_seen, last_seen, d_industrial_m, d_agri_m, d_residential_m) "
        "VALUES (?, 23.75, 86.40, 'industrial_fire', 0.95, 'Gating test site', 'extreme', 1, ?, datetime('now'), datetime('now'), 100.0, 5000.0, 5000.0)",
        (site_id, status),
    )
    execute(
        "INSERT INTO alerts (site_id, severity, is_anomalous, status, created_at, updated_at) "
        "VALUES (?, 'extreme', 1, ?, datetime('now'), datetime('now'))",
        (site_id, status),
    )
    row = query("SELECT id FROM alerts WHERE site_id=? ORDER BY id DESC LIMIT 1", (site_id,))[0]
    return row["id"]


def test_extreme_frp_ingest_sends_nothing_and_stays_alert_triggered():
    """1. Ingest of an extreme-FRP detection creates alert_triggered and does NOT auto-dispatch."""
    _cleanup()
    res = client.post(
        "/api/dev/detection",
        json={"lat": 26.5432, "lon": 83.2109, "frp": 250.0, "brightness": 450.0},
        headers=DEV_HEADER,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["alert_created"] == 1

    alerts = client.get("/api/alerts").json()
    created_alert = next(a for a in alerts if a["site_id"] == data["site_id"])
    assert created_alert["severity"] == "extreme"
    assert created_alert["status"] == "alert_triggered"
    assert created_alert.get("reviewed_by") is None


def test_notify_on_unconfirmed_alert_is_rejected_400():
    """2. /notify on an unconfirmed alert (alert_triggered) must be rejected with HTTP 400."""
    alert_id = _create_test_site_and_alert("SITE_GATING_TEST_UNCONFIRMED", status="alert_triggered")

    res = client.post(
        f"/api/alerts/{alert_id}/notify",
        headers={"Authorization": f"Bearer {TEST_REV_TOKEN}"},
    )
    assert res.status_code == 400
    assert "must be confirmed" in res.json()["detail"].lower()


def test_missing_or_invalid_token_returns_401():
    """3. Requests without a token or with an invalid token return 401 Unauthorized."""
    alert_id = _create_test_site_and_alert("SITE_GATING_TEST_AUTH", status="alert_triggered")

    # Transition without token
    res1 = client.post(f"/api/alerts/{alert_id}/transition", json={"action": "confirm"})
    assert res1.status_code == 401

    # Transition with invalid token
    res2 = client.post(
        f"/api/alerts/{alert_id}/transition",
        json={"action": "confirm"},
        headers={"Authorization": "Bearer invalid-random-token"},
    )
    assert res2.status_code == 401

    # Notify without token
    res3 = client.post(f"/api/alerts/{alert_id}/notify")
    assert res3.status_code == 401


def test_viewer_role_rejected_with_403_on_transition_and_notify():
    """4. Viewer role receives 403 Forbidden on transition/confirm/dismiss/notify."""
    alert_id = _create_test_site_and_alert("SITE_GATING_TEST_VIEWER", status="alert_triggered")
    viewer_headers = {"Authorization": f"Bearer {TEST_VIEW_TOKEN}"}

    # Confirm action
    res_confirm = client.post(
        f"/api/alerts/{alert_id}/transition",
        json={"action": "confirm"},
        headers=viewer_headers,
    )
    assert res_confirm.status_code == 403
    assert "Reviewer role required" in res_confirm.json()["detail"]

    # Dismiss action
    res_dismiss = client.post(
        f"/api/alerts/{alert_id}/transition",
        json={"action": "dismiss"},
        headers=viewer_headers,
    )
    assert res_dismiss.status_code == 403

    # Notify action
    res_notify = client.post(
        f"/api/alerts/{alert_id}/notify",
        headers=viewer_headers,
    )
    assert res_notify.status_code == 403


def test_reviewed_by_strictly_matches_authenticated_reviewer():
    """5. reviewed_by in alert_reviews matches authenticated reviewer name, never a default or payload body."""
    alert_id = _create_test_site_and_alert("SITE_GATING_TEST_IDENTITY", status="alert_triggered")

    # Payload attempts to spoof reviewed_by as 'unauthorized_imposter'
    payload = {
        "action": "confirm",
        "analyst_note": "Extreme thermal signature validated via ground truth.",
        "reviewed_by": "unauthorized_imposter",
    }
    res = client.post(
        f"/api/alerts/{alert_id}/transition",
        json=payload,
        headers={"Authorization": f"Bearer {TEST_REV_TOKEN}"},
    )
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["alert"]["status"] == "confirmed"
    assert res_data["alert"]["reviewed_by"] == "Officer Jane Doe"
    assert res_data["alert"]["reviewed_by"] != "unauthorized_imposter"

    # Check alert_reviews audit trail
    reviews = query("SELECT * FROM alert_reviews WHERE alert_id=? ORDER BY id DESC", (alert_id,))
    assert len(reviews) >= 1
    audit_row = reviews[0]
    assert audit_row["reviewed_by"] == "Officer Jane Doe"
    assert audit_row["reviewed_by"] != "unauthorized_imposter"
    assert audit_row["action"] == "confirm"
    assert audit_row["new_status"] == "confirmed"
