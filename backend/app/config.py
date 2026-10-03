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
FIRMS_RAW_DIR = DATA_DIR / "firms_raw"

# FIRMS regions (name -> bbox west,south,east,north), overridable by env
DEFAULT_FIRMS_REGIONS: dict[str, str] = {
    "jharia": "86.2,22.7,86.7,23.9",
    "jamnagar": "69.8,22.3,70.3,22.6",
    "punjab": "74.7,30.15,76.8,31.3",
    "uttarakhand": "78.9,29.9,79.4,30.2",
}

def _parse_firms_regions() -> dict[str, str]:
    raw = os.getenv("FIRMS_REGIONS", "").strip()
    if not raw:
        return dict(DEFAULT_FIRMS_REGIONS)
    try:
        import json
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    regions = {}
    delimiters = ";" if ";" in raw else ","
    for part in raw.split(delimiters):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            regions[k.strip()] = v.strip()
        elif ":" in part:
            k, v = part.split(":", 1)
            regions[k.strip()] = v.strip()
    return regions or dict(DEFAULT_FIRMS_REGIONS)

FIRMS_REGIONS: dict[str, str] = _parse_firms_regions()

DEFAULT_FIRMS_SOURCES: list[str] = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
]

def _parse_firms_sources() -> list[str]:
    raw = os.getenv("FIRMS_SOURCES", "").strip()
    if not raw:
        return list(DEFAULT_FIRMS_SOURCES)
    try:
        import json
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(s) for s in parsed]
    except Exception:
        pass
    return [s.strip() for s in raw.split(",") if s.strip()] or list(DEFAULT_FIRMS_SOURCES)

FIRMS_SOURCES: list[str] = _parse_firms_sources()
FIRMS_DAY_RANGE: int = int(os.getenv("FIRMS_DAY_RANGE", "5"))
FIRMS_SP_CUTOFF_DAYS: int = int(os.getenv("FIRMS_SP_CUTOFF_DAYS", "60"))

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

# EWMA + CUSUM temporal change detection (temporal_cusum.py)
EWMA_LAMBDA: float = float(os.getenv("EWMA_LAMBDA", "0.2"))
CUSUM_K_FACTOR: float = float(os.getenv("CUSUM_K_FACTOR", "0.5"))
CUSUM_H_FACTOR: float = float(os.getenv("CUSUM_H_FACTOR", "4.0"))
CUSUM_MIN_HISTORY_DAYS: int = int(os.getenv("CUSUM_MIN_HISTORY_DAYS", "5"))
CUSUM_SIGMA_FLOOR: float = float(os.getenv("CUSUM_SIGMA_FLOOR", "1.0"))
CUSUM_CONSECUTIVE_ALARMS: int = int(os.getenv("CUSUM_CONSECUTIVE_ALARMS", "2"))
# Days back from the final observation within which an alarm is still "live".
CUSUM_RECENT_DAYS: int = int(os.getenv("CUSUM_RECENT_DAYS", "7"))
# Observed days to exclude from the tail when computing sigma so that an
# active anomaly cannot inflate its own detection threshold.
CUSUM_TAIL_DAYS: int = int(os.getenv("CUSUM_TAIL_DAYS", os.getenv("CUSUM_SIGMA_TAIL", "3")))
CUSUM_SIGMA_TAIL: int = CUSUM_TAIL_DAYS
# Minimum sigma as a fraction of initial baseline to prevent over-sensitivity on short histories.
CUSUM_BASELINE_SIGMA_RATIO: float = float(os.getenv("CUSUM_BASELINE_SIGMA_RATIO", "0.05"))