from __future__ import annotations

from datetime import date, datetime, timezone
from fastapi import APIRouter, HTTPException

from .. import db, ml_model
from ..models import SiteRow

router = APIRouter(prefix="/api/sites", tags=["sites"])

# Coverage threshold: days after last pass to consider coverage uncertain
COVERAGE_GAP_DAYS = 2


def _get_coverage_info() -> tuple[Optional[str], Optional[int]]:
    """Get global last pass date and days since from detections table."""
    row = db.query("SELECT MAX(acq_date) as last_pass FROM detections WHERE is_synthetic = 0")
    if not row or not row[0]["last_pass"]:
        return None, None
    last_pass_str = row[0]["last_pass"]
    try:
        last_pass = date.fromisoformat(last_pass_str)
        today = datetime.now(timezone.utc).date()
        days_since = (today - last_pass).days
        return last_pass_str, days_since
    except Exception:
        return last_pass_str, None


def _attach_coverage(sites: list[dict]) -> None:
    """Attach coverage status to all sites based on global last pass date."""
    last_pass_date, days_since = _get_coverage_info()
    if last_pass_date is None:
        for s in sites:
            s["coverage_status"] = "unknown"
            s["last_pass_date"] = None
            s["days_since_last_pass"] = None
        return

    for s in sites:
        s["last_pass_date"] = last_pass_date
        s["days_since_last_pass"] = days_since
        if days_since is not None and days_since > COVERAGE_GAP_DAYS:
            s["coverage_status"] = "uncertain"
        else:
            s["coverage_status"] = "covered"


def _to_row(r: dict) -> SiteRow:
    r = dict(r)
    r["is_anomalous"] = bool(r["is_anomalous"])
    r["ml_prediction"] = ml_model.predict(r)
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
    return [_to_row(r) for r in rows]


@router.get("/{site_id}", response_model=SiteRow)
def get_site(site_id: str) -> SiteRow:
    rows = db.query("SELECT * FROM sites WHERE site_id=?", (site_id,))
    if not rows:
        raise HTTPException(404, "site not found")
    row = dict(rows[0])
    _attach_provenance([row])
    _attach_coverage([row])
    return _to_row(row)