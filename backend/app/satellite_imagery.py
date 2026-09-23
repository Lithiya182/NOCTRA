"""Satellite Imagery Acquisition Subsystem (Sentinel-2 L2A via AWS Earth Search STAC API).

Fetches real Copernicus optical imagery for sites based on geographic coordinates (lat/lon)
and observation dates. Enforces strict provenance tracking and honest reporting of cloud-cover / no-clear-pass rates.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db
from .config import DATA_DIR, ROOT
from .provenance import Provenance, get_now_iso

log = logging.getLogger("thermalguard.satellite_imagery")

STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
IMAGERY_DIR = DATA_DIR / "imagery"


def fetch_stac_scene(
    lat: float,
    lon: float,
    target_date_str: str,
    window_days: int = 5,
    max_cloud_cover: float = 50.0,
) -> Optional[Dict[str, Any]]:
    """Query AWS Earth Search STAC API for Sentinel-2 L2A scenes around (lat, lon) within ±window_days of target_date_str.

    Returns dict with keys: scene_id, datetime, cloud_cover, thumbnail_url, status ('available' | 'no_clear_pass').
    """
    try:
        # Parse date string
        dt = datetime.fromisoformat(target_date_str.replace("Z", "+00:00"))
    except Exception:
        dt = datetime.now(timezone.utc)

    start_dt = dt - timedelta(days=window_days)
    end_dt = dt + timedelta(days=window_days)

    date_range = f"{start_dt.strftime('%Y-%m-%dT00:00:00Z')}/{end_dt.strftime('%Y-%m-%dT23:59:59Z')}"

    # Bounding box ~5km around lat/lon (approx 0.05 degrees)
    bbox = [
        round(lon - 0.05, 5),
        round(lat - 0.05, 5),
        round(lon + 0.05, 5),
        round(lat + 0.05, 5),
    ]

    payload = {
        "collections": ["sentinel-2-l2a"],
        "bbox": bbox,
        "datetime": date_range,
        "limit": 10,
    }

    req = urllib.request.Request(
        STAC_SEARCH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "NOCTRA-ThermalGuard/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as res:
            data = json.loads(res.read().decode("utf-8"))
            features = data.get("features", [])
    except Exception as exc:
        log.warning(f"STAC API request failed for ({lat}, {lon}): {exc}")
        return {
            "scene_id": None,
            "datetime": dt.strftime("%Y-%m-%d"),
            "cloud_cover": 100.0,
            "thumbnail_url": None,
            "status": "no_clear_pass",
            "error": str(exc),
        }

    if not features:
        return {
            "scene_id": None,
            "datetime": dt.strftime("%Y-%m-%d"),
            "cloud_cover": 100.0,
            "thumbnail_url": None,
            "status": "no_clear_pass",
            "error": "no_scenes_in_window",
        }

    # Sort features by cloud cover percentage ascending
    def get_cloud(feat):
        return feat.get("properties", {}).get("eo:cloud_cover", 100.0)

    features.sort(key=get_cloud)

    best = features[0]
    cloud_cover = float(get_cloud(best))
    scene_datetime = best.get("properties", {}).get("datetime", dt.strftime("%Y-%m-%d"))
    acquired_date = scene_datetime.split("T")[0]

    assets = best.get("assets", {})
    thumb_url = None
    if "thumbnail" in assets:
        thumb_url = assets["thumbnail"]["href"]
    elif "rendered_preview" in assets:
        thumb_url = assets["rendered_preview"]["href"]

    if cloud_cover <= max_cloud_cover and thumb_url:
        return {
            "scene_id": best.get("id"),
            "datetime": acquired_date,
            "cloud_cover": cloud_cover,
            "thumbnail_url": thumb_url,
            "status": "available",
        }
    else:
        return {
            "scene_id": best.get("id"),
            "datetime": acquired_date,
            "cloud_cover": cloud_cover,
            "thumbnail_url": None,
            "status": "no_clear_pass",
            "error": f"cloud_cover_{cloud_cover:.1f}_pct_exceeds_threshold",
        }


def download_imagery_chip(url: str, target_path: Path) -> bool:
    """Download image chip from URL to target_path on disk."""
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "NOCTRA-ThermalGuard/1.0"})
        with urllib.request.urlopen(req, timeout=15) as res, open(target_path, "wb") as f:
            f.write(res.read())
        return target_path.exists() and target_path.stat().st_size > 0
    except Exception as exc:
        log.warning(f"Failed to download imagery chip from {url}: {exc}")
        return False


def acquire_imagery_for_site(
    site_id: str,
    lat: float,
    lon: float,
    last_seen: str,
    is_synthetic: bool = False,
    max_cloud_cover: float = 50.0,
) -> Dict[str, Any]:
    """Acquire real Sentinel-2 satellite chip for a site and record in DB."""
    stac_res = fetch_stac_scene(lat, lon, last_seen, window_days=5, max_cloud_cover=max_cloud_cover)

    now_iso = get_now_iso()
    is_syn_val = 1 if is_synthetic else 0
    acquired_date = stac_res["datetime"]
    cloud_pct = stac_res["cloud_cover"]
    status = stac_res["status"]

    file_path_str = None
    if status == "available" and stac_res.get("thumbnail_url"):
        file_name = f"{acquired_date}.jpg"
        local_dir = IMAGERY_DIR / site_id
        local_path = local_dir / file_name
        rel_path = f"data/imagery/{site_id}/{file_name}"

        success = download_imagery_chip(stac_res["thumbnail_url"], local_path)
        if success:
            file_path_str = rel_path
        else:
            status = "no_clear_pass"

    # Check if record exists in imagery table
    existing = db.query("SELECT id FROM imagery WHERE site_id=? AND acquired_date=?", (site_id, acquired_date))
    if existing:
        db.execute(
            """
            UPDATE imagery SET source='sentinel2-l2a', cloud_cover_pct=?, file_path=?, is_synthetic=?, status=?, created_at=?
            WHERE site_id=? AND acquired_date=?
            """,
            (cloud_pct, file_path_str, is_syn_val, status, now_iso, site_id, acquired_date),
        )
    else:
        db.execute(
            """
            INSERT INTO imagery (site_id, acquired_date, source, cloud_cover_pct, file_path, is_synthetic, status, created_at)
            VALUES (?, ?, 'sentinel2-l2a', ?, ?, ?, ?, ?)
            """,
            (site_id, acquired_date, cloud_pct, file_path_str, is_syn_val, status, now_iso),
        )

    return {
        "site_id": site_id,
        "acquired_date": acquired_date,
        "cloud_cover_pct": cloud_pct,
        "file_path": file_path_str,
        "is_synthetic": is_syn_val,
        "status": status,
    }


def acquire_all_real_imagery(max_cloud_cover: float = 50.0) -> Dict[str, Any]:
    """Audit all real sites in DB, acquire Sentinel-2 imagery chips from STAC API, and store with provenance."""
    from .routers.sites import _attach_provenance

    site_rows = [dict(r) for r in db.query("SELECT * FROM sites")]
    _attach_provenance(site_rows)

    real_sites = [s for s in site_rows if not s.get("is_synthetic")]

    results = []
    available_count = 0
    no_clear_pass_count = 0
    total_cloud_pct = 0.0

    for site in real_sites:
        site_id = site["site_id"]
        lat = site["lat"]
        lon = site["lon"]
        last_seen = site.get("last_seen") or get_now_iso()

        res = acquire_imagery_for_site(site_id, lat, lon, last_seen, is_synthetic=False, max_cloud_cover=max_cloud_cover)
        results.append(res)

        total_cloud_pct += res["cloud_cover_pct"]
        if res["status"] == "available" and res["file_path"]:
            available_count += 1
        else:
            no_clear_pass_count += 1

    total_real = len(real_sites)
    avg_cloud = (total_cloud_pct / total_real) if total_real > 0 else 0.0
    no_clear_pass_rate = (no_clear_pass_count / total_real * 100.0) if total_real > 0 else 0.0

    return {
        "total_real_sites": total_real,
        "chips_acquired": available_count,
        "no_clear_pass_count": no_clear_pass_count,
        "no_clear_pass_rate_pct": round(no_clear_pass_rate, 2),
        "avg_cloud_cover_pct": round(avg_cloud, 2),
        "results": results,
    }
