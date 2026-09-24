"""Phase 14: Demo Hardening Bug Fixes Tests."""
import os
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_static_imagery_serving():
    """Verify static imagery files under data/imagery are served cleanly by FastAPI."""
    imagery_dir = Path("data/imagery")
    if not imagery_dir.exists():
        imagery_dir.mkdir(parents=True, exist_ok=True)

    # Find or create a test imagery file
    test_subdir = imagery_dir / "test_site_phase14"
    test_subdir.mkdir(parents=True, exist_ok=True)
    test_file = test_subdir / "sample_chip.jpg"
    test_file.write_bytes(b"mock_jpeg_bytes")

    try:
        response = client.get("/data/imagery/test_site_phase14/sample_chip.jpg")
        assert response.status_code == 200
        assert response.content == b"mock_jpeg_bytes"
    finally:
        if test_file.exists():
            test_file.unlink()
        if test_subdir.exists():
            test_subdir.rmdir()


def test_vite_config_proxy_data():
    """Verify dashboard/vite.config.js proxies /data requests to backend."""
    vite_cfg = Path("dashboard/vite.config.js")
    assert vite_cfg.exists()
    content = vite_cfg.read_text(encoding="utf-8")
    assert '"/data"' in content or "'/data'" in content


def test_alert_click_to_locate_wiring():
    """Verify App.jsx wires alert-card click -> map flyTo + marker popup open."""
    app_jsx = Path("dashboard/src/App.jsx")
    assert app_jsx.exists()
    content = app_jsx.read_text(encoding="utf-8")

    # Handler exists and reads site coordinates from the alert payload
    assert "handleAlertClick" in content
    assert "alert.site.lat" in content
    assert "alert.site.lon" in content
    assert "setTargetLocation" in content

    # Map controller flies to the target
    assert "MapViewController" in content
    assert "flyTo" in content
    assert "<MapViewController" in content

    # Alert cards invoke the handler; markers keep refs for openPopup
    assert "onClick={() => handleAlertClick(a)}" in content
    assert "markerRefs" in content
    assert "openPopup" in content

    # Imagery thumbs normalize file_path so /data/... URLs resolve via proxy
    assert "img.file_path.startsWith" in content
    assert "imagery-thumb" in content


def test_alert_payload_includes_site_coords_for_locate():
    """Verify /api/alerts returns site.lat/lon required by click-to-locate."""
    from app.config import API_KEY

    response = client.get("/api/alerts", headers={"X-API-Key": API_KEY})
    assert response.status_code == 200
    alerts = response.json()
    assert len(alerts) >= 1

    with_coords = 0
    for a in alerts:
        site = a.get("site")
        if site and site.get("lat") is not None and site.get("lon") is not None:
            with_coords += 1
    assert with_coords >= 1, "no alert site has lat/lon for map locate"
