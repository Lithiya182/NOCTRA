from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import alert_engine
from ..models import AlertOut, AlertReviewOut, TransitionIn

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(active_only: bool = False) -> list[AlertOut]:
    alerts = alert_engine.get_alerts()
    if active_only:
        alerts = [a for a in alerts if a["status"] in ("alert_triggered", "confirmed")]
    return alerts


@router.get("/reviews", response_model=list[AlertReviewOut])
def list_alert_reviews() -> list[AlertReviewOut]:
    """List append-only audit trail of alert status reviews across all alerts."""
    return alert_engine.get_alert_reviews()


@router.get("/{alert_id}/reviews", response_model=list[AlertReviewOut])
def get_alert_reviews(alert_id: int) -> list[AlertReviewOut]:
    """List audit trail for a specific alert_id."""
    return alert_engine.get_alert_reviews(alert_id)


@router.post("/{alert_id}/transition", response_model=dict)
def transition(alert_id: int, body: TransitionIn) -> dict:
    try:
        return alert_engine.update_alert_status(
            alert_id,
            action=body.action,
            analyst_note=body.analyst_note,
            reviewed_by=body.reviewed_by,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{alert_id}/notify", response_model=dict)
def notify(alert_id: int) -> dict:
    """Manually re-fire SMS + Web Push for an alert (rehearsal / retry)."""
    rows = alert_engine.get_alerts()
    for a in rows:
        if a["id"] == alert_id:
            return alert_engine.dispatch_public(a)
    raise HTTPException(404, "alert not found")