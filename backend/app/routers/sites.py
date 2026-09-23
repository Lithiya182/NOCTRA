from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException

from .. import db, ml_model
from ..models import ImageryOut, SiteRow

router = APIRouter(prefix="/api/sites", tags=["sites"])

# Coverage threshold: days after last pass to consider coverage uncertain
COVERAGE_GAP_DAYS = 2
# Expected revisit days (VIIRS ~daily, but allow some margin)
EXPECTED_REVISIT_DAYS = 1

# FRP Intensity thresholds (MW)
FRP_INTENSITY_BANDS = [
    (100, "very-high"),
    (50, "high"),
    (20, "high-moderate"),
    (5, "moderate"),
    (0, "weak"),
]


def _frp_intensity(frp: float) -> str:
    """Classify FRP into intensity bands."""
    for threshold, label in FRP_INTENSITY_BANDS:
        if frp >= threshold:
            return label
    return "weak"


def _compute_frp_trend(frp_values: list[float]) -> str:
    """Determine FRP trend from chronological values.
    Returns: increasing, decreasing, stable, insufficient_data
    """
    if len(frp_values) < 3:
        return "insufficient_data"
    # Split into recent (last half) vs earlier (first half)
    mid = len(frp_values) // 2
    earlier = frp_values[:mid]
    recent = frp_values[mid:]
    if not earlier or not recent:
        return "insufficient_data"
    earlier_mean = statistics.mean(earlier)
    recent_mean = statistics.mean(recent)
    # Use 20% relative change as threshold for trend
    if recent_mean > earlier_mean * 1.2:
        return "increasing"
    if recent_mean < earlier_mean * 0.8:
        return "decreasing"
    return "stable"


def _compute_expansion_magnitude(lat: float, lon: float, site_id: str) -> float | None:
    """Compute cluster expansion magnitude in km² if data supports it.
    Uses convex hull area of detections within EXPANSION_RADIUS_M (4000m)
    comparing first half vs second half of pass dates.
    Returns None if insufficient data.
    """
    from haversine import haversine, Unit
    M = Unit.METERS
    EXPANSION_RADIUS_M = 4000

    # Get all detections for this site with coordinates and dates
    det_rows = db.query(
        """
        SELECT d.latitude, d.longitude, d.acq_date
        FROM detections d
        JOIN site_detections sd ON d.id = sd.detection_id
        WHERE sd.site_id = ?
        ORDER BY d.acq_date, d.acq_time
        """,
        (site_id,),
    )
    if not det_rows:
        return None

    # Group by pass date
    by_date: dict[str, list[tuple[float, float]]] = {}
    for d in det_rows:
        by_date.setdefault(d["acq_date"], []).append((d["latitude"], d["longitude"]))

    dates = sorted(by_date.keys())
    if len(dates) < 2:
        return None

    # Split dates into first half and second half
    mid = len(dates) // 2
    first_half_dates = dates[:mid]
    second_half_dates = dates[mid:]

    def convex_hull_area(pts: list[tuple[float, float]]) -> float:
        """Compute convex hull area in km² using Graham scan + shoelace formula."""
        if len(pts) < 3:
            return 0.0
        # Convert to local flat projection around centroid for area calc
        centroid_lat = sum(p[0] for p in pts) / len(pts)
        centroid_lon = sum(p[1] for p in pts) / len(pts)
        # Simple flat projection (valid for small areas < 4km)
        local_pts = []
        for lat, lon in pts:
            x = haversine((centroid_lat, centroid_lon), (centroid_lat, lon), unit=M)
            y = haversine((centroid_lat, centroid_lon), (lat, centroid_lon), unit=M)
            if lon < centroid_lon:
                x = -x
            if lat < centroid_lat:
                y = -y
            local_pts.append((x, y))

        # Graham scan for convex hull
        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        pts_sorted = sorted(local_pts)
        lower = []
        for p in pts_sorted:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)
        upper = []
        for p in reversed(pts_sorted):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)
        hull = lower[:-1] + upper[:-1]
        if len(hull) < 3:
            return 0.0

        # Shoelace formula
        area = 0.0
        for i in range(len(hull)):
            j = (i + 1) % len(hull)
            area += hull[i][0] * hull[j][1] - hull[j][0] * hull[i][1]
        return abs(area) / 2.0 / 1_000_000.0  # Convert m² to km²

    # Collect points within EXPANSION_RADIUS_M for each half
    def collect_pts(date_list: list[str]) -> list[tuple[float, float]]:
        pts = []
        for dt in date_list:
            for lat, lon in by_date[dt]:
                if haversine((lat, lon), (lat, lon), unit=M) <= EXPANSION_RADIUS_M:
                    pts.append((lat, lon))
        return pts

    first_pts = collect_pts(first_half_dates)
    second_pts = collect_pts(second_half_dates)

    if len(first_pts) < 3 or len(second_pts) < 3:
        return None

    area_first = convex_hull_area(first_pts)
    area_second = convex_hull_area(second_pts)

    return max(0.0, area_second - area_first)


def _attach_thermal_behavior(sites: list[dict]) -> None:
    """Attach thermal behavior indicators computed from detection data."""
    if not sites:
        return

    for s in sites:
        site_id = s["site_id"]
        lat = s["lat"]
        lon = s["lon"]

        # Get all detections for this site chronologically
        det_rows = db.query(
            """
            SELECT d.frp, d.latitude, d.longitude, d.acq_date, d.acq_time
            FROM detections d
            JOIN site_detections sd ON d.id = sd.detection_id
            WHERE sd.site_id = ?
            ORDER BY d.acq_date, d.acq_time
            """,
            (site_id,),
        )

        if not det_rows:
            s["frp_mean"] = None
            s["frp_std"] = None
            s["frp_last"] = None
            s["frp_trend"] = "insufficient_data"
            s["detection_count"] = 0
            s["active_pass_count"] = 0
            s["days_span"] = 0
            s["expansion_magnitude"] = None
            s["frp_intensity"] = "weak"
            continue

        frp_values = [d["frp"] for d in det_rows]
        dates = [d["acq_date"] for d in det_rows]

        # Basic statistics
        s["frp_mean"] = round(statistics.mean(frp_values), 2) if len(frp_values) >= 1 else None
        s["frp_std"] = round(statistics.stdev(frp_values), 2) if len(frp_values) >= 2 else None
        s["frp_last"] = round(frp_values[-1], 2)
        s["frp_trend"] = _compute_frp_trend(frp_values)
        s["detection_count"] = len(det_rows)
        s["active_pass_count"] = len(set(dates))
        s["days_span"] = len(set(dates))  # distinct pass dates

        # FRP intensity based on max_frp (site-level max)
        max_frp = s.get("max_frp", max(frp_values) if frp_values else 0)
        s["frp_intensity"] = _frp_intensity(max_frp)

        # Expansion magnitude
        s["expansion_magnitude"] = _compute_expansion_magnitude(lat, lon, site_id)


def _get_site_coverage(site_id: str) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """Get site-specific last pass date, days since, and next expected pass date.
    Returns (last_pass_date, days_since_last_pass, next_expected_pass_date).
    """
    row = db.query(
        """
        SELECT MAX(d.acq_date) as last_pass
        FROM detections d
        JOIN site_detections sd ON d.id = sd.detection_id
        WHERE sd.site_id = ? AND d.is_synthetic = 0
        """,
        (site_id,),
    )
    if not row or not row[0]["last_pass"]:
        return None, None, None
    last_pass_str = row[0]["last_pass"]
    try:
        last_pass = date.fromisoformat(last_pass_str)
        today = datetime.now(timezone.utc).date()
        days_since = (today - last_pass).days
        # Next expected pass is based on revisit cycle
        next_expected = last_pass + timedelta(days=EXPECTED_REVISIT_DAYS)
        next_expected_str = next_expected.isoformat()
        return last_pass_str, days_since, next_expected_str
    except Exception:
        return last_pass_str, None, None


def _attach_coverage(sites: list[dict]) -> None:
    """Attach coverage status to each site based on its own detection history."""
    for s in sites:
        site_id = s["site_id"]
        last_pass_date, days_since, next_expected = _get_site_coverage(site_id)
        
        if last_pass_date is None:
            s["coverage_status"] = "unknown"
            s["last_pass_date"] = None
            s["days_since_last_pass"] = None
            s["next_expected_pass_date"] = None
        else:
            s["last_pass_date"] = last_pass_date
            s["days_since_last_pass"] = days_since
            s["next_expected_pass_date"] = next_expected
            if days_since is not None and days_since > COVERAGE_GAP_DAYS:
                s["coverage_status"] = "uncertain"
            else:
                s["coverage_status"] = "covered"


def _to_row(r: dict) -> SiteRow:
    r = dict(r)
    r["is_anomalous"] = bool(r["is_anomalous"])
    r["ml_prediction"] = ml_model.predict(r)
    from .. import cnn_visual
    pred, conf = cnn_visual.predict_visual(r["site_id"])
    r["cnn_prediction"] = pred
    r["cnn_confidence"] = conf
    return SiteRow(**r)


def _attach_provenance(sites: list[dict]) -> None:
    """Attach is_synthetic and source fields based on detections.
    Three-way: Real-only (no synthetic), Demo-only (no real), Mixed (both).
    """
    if not sites:
        return
    site_ids = [s["site_id"] for s in sites]
    placeholders = ",".join("?" * len(site_ids))
    rows = db.query(
        f"""
        SELECT s.site_id,
               MIN(d.is_synthetic) as has_real,
               MAX(d.is_synthetic) as has_synthetic,
               GROUP_CONCAT(DISTINCT d.source) as sources
        FROM sites s
        JOIN site_detections sd ON s.site_id = sd.site_id
        JOIN detections d ON sd.detection_id = d.id
        WHERE s.site_id IN ({placeholders})
        GROUP BY s.site_id
        """,
        tuple(site_ids),
    )
    prov_map = {}
    for r in rows:
        has_real = r["has_real"] == 0
        has_synthetic = r["has_synthetic"] == 1
        if has_real and has_synthetic:
            is_syn, src = True, "synthetic,firms"  # Mixed → is_synthetic=True for badge logic
        elif has_real:
            is_syn, src = False, "firms"
        else:
            is_syn, src = True, "synthetic"
        prov_map[r["site_id"]] = {"is_synthetic": is_syn, "source": src}
    for s in sites:
        prov = prov_map.get(s["site_id"], {"is_synthetic": True, "source": "synthetic"})
        s["is_synthetic"] = prov["is_synthetic"]
        s["source"] = prov["source"]


@router.get("", response_model=list[SiteRow])
def list_sites(classification: str | None = None,
               severity: str | None = None,
               status: str | None = None) -> list[SiteRow]:
    sql = "SELECT * FROM sites WHERE 1=1"
    params: list = []
    if classification:
        sql += " AND classification=?"
        params.append(classification)
    if severity:
        sql += " AND severity=?"
        params.append(severity)
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY last_seen DESC"
    rows = [dict(r) for r in db.query(sql, tuple(params))]
    _attach_provenance(rows)
    _attach_coverage(rows)
    _attach_thermal_behavior(rows)
    return [_to_row(r) for r in rows]


@router.get("/{site_id}", response_model=SiteRow)
def get_site(site_id: str) -> SiteRow:
    rows = db.query("SELECT * FROM sites WHERE site_id=?", (site_id,))
    if not rows:
        raise HTTPException(404, "site not found")
    row = dict(rows[0])
    _attach_provenance([row])
    _attach_coverage([row])
    _attach_thermal_behavior([row])
    return _to_row(row)


@router.get("/{site_id}/imagery", response_model=list[ImageryOut])
def get_site_imagery(site_id: str) -> list[ImageryOut]:
    """Retrieve acquired satellite optical imagery chips for a site."""
    site_rows = db.query("SELECT site_id FROM sites WHERE site_id=?", (site_id,))
    if not site_rows:
        raise HTTPException(404, "site not found")
    rows = db.query("SELECT * FROM imagery WHERE site_id=? ORDER BY acquired_date DESC", (site_id,))
    return [dict(r) for r in rows]