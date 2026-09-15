from __future__ import annotations

from fastapi import APIRouter

from .. import push_service
from ..models import PushSubscribeIn

router = APIRouter(prefix="/api/push", tags=["push"])


@router.get("/vapid-public-key")
def vapid_public_key() -> dict:
    return {"publicKey": push_service.get_vapid_public_key()}


@router.post("/subscribe", status_code=201)
def subscribe(body: PushSubscribeIn) -> dict:
    push_service.subscribe(body.endpoint, body.p256dh, body.auth)
    return {"ok": True}