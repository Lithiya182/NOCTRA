"""ThermalGuard API server."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import ml_model
from .config import CORS_ORIGINS
from .ingest import ingest
from .routers import alerts, dev, health, needs, polygons, push, sites

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    summary = ingest(reset=True)
    if summary.get("sites"):
        # ML training is gated behind explicit flag - only run if enabled
        # Default: False to avoid silent retraining on every restart including tests
        import os
        if os.getenv("ENABLE_ML_TRAINING", "false").lower() == "true":
            try:
                ml_model.train()
            except Exception:  # noqa: BLE001
                logging.warning("ML weak-label training skipped", exc_info=True)
        else:
            logging.info("ML training disabled (set ENABLE_ML_TRAINING=true to enable)")
    logging.info("startup ingest complete: %s", summary)
    yield


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


@app.get("/")
def root() -> dict:
    return {"service": "ThermalGuard", "docs": "/docs", "health": "/api/health"}