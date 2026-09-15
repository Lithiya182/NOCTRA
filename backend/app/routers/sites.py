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
    return [_to_row(r) for r in db.query(sql, tuple(params))]


@router.get("/{site_id}", response_model=SiteRow)
def get_site(site_id: str) -> SiteRow:
    rows = db.query("SELECT * FROM sites WHERE site_id=?", (site_id,))
    if not rows:
        raise HTTPException(404, "site not found")
    return _to_row(rows[0])