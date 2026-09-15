"""Twilio SMS channel. Sends a real SMS when credentials are configured in .env;
otherwise logs the payload so the pipeline still runs fully offline."""
from __future__ import annotations

import logging

from .config import TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, TWILIO_SID, TWILIO_TO_NUMBER

log = logging.getLogger("thermalguard.sms")


def send_sms(body: str, to_number: str | None = None) -> dict:
    to_number = to_number or TWILIO_TO_NUMBER
    if not (TWILIO_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER and to_number):
        log.warning("Twilio not configured - SMS not sent. body=%r to=%r", body, to_number)
        return {"sent": False, "reason": "twilio not configured", "body": body}

    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=to_number)
        log.info("SMS sent: %s -> %s", msg.sid, to_number)
        return {"sent": True, "sid": msg.sid, "to": to_number, "body": body}
    except Exception as exc:  # noqa: BLE001
        log.exception("Twilio send failed")
        return {"sent": False, "reason": str(exc), "body": body}