# AUDIT: ThermalGuard → NOCTRA Upgrade

**Date of Audit**: September 29, 2026  
**Auditor**: Antigravity Technical Audit Agent  
**Audit Scope**: Complete repository (`C:\Users\Asus\thermalguard`)  
**Status**: Authoritative & Exhaustive  
**Operating System Target**: Windows 11 / PowerShell  

---

## Executive Summary & Upgrade Context

The ThermalGuard codebase is undergoing a structural upgrade to **NOCTRA**.
The **Frozen Target Architecture** for NOCTRA is defined as:
```text
FIRMS/VIIRS Ingest
       │
       ▼
Site Formation (1 km Haversine clustering)
       │
       ▼
Thermal DNA + OSM Land-Use Features
       │
       ▼
Rule Classification (Live) + EBM (Shadow)
       │
       ▼
LightGBM Severity + Hysteresis
       │
       ▼
EWMA + CUSUM Drift & Anomaly Detection
       │
       ▼
Sentinel-2 Corroboration (Optical STAC chips)
       │
       ▼
Bayesian Fusion (Probabilistic Posterior)
       │
       ▼
Routing & Priority (Contextual Bandit)
       │
       ▼
Human Review Console (Confirm / Dismiss / Notes / Thumbs)
       │
       ▼
Twilio SMS (STRICTLY ONLY after authorised confirmation)
       │
       ▼
Decision Trace (Immutable End-to-End Audit DAG)
       │
       ▼
OpenAI Layer (EXPLAIN-ONLY: Operator & Citizen Explanations)
```

This audit provides a complete catalog of all existing files, technical gaps against the frozen architecture, database contract discrepancies, notification safety violations, discovered bugs and dead code, and a multi-engineer ownership plan to prevent merge conflicts.

---

## 1. Directory Map & How to Run the Project

### 1.1 Complete Directory Map
```text
C:\Users\Asus\thermalguard\
├── .env                              # Local runtime secrets (gitignored; FIRMS key, API_KEY)
├── .env.example                      # Template environment file
├── .gitignore                        # Git exclusion rules
├── README.md                         # Legacy ThermalGuard quickstart and overview
├── docker-compose.yml                # Multi-container orchestration (FastAPI + Vite Dashboard)
├── start_demo.ps1                    # Multi-window PowerShell launcher for demo services
├── start_dev.ps1                     # Background process local development launcher
│
├── audit/                            # Verification & audit scripts (diagnostic tools, not prod)
│   ├── active_learning_log.txt       # Append-only log of retraining cycles
│   ├── check_consec_db.py            # [BROKEN] Diagnostic script for consecutive active days
│   ├── check_label_changes.py        # [BROKEN] Diagnostic script for region label changes
│   ├── check_provenance.py           # Provenance checker (leaks API key to stdout)
│   ├── excluded_mixed_provenance_sites.csv # Historical audit artifact
│   ├── final_baseline.py             # Baseline validation script
│   ├── inspect_db2.py                # Database inspection utility
│   ├── ml_expansion_dataset_report.txt     # Dataset summary report
│   ├── phase4d_model_report.txt      # Chronological split RF model report
│   ├── real_only_validation_candidates.csv # Validation candidates artifact
│   ├── reingest_check.py             # Ingestion verification script
│   └── verify_after.py               # Post-refactor verification script
│
├── backend/                          # Core Python FastAPI application
│   ├── Dockerfile                    # Container build file for backend
│   ├── requirements.txt              # Production & test Python dependencies
│   ├── smoke_test.py                 # Smoke test script (fails unless PYTHONPATH is set)
│   ├── debug_regions.py              # One-off debug script with hardcoded Windows paths
│   ├── app/                          # Application source code
│   │   ├── __init__.py               # Package marker
│   │   ├── main.py                   # FastAPI app entrypoint, lifespan, CORS, static routes
│   │   ├── config.py                 # Configuration loader and hardcoded threshold constants
│   │   ├── auth.py                   # API key dependency (X-API-Key and Bearer)
│   │   ├── db.py                     # SQLite access layer, schema init, reset routines
│   │   ├── models.py                 # Pydantic schemas for request/response payloads
│   │   ├── provenance.py             # Provenance metadata dataclass and helper routines
│   │   ├── feature_utils.py          # Spatial helpers (point-in-polygon, ray casting, distance)
│   │   ├── ingest.py                 # FIRMS CSV ingestion, site clustering, detection trigger
│   │   ├── classifier.py             # Rule-based fire classifier (Section 3 PS) + Evidence
│   │   ├── ml_model.py               # Weak-label RandomForest model (to be replaced)
│   │   ├── satellite_imagery.py      # Sentinel-2 STAC querying & chip downloading
│   │   ├── cnn_visual.py             # Classical CV (102-dim RGB) visual feature classifier
│   │   ├── cap.py                    # OASIS CAP 1.2 payload, SMS text, and Web Push builder
│   │   ├── alert_engine.py           # Alert lifecycle, human feedback, and dispatch logic
│   │   ├── twilio_sender.py          # Twilio SMS client wrapper (offline fallback safe)
│   │   ├── push_service.py           # Web Push (VAPID + pywebpush) delivery service
│   │   ├── rl_policy.py              # LinUCB contextual bandit priority recommendation
│   │   ├── active_learning.py        # Active learning retraining loop from human feedback
│   │   ├── firms_scheduler.py        # APScheduler background fetcher for FIRMS NRT
│   │   └── routers/                  # API endpoint controllers
│   │       ├── __init__.py           # Package marker
│   │       ├── alerts.py             # Alert listing, reviews, transition, feedback, notify
│   │       ├── dev.py                # Dev/re-ingest, live detection injection, retrain
│   │       ├── health.py             # System health check endpoint (/api/health)
│   │       ├── needs.py              # Citizen SOS/need reporting (rate-limited)
│   │       ├── polygons.py           # OSM polygon GeoJSON listing
│   │       ├── push.py               # VAPID public key and browser subscription endpoints
│   │       └── sites.py              # Site registry, thermal behavior, visual evidence, imagery
│   ├── keys/                         # Cryptographic keys
│   │   └── vapid.json                # Generated VAPID private and public key pair
│   ├── models/                       # Git-tracked/persisted model weights
│   │   ├── clf.pkl                   # Weak-label RF model binary
│   │   ├── cnn_visual.pkl            # Classical CV visual RF binary
│   │   └── rl_policy.pkl             # Contextual bandit state binary
│   └── tests/                        # 14 Pytest test suites (90 tests total)
│       ├── test_alert_reviews.py
│       ├── test_classifier_correctness.py
│       ├── test_firms_scheduler.py
│       ├── test_phase6_frontend_api.py
│       ├── test_phase7_satellite_imagery.py
│       ├── test_phase8_cnn.py
│       ├── test_phase9_fusion.py
│       ├── test_phase10_active_learning.py
│       ├── test_phase11_rl_policy.py
│       ├── test_phase13_security.py
│       ├── test_phase14_demo_fixes.py
│       ├── test_provenance.py
│       ├── test_success_criteria.py
│       └── test_thermal_behavior.py
│
├── dashboard/                        # Control Room Web Application (Port 5173)
│   ├── Dockerfile
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.js                # Proxies /api and /data to http://127.0.0.1:8000
│   ├── public/
│   ├── dist/
│   └── src/
│       ├── main.jsx
│       ├── index.css
│       └── App.jsx                   # Primary Leaflet console, filter panel, review cards
│
├── public-app/                       # Public Safety Citizen Portal (Port 5174)
│   ├── Dockerfile
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.js                # Proxies /api to http://127.0.0.1:8000
│   ├── public/
│   ├── dist/
│   └── src/
│       ├── main.jsx
│       ├── index.css
│       └── App.jsx                   # Citizen advisory view & SOS check-in submission form
│
├── data/                             # SQLite database, seed files, and satellite chips
│   ├── thermalguard.db               # SQLite database file (WAL mode)
│   ├── firms_seed.csv                # Synthetic seed CSV (424 detections)
│   ├── firms_real.csv                # Real FIRMS VIIRS extract (gitignored)
│   ├── firms_history_jharia.csv      # Real historical CSV (693 detections)
│   ├── firms_history_korba.csv       # Real historical CSV (gitignored)
│   ├── ml_expansion_features.csv     # Extracted features for expansion model
│   ├── osm_seed.geojson              # Pre-fetched OSM industrial/agricultural polygons
│   ├── backups/                      # Phase database snapshots
│   └── imagery/                      # Sentinel-2 JPG chips organized by site ID
│
├── models/                           # Root model directory
│   └── expansion_rf_phase4d.pkl      # Phase 4D experimental research model
│
├── scripts/                          # Data extraction and offline training utilities
│   ├── build_ml_expansion_dataset.py # Builds feature CSV from historical detections
│   ├── fetch_firms.py                # Pre-fetches real FIRMS VIIRS detections
│   ├── fetch_history_jharia.py       # Pre-fetches multi-month historical data
│   ├── fetch_osm.py                  # Fetches Overpass OSM polygons for demo bboxes
│   ├── generate_seed_data.py         # Deterministic synthetic seed data generator
│   └── train_expansion_rf.py         # [BUGGY] Standalone script to train expansion RF
│
├── scratch/                          # Developer verification artifacts (gitignored)
├── docs/                             # Architecture specifications & Phase reports (Phases 0-15)
├── after_classifier.py               # [DEAD CODE] Orphaned duplicate of classifier.py
├── before_classifier.py              # [DEAD CODE] Orphaned UTF-16LE duplicate
├── check_osm.py                      # [DEAD CODE] Ad-hoc 9-line test script
├── inspect_db.py                     # Root DB inspection utility
├── inspect_db_temp.py                # [DEAD CODE] Temporary DB inspector
├── inspect_db_temp2.py               # [DEAD CODE] Temporary DB inspector
└── inspect_db_temp3.py               # [DEAD CODE] Temporary DB inspector
```

---

### 1.2 How to Run the Project (Windows & PowerShell Guide)

#### Prerequisites
- Windows 10/11 with PowerShell 5.1+ or PowerShell 7+
- Python 3.11+ (verified running on Python 3.13.2)
- Node.js 18+ and npm 9+

#### Setup Instructions
```powershell
# 1. Clone/Navigate to workspace
cd C:\Users\Asus\thermalguard

# 2. Configure Environment Variables
Copy-Item .env.example .env
# Edit .env to set your FIRMS_MAP_KEY and API_KEY if needed.

# 3. Create and Activate Virtual Environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 4. Install Backend Dependencies
pip install -r backend\requirements.txt

# 5. Generate Local Seed Data (if database or seed CSV is missing)
python scripts\generate_seed_data.py

# 6. Install Frontend Dependencies
Push-Location dashboard; npm install; Pop-Location
Push-Location public-app; npm install; Pop-Location
```

#### Launching Services (Local Development)
There are two ways to start the project:

##### Option A: Interactive Multi-Window Mode (`start_demo.ps1`)
Launches Backend, Dashboard, and Public App into 3 separate PowerShell windows:
```powershell
.\start_demo.ps1
```
*Note on `start_demo.ps1`: Line 37 contains a hardcoded path `C:\Users\Asus\thermalguard`. If running in a different directory, use Option B or edit the path.*

##### Option B: Background Dev Mode (`start_dev.ps1`)
Runs the backend in the background and launches the Vite frontends:
```powershell
.\start_dev.ps1
```

##### Option C: Manual Launch (Recommended for Development & Debugging)
Run each command in its own dedicated terminal:
```powershell
# Terminal 1: Backend API (Run from repo root with PYTHONPATH=backend)
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2: Control Room Dashboard (Port 5173)
cd dashboard
npm run dev

# Terminal 3: Public Safety Portal (Port 5174)
cd public-app
npm run dev
```

#### Port Assignments
| Service | URL | Notes |
|:---|:---|:---|
| Backend REST API | `http://127.0.0.1:8000` | OpenAPI docs at `/docs` |
| Control Room Dashboard | `http://127.0.0.1:5173` | Proxies `/api` & `/data` to port 8000 |
| Public Safety Citizen Portal | `http://127.0.0.1:5174` | Proxies `/api` to port 8000 |

#### Running Tests
To run the complete 90-test backend test suite:
```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m pytest backend/tests -v
```

---

### 1.3 Environment Variables Contract

| Variable Name | Required | Default / Fallback | Purpose & Frozen Architecture Contract |
|:---|:---:|:---|:---|
| `FIRMS_MAP_KEY` | Optional | `""` | NASA FIRMS MAP API key for querying live VIIRS NRT detections. |
| `API_KEY` | **Required** | `noctra-dev-key-2026` | Service-tier authorization secret for state mutations (`/transition`, `/feedback`, `/notify`, `/dev/*`). |
| `VITE_API_KEY` | **Required** | `noctra-dev-key-2026` | Client-side Vite environment variable passed by dashboard in `X-API-Key`. **Must match `API_KEY`!** |
| `DB_PATH` | Optional | `data/thermalguard.db` | Relative or absolute path to SQLite database. |
| `CORS_ORIGINS` | Optional | `http://localhost:5173,http://localhost:5174` | Comma-separated allowed HTTP origins for CORS headers. |
| `ENABLE_FIRMS_SCHEDULER` | Optional | `false` | When `"true"`, APScheduler starts background polling of FIRMS. |
| `ENABLE_SYNTHETIC_INGEST`| Optional | `false` | When `"true"`, re-ingests synthetic seed on backend startup. |
| `ENABLE_ML_TRAINING` | Optional | `false` | When `"true"`, runs model training on backend startup. |
| `TWILIO_SID` | Optional | `""` | Twilio Account SID. |
| `TWILIO_AUTH_TOKEN` | Optional | `""` | Twilio Auth Token. |
| `TWILIO_FROM_NUMBER` | Optional | `""` | Twilio sending phone number (E.164 format). |
| `TWILIO_TO_NUMBER` | Optional | `""` | Fallback recipient phone number for demo SMS. |
| `OPENAI_API_KEY` | **NEW** | `""` | [NEW Stage] OpenAI API key for explain-only summarization. |

---

## 2. File-by-File Verdict & NOCTRA Stage Mapping

**Verdict Definitions**:
- **KEEP**: Functions correctly as-is; minimal or zero logic change required.
- **MODIFY**: Core logic requires bug fixing, interface adaptation, or security gating.
- **MOVE**: File belongs in a different directory to preserve clean architectural boundaries.
- **REMOVE**: Dead code, unreferenced duplicate, or temporary scratch artifact.

| File Path | Verdict | NOCTRA Stage | Rationale & Required Changes |
|:---|:---:|:---|:---|
| `backend/app/__init__.py` | **KEEP** | Infrastructure | Python package marker. |
| `backend/app/main.py` | **MODIFY** | Routing / Infrastructure | **Line 101**: Fix `Path("data/imagery")` relative path bug to use `DATA_DIR / "imagery"`. Mount new explainability router. |
| `backend/app/config.py` | **MODIFY** | Infrastructure | **Line 24**: Remove weak hardcoded fallback key. Add configurations for EBM, LightGBM, and OpenAI API key. |
| `backend/app/auth.py` | **KEEP** | Routing / Security | Verifies `X-API-Key` and `Bearer` tokens on state-changing endpoints. |
| `backend/app/db.py` | **MODIFY** | Contract Storage | **Lines 220–231**: Eliminate duplicate `reset_derived_tables()` bug that fails to clear `alert_reviews`. Add schemas for `Trace` and `Evidence`. |
| `backend/app/models.py` | **MODIFY** | Frozen Contracts | Update Pydantic schemas to strictly match Event, Evidence, Site, Review, Trace contracts. |
| `backend/app/provenance.py` | **KEEP** | FIRMS/VIIRS Ingest | Shared metadata dataclass (`is_synthetic`, `source`, `ingestion_batch`). |
| `backend/app/feature_utils.py` | **KEEP** | Thermal DNA + OSM | Haversine distance, Ray-casting point-in-polygon, and boundary proximity calculation. |
| `backend/app/ingest.py` | **MODIFY** | FIRMS Ingest & Site Formation | **Lines 279–283**: **REMOVE extreme auto-dispatch!** Disallow automated notification dispatch during ingestion. |
| `backend/app/classifier.py` | **MODIFY** | Rule Classification (Live) | **Lines 159, 195**: Remove unused `in_industrial` parameter. **Lines 200–211**: Remove dead duplicate feature dictionary assignment. Decouple `fuse_evidence` into Bayesian fusion module. |
| `backend/app/ml_model.py` | **MODIFY** | EBM (Shadow) & LightGBM | Current weak-label RandomForest must be replaced or adapted into EBM shadow classifier and LightGBM severity estimator. |
| `backend/app/satellite_imagery.py` | **KEEP** | Sentinel-2 Corroboration | AWS Earth Search STAC scene search and JPEG chip fetcher with provenance tracking. |
| `backend/app/cnn_visual.py` | **MODIFY** | Sentinel-2 Corroboration | 102-dim RGB/color histogram visual feature extractor. Renaming recommended (it is classical CV, not a deep CNN). |
| `backend/app/cap.py` | **KEEP** | Twilio & Push Payload | OASIS CAP 1.2 JSON, SMS text formatter, and Web Push title/body builder. |
| `backend/app/alert_engine.py` | **MODIFY** | Routing & Human Review | **Line 5**: Clean up contradictory docstring. Ensure SMS dispatch ONLY executes after authorized human confirmation. Attach Decision Trace records. |
| `backend/app/twilio_sender.py` | **KEEP** | Twilio Dispatch | Twilio SMS API caller with safe offline logging fallback. |
| `backend/app/push_service.py` | **KEEP** | Notification Dispatch | Web Push sender using pywebpush and SECP256R1 VAPID keys. |
| `backend/app/rl_policy.py` | **KEEP** | Routing / Priority | LinUCB contextual bandit priority tier recommender (`routine`, `watch`, `urgent`). |
| `backend/app/active_learning.py` | **MODIFY** | Human Review Feedback | Human feedback retraining trigger and correction diversity analysis; logs to `audit/active_learning_log.txt`. |
| `backend/app/firms_scheduler.py` | **MODIFY** | FIRMS/VIIRS Ingest | **Lines 87, 105**: Remove duplicate `_iso()` function. **Line 18**: Remove redundant `load_dotenv()`. **Lines 110–184**: Remove dead `_ingest_rows()` function. |
| `backend/app/routers/health.py` | **KEEP** | Infrastructure | Health check endpoint returning database counts. |
| `backend/app/routers/sites.py` | **MODIFY** | Site Formation & Thermal DNA | Move thermal DNA calculations (`_compute_frp_trend`, `_compute_expansion_magnitude`) into `feature_utils.py` or dedicated module; keep router clean. |
| `backend/app/routers/alerts.py` | **MODIFY** | Routing & Human Review | **Lines 60–67**: **MODIFY `/notify` endpoint** to enforce that alert status is `confirmed` before dispatching. |
| `backend/app/routers/dev.py` | **MODIFY** | Ingestion & Dev | Guard or disable runtime detection injection that triggers extreme auto-dispatch. |
| `backend/app/routers/needs.py` | **KEEP** | Citizen Review / Needs | Citizen SOS submission with 5 req/60s IP rate limiting. |
| `backend/app/routers/polygons.py`| **KEEP** | Thermal DNA + OSM | Serves OSM land-use polygons. |
| `backend/app/routers/push.py` | **KEEP** | Notification Setup | Serves VAPID public key and receives browser push subscriptions. |
| `backend/smoke_test.py` | **MOVE** | Test / Verification | Move to `scripts/smoke_test.py` and fix `sys.path` import bug (`Path(__file__).parent` instead of `parent.parent`). |
| `backend/debug_regions.py` | **REMOVE** | Dead Code | Unused debug script containing hardcoded absolute Windows path (`C:\Users\Asus\...`). |
| `backend/keys/vapid.json` | **KEEP** | Notification Keys | Auto-generated VAPID key pair (gitignored). |
| `backend/models/clf.pkl` | **REMOVE** | Legacy Artifact | Weak-label RF binary; replace with EBM shadow artifact. |
| `backend/models/cnn_visual.pkl` | **KEEP** | Sentinel-2 Corroboration | Classical CV visual RF classifier weights. |
| `backend/models/rl_policy.pkl` | **KEEP** | Routing / Priority | LinUCB contextual bandit model parameters. |
| `backend/tests/test_*.py` (14 files)| **KEEP** | Verification | All 14 test modules (90 tests) currently pass 100%. |
| `dashboard/src/App.jsx` | **MODIFY** | Frontend / Human Review | **Line 5**: Fix `VITE_API_KEY` handling. Add Decision Trace inspector panel and Bayesian posterior visualization. |
| `dashboard/vite.config.js` | **KEEP** | Frontend Infrastructure | Proxies `/api` and `/data` to port 8000. |
| `dashboard/package.json` | **KEEP** | Frontend Dependencies | React 18, Leaflet, Axios, Vite. |
| `public-app/src/App.jsx` | **MODIFY** | Frontend / Citizen Portal | Add OpenAI explain-only advisory cards for citizens. |
| `public-app/vite.config.js` | **KEEP** | Frontend Infrastructure | Proxies `/api` to port 8000. |
| `public-app/package.json` | **KEEP** | Frontend Dependencies | React 18, Axios, Vite. |
| `scripts/fetch_firms.py` | **KEEP** | FIRMS Ingest | Tool to query live NASA FIRMS API. |
| `scripts/fetch_history_jharia.py`| **KEEP** | Historical Data Ingest | Pre-fetches Jharia coalfield historical records. |
| `scripts/fetch_osm.py` | **KEEP** | OSM Land-Use Ingest | Overpass API fetcher for demo bounding boxes. |
| `scripts/generate_seed_data.py`| **KEEP** | FIRMS / Ingest Seed | Generates deterministic synthetic VIIRS detections. |
| `scripts/build_ml_expansion_dataset.py` | **KEEP** | Thermal DNA / Research | Offline dataset builder for expansion analysis. |
| `scripts/train_expansion_rf.py`| **MODIFY** | Research / Thermal DNA | **Line 56**: Fix `return valid` global variable reference bug in `convert_feature_columns()`. |
| `models/expansion_rf_phase4d.pkl`| **REMOVE** | Research Artifact | Unused offline 24h expansion RF model. |
| `audit/check_consec_db.py` | **REMOVE** | Broken Script | **Line 34**: Fails on missing `month` column in `sites` table. |
| `audit/check_label_changes.py`| **REMOVE** | Broken Script | **Line 19**: Fails with `AssertionError` on current real/synthetic dataset. |
| `audit/check_provenance.py` | **MODIFY** | Audit Utility | **Lines 10–13**: Stop printing plaintext `FIRMS_MAP_KEY` to stdout. |
| `audit/*.py` (other 5 scripts) | **KEEP** | Audit Utilities | Diagnostic audit scripts. |
| `after_classifier.py` | **REMOVE** | Dead Code | Orphaned duplicate of `classifier.py` in root with unresolvable relative imports. |
| `before_classifier.py` | **REMOVE** | Dead Code | Orphaned legacy duplicate encoded in UTF-16LE. |
| `check_osm.py` | **REMOVE** | Dead Code | 9-line test script in root with hardcoded absolute path. |
| `inspect_db.py` | **MOVE** | Diagnostic Utility | Move from root to `scripts/inspect_db.py`. |
| `inspect_db_temp*.py` (3 files)| **REMOVE** | Dead Code | Temporary root inspection scripts from earlier dev phases. |
| `start_demo.ps1` | **MODIFY** | Deployment | **Line 37**: Replace hardcoded `C:\Users\Asus\thermalguard` with `$PSScriptRoot`. |
| `start_dev.ps1` | **MODIFY** | Deployment | **Line 23**: Run uvicorn from root with `PYTHONPATH=backend` so `data/imagery` static path mounts correctly. |

---

## 3. NEW: NOCTRA Stages With No Existing Implementation

The following 6 stages from the frozen architecture have **zero or strictly partial** implementation in the current repository:

```text
[NEW STAGE GAP MATRIX]
┌───────────────────────────────────────────────┬─────────────────────────┬─────────────────────────┐
│ NOCTRA Frozen Architecture Stage              │ Codebase Current State  │ Required New Components │
├───────────────────────────────────────────────┼─────────────────────────┼─────────────────────────┤
│ 1. EBM (Shadow) Classification                │ ❌ MISSING              │ InterpretML EBM model   │
│ 2. LightGBM Severity + Hysteresis             │ ❌ MISSING              │ LightGBM + State Filter │
│ 3. EWMA + CUSUM Temporal Anomaly Detection    │ ❌ MISSING              │ Dynamic Time-Series Math│
│ 4. Bayesian Fusion Engine                     │ ❌ MISSING              │ Posterior Probability   │
│ 5. Decision Trace Contract & Pipeline DAG     │ ❌ MISSING              │ Trace DB Table & Logger │
│ 6. OpenAI Explain-Only Layer                  │ ❌ MISSING              │ LLM Explainer Service   │
└───────────────────────────────────────────────┴─────────────────────────┴─────────────────────────┘
```

### Detailed Breakdown of Missing Stages:

#### 1. EBM (Explainable Boosting Machine) Shadow Classification (Stage 4 Shadow)
- **Gap**: The current ML layer (`backend/app/ml_model.py`) is a weak-label `RandomForestClassifier` trained on the rule engine's outputs. There is no Explainable Boosting Machine (e.g. from Microsoft's `interpret` library).
- **Specification Needed**:
  - Add `interpret>=0.6.0` to `backend/requirements.txt`.
  - Create `backend/app/ebm_shadow.py` to train an `ExplainableBoostingClassifier`.
  - Wire shadow inference alongside `classifier.py:classify()`, outputting local feature importances (additive contributions) into the Decision Trace without overriding the live rule decision.

#### 2. LightGBM Severity + Hysteresis (Stage 5)
- **Gap**: Severity is currently evaluated purely through static rule-based thresholds on FRP (`classifier.py:123` and `config.py:45`: `<15 minor`, `15–40 moderate`, `40–100 severe`, `>=100 extreme`). There is no LightGBM model and no hysteresis mechanism to prevent alert flapping.
- **Specification Needed**:
  - Add `lightgbm>=4.3.0` to `backend/requirements.txt`.
  - Create `backend/app/severity_model.py` trained on multi-attribute features (FRP, brightness, persistence, duty cycle, expansion rate).
  - Implement a bi-directional hysteresis filter: an alert cannot downgrade severity until metric drops below threshold $-\, \Delta_{down}$ for $N$ consecutive passes, preventing oscillating alert statuses.

#### 3. EWMA + CUSUM Temporal Anomaly & Drift Detection (Stage 6)
- **Gap**: FRP trends are currently evaluated via a crude split-half mean comparison (`sites.py:37` `_compute_frp_trend`). There is no continuous statistical time-series monitoring.
- **Specification Needed**:
  - Create `backend/app/temporal_cusum.py`.
  - Implement **EWMA** ($S_t = \lambda Y_t + (1 - \lambda) S_{t-1}$) to track smoothed background thermal intensity.
  - Implement tabular **CUSUM** ($C_t^+ = \max(0, C_{t-1}^+ + Y_t - \mu_0 - K)$) to detect sudden structural upward shifts (e.g., active flare-up or rapid perimeter expansion).

#### 4. Bayesian Fusion (Stage 8)
- **Gap**: `classifier.py:346` defines `fuse_evidence()`, which performs simple string comparison (`corroborating`, `conflicting`, `none`) between the rule output and the visual classifier output. In the current dataset, 19 of 31 real sites (61.3%) are marked conflicting because the classical visual model has low precision ($P=0.25$).
- **Specification Needed**:
  - Replace heuristic matching with formal Bayesian fusion in `backend/app/bayesian_fusion.py`:
    $$\mathcal{P}(C_k \mid T, V) = \frac{\mathcal{P}(V \mid C_k) \mathcal{P}(C_k \mid T)}{\sum_j \mathcal{P}(V \mid C_j) \mathcal{P}(C_j \mid T)}$$
  - Model optical likelihood conditioned on cloud cover percentage and calibrated error matrices.

#### 5. Decision Trace (Stage 12)
- **Gap**: No `traces` table or end-to-end trace object exists. `alert_reviews` only logs status transition notes and thumbs feedback. It does not record the raw detection event IDs, intermediate model scores, shadow EBM outputs, Bayesian posteriors, or Twilio message SIDs.
- **Specification Needed**:
  - Create `decision_traces` table in `backend/app/db.py`.
  - Build `backend/app/trace.py` to record an immutable JSON execution DAG for every alert from initial FIRMS detection to final dispatch.

#### 6. OpenAI Explain-Only Layer
- **Gap**: No OpenAI SDK or endpoint exists in the codebase.
- **Specification Needed**:
  - Create `backend/app/services/openai_explainer.py`.
  - Expose `GET /api/alerts/{id}/explanation`.
  - **Strict Constraint**: Explain-only. The layer generates human-readable explanations of the `Evidence` and `Decision Trace` for operators and citizens. It has zero authority to mutate database state or trigger notifications.

---

## 4. Existing DB Schemas vs. Frozen Contracts

NOCTRA requires five frozen contract entities: **Event, Evidence, Site, Review, and Trace**.

```text
[SCHEMA COMPLIANCE MATRIX]
┌──────────┬─────────────────────────────┬───────────┬──────────────────────────────────────────────┐
│ Contract │ Existing SQLite Table       │ Status    │ Conflicts & Gaps                             │
├──────────┼─────────────────────────────┼───────────┼──────────────────────────────────────────────┤
│ Event    │ detections                  │ PARTIAL   │ Named 'detections'; lacks UUID 'event_id'.   │
│ Evidence │ (In-memory + split columns) │ CONFLICT  │ No table or JSON blob; split into free text. │
│ Site     │ sites                       │ MATCH     │ Strong match; lacks 'trace_id' foreign key.  │
│ Review   │ alert_reviews               │ MATCH     │ Strong match; lacks event linkage.           │
│ Trace    │ NONE                        │ ❌ ABSENT │ No table, schema, or trace ID in DB.         │
└──────────┴─────────────────────────────┴───────────┴──────────────────────────────────────────────┘
```

### Detailed Contract Analysis:

#### 1. Event Contract vs. `detections` Table (`backend/app/db.py:28–47`)
- **Existing Schema**:
  ```sql
  CREATE TABLE IF NOT EXISTS detections (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      latitude REAL NOT NULL, longitude REAL NOT NULL,
      bright_ti4 REAL, scan REAL, track REAL,
      acq_date TEXT NOT NULL, acq_time TEXT,
      satellite TEXT, instrument TEXT, confidence REAL, version TEXT,
      bright_ti5 REAL, frp REAL DEFAULT 0, daynight TEXT,
      is_synthetic INTEGER DEFAULT 1, source TEXT DEFAULT 'synthetic',
      ingestion_batch TEXT
  );
  CREATE UNIQUE INDEX uq_detection_natural_key 
      ON detections(latitude, longitude, acq_date, acq_time, satellite);
  ```
- **Matches**: Contains complete VIIRS sensor telemetry, acquisition timestamps, spatial coordinates, and provenance attributes.
- **Conflicts & Gaps**:
  - Table is named `detections` instead of `events`.
  - Uses SQLite integer auto-increment `id` rather than a standard natural-key UUID `event_id`.
  - Linked to sites via join table `site_detections(site_id, detection_id)`.

#### 2. Evidence Contract vs. Existing Schema
- **Existing Schema**: **No dedicated Evidence table exists.**
- **Current Storage**: Evidence is an in-memory Python dataclass (`classifier.py:Evidence`) whose attributes are partially flattened across `sites` columns (`explanation`, `classification`, `confidence`, `severity`, `is_anomalous`, `duty_cycle_pct`, `d_industrial_m`, `d_agri_m`, `d_residential_m`) and `alerts.cap_json`.
- **Conflicts & Gaps**:
  - No structured JSON evidence object stored in DB.
  - Optical evidence (`visual_evidence`, `cnn_confidence`) is dynamically computed on read via `routers/sites.py:_attach_visual_evidence()` rather than persisted upon evaluation.
  - Required: Store an explicit `evidence_json` column in `sites` or a dedicated `evidence` table linked to `trace_id`.

#### 3. Site Contract vs. `sites` Table (`backend/app/db.py:49–72`)
- **Existing Schema**:
  ```sql
  CREATE TABLE IF NOT EXISTS sites (
      site_id TEXT PRIMARY KEY,
      lat REAL NOT NULL, lon REAL NOT NULL,
      classification TEXT NOT NULL DEFAULT 'other',
      confidence REAL DEFAULT 0, explanation TEXT DEFAULT '',
      severity TEXT DEFAULT 'minor', is_anomalous INTEGER DEFAULT 0,
      status TEXT DEFAULT 'routine',
      first_seen TEXT, last_seen TEXT,
      max_frp REAL DEFAULT 0, brightness REAL DEFAULT 0,
      persistence INTEGER DEFAULT 0, consec_days INTEGER DEFAULT 0,
      duty_cycle_pct REAL DEFAULT 0,
      d_industrial_m REAL, d_agri_m REAL, d_residential_m REAL,
      coverage_status TEXT DEFAULT 'unknown',
      last_pass_date TEXT, days_since_last_pass INTEGER
  );
  ```
- **Matches**: High fidelity match to NOCTRA Site entity. Generates consistent IDs (`TG-{lat*1000}-{lon*1000}`), tracks spatial bounding metrics, persistence, and coverage.
- **Conflicts & Gaps**:
  - Lacks a `trace_id` referencing the active Decision Trace.
  - Does not store historical FRP arrays needed for EWMA/CUSUM state evaluation without re-querying `detections`.

#### 4. Review Contract vs. `alert_reviews` Table (`backend/app/db.py:95–107`)
- **Existing Schema**:
  ```sql
  CREATE TABLE IF NOT EXISTS alert_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      alert_id INTEGER NOT NULL, site_id TEXT NOT NULL,
      action TEXT NOT NULL, previous_status TEXT, new_status TEXT NOT NULL,
      analyst_note TEXT, reviewed_by TEXT DEFAULT 'analyst',
      feedback_label TEXT, created_at TEXT NOT NULL,
      FOREIGN KEY (alert_id) REFERENCES alerts(id)
  );
  ```
- **Matches**: Append-only audit log tracking operator status changes (`confirm`, `dismiss`), analyst notes, operator ID, and thumbs feedback (`correct`/`incorrect`).
- **Conflicts & Gaps**:
  - Does not link back to raw `detection_id` / `event_id`.
  - Operator overrides only support binary classification feedback (`correct`/`incorrect`), lacking structured override fields (e.g. changing class from `industrial_fire` to `wildfire`).

#### 5. Trace Contract vs. Existing Schema
- **Existing Schema**: **COMPLETELY ABSENT.**
- **Conflicts & Gaps**: There is no table, schema, or model representing `Trace`. To trace an alert today, an operator must manually piece together `detections` -> `site_detections` -> `sites` -> `alerts` -> `alert_reviews`. A formal `decision_traces` table is required.

---

## 5. Alert / SMS / Notification Audit: Human Confirmation Gating

> [!CAUTION]
> **CRITICAL ARCHITECTURAL VIOLATIONS DISCOVERED**:
> The frozen architecture strictly dictates: **"Twilio (only after authorised confirmation)"**.
> In the current codebase, **two distinct pathways trigger real notifications without human confirmation**.

```text
[NOTIFICATION CALL SITES & CONFIRMATION GATING]
┌──────────────────────────────────────┬────────────────────────┬──────────────────────────────────────────┐
│ Call Site Location                   │ Channel                │ Human Confirmation Status                │
├──────────────────────────────────────┼────────────────────────┼──────────────────────────────────────────┤
│ 1. ingest.py:279–283                 │ SMS + Web Push         │ ❌ BYPASSED (Auto-fires on 'extreme')    │
│ 2. routers/alerts.py:60–67 (/notify) │ SMS + Web Push         │ ❌ BYPASSED (Manual trigger on any state)│
│ 3. alert_engine.py:89–91             │ SMS + Web Push         │ ✅ GATED (Requires 'confirm' action)     │
└──────────────────────────────────────┴────────────────────────┴──────────────────────────────────────────┘
```

### Complete Inventory of Notification Call Sites:

#### Call Site 1: Auto-Dispatch on "Extreme" Severity Ingestion
- **File**: `backend/app/ingest.py`
- **Lines**: 279–283 (inside `trigger_runtime_detection()`)
- **Code**:
  ```python
  created = _ensure_alert(sid, severity)
  if created and severity == "extreme":
      from .alert_engine import dispatch_public
      alert = dict(db.query("SELECT * FROM alerts WHERE site_id=? AND status='alert_triggered' "
                            "ORDER BY id DESC LIMIT 1", (sid,))[0])
      dispatch_public(alert, site)
  ```
- **Analysis**: If a detection has FRP $\ge 100$ MW (default is 120.0 MW), `dispatch_public()` is called immediately upon ingestion. This directly triggers `send_sms()` and `send_push()` without any operator ever seeing or confirming the alert in the console.
- **Required Fix**: Delete lines 279–283. All alerts must stay in `alert_triggered` state until an authorized human executes a transition.

#### Call Site 2: Unverified Manual Notify Endpoint (`/api/alerts/{id}/notify`)
- **File**: `backend/app/routers/alerts.py`
- **Lines**: 60–67
- **Code**:
  ```python
  @router.post("/{alert_id}/notify", response_model=dict, dependencies=[Depends(verify_api_key)])
  def notify(alert_id: int) -> dict:
      """Manually re-fire SMS + Web Push for an alert (rehearsal / retry)."""
      rows = alert_engine.get_alerts()
      for a in rows:
          if a["id"] == alert_id:
              return alert_engine.dispatch_public(a)
      raise HTTPException(404, "alert not found")
  ```
- **Analysis**: Intended as a rehearsal/retry endpoint, it checks only that the caller has a valid `API_KEY`. It **does not check** `a["status"] == "confirmed"`. An automated script or rogue caller can trigger real SMS and Web Push for `dismissed` or unreviewed `alert_triggered` alerts.
- **Required Fix**: Add guard: `if a["status"] != "confirmed": raise HTTPException(400, "Alert must be confirmed by an analyst before dispatch.")`.

#### Call Site 3: Authorized Human Confirmation Transition (Compliant Gate)
- **File**: `backend/app/alert_engine.py`
- **Lines**: 50–91 (inside `update_alert_status()`)
- **Code**:
  ```python
  status = "confirmed" if action == "confirm" else "dismissed"
  ...
  dispatched = {}
  if status == "confirmed":
      dispatched = dispatch_public(alert)
  return {"alert": _as_dict(alert), "dispatched": dispatched}
  ```
- **Analysis**: This is the intended compliant path. It is triggered by `POST /api/alerts/{id}/transition` with `{"action": "confirm"}` and requires `verify_api_key`. It records an append-only audit record in `alert_reviews` and then dispatches notifications.

#### Actual Dispatch Execution: `dispatch_public`
- **File**: `backend/app/alert_engine.py`
- **Lines**: 137–150
- **Code**:
  ```python
  def dispatch_public(alert: dict, site: dict | None = None) -> dict:
      ...
      sms = send_sms(cap_to_sms_text(cap))           # Line 147 -> twilio_sender.py
      push = send_push(cap_to_push_title(cap), ...)  # Line 148 -> push_service.py
      db.execute("UPDATE alerts SET public_notified=1 WHERE id=?", (alert["id"],))
      return {"sms": sms, "push": push}
  ```

---

## 6. Hard-Coded Secrets, Broken Tests, Dead Code & Known Bugs

### 6.1 Hard-Coded Secrets & Credential Exposures

| File Path | Line(s) | Description | Risk Level |
|:---|:---:|:---|:---:|
| `.env` | 4 | Real active NASA FIRMS API key `2fd3555411611a98e9d17e083b7a0965` present on local disk. | **HIGH** |
| `.env` | 15 | Active secret API key `noctra-sec-f6576628d2e5d5791d3bd191bab05724` stored in local file. | **MEDIUM** |
| `backend/app/config.py` | 24 | Default hardcoded fallback secret: `os.getenv("API_KEY", "noctra-dev-key-2026")`. | **MEDIUM** |
| `dashboard/src/App.jsx` | 5 | Hardcoded fallback API key baked into client bundle: `import.meta.env.VITE_API_KEY \|\| "noctra-dev-key-2026"`. | **HIGH** |
| `backend/keys/vapid.json` | 2–3 | Raw SECP256R1 VAPID private and public key pair stored in repository filesystem. | **MEDIUM** |
| `backend/app/push_service.py` | 20 | Hardcoded subject claim: `VAPID_SUBJECT = "mailto:thermalguard@district-control.gov.in"`. | **LOW** |
| `backend/app/cap.py` | 57 | Hardcoded sender email: `"sender": "thermalguard@district-control.gov.in"`. | **LOW** |
| `audit/check_provenance.py` | 10–13 | Leaks/prints raw plaintext `FIRMS_MAP_KEY` from `.env` to console stdout. | **MEDIUM** |

---

### 6.2 Broken Tests & Broken Diagnostic Scripts

| File Path | Line(s) | Failure Symptom & Cause |
|:---|:---:|:---|
| `audit/check_consec_db.py` | 34 | **Crash (`sqlite3.OperationalError: no such column: month`)**: Queries `SELECT ... month FROM sites`, but `sites` table has no `month` column. |
| `audit/check_label_changes.py` | 19 | **Crash (`AssertionError`)**: Asserts Jharia dominant classification is `industrial_fire`, but current database contains 19 `other` and 10 `industrial_fire`, failing the assertion. |
| `backend/smoke_test.py` | 7–9 | **ImportError**: Inserts repository root into `sys.path` and attempts `from app.ingest import ingest`. Fails when executed from root because `app` is inside `backend/`. |

*(Note: The main test suite in `backend/tests/` currently passes 90/90 tests cleanly).*

---

### 6.3 Known Bugs & Inconsistencies

1. **Duplicate Function Bug in `backend/app/db.py:205–231`**:
   `reset_derived_tables()` is defined at line 205 (which correctly includes `DELETE FROM alert_reviews`), and then immediately redefined at line 220 without `alert_reviews`. The second definition overrides the first, leaving stale review records in the DB during re-ingestion.
2. **Static Imagery Mount Path Failure in `backend/app/main.py:101`**:
   `imagery_dir = Path("data/imagery")` uses a relative path instead of `DATA_DIR / "imagery"`. When running backend from the `backend/` working directory (as in `start_dev.ps1:23`), `Path("data/imagery").exists()` evaluates to `False`, silently disabling satellite chip delivery!
3. **Frontend/Backend API Key Mismatch in `dashboard/src/App.jsx:5` vs `.env:15`**:
   Vite only exposes environment variables prefixed with `VITE_` to client code. `.env` sets `API_KEY=noctra-sec-...` but does not define `VITE_API_KEY`. As a result, the browser sends the fallback key `noctra-dev-key-2026`, causing 401 Unauthorized errors on transitions when `.env` has a custom key.
4. **Duplicate Function in `backend/app/firms_scheduler.py:87 & 105`**:
   `_iso(d: str, t: str)` is defined twice identically at lines 87 and 105. Line 105 silently overwrites line 87.
5. **Redundant `load_dotenv()` in `backend/app/firms_scheduler.py:18`**:
   Calls `load_dotenv()` with default working directory, conflicting with `config.py:10` which explicitly loads `ROOT / ".env"`.
6. **Dead Parameter in `backend/app/classifier.py:159, 195`**:
   `_spatial_evidence(d_ind: float, in_industrial: bool)` receives `in_industrial`, but lines 161–165 only check `d_ind == 0.0`. The parameter is unused.
7. **Dead Assignment in `backend/app/classifier.py:200–211 & 306–320`**:
   The `features` dictionary is built at lines 200–211 and then completely re-assigned and overwritten at lines 306–320.
8. **Global Variable Leak in `scripts/train_expansion_rf.py:56`**:
   Inside `convert_feature_columns(df)`, the function concludes with `return valid` instead of `return df`, referencing a global dataframe.
9. **Hardcoded Machine Path in `start_demo.ps1:37`**:
   Hardcodes `C:\Users\Asus\thermalguard` in the PowerShell startup string.

---

### 6.4 Dead & Orphaned Code

- `after_classifier.py` (Repo Root): 14 KB unimported duplicate of `classifier.py` containing relative imports that crash if run.
- `before_classifier.py` (Repo Root): 28 KB UTF-16LE encoded legacy duplicate of `classifier.py`.
- `check_osm.py` (Repo Root): 9-line ad-hoc script with hardcoded machine path.
- `inspect_db_temp.py`, `inspect_db_temp2.py`, `inspect_db_temp3.py` (Repo Root): Temporary diagnostic scripts.
- `backend/debug_regions.py`: 21-line debug script with hardcoded file path.
- `backend/scripts/`: Empty directory.
- `backend/app/firms_scheduler.py:110–184`: Dead duplicate `_ingest_rows()` function (actual ingestion is handled by `ingest.py`).
- `models/expansion_rf_phase4d.pkl`: 24h expansion RF model artifact that is not imported or served by any API route.

---

## 7. Proposed Ownership Matrix & Merge-Conflict Risk Analysis

To ensure rapid, collision-free development across three engineers, file ownership is partitioned by domain responsibility:
- **P1: Intelligence** (Sensors, Thermal DNA, Rules, ML/EBM, LightGBM, EWMA/CUSUM)
- **P2: Backend + Fusion + Twilio + Trace** (Database, Schemas, Bayesian Fusion, Dispatch Gating, Twilio, Decision Trace, API Routes)
- **P3: Frontend + OpenAI** (Console Dashboard, Public Portal, OpenAI Explain-Only Integration)

```text
[THREE-ENGINEER OWNERSHIP MAP]
┌───────────────────────────────────────┬───────────┬──────────────────────────────────────────┐
│ Subsystem / File Area                 │ Owner     │ Responsibilities                         │
├───────────────────────────────────────┼───────────┼──────────────────────────────────────────┤
│ FIRMS / Ingest / Seed Scripts         │ P1        │ Raw data parsing, clustering, seeding    │
│ Thermal DNA / Spatial Geometry        │ P1        │ feature_utils.py, FRP & temporal stats   │
│ Rule Classifier & EBM Shadow          │ P1        │ classifier.py, ebm_shadow.py             │
│ Severity Model & Hysteresis           │ P1        │ LightGBM severity, hysteresis state      │
│ EWMA & CUSUM Change Detection         │ P1        │ Time-series drift detection math         │
│ Sentinel-2 Chip Pipeline & Features   │ P1        │ satellite_imagery.py, cnn_visual.py      │
│                                       │           │                                          │
│ DB Schemas, Migrations & Contracts    │ P2        │ db.py, models.py, SQLite transactions    │
│ Bayesian Fusion Engine                │ P2        │ bayesian_fusion.py (probabilistic update)│
│ Decision Trace Logger & DAG           │ P2        │ trace.py, decision_traces schema         │
│ Alert Engine & Dispatch Gating        │ P2        │ alert_engine.py, human review gate       │
│ Twilio SMS & Web Push Services        │ P2        │ twilio_sender.py, push_service.py        │
│ API Routers & Key Authentication      │ P2        │ routers/*, auth.py, main.py lifespan     │
│ APScheduler Daemon                    │ P2        │ firms_scheduler.py                       │
│                                       │           │                                          │
│ Control Room Dashboard (Port 5173)    │ P3        │ dashboard/src/* (React/Leaflet/Console)  │
│ Public Safety Citizen Portal (5174)   │ P3        │ public-app/src/* (Citizen UI / SOS)      │
│ OpenAI Explain-Only Integration       │ P3        │ openai_explainer.py, explain router      │
│ UI Build & Client Bundling            │ P3        │ vite.config.js, package.json             │
└───────────────────────────────────────┴───────────┴──────────────────────────────────────────┘
```

---

### Detailed File Ownership Assignments

| File Path | Primary Owner | Secondary / Reviewer | Domain Scope |
|:---|:---:|:---:|:---|
| `backend/app/classifier.py` | **P1** | P2 | Rule precedence, evidence extraction |
| `backend/app/feature_utils.py` | **P1** | P2 | Spatial containment & proximity |
| `backend/app/ml_model.py` | **P1** | P2 | Upgrade to EBM shadow classifier |
| `backend/app/ebm_shadow.py` *(NEW)* | **P1** | P2 | Explainable Boosting Machine implementation |
| `backend/app/severity_model.py` *(NEW)* | **P1** | P2 | LightGBM severity rating + hysteresis |
| `backend/app/temporal_cusum.py` *(NEW)* | **P1** | P2 | EWMA baseline & CUSUM drift detection |
| `backend/app/satellite_imagery.py` | **P1** | P2 | STAC scene queries and image downloading |
| `backend/app/cnn_visual.py` | **P1** | P2 | Classical CV visual feature extractor |
| `scripts/*` (all scripts) | **P1** | P2 | Ingestion and offline training tools |
| `backend/app/db.py` | **P2** | P1 | SQLite tables, Event, Site, Review, Trace |
| `backend/app/models.py` | **P2** | P1/P3 | Pydantic contracts and schemas |
| `backend/app/auth.py` | **P2** | P3 | API key security validation |
| `backend/app/trace.py` *(NEW)* | **P2** | P1/P3 | Decision Trace logger & audit DAG |
| `backend/app/bayesian_fusion.py` *(NEW)*| **P2** | P1 | Bayesian posterior calculation |
| `backend/app/alert_engine.py` | **P2** | P3 | Notification gating and status lifecycle |
| `backend/app/twilio_sender.py` | **P2** | - | Twilio SMS API integration |
| `backend/app/push_service.py` | **P2** | P3 | Web Push delivery |
| `backend/app/cap.py` | **P2** | P3 | CAP 1.2 payload generation |
| `backend/app/rl_policy.py` | **P2** | P1 | LinUCB routing priority bandit |
| `backend/app/firms_scheduler.py` | **P2** | P1 | APScheduler background worker |
| `backend/app/routers/alerts.py` | **P2** | P3 | Alert endpoints & notify gating |
| `backend/app/routers/sites.py` | **P2** | P1/P3 | Site endpoints |
| `backend/app/routers/dev.py` | **P2** | P1 | Ingest & test endpoints |
| `backend/app/routers/health.py` | **P2** | - | Health checks |
| `backend/app/routers/needs.py` | **P2** | P3 | Citizen need records |
| `backend/app/routers/push.py` | **P2** | P3 | Push subscription management |
| `backend/app/main.py` | **P2** | P3 | App lifespan, router mounting, static routes |
| `dashboard/` (all files) | **P3** | P2 | Control room console, Leaflet, review cards |
| `public-app/` (all files) | **P3** | P2 | Citizen emergency portal, SOS form |
| `backend/app/services/openai_explainer.py` *(NEW)* | **P3** | P2 | OpenAI prompt generation and execution |
| `backend/app/routers/explain.py` *(NEW)* | **P3** | P2 | Explain-only API endpoint |

---

### Critical Merge-Conflict Hotspots & Prevention Protocol

Four files are flagged as **high merge-conflict risks** because they sit on the boundaries between P1, P2, and P3:

```text
[HIGH-RISK CONFLICT HOTSPOTS]
1. backend/app/classifier.py    ◄─── [P1 rules/EBM vs P2 fusion output]
2. backend/app/db.py            ◄─── [P2 trace/review vs P1 EBM/LGBM columns]
3. backend/app/routers/sites.py ◄─── [P1 thermal DNA vs P2 API router vs P3 UI fields]
4. backend/app/main.py          ◄─── [P2 lifespan/wiring vs P3 new explain router]
```

#### Hotspot 1: `backend/app/classifier.py` (P1 vs. P2)
- **Conflict Source**: P1 will be modifying rule logic and adding EBM shadow evaluation, while P2 needs to hook in Bayesian fusion outputs.
- **Protocol**:
  - P1 exclusively owns `classifier.py`.
  - P2 must **not** edit `classifier.py`. P2 implements Bayesian fusion in a completely separate module: `backend/app/bayesian_fusion.py`.
  - The router (`routers/sites.py` or `alert_engine.py`) takes P1's `ClassResult` and passes it into P2's `bayesian_fusion.py`.

#### Hotspot 2: `backend/app/db.py` & `backend/app/models.py` (P1 vs. P2)
- **Conflict Source**: P1 needs new columns on `sites` for EBM predictions, LightGBM severity, and CUSUM status. P2 needs new tables for `decision_traces` and `evidence`.
- **Protocol**:
  - P2 has sole commit authority on `db.py` and `models.py`.
  - P1 submits requested column names and types in an issue or PR specification. P2 implements the schema migrations and exposes typed Pydantic models.

#### Hotspot 3: `backend/app/routers/sites.py` (P1 vs. P2 vs. P3)
- **Conflict Source**: `sites.py` currently mixes API routing (P2), mathematical FRP trend calculations and convex hull algorithms (P1), and UI badge attachments (P3).
- **Protocol**:
  - **Refactor before feature work**: P1 extracts `_compute_frp_trend`, `_compute_expansion_magnitude`, and `_frp_intensity` into `backend/app/feature_utils.py`.
  - `routers/sites.py` becomes a thin controller owned by P2.
  - P3 consumes the finalized API contract without modifying the Python controller.

#### Hotspot 4: `backend/app/main.py` (P2 vs. P3)
- **Conflict Source**: P2 maintains server startup, scheduler gating, and static mounts. P3 needs to register the new OpenAI explain router.
- **Protocol**:
  - P3 implements the explainability controller in `backend/app/routers/explain.py`.
  - P2 performs the single-line inclusion in `backend/app/main.py`: `app.include_router(explain.router)`.

---

## 8. Summary Checklist for Phase Execution

- [ ] **Immediate Fix**: Remove extreme auto-dispatch in `backend/app/ingest.py:279–283`.
- [ ] **Immediate Fix**: Add confirmation status check to `backend/app/routers/alerts.py:60–67` (`/notify`).
- [ ] **Immediate Fix**: Remove duplicate `reset_derived_tables()` in `backend/app/db.py:220–231`.
- [ ] **Immediate Fix**: Fix `Path("data/imagery")` static route path in `backend/app/main.py:101`.
- [ ] **Immediate Fix**: Configure `VITE_API_KEY` in `.env` and `dashboard/src/App.jsx`.
- [ ] **Immediate Cleanup**: Delete dead files (`before_classifier.py`, `after_classifier.py`, `check_osm.py`, `inspect_db_temp*.py`).
- [ ] **Schema Migration**: Add `decision_traces` table and update `Event`, `Evidence`, `Site`, `Review`, `Trace` contracts.
- [ ] **New Stage 1**: Implement EBM shadow classifier (`backend/app/ebm_shadow.py`).
- [ ] **New Stage 2**: Implement LightGBM severity + hysteresis (`backend/app/severity_model.py`).
- [ ] **New Stage 3**: Implement EWMA + CUSUM change detection (`backend/app/temporal_cusum.py`).
- [ ] **New Stage 4**: Implement Bayesian fusion engine (`backend/app/bayesian_fusion.py`).
- [ ] **New Stage 5**: Implement OpenAI explain-only service (`backend/app/services/openai_explainer.py`).
- [ ] **Frontend Update**: Add Decision Trace viewer & OpenAI explanation modal to Control Room console.

---
*End of AUDIT.md — Authoritative Upgrade Audit Report for NOCTRA*