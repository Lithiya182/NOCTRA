from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from .. import db
from ..models import NeedIn, NeedOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/needs", tags=["needs"])


@router.get("", response_model=list[NeedOut])
def list_needs() -> list[NeedOut]:
    try:
        rows = db.query("SELECT * FROM needs ORDER BY id DESC LIMIT 200")
        return [NeedOut(**dict(r)) for r in rows]
    except Exception as e:
        logger.error("Failed to list needs: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list safety needs records",
        ) from e


@router.post("", response_model=NeedOut, status_code=status.HTTP_201_CREATED)
def create_need(body: NeedIn) -> NeedOut:
    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur = db.execute(
            "INSERT INTO needs (kind, lat, lon, message, created_at) VALUES (?,?,?,?,?)",
            (body.kind, body.lat, body.lon, body.message, now),
        )
        rows = db.query("SELECT * FROM needs WHERE id=?", (cur.lastrowid,))
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Need entry created but failed to read back",
            )
        return NeedOut(**dict(rows[0]))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create need: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record safety need entry",
        ) from e