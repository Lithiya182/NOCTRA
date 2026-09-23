"""Phase 13 security regression tests: API key authentication & public SOS rate limiting."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import API_KEY
from app.db import execute, query
from app.main import app
from app.routers.needs import _reset_rate_limits

client = TestClient(app)

DEV_HEADER = {"X-API-Key": API_KEY}
BEARER_HEADER = {"Authorization": f"Bearer {API_KEY}"}


@pytest.fixture(autouse=True)
def cleanup_security_test_data():
    """Clean up test data and reset rate limit counters between tests."""
    _reset_rate_limits()
    _do_cleanup()
    yield
    _do_cleanup()
    _reset_rate_limits()


def _do_cleanup():
    execute("DELETE FROM alert_reviews WHERE site_id LIKE 'SITE_P13_TEST%'")
    execute("DELETE FROM alerts WHERE site_id LIKE 'SITE_P13_TEST%'")
    execute("DELETE FROM sites WHERE site_id LIKE 'SITE_P13_TEST%'")
    execute("DELETE FROM needs WHERE message LIKE '%P13_TEST%'")


def test_unauthenticated_transition_rejected():
    """Verify state-changing alert transition endpoint rejects unauthenticated/invalid requests with 401."""
    execute(
        "INSERT OR REPLACE INTO sites (site_id, lat, lon, classification, confidence, explanation, severity, is_anomalous, status, first_seen, last_seen, d_industrial_m, d_agri_m, d_residential_m) "
        "VALUES ('SITE_P13_TEST_1', 23.76, 86.41, 'industrial_fire', 0.90, 'Test site', 'severe', 1, 'alert_triggered', datetime('now'), datetime('now'), 100.0, 5000.0, 5000.0)"
    )
    execute(
        "INSERT INTO alerts (site_id, severity, is_anomalous, status, created_at, updated_at) "
        "VALUES ('SITE_P13_TEST_1', 'severe', 1, 'alert_triggered', datetime('now'), datetime('now'))"
    )
    alert_row = query("SELECT id FROM alerts WHERE site_id='SITE_P13_TEST_1' ORDER BY id DESC LIMIT 1")[0]
    alert_id = alert_row["id"]

    payload = {"action": "confirm", "analyst_note": "Test confirm"}

    # 1. No auth headers -> 401
    res_no_auth = client.post(f"/api/alerts/{alert_id}/transition", json=payload)
    assert res_no_auth.status_code == 401
    assert "Unauthorized" in res_no_auth.json()["detail"]

    # 2. Invalid API key -> 401
    res_invalid = client.post(
        f"/api/alerts/{alert_id}/transition",
        json=payload,
        headers={"X-API-Key": "invalid-secret-key"},
    )
    assert res_invalid.status_code == 401

    # 3. Valid X-API-Key header -> 200
    res_valid_header = client.post(
        f"/api/alerts/{alert_id}/transition",
        json=payload,
        headers=DEV_HEADER,
    )
    assert res_valid_header.status_code == 200
    assert res_valid_header.json()["alert"]["status"] == "confirmed"

    # 4. Valid Bearer Token -> 200
    payload_dismiss = {"action": "dismiss", "analyst_note": "Test dismiss"}
    res_valid_bearer = client.post(
        f"/api/alerts/{alert_id}/transition",
        json=payload_dismiss,
        headers=BEARER_HEADER,
    )
    assert res_valid_bearer.status_code == 200
    assert res_valid_bearer.json()["alert"]["status"] == "dismissed"


def test_unauthenticated_dev_endpoints_rejected():
    """Verify all /api/dev/* state-changing endpoints require API key authentication."""
    # 1. /api/dev/ingest without auth -> 401
    assert client.post("/api/dev/ingest").status_code == 401

    # 2. /api/dev/detection without auth -> 401
    detection_body = {"lat": 23.76, "lon": 86.42, "frp": 120.0, "brightness": 350.0}
    assert client.post("/api/dev/detection", json=detection_body).status_code == 401

    # 3. /api/dev/retrain without auth -> 401
    assert client.post("/api/dev/retrain").status_code == 401

    # 4. With valid auth -> dev endpoints do not return 401
    # Check detection endpoint with valid key
    res_det = client.post("/api/dev/detection", json=detection_body, headers=DEV_HEADER)
    assert res_det.status_code == 200


def test_public_sos_rate_limiting():
    """Verify POST /api/needs accepts 5 requests per 60s window and rejects the 6th request with 429."""
    _reset_rate_limits()

    need_payload = {
        "kind": "sos",
        "lat": 23.76,
        "lon": 86.42,
        "message": "P13_TEST Emergency SOS check",
    }

    # First 5 requests succeed (HTTP 201 Created)
    for i in range(5):
        res = client.post("/api/needs", json=need_payload)
        assert res.status_code == 201, f"Request {i+1} failed with {res.status_code}"

    # 6th request fails with HTTP 429 Too Many Requests
    res_throttled = client.post("/api/needs", json=need_payload)
    assert res_throttled.status_code == 429
    assert "Rate limit exceeded" in res_throttled.json()["detail"]
