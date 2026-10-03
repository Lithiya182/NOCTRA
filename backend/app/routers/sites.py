from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db, ml_model
from ..models import ImageryOut, SiteRow
from ..feature_utils import (
    COVERAGE_GAP_DAYS,
    EXPECTED_REVISIT_DAYS,
    FRP_INTENSITY_BANDS,
    _frp_intensity,
    _compute_frp_trend,
    _compute_expansion_magnitude,
    _attach_thermal_behavior,
    _get_site_coverage,
    _attach_coverage,
    _attach_provenance,
)

router = APIRouter(prefix="/api/sites", tags=["sites"])



def _to_row(r: dict) -> SiteRow:
    r = dict(r)
    r["is_anomalous"] = bool(r["is_anomalous"])
    r["ml_prediction"] = ml_model.predict(r)
    from .. import classifier, cnn_visual
    pred, conf = cnn_visual.predict_visual(r["site_id"])
    r["cnn_prediction"] = pred
    r["cnn_confidence"] = conf

    img_rows = db.query("SELECT COUNT(*) as cnt FROM imagery WHERE site_id=? AND status='available'", (r["site_id"],))
    has_imagery = bool(img_rows and img_rows[0]["cnt"] > 0)

    base_evidence = classifier.Evidence(
        spatial="polygon_containment" if "industrial polygon" in r["explanation"].lower() or "agri" in r["explanation"].lower() else ("proximity" if "within" in r["explanation"].lower() else "none"),
        temporal="persistent" if r.get("persistence", 0) >= 3 else ("sufficient" if "sufficient" in r["explanation"].lower() else "insufficient"),
        intensity=classifier._frp_intensity(r.get("max_frp", 0.0)),
        sufficiency="sufficient" if r["classification"] != "other" else "insufficient",
        reason=r["explanation"],
        visual="none",
    )
    base_result = classifier.ClassResult(
        classification=r["classification"],
        confidence=r.get("confidence", 0.5),
        explanation=r["explanation"],
        features={},
        evidence=base_evidence,
    )
    fused_result = classifier.fuse_evidence(
        base_result,
        cnn_prediction=pred,
        cnn_confidence=conf,
        has_imagery=has_imagery,
    )
    r["explanation"] = fused_result.explanation
    r["visual_evidence"] = fused_result.evidence.visual
    r["evidence_sufficiency"] = fused_result.evidence.sufficiency

    from .. import rl_policy
    prio, prio_conf = rl_policy.suggest_priority(r)
    r["suggested_priority"] = prio
    r["suggested_priority_confidence"] = prio_conf

    return SiteRow(**r)


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