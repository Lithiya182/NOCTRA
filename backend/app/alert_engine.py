"""Alert engine: severity gating + dispatch to public channels.

Gating rule (from the PS):
  - Government tier (dashboard entry): fires automatically for every anomalous site.
  - Public tier (SMS + Web Push): fires only after a human clicks "Confirm" in the
    dashboard, OR automatically at the `extreme` severity tier.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from . import db
from .cap import build_cap_alert, cap_to_push_body, cap_to_push_title, cap_to_sms_text
from .push_service import send_push
from .twilio_sender import send_sms

log = logging.getLogger("thermalguard.alert")


def _as_dict(alert) -> dict:
    d = dict(alert)
    d["is_anomalous"] = bool(d["is_anomalous"])
    return d


def get_alerts() -> list[dict]:
    rows = db.query("SELECT * FROM alerts ORDER BY id DESC LIMIT 200")
    out = []
    for r in rows:
        a = dict(r)
        a["is_anomalous"] = bool(a["is_anomalous"] or 0)
        try:
            a["cap"] = json.loads(a["cap_json"]) if a["cap_json"] else None
        except json.JSONDecodeError:
            a["cap"] = None
        site = db.query("SELECT * FROM sites WHERE site_id=?", (a["site_id"],))
        a["site"] = dict(site[0]) if site else None
        
        from . import rl_policy
        prio, prio_conf = rl_policy.suggest_priority(a["site"] or a)
        a["suggested_priority"] = prio
        a["suggested_priority_confidence"] = prio_conf

        out.append(a)
    return out


def update_alert_status(
    alert_id: int,
    action: str,
    analyst_note: str | None = None,
    reviewed_by: str = "",
    feedback_label: str | None = None,
) -> dict:
    """action: confirm | dismiss. Confirm fires the public tier (SMS + push)."""
    rows = db.query("SELECT * FROM alerts WHERE id=?", (alert_id,))
    if not rows:
        raise LookupError(f"alert {alert_id} not found")
    alert = dict(rows[0])
    prev_status = alert.get("status")
    status = "confirmed" if action == "confirm" else "dismissed"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reviewer_name = reviewed_by.strip()
    
    # Update alerts table
    db.execute(
        "UPDATE alerts SET status=?, updated_at=?, analyst_note=?, reviewed_by=?, feedback_label=? WHERE id=?",
        (status, now, analyst_note, reviewer_name, feedback_label, alert_id),
    )
    db.execute("UPDATE sites SET status=? WHERE site_id=?", (status, alert["site_id"]))
    
    # Write append-only record to alert_reviews audit table
    db.execute(
        """
        INSERT INTO alert_reviews (alert_id, site_id, action, previous_status, new_status, analyst_note, reviewed_by, feedback_label, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (alert_id, alert["site_id"], action, prev_status, status, analyst_note, reviewer_name, feedback_label, now),
    )
    
    alert["status"] = status
    alert["updated_at"] = now
    alert["analyst_note"] = analyst_note
    alert["reviewed_by"] = reviewer_name
    alert["feedback_label"] = feedback_label

    dispatched = {}
    if status == "confirmed":
        dispatched = dispatch_public(alert)
    return {"alert": _as_dict(alert), "dispatched": dispatched}


def record_feedback(
    alert_id: int,
    feedback: str,
    analyst_note: str | None = None,
    reviewed_by: str = "",
) -> dict:
    """Record human classification review feedback (correct/incorrect) in alerts and append-only audit trail."""
    rows = db.query("SELECT * FROM alerts WHERE id=?", (alert_id,))
    if not rows:
        raise LookupError(f"alert {alert_id} not found")
    alert = dict(rows[0])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reviewer_name = reviewed_by.strip()
    
    db.execute(
        "UPDATE alerts SET feedback_label=?, updated_at=?, analyst_note=COALESCE(?, analyst_note), reviewed_by=? WHERE id=?",
        (feedback, now, analyst_note, reviewer_name, alert_id),
    )
    
    db.execute(
        """
        INSERT INTO alert_reviews (alert_id, site_id, action, previous_status, new_status, analyst_note, reviewed_by, feedback_label, created_at)
        VALUES (?, ?, 'feedback', ?, ?, ?, ?, ?, ?)
        """,
        (alert_id, alert["site_id"], alert.get("status"), alert.get("status"), analyst_note, reviewer_name, feedback, now),
    )
    
    alert["feedback_label"] = feedback
    alert["updated_at"] = now
    if analyst_note:
        alert["analyst_note"] = analyst_note
    alert["reviewed_by"] = reviewer_name
    return {"alert": _as_dict(alert), "feedback": feedback}


def get_alert_reviews(alert_id: int | None = None) -> list[dict]:
    """Retrieve audit history from alert_reviews table."""
    if alert_id is not None:
        rows = db.query("SELECT * FROM alert_reviews WHERE alert_id=? ORDER BY id ASC", (alert_id,))
    else:
        rows = db.query("SELECT * FROM alert_reviews ORDER BY id DESC LIMIT 200")
    return [dict(r) for r in rows]


def dispatch_public(alert: dict, site: dict | None = None) -> dict:
    """Fire the public tier for a confirmed (or extreme) alert."""
    if site is None:
        row = db.query("SELECT * FROM sites WHERE site_id=?", (alert["site_id"],))
        site = dict(row[0]) if row else {}
    cap = alert.get("cap")
    if not cap:
        cap = build_cap_alert(site)
        db.execute("UPDATE alerts SET cap_json=? WHERE id=?",
                   (json.dumps(cap, indent=2), alert["id"]))
    sms = send_sms(cap_to_sms_text(cap))
    push = send_push(cap_to_push_title(cap), cap_to_push_body(cap))
    db.execute("UPDATE alerts SET public_notified=1 WHERE id=?", (alert["id"],))
    return {"sms": sms, "push": push}