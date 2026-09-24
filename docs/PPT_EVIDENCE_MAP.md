# NOCTRA — PPT Evidence Map (SIH26162)

**Rule**: Every slide claim must cite a file, test command, or live metric recorded in this repo. If no evidence exists → **FLAGGED — do not put on slide**.

**Session baseline**: commit `38ab7cc` · full suite **90/90 passed** (`$env:PYTHONPATH="backend"; .venv\Scripts\python.exe -m pytest backend/tests -v`)

---

## Slide claim → evidence

| # | Intended slide claim | Honest status | Exact evidence |
|---|----------------------|---------------|----------------|
| 1 | Dual-tier system: control console :5173 + public portal :5174 | OPERATIONAL (POC) | `dashboard/`, `public-app/`; `start_demo.ps1`; Phase 14 browser run |
| 2 | Uses NASA FIRMS VIIRS thermal detections | OPERATIONAL — VERIFIED | `backend/app/firms_scheduler.py`; `data` CSV provenance; detections live **1299** (875 real / 424 synth) |
| 3 | 1 km spatial clustering into persistent sites | OPERATIONAL — VERIFIED | `ingest.py` / `feature_utils.py`; live sites **161**; `test_success_criteria.py` |
| 4 | Explainable 4-class rule classifier (never overridden by ML) | OPERATIONAL — VERIFIED | `classifier.py` + `Evidence`; `test_classifier_correctness.py` **17/17** |
| 5 | FRP thermal metrics: trend, persistence, expansion | OPERATIONAL — VERIFIED | `routers/sites.py`; `test_thermal_behavior.py` **11/11** |
| 6 | OASIS CAP 1.2 alert payloads | OPERATIONAL — VERIFIED | `cap.py`; 30 alerts live; alert lifecycle tests |
| 7 | Human confirm/dismiss + analyst notes + append-only audit | OPERATIONAL — VERIFIED | `alert_reviews` table; `test_alert_reviews.py` **4/4**; **0 rows** until operators use it |
| 8 | Real Sentinel-2 optical chips for sites | OPERATIONAL (POC) | `satellite_imagery.py`; imagery DB **31 available**; `test_phase7_*` **3/3**; STAC no API key |
| 9 | Thumbnail renders in dashboard (not broken icon) | OPERATIONAL (POC) | Browser: img naturalWidth **343×343**, proxy 200 / 52908 B; `test_static_imagery_serving`; Phase 14 screenshots |
| 10 | Click alert → map pans/zooms + opens popup | OPERATIONAL (POC) | Browser 3/3 cards; `test_alert_click_to_locate_wiring`; Phase 14 screenshots |
| 11 | Visual classifier | **RESEARCH / EXPERIMENTAL** | **NOT a CNN** (weights download blocked). Classical CV RF; Acc **0.40**, Prec **0.25**, N_test_pos=**2**; `cnn_visual.py`; `test_phase8_*` |
| 12 | Thermal + visual evidence fusion | OPERATIONAL (POC) | live visual_evidence: **19 conflicting / 12 corroborating** on 31 real; `test_phase9_*` **4/4** |
| 13 | Active learning improves model | **RESEARCH / EXPERIMENTAL — null result** | Logged **Δ=+0.0000**; 89.5% duplicate corrections; `audit/active_learning_log.txt`; `test_phase10_*` |
| 14 | RL / deep reinforcement learning agent | **FLAGGED if claimed as deep RL** | Actual: **offline contextual bandit** (LinUCB) heuristic proxy; `alert_reviews=0` → **no human-feedback learning yet**; `test_phase11_*`; `rl_policy.py` disclaimer |
| 15 | Priority suggestions shown to operators | RESEARCH / EXPERIMENTAL | `suggested_priority` on `/api/alerts`; human-in-the-loop only |
| 16 | Production-grade auth / RBAC | **FLAGGED — do not claim RBAC** | Service **API key** only: 401 tests `test_phase13_*`; SOS **429** rate limit |
| 17 | SMS alerts working in demo | **FLAGGED if Twilio live** | `TWILIO_AUTH_TOKEN` empty; Web Push path exists (3 subscriptions) |
| 18 | Full test suite green | OPERATIONAL — VERIFIED | **90 passed** this session (see §18 of A-to-Z report) |
| 19 | Independent validation pass | OPERATIONAL — VERIFIED | `docs/VALIDATION_REPORT.md` (Phases 0–12) + Phase 14–15 updates |
| 20 | Git history free of secret keys | OPERATIONAL (POC) | Phase 13 scan; `.gitignore`: `.env`, `data/*.db`, `backend/keys/`, `data/imagery/` |
| 21 | Geographically general solution | **FLAGGED** | Real clusters **N=31**, Jharia-heavy; do not overclaim |
| 22 | “Implemented” without qualifier | **FLAGGED by policy** | Always use one of: NOT IMPLEMENTED / RESEARCH-EXPERIMENTAL / OPERATIONAL-POC / OPERATIONAL-VERIFIED |

---

## Metrics safe to show (measured, not estimated)

| Metric | Value | Source command/query |
|--------|-------|----------------------|
| Pytest pass count | 90/0 | `pytest backend/tests -v` 2026-09-24 |
| Detections | 1299 | `SELECT COUNT(*) FROM detections` |
| Real detections | 875 | `is_synthetic=0` |
| Synthetic detections | 424 | `is_synthetic=1` |
| Sites | 161 | `SELECT COUNT(*) FROM sites` |
| Real-only sites | 31 | provenance join query |
| Alerts | 30 | `SELECT COUNT(*) FROM alerts` |
| alert_reviews | 0 | `SELECT COUNT(*) FROM alert_reviews` |
| Imagery available | 31 | `status='available'` |
| Fusion conflict (real) | 19/31 (61.29%) | `/api/sites` visual_evidence |
| Visual model precision | 0.2500 | Phase 12 re-derivation / phase_8.md |
| Visual model accuracy | 0.4000 | same |
| Active learning delta | +0.0000 | `audit/active_learning_log.txt` |
| Unauth transition | HTTP 401 | live TestClient this session |
| SOS rate limit | 5/60s → 429 | `test_phase13_security.py` |
| Imagery thumb decode | 343×343 | Playwright Phase 14 |

---

## Explicit non-claims (do not slide)

1. “CNN deep learning visual classifier” — false; classical features + RF.
2. “RL agent trained on operator behavior” — false; heuristic-proxy bandit, 0 reviews.
3. “Model retraining improved accuracy” — false; Δ=0 measured.
4. “RBAC / OAuth production security” — false; API key only.
5. “SMS alerts configured” — false in this environment.
6. “State nationwide coverage” — false; 31 real sites, regional.

---

*Every status label above matches `docs/NOCTRA_A_TO_Z_PROJECT_REPORT.md` §22 and `docs/VALIDATION_REPORT.md`.*
