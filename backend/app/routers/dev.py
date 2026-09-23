from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from .. import db, ml_model
from ..ingest import ingest, trigger_runtime_detection
from ..models import IngestOut, RuntimeDetectionIn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dev", tags=["dev"])


@router.post("/ingest", response_model=IngestOut)
def reingest() -> IngestOut:
    try:
        result = ingest(reset=True)
        try:
            ml_model.train()
        except Exception:  # noqa: BLE001
            logger.warning("ML training failed after ingestion", exc_info=True)
        return IngestOut(
            detections=result["detections"],
            sites=result["sites"],
            passes=result["pass_dates"],
            polygons=result["polygons"],
            alerts_created=result["alerts_created"],
        )
    except Exception as e:
        logger.error("Error during dev re-ingest: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dev re-ingestion failed: {e}",
        ) from e


@router.post("/detection")
def push_runtime_detection(body: RuntimeDetectionIn) -> dict:
    try:
        result = trigger_runtime_detection(body.lat, body.lon, body.frp, body.brightness)
        result["now"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        result["severity"] = result.get("severity", "extreme")
        return result
    except Exception as e:
        logger.error("Error pushing runtime detection: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to push runtime detection: {e}",
        ) from e


@router.post("/retrain")
def trigger_retrain() -> dict:
    """Trigger active learning retraining cycle using human feedback and review audit table."""
    try:
        from .. import active_learning
        return active_learning.run_active_learning_cycle()
    except Exception as e:
        logger.error("Error running active learning retrain: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Active learning retrain failed: {e}",
        ) from e