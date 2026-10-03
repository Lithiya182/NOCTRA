"""Tests for thermal behavior indicators (Module 4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.routers.sites import _frp_intensity, _compute_frp_trend, _attach_thermal_behavior
from app import db


def test_frp_intensity_boundaries():
    """Test FRP intensity classification at exact boundaries."""
    # < 5 MW = weak
    assert _frp_intensity(0.0) == "weak"
    assert _frp_intensity(4.9) == "weak"
    # 5 MW = moderate
    assert _frp_intensity(5.0) == "moderate"
    assert _frp_intensity(19.9) == "moderate"
    # 20 MW = high-moderate
    assert _frp_intensity(20.0) == "high-moderate"
    assert _frp_intensity(49.9) == "high-moderate"
    # 50 MW = high
    assert _frp_intensity(50.0) == "high"
    assert _frp_intensity(99.9) == "high"
    # 100 MW = very-high
    assert _frp_intensity(100.0) == "very-high"
    assert _frp_intensity(150.0) == "very-high"
    print("PASS: test_frp_intensity_boundaries")


def test_frp_trend_increasing():
    """Test FRP trend detection - increasing."""
    # Clear increasing trend
    frp = [10.0, 12.0, 15.0, 20.0, 25.0, 30.0]
    assert _compute_frp_trend(frp) == "increasing"
    # Less data but still increasing
    frp = [10.0, 15.0, 20.0]
    assert _compute_frp_trend(frp) == "increasing"
    print("PASS: test_frp_trend_increasing")


def test_frp_trend_decreasing():
    """Test FRP trend detection - decreasing."""
    frp = [30.0, 25.0, 20.0, 15.0, 12.0, 10.0]
    assert _compute_frp_trend(frp) == "decreasing"
    frp = [20.0, 15.0, 10.0]
    assert _compute_frp_trend(frp) == "decreasing"
    print("PASS: test_frp_trend_decreasing")


def test_frp_trend_stable():
    """Test FRP trend detection - stable."""
    frp = [10.0, 10.5, 10.2, 9.8, 10.1, 10.0]
    assert _compute_frp_trend(frp) == "stable"
    frp = [10.0, 10.1, 9.9]
    assert _compute_frp_trend(frp) == "stable"
    print("PASS: test_frp_trend_stable")


def test_frp_trend_insufficient_data():
    """Test FRP trend returns insufficient_data for < 3 observations."""
    assert _compute_frp_trend([]) == "insufficient_data"
    assert _compute_frp_trend([10.0]) == "insufficient_data"
    assert _compute_frp_trend([10.0, 15.0]) == "insufficient_data"
    print("PASS: test_frp_trend_insufficient_data")


def test_thermal_behavior_real_site():
    """Test thermal behavior computation for a real FIRMS site."""
    # Use a real site from the database
    rows = db.query("""
        SELECT s.site_id, s.lat, s.lon, s.max_frp
        FROM sites s
        JOIN site_detections sd ON s.site_id = sd.site_id
        JOIN detections d ON sd.detection_id = d.id
        WHERE d.is_synthetic = 0
        GROUP BY s.site_id
        ORDER BY s.max_frp DESC
        LIMIT 1
    """)
    assert len(rows) > 0, "No real sites in database"

    site = dict(rows[0])
    sites = [site]
    _attach_thermal_behavior(sites)

    s = sites[0]
    assert "frp_mean" in s
    assert "frp_std" in s
    assert "frp_last" in s
    assert "frp_trend" in s
    assert "detection_count" in s
    assert "active_pass_count" in s
    assert "days_span" in s
    assert "expansion_magnitude" in s
    assert "frp_intensity" in s

    # Verify values are reasonable
    assert s["detection_count"] > 0
    assert s["active_pass_count"] > 0
    assert s["frp_intensity"] in ("weak", "moderate", "high-moderate", "high", "very-high")
    assert s["frp_trend"] in ("increasing", "decreasing", "stable", "insufficient_data")

    print(f"PASS: test_thermal_behavior_real_site -> {s['site_id']}: intensity={s['frp_intensity']}, trend={s['frp_trend']}, detections={s['detection_count']}")


def test_thermal_behavior_demo_site():
    """Test thermal behavior computation for a demo site."""
    rows = db.query("""
        SELECT s.site_id, s.lat, s.lon, s.max_frp
        FROM sites s
        JOIN site_detections sd ON s.site_id = sd.site_id
        JOIN detections d ON sd.detection_id = d.id
        WHERE d.is_synthetic = 1
        GROUP BY s.site_id
        ORDER BY s.max_frp DESC
        LIMIT 1
    """)
    assert len(rows) > 0, "No demo sites in database"

    site = dict(rows[0])
    sites = [site]
    _attach_thermal_behavior(sites)

    s = sites[0]
    assert s["detection_count"] > 0
    assert s["active_pass_count"] > 0
    assert s["frp_intensity"] in ("weak", "moderate", "high-moderate", "high", "very-high")

    print(f"PASS: test_thermal_behavior_demo_site -> {s['site_id']}: intensity={s['frp_intensity']}, detections={s['detection_count']}")


def test_sparse_observations_not_inactive():
    """Test that sparse observations (persistence=0) are NOT interpreted as confirmed inactive.
    Real FIRMS sites with low persistence should still show thermal activity data.
    """
    # Find a real site with persistence=0 but detections exist
    rows = db.query("""
        SELECT s.site_id, s.lat, s.lon, s.max_frp, s.persistence
        FROM sites s
        JOIN site_detections sd ON s.site_id = sd.site_id
        JOIN detections d ON sd.detection_id = d.id
        WHERE d.is_synthetic = 0 AND s.persistence = 0
        GROUP BY s.site_id
        LIMIT 1
    """)
    assert len(rows) > 0, "No real site with persistence=0 found"

    site = dict(rows[0])
    sites = [site]
    _attach_thermal_behavior(sites)

    s = sites[0]
    # Even though persistence=0 (no activity on last 5 passes), thermal behavior should show data
    assert s["detection_count"] > 0, "Should have detections even with persistence=0"
    assert s["active_pass_count"] > 0, "Should have active passes"
    assert s["frp_mean"] is not None, "Should have FRP mean"
    assert s["frp_last"] is not None, "Should have last FRP"

    print(f"PASS: test_sparse_observations_not_inactive -> {s['site_id']}: persistence={s['persistence']}, detections={s['detection_count']}, active_passes={s['active_pass_count']}")


def test_frp_statistics_locking():
    """Lock in formula for FRP mean, std, frp_last, and count calculations."""
    from app.routers.sites import _attach_thermal_behavior
    
    # 1. Single observation: mean=val, std=None
    mock_site_single = {"site_id": "MOCK-TG-001", "lat": 23.8, "lon": 86.4, "max_frp": 45.0}
    # Insert mock detection
    db.execute(
        "INSERT OR IGNORE INTO detections (id, latitude, longitude, bright_ti4, acq_date, acq_time, frp, is_synthetic, source, ingestion_batch) "
        "VALUES (99901, 23.8, 86.4, 340.0, '2026-09-01', '1200', 45.0, 1, 'test', 'test_batch_th')"
    )
    db.execute("INSERT OR IGNORE INTO sites (site_id, lat, lon) VALUES ('MOCK-TG-001', 23.8, 86.4)")
    db.execute("INSERT OR IGNORE INTO site_detections (site_id, detection_id) VALUES ('MOCK-TG-001', 99901)")

    sites = [mock_site_single]
    _attach_thermal_behavior(sites)
    s = sites[0]
    assert s["frp_mean"] == 45.0
    assert s["frp_std"] is None
    assert s["frp_last"] == 45.0
    assert s["detection_count"] == 1
    assert s["active_pass_count"] == 1

    # Cleanup
    db.execute("DELETE FROM site_detections WHERE site_id='MOCK-TG-001'")
    db.execute("DELETE FROM sites WHERE site_id='MOCK-TG-001'")
    db.execute("DELETE FROM detections WHERE ingestion_batch='test_batch_th'")


def test_expansion_magnitude_insufficient_dates():
    """Verify expansion magnitude returns None when dates < 2."""
    from app.routers.sites import _compute_expansion_magnitude
    assert _compute_expansion_magnitude(23.8, 86.4, "NON_EXISTENT_SITE") is None


def test_duty_cycle_and_consecutive_days_formulas():
    """Lock in duty cycle percentage and consecutive day streak formulas."""
    from app.classifier import _active_on_last_passes
    lat, lon = 23.8, 86.4
    rows = [
        {"latitude": 23.8, "longitude": 86.4, "acq_date": "2026-09-10"},
        {"latitude": 23.8, "longitude": 86.4, "acq_date": "2026-09-11"},
        {"latitude": 23.8, "longitude": 86.4, "acq_date": "2026-09-12"},
        {"latitude": 23.8, "longitude": 86.4, "acq_date": "2026-09-14"}, # gap on 13th
    ]
    pass_dates = ["2026-09-10", "2026-09-11", "2026-09-12", "2026-09-13", "2026-09-14"]
    dates_active, active_on_last5, max_consec = _active_on_last_passes(lat, lon, rows, pass_dates)
    
    assert len(dates_active) == 4
    assert active_on_last5 == 4
    assert max_consec == 3 # 10, 11, 12 is max streak of 3
    
    duty_cycle = (active_on_last5 / max(1, len(pass_dates[-5:]))) * 100.0
    assert duty_cycle == 80.0


def test_compute_thermal_dna_validates_contract():
    """Verify compute_thermal_dna validates against contracts.site.ThermalDNA."""
    from app.feature_utils import compute_thermal_dna
    from contracts.site import ThermalDNA

    # Test on non-existent site
    dna_empty = compute_thermal_dna("NON_EXISTENT_SITE_XYZ")
    assert dna_empty["typical_frp"] is None
    assert dna_empty["history_days"] == 0
    validated_empty = ThermalDNA.model_validate(dna_empty)
    assert validated_empty.stage_status == "live"
    assert validated_empty.mock is False

    # Test on existing site
    site_row = db.query("SELECT site_id FROM sites LIMIT 1")
    if site_row:
        sid = site_row[0]["site_id"]
        dna_site = compute_thermal_dna(sid)
        validated_site = ThermalDNA.model_validate(dna_site)
        assert validated_site.stage_status == "live"
        assert validated_site.mock is False
        if dna_site["history_days"] > 0:
            assert validated_site.median_frp is not None
            assert validated_site.typical_frequency is not None


if __name__ == "__main__":
    test_frp_intensity_boundaries()
    test_frp_trend_increasing()
    test_frp_trend_decreasing()
    test_frp_trend_stable()
    test_frp_trend_insufficient_data()
    test_thermal_behavior_real_site()
    test_thermal_behavior_demo_site()
    test_sparse_observations_not_inactive()
    test_frp_statistics_locking()
    test_expansion_magnitude_insufficient_dates()
    test_duty_cycle_and_consecutive_days_formulas()
    test_compute_thermal_dna_validates_contract()
    print("\n=== ALL THERMAL BEHAVIOR TESTS PASSED ===")