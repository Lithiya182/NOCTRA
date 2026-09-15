from __future__ import annotations

import json

from fastapi import APIRouter

from .. import db
from ..models import PolygonOut

router = APIRouter(prefix="/api/polygons", tags=["polygons"])


@router.get("", response_model=list[PolygonOut])
def list_polygons() -> list[PolygonOut]:
    out = []
    for r in db.query("SELECT * FROM polygons"):
        ring = [[pt[0], pt[1]] for pt in json.loads(r["boundary_json"])]
        out.append(PolygonOut(kind=r["kind"], name=r["name"], ring=ring))
    return out