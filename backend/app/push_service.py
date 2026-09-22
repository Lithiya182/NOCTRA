"""Web Push (Push API + Service Worker) delivery using pywebpush + VAPID keys.

VAPID keys are generated once on first use (cryptography) and cached to
backend/keys/vapid.json so the demo is fully self-contained.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from . import db
from .config import VAPID_KEYS_FILE

log = logging.getLogger("thermalguard.push")

VAPID_SUBJECT = "mailto:thermalguard@district-control.gov.in"


def _load_or_create_keys(path: Path) -> dict:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            priv = data.get("private", "")
            if priv and not priv.startswith("-----BEGIN"):
                return data
        except Exception:
            pass

    import base64
    urlb64 = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")  # noqa: E731

    private_key = ec.generate_private_key(ec.SECP256R1())
    priv_der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    keys = {"private": urlb64(priv_der), "public": urlb64(pub)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    return keys


def get_vapid_public_key() -> str:
    return _load_or_create_keys(VAPID_KEYS_FILE)["public"]


def subscribe(endpoint: str, p256dh: str, auth: str) -> str:
    db.execute(
        "INSERT OR REPLACE INTO push_subscriptions (endpoint, p256dh, auth, created_at) "
        "VALUES (?,?,?, datetime('now'))",
        (endpoint, p256dh, auth),
    )
    return endpoint


def get_subscriptions() -> list[dict]:
    return [dict(r) for r in db.query("SELECT * FROM push_subscriptions")]


def send_push(title: str, body: str) -> dict:
    """Send a Web Push notification to every registered browser subscription."""
    keys = _load_or_create_keys(VAPID_KEYS_FILE)
    subs = get_subscriptions()
    if not subs:
        log.warning("No push subscriptions registered - skipping web push.")
        return {"sent": 0, "total": 0}
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        log.warning("pywebpush not installed; skipping web push.")
        return {"sent": 0, "total": len(subs), "error": "pywebpush missing"}

    sent = 0
    payload = json.dumps({"title": title, "body": body}).encode()
    for s in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": s["endpoint"],
                    "keys": {"p256dh": s["p256dh"], "auth": s["auth"]},
                },
                data=payload,
                vapid_private_key=keys["private"],
                vapid_claims={"sub": VAPID_SUBJECT, "aud": None},
            )
            sent += 1
        except Exception as exc:
            log.warning("push failed for %s: %s", s["endpoint"], exc)
            if getattr(exc, "response", None) and getattr(exc.response, "status_code", None) in (404, 410):
                db.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (s["endpoint"],))
    return {"sent": sent, "total": len(subs)}