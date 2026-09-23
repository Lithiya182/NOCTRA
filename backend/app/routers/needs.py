from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status

from .. import db
from ..models import NeedIn, NeedOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/needs", tags=["needs"])

# IP rate limiting store for POST /api/needs (5 requests per 60 seconds per IP)
# Rationale: Allows citizens to check in or update status multiple times during a crisis,
# while preventing automated spam loops or denial-of-service floods.
SOS_RATE_LIMIT_WINDOW = 60  # seconds
SOS_MAX_REQUESTS = 5
_ip_request_history: dict[str, deque[float]] = defaultdict(deque)


def _reset_rate_limits() -> None:
    """Helper for unit tests to clear rate limit history."""
    _ip_request_history.clear()


def check_sos_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "127.0.0.1"
    now = time.time()
    history = _ip_request_history[client_ip]

    while history and history[0] < now - SOS_RATE_LIMIT_WINDOW:
        history.popleft()

    if len(history) >= SOS_MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Maximum {SOS_MAX_REQUESTS} safety submissions per {SOS_RATE_LIMIT_WINDOW} seconds.",
        )

    history.append(now)


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
def create_need(body: NeedIn, request: Request) -> NeedOut:
    check_sos_rate_limit(request)
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