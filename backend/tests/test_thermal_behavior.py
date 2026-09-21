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


if __name__ == "__main__":
    test_frp_intensity_boundaries()
    test_frp_trend_increasing()
    test_frp_trend_decreasing()
    test_frp_trend_stable()
    test_frp_trend_insufficient_data()
    test_thermal_behavior_real_site()
    test_thermal_behavior_demo_site()
    test_sparse_observations_not_inactive()
    print("\n=== ALL THERMAL BEHAVIOR TESTS PASSED ===")