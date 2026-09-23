"""Phase 7 regression tests: Sentinel-2 satellite imagery acquisition subsystem and provenance."""
from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import DATA_DIR
from app.db import execute, query
from app.main import app
from app.satellite_imagery import acquire_imagery_for_site, fetch_stac_scene

client = TestClient(app)


def test_stac_scene_query_structure():
    """Verify fetch_stac_scene returns standard dictionary contract."""
    res = fetch_stac_scene(23.71944, 86.42186, "2026-09-20T19:23:00Z", window_days=5, max_cloud_cover=50.0)
    assert isinstance(res, dict)
    assert "status" in res
    assert "datetime" in res
    assert "cloud_cover" in res
    assert res["status"] in ("available", "no_clear_pass")


def test_imagery_acquisition_db_and_provenance():
    """Verify acquire_imagery_for_site writes provenance row to imagery DB table."""
    # Insert test site
    execute(
        "INSERT OR REPLACE INTO sites (site_id, lat, lon, classification, confidence, explanation, severity, is_anomalous, status, first_seen, last_seen, d_industrial_m, d_agri_m, d_residential_m) "
        "VALUES ('SITE_P7_TEST_1', 23.71944, 86.42186, 'industrial_fire', 0.95, 'Test real site', 'severe', 1, 'alert_triggered', '2026-09-20T19:23:00Z', '2026-09-20T19:23:00Z', 100.0, 5000.0, 5000.0)"
    )

    result = acquire_imagery_for_site("SITE_P7_TEST_1", 23.71944, 86.42186, "2026-09-20T19:23:00Z", is_synthetic=False, max_cloud_cover=50.0)
    assert result["site_id"] == "SITE_P7_TEST_1"
    assert result["is_synthetic"] == 0

    # Query DB
    db_rows = query("SELECT * FROM imagery WHERE site_id='SITE_P7_TEST_1'")
    assert len(db_rows) >= 1
    row = db_rows[0]
    assert row["source"] == "sentinel2-l2a"
    assert row["is_synthetic"] == 0
    assert row["status"] in ("available", "no_clear_pass")

    # Cleanup test site and imagery
    execute("DELETE FROM imagery WHERE site_id='SITE_P7_TEST_1'")
    execute("DELETE FROM sites WHERE site_id='SITE_P7_TEST_1'")


def test_no_clear_pass_honesty_constraint():
    """Verify sites with cloud cover > max_cloud_cover record status='no_clear_pass' with file_path=None."""
    execute(
        "INSERT OR REPLACE INTO sites (site_id, lat, lon, classification, confidence, explanation, severity, is_anomalous, status, first_seen, last_seen, d_industrial_m, d_agri_m, d_residential_m) "
        "VALUES ('SITE_P7_TEST_2', 23.71944, 86.42186, 'industrial_fire', 0.95, 'Test cloudy site', 'severe', 1, 'alert_triggered', '2026-09-20T19:23:00Z', '2026-09-20T19:23:00Z', 100.0, 5000.0, 5000.0)"
    )

    # Force max_cloud_cover = 0.0% so scene triggers no_clear_pass threshold
    result = acquire_imagery_for_site("SITE_P7_TEST_2", 23.71944, 86.42186, "2026-09-20T19:23:00Z", is_synthetic=False, max_cloud_cover=0.0)
    assert result["status"] == "no_clear_pass"
    assert result["file_path"] is None

    # Query DB
    db_rows = query("SELECT * FROM imagery WHERE site_id='SITE_P7_TEST_2'")
    assert len(db_rows) == 1
    assert db_rows[0]["status"] == "no_clear_pass"
    assert db_rows[0]["file_path"] is None

    # Cleanup
    execute("DELETE FROM imagery WHERE site_id='SITE_P7_TEST_2'")
    execute("DELETE FROM sites WHERE site_id='SITE_P7_TEST_2'")
