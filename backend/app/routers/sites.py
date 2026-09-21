from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db, ml_model
from ..models import SiteRow

router = APIRouter(prefix="/api/sites", tags=["sites"])


def _to_row(r: dict) -> SiteRow:
    r = dict(r)
    r["is_anomalous"] = bool(r["is_anomalous"])
    r["ml_prediction"] = ml_model.predict(r)
    return SiteRow(**r)


def _attach_provenance(sites: list[dict]) -> None:
    """Attach is_synthetic and source fields based on detections."""
    if not sites:
        return
    site_ids = [s["site_id"] for s in sites]
    placeholders = ",".join("?" * len(site_ids))
    rows = db.query(
        f"""
        SELECT s.site_id,
               MIN(d.is_synthetic) as min_is_synthetic,
               GROUP_CONCAT(DISTINCT d.source) as sources
        FROM sites s
        JOIN site_detections sd ON s.site_id = sd.site_id
        JOIN detections d ON sd.detection_id = d.id
        WHERE s.site_id IN ({placeholders})
        GROUP BY s.site_id
        """,
        tuple(site_ids),
    )
    prov_map = {r["site_id"]: {"is_synthetic": bool(r["min_is_synthetic"]), "source": r["sources"]} for r in rows}
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
    return [_to_row(r) for r in rows]


@router.get("/{site_id}", response_model=SiteRow)
def get_site(site_id: str) -> SiteRow:
    rows = db.query("SELECT * FROM sites WHERE site_id=?", (site_id,))
    if not rows:
        raise HTTPException(404, "site not found")
    row = dict(rows[0])
    _attach_provenance([row])
    return _to_row(row)