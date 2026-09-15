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
        a["site"] = dict(site[0]) if site else {}
        out.append(a)
    return out


def update_alert_status(alert_id: int, action: str) -> dict:
    """action: confirm | dismiss. Confirm fires the public tier (SMS + push)."""
    rows = db.query("SELECT * FROM alerts WHERE id=?", (alert_id,))
    if not rows:
        raise LookupError(f"alert {alert_id} not found")
    alert = dict(rows[0])
    status = "confirmed" if action == "confirm" else "dismissed"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.execute("UPDATE alerts SET status=?, updated_at=? WHERE id=?",
               (status, now, alert_id))
    db.execute("UPDATE sites SET status=? WHERE site_id=?", (status, alert["site_id"]))
    alert["status"] = status

    dispatched = {}
    if status == "confirmed":
        dispatched = dispatch_public(alert)
    return {"alert": _as_dict(alert), "dispatched": dispatched}


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