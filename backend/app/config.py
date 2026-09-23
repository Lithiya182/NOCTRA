"""Shared configuration loaded from the root .env file."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
FIRMS_CSV = DATA_DIR / "firms_seed.csv"
OSM_GEOJSON = DATA_DIR / "osm_seed.geojson"
DB_PATH = Path(os.getenv("DB_PATH", "data/thermalguard.db"))
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if not CORS_ORIGINS:
    CORS_ORIGINS = ["http://localhost:5173", "http://localhost:5174"]

FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "")
API_KEY = os.getenv("API_KEY", "noctra-dev-key-2026")
ENABLE_FIRMS_SCHEDULER = os.getenv("ENABLE_FIRMS_SCHEDULER", "false").lower() == "true"
TWILIO_SID = os.getenv("TWILIO_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
TWILIO_TO_NUMBER = os.getenv("TWILIO_TO_NUMBER", "")

# Data paths
FIRMS_REAL_CSV = DATA_DIR / "firms_real.csv"

# Rule-based classifier thresholds (locked by the PS).
IND_DIST_M = 500          # max distance to industrial polygon -> industrial
AGR_MONTHS = {4, 5, 10, 11}
AGR_MAX_CONSEC_DAYS = 3
PERSISTENCE_MIN = 3       # active on >= 3 of last 5 passes
CLUSTER_RADIUS_M = 1000   # detections within this distance form one site
WILDFIRE_FRP_MIN = 50.0
WILDFIRE_DIST_M = 500     # must be > this from industrial/agri polygons
EXPANSION_RADIUS_M = 4000

# Severity tiers (frp MW thresholds).
SEV = {"minor": (0, 15), "moderate": (15, 40), "severe": (40, 100), "extreme": (100, 1e9)}

VAPID_KEYS_FILE = ROOT / "backend" / "keys" / "vapid.json"
MODELS_DIR = ROOT / "backend" / "models"
ML_MODEL_FILE = MODELS_DIR / "clf.pkl"
CNN_MODEL_FILE = MODELS_DIR / "cnn_visual.pkl"