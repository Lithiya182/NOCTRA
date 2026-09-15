from __future__ import annotations

from fastapi import APIRouter

from .. import db

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health() -> dict:
    counts = {
        "detections": db.query("SELECT COUNT(*) AS c FROM detections")[0]["c"],
        "sites": db.query("SELECT COUNT(*) AS c FROM sites")[0]["c"],
        "alerts": db.query("SELECT COUNT(*) AS c FROM alerts")[0]["c"],
        "needs": db.query("SELECT COUNT(*) AS c FROM needs")[0]["c"],
    }
    return {"status": "ok", "counts": counts}