from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter

from .. import db
from ..models import NeedIn, NeedOut

router = APIRouter(prefix="/api/needs", tags=["needs"])


@router.get("", response_model=list[NeedOut])
def list_needs() -> list[NeedOut]:
    rows = db.query("SELECT * FROM needs ORDER BY id DESC LIMIT 200")
    return [NeedOut(**dict(r)) for r in rows]


@router.post("", response_model=NeedOut, status_code=201)
def create_need(body: NeedIn) -> NeedOut:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO needs (kind, lat, lon, message, created_at) VALUES (?,?,?,?,?)",
        (body.kind, body.lat, body.lon, body.message, now),
    )
    got = db.query("SELECT * FROM needs WHERE id=?",
                   (cur.lastrowid,))[0]
    return NeedOut(**dict(got))