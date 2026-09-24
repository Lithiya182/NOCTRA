"""ThermalGuard API server."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import ml_model, db
from .config import CORS_ORIGINS, FIRMS_REAL_CSV
from .ingest import ingest
from .db import init_schema
from .routers import alerts, dev, health, needs, polygons, push, sites

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Check if synthetic demo ingestion is enabled
    enable_synthetic = os.getenv("ENABLE_SYNTHETIC_INGEST", "false").lower() == "true"
    
    if enable_synthetic:
        # Demo mode: ingest synthetic seed data
        summary = ingest(reset=True)
    else:
        # Production mode: ensure schema exists, load real data if database is empty
        init_schema(db.get_conn())
        
        # Check if database has any detections
        det_count = db.query("SELECT COUNT(*) as c FROM detections")[0]["c"]
        if det_count == 0:
            # Database empty - ingest real FIRMS data if available
            if FIRMS_REAL_CSV.exists():
                summary = ingest(real_csv=FIRMS_REAL_CSV)
                logging.info("startup: ingested real FIRMS data: %s", summary)
            else:
                summary = {"detections": 0, "sites": 0, "pass_dates": [], "polygons": 0, "alerts_created": 0}
                logging.warning("startup: no data in database and no real FIRMS CSV available")
        else:
            # Data already exists - just ensure schema is up to date
            summary = {"detections": det_count, "sites": 0, "pass_dates": [], "polygons": 0, "alerts_created": 0}
            logging.info("startup: using existing database (%d detections)", det_count)
    
    # ML training is gated behind explicit flag - only run if enabled
    if os.getenv("ENABLE_ML_TRAINING", "false").lower() == "true":
        try:
            ml_model.train()
        except Exception:  # noqa: BLE001
            logging.warning("ML weak-label training skipped", exc_info=True)
    else:
        logging.info("ML training disabled (set ENABLE_ML_TRAINING=true to enable)")
    
    # FIRMS scheduler is gated behind ENABLE_FIRMS_SCHEDULER env var
    if os.getenv("ENABLE_FIRMS_SCHEDULER", "false").lower() == "true":
        try:
            from .firms_scheduler import start_scheduler
            start_scheduler()
            logging.info("startup: FIRMS NRT scheduler started (ENABLE_FIRMS_SCHEDULER=true)")
        except Exception:  # noqa: BLE001
            logging.warning("startup: failed to start FIRMS NRT scheduler", exc_info=True)
    else:
        logging.info("startup: FIRMS scheduler disabled (set ENABLE_FIRMS_SCHEDULER=true to enable)")

    logging.info("startup complete: %s", summary)
    yield

    # Lifespan shutdown: stop scheduler if it was enabled
    if os.getenv("ENABLE_FIRMS_SCHEDULER", "false").lower() == "true":
        try:
            from .firms_scheduler import stop_scheduler
            stop_scheduler()
            logging.info("shutdown: FIRMS NRT scheduler stopped")
        except Exception:  # noqa: BLE001
            pass


app = FastAPI(
    title="ThermalGuard",
    description="Satellite thermal-anomaly classification + alerting (SIH26162)",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (health, sites, alerts, polygons, needs, push, dev):
    app.include_router(r.router)

imagery_dir = Path("data/imagery")
if imagery_dir.exists():
    app.mount("/data/imagery", StaticFiles(directory=imagery_dir), name="imagery")


@app.get("/")
def root() -> dict:
    return {"service": "ThermalGuard", "docs": "/docs", "health": "/api/health"}