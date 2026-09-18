"""Rule-based fire classifier — the guaranteed-working core (Section 3 of the PS).

Decision order is significant and matches the spec exactly:
1. industrial_fire   if <=500m from an industrial polygon AND persistence >= 3/5 passes
2. agricultural_burn if inside agri landuse AND short-lived AND in agri months
3. wildfire          if expanding cluster, frp > 50 MW, far from industrial/agri
4. other
"""
from __future__ import annotations

from dataclasses import dataclass

from haversine import haversine, Unit

from .config import (
    AGR_MAX_CONSEC_DAYS,
    AGR_MONTHS,
    CLUSTER_RADIUS_M,
    EXPANSION_RADIUS_M,
    IND_DIST_M,
    PERSISTENCE_MIN,
    WILDFIRE_DIST_M,
    WILDFIRE_FRP_MIN,
)
from .feature_utils import inside_polygon, nearest_polygon_dist

M = Unit.METERS

CLASSES = ("industrial_fire", "agricultural_burn", "wildfire", "other")


@dataclass
class ClassResult:
    classification: str
    confidence: float
    explanation: str
    features: dict


def _active_on_last_passes(
    lat: float, lon: float, rows: list[dict], pass_dates: list[str]
) -> tuple[set[str], int, int]:
    """Rows within ~1km of the site. Returns (dates active, active-on-last-5, max-consecutive-streak)."""
    nearby_dates: set[str] = set()
    for r in rows:
        if haversine((lat, lon), (r["latitude"], r["longitude"]), unit=M) <= CLUSTER_RADIUS_M:
            nearby_dates.add(r["acq_date"])
    last5 = pass_dates[-5:]
    active_on = len(nearby_dates & set(last5))

    # Compute maximum consecutive calendar-day streak anywhere in the observation window.
    # This matches the PS "short-lived" definition for agricultural burns.
    consec = 0
    current_streak = 0
    for d in sorted(pass_dates):
        if d in nearby_dates:
            current_streak += 1
            consec = max(consec, current_streak)
        else:
            current_streak = 0
    return nearby_dates, active_on, consec


def _cluster_expanded(lat: float, lon: float, rows: list[dict]) -> bool:
    """True if the detection cluster within EXPANSION_RADIUS_M grew (count + extent)
    between the previous and latest pass dates."""
    by_date: dict[str, list[tuple[float, float]]] = {}
    for r in rows:
        if haversine((lat, lon), (r["latitude"], r["longitude"]), unit=M) <= EXPANSION_RADIUS_M:
            by_date.setdefault(r["acq_date"], []).append((r["latitude"], r["longitude"]))
    if len(by_date) < 2:
        return False
    dates = sorted(by_date)
    prev, curr = dates[-2], dates[-1]

    def stats(pts: list[tuple[float, float]]) -> tuple[int, float]:
        n = len(pts)
        if n <= 1:
            return n, 0.0
        best = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                best = max(best, haversine(pts[i], pts[j], unit=M))
        return n, best

    nc, ext_c = stats(by_date[curr])
    np_, ext_p = stats(by_date[prev])
    return nc > np_ and ext_c > ext_p


def severity_for_frp(frp: float) -> str:
    if frp >= 100:
        return "extreme"
    if frp >= 40:
        return "severe"
    if frp >= 15:
        return "moderate"
    return "minor"


def classify(
    lat: float, lon: float, rows: list[dict], polys: list[dict],
    pass_dates: list[str], month: int, max_frp: float, max_brightness: float,
) -> ClassResult:
    """Classify a site at (lat, lon) using all detections `rows` and OSM `polys`."""
    nearby, active_on, consec = _active_on_last_passes(lat, lon, rows, pass_dates)
    duty_cycle = (active_on / max(1, len(pass_dates[-5:]))) * 100.0

    d_ind = nearest_polygon_dist(lat, lon, polys, "industrial")
    d_agri = nearest_polygon_dist(lat, lon, polys, "agricultural")
    d_res = nearest_polygon_dist(lat, lon, polys, "residential")
    in_agri = inside_polygon(lat, lon, polys, "agricultural")
    expanded = _cluster_expanded(lat, lon, rows)

    features = {
        "frp": max_frp,
        "brightness": max_brightness,
        "month": month,
        "d_industrial": d_ind,
        "d_agri": d_agri,
        "d_residential": d_res,
        "duty_cycle_pct": duty_cycle,
        "persistence": active_on,
        "consec_days": consec,
        "cluster_expanded": expanded,
    }

    # Rule 1: industrial
    if d_ind <= IND_DIST_M and active_on >= PERSISTENCE_MIN:
        conf = min(0.99, 0.80 + 0.03 * (active_on - PERSISTENCE_MIN))
        expl = (
            f"Within {d_ind:.0f}m of an industrial polygon; active on {active_on} of "
            f"last 5 passes (persistent burn/flare)."
        )
        return ClassResult("industrial_fire", round(conf, 2), expl, features)

    # Rule 2: agricultural burn
    if in_agri and consec <= AGR_MAX_CONSEC_DAYS and month in AGR_MONTHS:
        expl = (
            f"Inside agricultural landuse and burned only {consec} consecutive day(s) "
            f"in month {month:02d} (short stubble-season burst)."
        )
        return ClassResult("agricultural_burn", 0.75, expl, features)

    # Rule 3: wildfire
    if expanded and max_frp > WILDFIRE_FRP_MIN and min(d_ind, d_agri) > WILDFIRE_DIST_M:
        conf = min(0.95, 0.70 + max_frp / 400.0)
        expl = (
            f"Cluster footprint expanded day-over-day with frp {max_frp:.1f} MW and no "
            f"industrial/agricultural polygon within 500m -> spreading vegetation fire."
        )
        return ClassResult("wildfire", round(conf, 2), expl, features)

    # Rule 4: other
    expl = (
        f"No rule matched (d_industrial={d_ind:.0f}m, d_agri={d_agri:.0f}m, "
        f"persistence={active_on}/5, frp={max_frp:.1f} MW, expanded={expanded})."
    )
    return ClassResult("other", 0.40, expl, features)


def feature_vector(result_feats: dict) -> list[float]:
    return [
        result_feats["frp"],
        result_feats["brightness"],
        result_feats["month"],
        min(result_feats["d_industrial"], 20_000),
        min(result_feats["d_agri"], 20_000),
        min(result_feats["d_residential"], 20_000),
        result_feats["duty_cycle_pct"],
    ]