"""Rule-based fire classifier — the guaranteed-working core (Section 3 of the PS).

Decision order is significant and matches the spec exactly:
1. industrial_fire   if inside industrial polygon OR (within 500m of industrial polygon AND sufficient temporal evidence)
2. agricultural_burn if inside agri landuse AND short-lived AND in agri months
3. wildfire          if expanding cluster, frp > 50 MW, far from industrial/agri
4. other

Evidence-aware classification:
- Polygon containment is strong spatial evidence for industrial_fire
- Proximity is supporting evidence, requires temporal evidence
- Insufficient temporal evidence prevents proximity-based classification
- FRP intensity is separate from fire type
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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

# Minimum observation days for sufficient temporal evidence
MIN_TEMPORAL_EVIDENCE_DAYS = 3

# Evidence types
SpatialEvidence = Literal["polygon_containment", "proximity", "none"]
TemporalEvidence = Literal["persistent", "sufficient", "insufficient"]
IntensityEvidence = Literal["weak", "moderate", "high-moderate", "high", "very-high"]
VisualEvidence = Literal["corroborating", "conflicting", "uninformative", "none"]
EvidenceSufficiency = Literal["sufficient", "insufficient", "conflicting"]


@dataclass
class Evidence:
    """Human-readable evidence for classification decision."""
    spatial: SpatialEvidence
    temporal: TemporalEvidence
    intensity: IntensityEvidence
    sufficiency: EvidenceSufficiency
    reason: str
    visual: VisualEvidence = "none"


@dataclass
class ClassResult:
    classification: str
    confidence: float
    explanation: str
    features: dict
    evidence: Evidence = field(default_factory=lambda: Evidence(
        spatial="none", temporal="insufficient", intensity="weak",
        sufficiency="insufficient", reason="No evidence evaluated", visual="none"
    ))


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


def _frp_intensity(frp: float) -> IntensityEvidence:
    """Classify FRP into intensity bands (separate from fire type)."""
    if frp >= 100:
        return "very-high"
    if frp >= 50:
        return "high"
    if frp >= 20:
        return "high-moderate"
    if frp >= 5:
        return "moderate"
    return "weak"


def _temporal_evidence(active_on: int, observation_days: int) -> tuple[TemporalEvidence, str]:
    """Determine temporal evidence and reason.
    
    Returns:
        (temporal_evidence, reason)
    """
    if active_on >= 3:
        return "persistent", f"Active on {active_on}/5 recent passes (persistent)"
    if observation_days >= 3:
        return "sufficient", f"{observation_days} observation days (sufficient temporal evidence)"
    return "insufficient", f"Only {observation_days} observation day(s) — insufficient temporal evidence"


def _spatial_evidence(d_ind: float) -> tuple[SpatialEvidence, str]:
    """Determine spatial evidence and reason."""
    if d_ind == 0.0:
        return "polygon_containment", "Inside industrial polygon (strong spatial evidence)"
    if d_ind <= IND_DIST_M:
        return "proximity", f"Within {d_ind:.0f}m of industrial polygon (proximity evidence)"
    return "none", f"No industrial spatial evidence (nearest: {d_ind:.0f}m)"


def classify(
    lat: float, lon: float, rows: list[dict], polys: list[dict],
    pass_dates: list[str], month: int, max_frp: float, max_brightness: float,
) -> ClassResult:
    """Classify a site at (lat, lon) using all detections `rows` and OSM `polys`.
    
    Evidence-aware classification:
    - Polygon containment (0m, inside) -> strong spatial evidence for industrial_fire
    - Proximity (<=500m) -> supporting evidence, requires temporal evidence
    - Insufficient temporal evidence -> prevents proximity-based classification
    - FRP intensity is separate from fire type
    """
    nearby, active_on, consec = _active_on_last_passes(lat, lon, rows, pass_dates)
    duty_cycle = (active_on / max(1, len(pass_dates[-5:]))) * 100.0

    d_ind = nearest_polygon_dist(lat, lon, polys, "industrial")
    d_agri = nearest_polygon_dist(lat, lon, polys, "agricultural")
    d_res = nearest_polygon_dist(lat, lon, polys, "residential")
    in_agri = inside_polygon(lat, lon, polys, "agricultural")
    in_industrial = inside_polygon(lat, lon, polys, "industrial")
    expanded = _cluster_expanded(lat, lon, rows)

    # Temporal evidence
    observation_days = len(set(r["acq_date"] for r in rows if haversine((lat, lon), (r["latitude"], r["longitude"]), unit=M) <= CLUSTER_RADIUS_M))
    temporal_evidence, temporal_reason = _temporal_evidence(active_on, observation_days)

    # Spatial evidence
    spatial_evidence, spatial_reason = _spatial_evidence(d_ind)

    # Intensity evidence (separate from fire type)
    intensity_evidence = _frp_intensity(max_frp)

    # --- Rule 1: industrial_fire ---
    # Strong evidence: polygon containment (inside industrial polygon)
    # Supporting evidence: proximity (<=500m) + sufficient temporal evidence
    in_industrial_polygon = in_industrial or d_ind == 0.0
    proximity_to_industrial = d_ind <= IND_DIST_M
    sufficient_temporal = observation_days >= MIN_TEMPORAL_EVIDENCE_DAYS or active_on >= PERSISTENCE_MIN

    evidence_sufficiency: EvidenceSufficiency = "insufficient"
    classification = "other"
    confidence = 0.40
    explanation = ""
    spatial: SpatialEvidence = "none"
    temporal: TemporalEvidence = "insufficient"
    intensity: IntensityEvidence = _frp_intensity(max_frp)
    reason = ""

    # Rule 1: industrial_fire
    if in_industrial_polygon:
        # Strong evidence: polygon containment
        spatial = "polygon_containment"
        temporal = "persistent" if active_on >= PERSISTENCE_MIN else ("sufficient" if observation_days >= MIN_TEMPORAL_EVIDENCE_DAYS else "insufficient")
        evidence_sufficiency = "sufficient"
        classification = "industrial_fire"
        confidence = 0.90
        reason = f"Inside industrial polygon (strong spatial evidence). {_temporal_evidence(active_on, observation_days)[1]}"
    elif proximity_to_industrial and sufficient_temporal:
        # Supporting evidence: proximity + temporal evidence
        spatial = "proximity"
        temporal = "persistent" if active_on >= PERSISTENCE_MIN else "sufficient"
        evidence_sufficiency = "sufficient"
        classification = "industrial_fire"
        confidence = 0.80
        reason = f"Within {d_ind:.0f}m of industrial polygon with {active_on}/5 recent passes ({_temporal_evidence(active_on, observation_days)[1]})"
    elif proximity_to_industrial and not sufficient_temporal:
        # Proximity without temporal evidence
        spatial = "proximity"
        temporal = "insufficient"
        evidence_sufficiency = "insufficient"
        classification = "other"
        confidence = 0.40
        reason = f"Within {d_ind:.0f}m of industrial polygon but insufficient temporal evidence ({observation_days} observation day(s)). Need {MIN_TEMPORAL_EVIDENCE_DAYS}+ days or {PERSISTENCE_MIN}+ active passes."
    else:
        # No industrial spatial evidence
        spatial = "none"
        temporal = "insufficient"
        evidence_sufficiency = "insufficient"

    # Rule 2: agricultural_burn (unchanged logic, just add evidence)
    if classification == "other" and in_agri and consec <= AGR_MAX_CONSEC_DAYS and month in AGR_MONTHS:
        classification = "agricultural_burn"
        confidence = 0.75
        spatial = "polygon_containment" if in_agri else "none"
        temporal = "sufficient" if observation_days >= MIN_TEMPORAL_EVIDENCE_DAYS else "insufficient"
        reason = f"Inside agricultural landuse, {consec} consecutive day(s) in month {month:02d} (agricultural season)."
        evidence_sufficiency = "sufficient" if observation_days >= MIN_TEMPORAL_EVIDENCE_DAYS else "insufficient"

    # Rule 3: wildfire (unchanged threshold)
    if classification == "other" and expanded and max_frp > WILDFIRE_FRP_MIN and min(d_ind, d_agri) > WILDFIRE_DIST_M:
        classification = "wildfire"
        confidence = min(0.95, 0.70 + max_frp / 400.0)
        spatial = "expansion"
        temporal = "sufficient" if observation_days >= MIN_TEMPORAL_EVIDENCE_DAYS else "insufficient"
        reason = f"Cluster expanded day-over-day, FRP {max_frp:.1f} MW, far from industrial/agricultural."
        evidence_sufficiency = "sufficient" if observation_days >= MIN_TEMPORAL_EVIDENCE_DAYS else "insufficient"

    # Rule 4: other (default)
    if classification == "other":
        if not sufficient_temporal and proximity_to_industrial:
            reason = f"Within {d_ind:.0f}m of industrial polygon but insufficient temporal evidence ({observation_days} observation day(s), {active_on}/5 active passes)."
        elif not proximity_to_industrial and not in_agri:
            reason = f"No spatial evidence (nearest industrial: {d_ind:.0f}m, nearest agricultural: {d_agri:.0f}m), insufficient temporal evidence."
        elif in_agri and month not in AGR_MONTHS:
            reason = f"Inside agricultural landuse but month {month:02d} not in agricultural season (Apr, May, Oct, Nov)."
        elif in_agri and consec > AGR_MAX_CONSEC_DAYS:
            reason = f"Inside agricultural landuse but {consec} consecutive days exceeds agricultural burn threshold ({AGR_MAX_CONSEC_DAYS})."
        elif expanded and max_frp <= WILDFIRE_FRP_MIN:
            reason = f"Cluster expanded but FRP {max_frp:.1f} MW below wildfire threshold ({WILDFIRE_FRP_MIN} MW)."
        elif expanded and min(d_ind, d_agri) <= WILDFIRE_DIST_M:
            reason = f"Cluster expanded but near industrial/agricultural polygon (d_ind={d_ind:.0f}m, d_agri={d_agri:.0f}m)."
        else:
            reason = f"No rule matched (d_ind={d_ind:.0f}m, d_agri={d_agri:.0f}m, persistence={active_on}/5, frp={max_frp:.1f}, expanded={expanded})."
        evidence_sufficiency = "insufficient"

    # Build evidence object
    evidence = Evidence(
        spatial=spatial,
        temporal=temporal,
        intensity=_frp_intensity(max_frp),
        sufficiency=evidence_sufficiency,
        reason=reason,
    )

    # Add evidence to features
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
        "observation_days": observation_days,
        "in_industrial_polygon": in_industrial,
        "in_agri_polygon": in_agri,
    }

    return ClassResult(
        classification=classification,
        confidence=round(confidence, 2),
        explanation=reason,
        features=features,
        evidence=evidence,
    )


def feature_vector(result_feats: dict) -> list[float]:
    d_ind = result_feats.get("d_industrial")
    d_ag = result_feats.get("d_agri")
    d_res = result_feats.get("d_residential")
    return [
        result_feats.get("frp", 0.0) or 0.0,
        result_feats.get("brightness", 0.0) or 0.0,
        result_feats.get("month", 1) or 1,
        min(d_ind if d_ind is not None else 20_000, 20_000),
        min(d_ag if d_ag is not None else 20_000, 20_000),
        min(d_res if d_res is not None else 20_000, 20_000),
        result_feats.get("duty_cycle_pct", 0.0) or 0.0,
    ]


def fuse_evidence(
    class_result: ClassResult,
    cnn_prediction: str | None = None,
    cnn_confidence: float | None = None,
    has_imagery: bool = False,
) -> ClassResult:
    """Fuse rule-based thermal evidence with visual (Phase 8 CV) evidence.
    
    Rule-based thermal classification remains authoritative.
    Visual evidence cautiously adjusts evidence sufficiency and reason:
    - No imagery or no CNN prediction -> visual="none", thermal-only fallback.
    - CNN prediction agrees with thermal classification -> visual="corroborating".
    - CNN prediction disagrees with thermal classification -> visual="conflicting", sufficiency="conflicting", flagged for human review.
    """
    orig_ev = class_result.evidence

    if not has_imagery or cnn_prediction is None:
        fused_ev = Evidence(
            spatial=orig_ev.spatial,
            temporal=orig_ev.temporal,
            intensity=orig_ev.intensity,
            sufficiency=orig_ev.sufficiency,
            reason=orig_ev.reason,
            visual="none",
        )
        return ClassResult(
            classification=class_result.classification,
            confidence=class_result.confidence,
            explanation=orig_ev.reason,
            features=class_result.features,
            evidence=fused_ev,
        )

    thermal_class = class_result.classification
    conf_val = f" (conf: {cnn_confidence:.2f})" if cnn_confidence is not None else ""

    if cnn_prediction == thermal_class:
        visual_status: VisualEvidence = "corroborating"
        sufficiency_status: EvidenceSufficiency = orig_ev.sufficiency
        if thermal_class != "other":
            fused_reason = f"{orig_ev.reason}; Visual evidence corroborates thermal classification (CNN: {cnn_prediction}{conf_val})."
        else:
            fused_reason = f"{orig_ev.reason}; Visual evidence corroborates non-fire classification."
    else:
        visual_status = "conflicting"
        sufficiency_status = "conflicting"
        fused_reason = f"{orig_ev.reason}; Visual evidence conflicts with thermal classification (CNN: {cnn_prediction}{conf_val} vs Thermal: {thermal_class}) — flagged for human review."

    fused_ev = Evidence(
        spatial=orig_ev.spatial,
        temporal=orig_ev.temporal,
        intensity=orig_ev.intensity,
        sufficiency=sufficiency_status,
        reason=fused_reason,
        visual=visual_status,
    )

    return ClassResult(
        classification=class_result.classification,
        confidence=class_result.confidence,
        explanation=fused_reason,
        features=class_result.features,
        evidence=fused_ev,
    )