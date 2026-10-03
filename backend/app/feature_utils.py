"""Spatial and thermal feature helpers (no GIS extension required)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import statistics
from typing import Optional

from haversine import Unit, haversine

from . import db
from .config import OSM_GEOJSON

M = Unit.METERS


def dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres between (lat, lon) pairs."""
    return haversine(a, b, unit=M)


def point_in_polygon(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test (planar approximation; fine at this scale).
    
    Args:
        lat: Point latitude
        lon: Point longitude
        ring: Polygon ring as list of (lat, lon) tuples
    """
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        lat_i, lon_i = ring[i]
        lat_j, lon_j = ring[j]
        # Check if ray crosses edge
        if ((lat_i > lat) != (lat_j > lat)) and (
            lon < (lon_j - lon_i) * (lat - lat_i) / (lat_j - lat_i) + lon_i
        ):
            inside = not inside
        j = i
    return inside


def _sample_ring(ring: list[tuple[float, float]], step_m: float = 150.0) -> list[tuple[float, float]]:
    """Densify a polygon ring into points ~step_m apart so haversine gives good
    point-to-boundary distances."""
    pts: list[tuple[float, float]] = []
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        d = dist_m(a, b)
        steps = max(1, int(math.ceil(d / step_m)))
        for k in range(steps):
            t = k / steps
            pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return pts


def distance_to_polygon(
    lat: float, lon: float, ring: list[tuple[float, float]]
) -> float:
    """Distance in metres from a point to a polygon: 0 if inside, else distance to
    the densified boundary."""
    if point_in_polygon(lat, lon, ring):
        return 0.0
    return min(dist_m((lat, lon), p) for p in _sample_ring(ring))


def load_polygons(path: Path | str = OSM_GEOJSON) -> list[dict]:
    """Load OSM seed polygons -> [{kind, name, ring: [(lat, lon), ...]}].
    Source GeoJSON uses standard [lon, lat] ordering (CRS84).
    Converts to internal (lat, lon) representation."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    polys = []
    for feature in raw.get("features", []):
        geom = feature.get("geometry", {})
        ring_coords = geom.get("coordinates", [[]])[0]  # standard [lon, lat] ordering
        # Convert from [lon, lat] to (lat, lon) for internal use
        ring = [(pt[1], pt[0]) for pt in ring_coords if len(pt) >= 2]
        if len(ring) >= 3:
            polys.append({
                "kind": feature.get("properties", {}).get("kind", "other"),
                "name": feature.get("properties", {}).get("name", ""),
                "ring": ring,
            })
    return polys


def nearest_polygon_dist(
    lat: float, lon: float, polys: list[dict], kind: str
) -> float:
    """Minimum distance to any polygon of the given kind (large if none present)."""
    candidates = [p for p in polys if p["kind"] == kind]
    if not candidates:
        return 999_999.0
    return min(distance_to_polygon(lat, lon, p["ring"]) for p in candidates)


def inside_polygon(lat: float, lon: float, polys: list[dict], kind: str) -> bool:
    return any(
        point_in_polygon(lat, lon, p["ring"]) for p in polys if p["kind"] == kind
    )


# --- Thermal & Temporal Behavior Indicators (moved from routers/sites.py) ---

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
        for p_lat, p_lon in pts:
            x = haversine((centroid_lat, centroid_lon), (centroid_lat, p_lon), unit=M)
            y = haversine((centroid_lat, centroid_lon), (p_lat, centroid_lon), unit=M)
            if p_lon < centroid_lon:
                x = -x
            if p_lat < centroid_lat:
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
            for p_lat, p_lon in by_date[dt]:
                if haversine((lat, lon), (p_lat, p_lon), unit=M) <= EXPANSION_RADIUS_M:
                    pts.append((p_lat, p_lon))
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


def compute_thermal_dna(site_id: str) -> dict:
    """Compute ThermalDNA behavioral fingerprint from detections for a site.
    Returns exactly the fields of contracts/site.py ThermalDNA.
    """
    det_rows = db.query(
        """
        SELECT d.frp, d.acq_date, d.acq_time
        FROM detections d
        JOIN site_detections sd ON d.id = sd.detection_id
        WHERE sd.site_id = ?
        ORDER BY d.acq_date, d.acq_time
        """,
        (site_id,),
    )
    if not det_rows:
        return {
            "typical_frp": None,
            "median_frp": None,
            "variability": None,
            "typical_frequency": None,
            "active_hours": None,
            "typical_duration": None,
            "history_days": 0,
            "stage_status": "live",
            "mock": False,
        }

    frp_values = [float(d["frp"]) for d in det_rows if d["frp"] is not None]
    dates = sorted(set(d["acq_date"] for d in det_rows if d["acq_date"]))

    med_frp = round(float(statistics.median(frp_values)), 2) if frp_values else None
    var_frp = round(float(statistics.stdev(frp_values)), 2) if len(frp_values) >= 2 else 0.0

    # History span in days from first to last observed date
    if len(dates) >= 2:
        d_start = datetime.strptime(dates[0], "%Y-%m-%d").date()
        d_end = datetime.strptime(dates[-1], "%Y-%m-%d").date()
        history_days = (d_end - d_start).days + 1
    else:
        history_days = len(dates)

    # Typical frequency: detections per active pass day
    typ_freq = round(len(det_rows) / max(1, len(dates)), 2)

    # Active hours extracted from UTC acq_time (e.g. '1340' -> 13)
    active_hrs = sorted(set(
        int(str(d["acq_time"])[:2])
        for d in det_rows
        if d["acq_time"] and len(str(d["acq_time"])) >= 2 and str(d["acq_time"])[:2].isdigit()
    )) or None

    # Typical duration: average streak of consecutive active days
    streaks: list[int] = []
    if dates:
        dt_objs = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
        curr_len = 1
        for j in range(1, len(dt_objs)):
            if (dt_objs[j] - dt_objs[j - 1]).days == 1:
                curr_len += 1
            else:
                streaks.append(curr_len)
                curr_len = 1
        streaks.append(curr_len)
        typ_duration = round(float(statistics.mean(streaks)), 1)
    else:
        typ_duration = None

    return {
        "typical_frp": med_frp,
        "median_frp": med_frp,
        "variability": var_frp,
        "typical_frequency": typ_freq,
        "active_hours": active_hrs,
        "typical_duration": typ_duration,
        "history_days": history_days,
        "stage_status": "live",
        "mock": False,
    }