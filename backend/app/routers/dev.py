from __future__ import annotations

from fastapi import APIRouter
from datetime import datetime, timezone

from .. import db, ml_model
from ..ingest import ingest, trigger_runtime_detection
from ..models import IngestOut, RuntimeDetectionIn

router = APIRouter(prefix="/api/dev", tags=["dev"])


@router.post("/ingest", response_model=IngestOut)
def reingest() -> IngestOut:
    result = ingest(reset=True)
    ml_model.train()
    return IngestOut(detections=result["detections"], sites=result["sites"],
                     passes=result["pass_dates"], polygons=result["polygons"],
                     alerts_created=result["alerts_created"])


@router.post("/detection")
def push_runtime_detection(body: RuntimeDetectionIn) -> dict:
    result = trigger_runtime_detection(body.lat, body.lon, body.frp, body.brightness)
    result["now"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result["severity"] = result.get("severity", "extreme")
    return result