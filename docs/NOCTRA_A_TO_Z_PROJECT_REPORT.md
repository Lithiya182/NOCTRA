# NOCTRA (ThermalGuard) — A-to-Z Project Technical Audit Report

**Audit Target**: `C:\Users\Asus\thermalguard`  
**Date**: September 24, 2026 (supersedes baseline September 22, 2026)  
**Audit Type**: Live re-scan for Phases 0–15 end state (same section numbering 1–25 as baseline for direct diff)  
**Status**: COMPLETE — authoritative for SIH submission  
**Session commit**: `38ab7cc` `[Phase 14] Fix imagery static serving and alert click-to-locate — 90/90 passed`  
**Baseline tag**: `noctra-baseline-pre-master-build`

Status vocabulary (exactly four labels): `NOT IMPLEMENTED` · `RESEARCH / EXPERIMENTAL` · `OPERATIONAL (POC)` · `OPERATIONAL — VERIFIED`

---

## 1. PROJECT OVERVIEW

- **Project Name**: NOCTRA (ThermalGuard in codebase; SIH26162).
- **Purpose**: Satellite thermal anomaly detection, spatial clustering, rule-based fire source classification, risk scoring, CAP 1.2 alerting, optical imagery evidence, weak-label visual classification, evidence fusion, human review audit, active learning, contextual-bandit priority suggestions, and dual-tier public safety UIs.
- **Product Tiers**:
  1. **District Control Room Console** (`dashboard`, port 5173)
  2. **Public Safety Portal** (`public-app`, port 5174)
- **Technology Stack (live)**: Python 3.13.2, FastAPI, Uvicorn, SQLite 3 (WAL), Pydantic, Haversine, APScheduler, Twilio SDK (unconfigured), pywebpush/VAPID, scikit-learn, React 18.3 + Vite, Leaflet/react-leaflet, Axios, Docker/Compose, Pytest.
- **Architecture (current)**:
  ```
  NASA FIRMS / CSV history / synthetic seed
           │
           ▼
  ingest.py ──► SQLite (WAL) ──► 1km Haversine clustering
           │
           ▼
  Thermal metrics ──► Rule classifier + Evidence
           │                │
           │                ├─► weak-label RF (clf.pkl)
           │                ├─► Sentinel-2 imagery (STAC)
           │                ├─► classical CV visual RF (cnn_visual.pkl)
           │                ├─► fusion (visual_evidence)
           │                └─► contextual bandit (rl_policy.pkl)
           ▼
  Risk / CAP 1.2 alerts ──► FastAPI ──► Dashboard + Public portal
           │
           └─► human review (alert_reviews) ──► active learning log
  ```

---

## 2. COMPLETE REPOSITORY STRUCTURE

```
C:\Users\Asus\thermalguard
├── .env / .env.example / .gitignore
├── docker-compose.yml, start_demo.ps1, start_dev.ps1, README.md
├── audit/                    # provenance/consec/label checks + active_learning_log.txt
├── backend/
│   ├── app/
│   │   ├── main.py           # lifespan, routers, StaticFiles /data/imagery
│   │   ├── auth.py           # verify_api_key (X-API-Key / Bearer)
│   │   ├── ingest.py, classifier.py, feature_utils.py
│   │   ├── firms_scheduler.py, provenance.py, models.py, db.py, config.py
│   │   ├── alert_engine.py, cap.py, push_service.py, twilio_sender.py
│   │   ├── ml_model.py, cnn_visual.py, satellite_imagery.py, rl_policy.py
│   │   └── routers/          # alerts, sites, polygons, needs, push, dev, health
│   ├── models/               # clf.pkl, cnn_visual.pkl, rl_policy.pkl (gitignored binaries)
│   └── tests/                # 14 test modules, 90 tests
├── dashboard/                # control console (5173), /data Vite proxy
├── public-app/               # citizen portal (5174)
├── data/                     # thermalguard.db (gitignored), imagery/, CSVs (gitignored)
├── models/                   # expansion_rf_phase4d.pkl research artifact
├── docs/
│   ├── NOCTRA_A_TO_Z_PROJECT_REPORT.md   # this file
│   ├── VALIDATION_REPORT.md
│   ├── PPT_EVIDENCE_MAP.md
│   ├── PHASE_CHANGELOG.md
│   └── PHASE_REPORTS/phase_0..15.md
└── scripts/                  # seed/OSM/FIRMS/ML helpers
```

---

## 3. FRONTEND AUDIT

- **Dashboard** (`dashboard/src/App.jsx`): Leaflet map, class + provenance filters, site popups (thermal + CNN + fusion + RL badges), government alert console, analyst notes, thumbs feedback, satellite imagery panel, **click-to-locate** (alert card → `flyTo` + popup).
- **Imagery panel**: `SatelliteImageryPanel` loads `/api/sites/{id}/imagery`; thumbnails use normalized `/data/imagery/...` URLs via Vite proxy → FastAPI `StaticFiles`.
- **Public portal**: advisories + SOS/check-in form → `POST /api/needs`.
- **UI capability status (live)**:
  - Map & popups: `OPERATIONAL — VERIFIED` (browser click-through Phase 14)
  - Provenance/class filters: `OPERATIONAL — VERIFIED`
  - Alert confirm/dismiss + notes + feedback: `OPERATIONAL — VERIFIED`
  - Public SOS form: `OPERATIONAL — VERIFIED`
  - Web Push registration: `OPERATIONAL (POC)` (depends on VAPID + browser)
  - Satellite snapshot viewer: `OPERATIONAL (POC)` — browser-verified thumbs for real chips (`38ab7cc`)
  - Alert click-to-locate: `OPERATIONAL (POC)` — 3/3 browser-verified (`38ab7cc`)
  - RL priority badges on cards: `RESEARCH / EXPERIMENTAL` (displays suggestions; no real reward learning yet)

---

## 4. BACKEND AUDIT

- **App**: `backend/app/main.py` (lifespan, CORS, routers, optional FIRMS scheduler gate, static imagery mount).
- **Routers**: health, sites (+ `/imagery`), alerts (+ transition/feedback/notify/reviews), polygons, needs, push, dev (ingest/detection/retrain).
- **Auth**: `auth.verify_api_key` on all state-changing alert + dev routes; `/api/dev` router-level dependency.
- **Pipeline modules**: ingest → cluster → classify → thermal metrics → risk/CAP → optional visual/fusion/priority attach on API responses.
- **Provenance helper**: `backend/app/provenance.py` (shared `is_synthetic` / `source` / `created_at` pattern).
- **Imagery static serving**: `app.mount("/data/imagery", StaticFiles(...))` when directory exists.

---

## 5. API INVENTORY

| Method | Path | Auth | Status |
| :--- | :--- | :--- | :--- |
| GET | `/` | none | OPERATIONAL — VERIFIED |
| GET | `/api/health` | none | OPERATIONAL — VERIFIED |
| GET | `/api/sites` | none | OPERATIONAL — VERIFIED |
| GET | `/api/sites/{id}` | none | OPERATIONAL — VERIFIED |
| GET | `/api/sites/{id}/imagery` | none | OPERATIONAL (POC) |
| GET | `/api/alerts` | none | OPERATIONAL — VERIFIED |
| GET | `/api/alerts/reviews` | none | OPERATIONAL — VERIFIED |
| GET | `/api/alerts/{id}/reviews` | none | OPERATIONAL — VERIFIED |
| POST | `/api/alerts/{id}/transition` | API key / Bearer | OPERATIONAL — VERIFIED (401 without key) |
| POST | `/api/alerts/{id}/feedback` | API key / Bearer | OPERATIONAL — VERIFIED |
| POST | `/api/alerts/{id}/notify` | API key / Bearer | OPERATIONAL — VERIFIED |
| GET | `/api/polygons` | none | OPERATIONAL — VERIFIED |
| GET/POST | `/api/needs` | none; POST rate-limited 5/60s/IP | OPERATIONAL — VERIFIED (429 tested) |
| GET/POST | `/api/push/*` | none | OPERATIONAL (POC) |
| POST | `/api/dev/ingest\|detection\|retrain` | API key / Bearer | OPERATIONAL — VERIFIED (401 tested) |
| GET | `/data/imagery/{site}/{file}` | none (local static) | OPERATIONAL (POC) |

---

## 6. DATABASE

- **Tech**: SQLite 3, `PRAGMA journal_mode=wal` (confirmed live).
- **Tables**: `detections`, `sites`, `site_detections`, `alerts` (+ `analyst_note`, `reviewed_by`, `feedback_label`), `alert_reviews` (append-only), `imagery`, `needs`, `push_subscriptions`, `polygons`.
- **Key indexes**: `uq_detection_natural_key`, `idx_det_date`, `idx_sites_class`, `idx_alerts_status`, `idx_imagery_site`, `idx_alert_reviews_*`.
- **Dedup**: `INSERT OR IGNORE` + unique natural key.

---

## 7. DATA SOURCES

1. **NASA FIRMS VIIRS NRT** — CSV over HTTPS (`FIRMS_MAP_KEY`); scheduler gated by `ENABLE_FIRMS_SCHEDULER`.
2. **Historical CSVs** — `firms_history_jharia.csv` (693 real), `firms_history_korba.csv` (gitignored pattern).
3. **Real NRT extract** — `firms_real.csv` (154 real rows historically; gitignored).
4. **Synthetic seed** — `firms_seed.csv` (424 synthetic; gitignored).
5. **OSM land-use** — `data/osm_seed.geojson` (14 polygons, 4 regions).
6. **Sentinel-2 L2A** — AWS Earth Search STAC (no API key); chips under `data/imagery/` (gitignored).

---

## 8. FIRMS INGESTION

- Endpoint pattern: `.../VIIRS_SNPP_NRT/{bbox}/{days}/{date}` with `JHARIA_BBOX`.
- Confidence string mapping + numeric normalization; provenance columns on every row.
- Scheduler: `firms_scheduler.start_scheduler()` exists; **lifespan invokes only if `ENABLE_FIRMS_SCHEDULER=true`** (Phase 2).
- State file: `data/firms_last_fetch.txt`.

---

## 9. CURRENT DATA STATE

*Live SQLite query, 2026-09-24, session commit `38ab7cc`:*

| Metric | Value |
| :--- | :--- |
| Detections total | **1299** |
| Real (`is_synthetic=0`) | **875** (`firms` 182 + `firms_history` 693) |
| Synthetic | **424** (`source=synthetic`) |
| Sites total | **161** |
| Real-only sites | **31** |
| Classification | agricultural_burn **89**, other **40**, industrial_fire **20**, wildfire **12** |
| Alerts | **30** (all `alert_triggered`) |
| `alert_reviews` rows | **0** |
| Imagery rows | **31** all `status=available`, `source=sentinel2-l2a`, `is_synthetic=0` |
| Detection date range | **2025-11-10** → **2026-09-20** |
| Push subscriptions | 3 |
| Needs | 0 |

---

## 10. GEOSPATIAL PIPELINE

- WGS84 lat/lon; single-linkage Haversine clustering `CLUSTER_RADIUS_M = 1000`.
- Site IDs: `TG-{round(lat*1000)}-{round(lon*1000)}`.
- Ray-casting point-in-polygon; densified boundary distance (`step_m=150`) for nearest-polygon meters.

---

## 11. THERMAL BEHAVIOUR

Per-site (tested in `test_thermal_behavior.py`, **11/11 passed** this session):

- FRP: `max_frp`, `frp_mean`, `frp_std`, `frp_last`, intensity bands, trend (`increasing|decreasing|stable|insufficient_data`).
- Temporal: detection/active pass counts, `days_span`, persistence, `duty_cycle_pct`.
- Expansion: Graham-scan + Shoelace hull area delta (km²) within 4 km.
- Coverage status: covered / uncertain / unknown.

**Status: `OPERATIONAL — VERIFIED`**

---

## 12. CLASSIFICATION

- Precedence: `industrial_fire` → `agricultural_burn` → `wildfire` → `other`.
- Spatial (OSM polygons, `IND_DIST_M=500`), temporal (consec days, `AGR_MONTHS`), intensity (`WILDFIRE_FRP_MIN=50`) rules.
- Every decision returns `Evidence` (spatial, temporal, intensity, sufficiency, reason) + optional `visual` after Phase 9.
- Tests: `test_classifier_correctness.py` **17/17 passed**.

**Status: `OPERATIONAL — VERIFIED`** (rule engine authoritative; never overridden by ML)

---

## 13. RISK / ALERT SYSTEM

- Severity bands by FRP (minor/moderate/severe/extreme); anomalous at FRP ≥ 40 MW.
- OASIS CAP 1.2 builder (`cap.py`).
- Confirm → SMS (if Twilio configured) + Web Push; dismiss → status only.
- Live: 30 open alerts; unauthenticated transition returns **401** (tested this session).

**Status: `OPERATIONAL — VERIFIED`** (CAP path); SMS channel `NOT IMPLEMENTED` in this env (empty Twilio token).

---

## 14. HUMAN REVIEW

- `POST /api/alerts/{id}/transition` accepts optional `analyst_note`, `reviewed_by`.
- Columns on `alerts`: `analyst_note`, `reviewed_by`, `feedback_label`.
- Append-only **`alert_reviews`** table (+ indexes); `GET /api/alerts/reviews`.
- Classification feedback: thumbs correct/incorrect → audit rows.
- Tests: `test_alert_reviews.py` **4/4**; Phase 6 feedback tests **2/2**.
- **Live human outcome rows: 0** (no operator has confirmed/dismissed in current DB).

**Status: `OPERATIONAL — VERIFIED`** (mechanism tested; zero production usage yet)

---

## 15. EXPLAINABILITY / EVIDENCE

- Rule `Evidence` fields as baseline + **`visual`** fusion field (`corroborating` | `conflicting` | `none`).
- Live `/api/sites` visual_evidence: **conflicting 19**, **corroborating 12**, **none 130** (all 31 real sites evaluated: 19/31 = **61.29%** conflict).
- Surfaced in site popups and alert cards (Phase 6/9/14 UI).

**Status: `OPERATIONAL (POC)`** (correct logic; conflict rate driven by weak visual model)

---

## 16. MACHINE LEARNING

### Weak-label operational RF — `OPERATIONAL (POC)`
- `backend/app/ml_model.py` + `backend/models/clf.pkl` (278,169 bytes).
- Features: FRP, brightness, month, capped distances, duty cycle; target = rule labels.

### Visual classical-CV RF (Phase 8) — `RESEARCH / EXPERIMENTAL`
- **Not a CNN.** Pretrained torchvision weights blocked by environment network restriction.
- 102-dim RGB/patch/histogram features + balanced RandomForest → `cnn_visual.pkl` (69,943 bytes).
- Stratified 70/30: N_train=21, N_test=10, **N_test_pos=2**.
- Metrics (Phase 12 re-derived): Accuracy **0.4000**, Precision **0.2500**, Recall **1.0000**, F1 **0.4000**, CM `[[2,6],[0,2]]`.
- Auxiliary fields only: `cnn_prediction`, `cnn_confidence`.

### Fusion (Phase 9) — `OPERATIONAL (POC)`
- Rule classification stays authoritative; visual corroborates or conflicts for human review.
- 19/31 real sites conflicting (expected from 25% visual precision).

### Active learning (Phase 10) — `RESEARCH / EXPERIMENTAL`
- Retrain cycle runs; logged **Δ = +0.0000** on held-out metrics.
- Root cause: N_test_pos=2; 17/19 (89.5%) near-duplicate boundary cases at conf≈0.5391.
- Log: `audit/active_learning_log.txt` (**33** retrain events in file this session).

### Contextual bandit (Phase 11) — `RESEARCH / EXPERIMENTAL`
- LinUCB-style priority `routine|watch|urgent`; artifact `rl_policy.pkl`.
- **Disclaimer**: initialized on severity/FRP heuristic proxy because **alert_reviews COUNT=0** — no learning from real human outcomes yet.
- Surfaced as `suggested_priority` on alerts/sites; never auto-executed.
- Live alert suggested_priority this session: all 30 currently `urgent` under current policy state.

### Phase 4D expansion RF — `RESEARCH / EXPERIMENTAL`
- `models/expansion_rf_phase4d.pkl`; ROC-AUC **0.7585** on chronological June split (from `audit/phase4d_model_report.txt`); not wired to API.

---

## 17. RANDOM FOREST (Phase 4D Research Model)

Unchanged research artifact (see §16): chronological split June 2026; ROC-AUC 0.7585, PR-AUC 0.4535, F1 0.5405, CM `[[29,13],[4,10]]`. **Not operational.**

---

## 18. TEST SUITE

**Command (this session)**:
```powershell
$env:PYTHONPATH="backend"; .venv\Scripts\python.exe -m pytest backend/tests -v
```
**Result**: **90 passed, 0 failed** (~69s), 2 warnings (httpx/anyio deprecations only).

| Test file | Count |
| :--- | ---: |
| test_classifier_correctness.py | 17 |
| test_firms_scheduler.py | 18 |
| test_success_criteria.py | 10 |
| test_thermal_behavior.py | 11 |
| test_provenance.py | 5 |
| test_alert_reviews.py | 4 |
| test_phase14_demo_fixes.py | 4 |
| test_phase9_fusion.py | 4 |
| test_phase6_frontend_api.py | 2 |
| test_phase7_satellite_imagery.py | 3 |
| test_phase8_cnn.py | 3 |
| test_phase10_active_learning.py | 3 |
| test_phase11_rl_policy.py | 3 |
| test_phase13_security.py | 3 |
| **Total** | **90** |

Browser verification (Phase 14 fixes): Playwright Chromium vs live stack — imagery naturalWidth 343×343 non-broken; 3/3 alert cards pan/zoom+popup; `overallPass: true` (artifacts under gitignored `scratch/phase14_*`).

**Status: `OPERATIONAL — VERIFIED`**

---

## 19. SECURITY

- **Auth**: API key / Bearer on transition, feedback, notify, all `/api/dev/*`. Live test: unauthenticated transition → **401**.
- **Rate limit**: `POST /api/needs` 5 req/60s/IP → **429** (tested Phase 13).
- **Secrets**: `.env` gitignored; `backend/keys/` gitignored; `data/*.db` gitignored; imagery binaries gitignored.
- **Live env key presence (values not shown)**: `FIRMS_MAP_KEY` present (len 32); `API_KEY` present (len 43); `TWILIO_SID` / `TWILIO_AUTH_TOKEN` **empty**.
- **Not implemented (explicit)**: full RBAC, OAuth2/OIDC, per-user sessions. Client-bundle API key is service-tier only.

**Status: `OPERATIONAL (POC)`**

---

## 20. DEPLOYMENT

- `backend/Dockerfile`, `docker-compose.yml`, `start_demo.ps1` (8000/5173/5174), `start_dev.ps1`.
- Local stack was running during Phase 14 visual verification.

**Status: `OPERATIONAL (POC)`**

---

## 21. ARCHITECTURE

```
FIRMS/CSV/Seed ─► ingest ─► SQLite WAL ─► 1km cluster
                        │
                        ▼
              thermal metrics + rule Evidence
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
   weak-label RF   Sentinel-2 chips   CAP alerts
        │               │                │
        │          classical CV RF        │
        │               │                │
        └──────► fusion visual_evidence ◄─┘
                        │
                 contextual bandit
                        │
                 FastAPI + auth
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
         Dashboard 5173      Public 5174
              │
         alert_reviews ──► active learning log
```

---

## 22. CURRENT CAPABILITY MATRIX

Aligned with `docs/VALIDATION_REPORT.md` (Phases 0–12 labels + Phase 13–15 updates in this report).

| Capability | Status | Evidence (this session unless noted) |
| :--- | :--- | :--- |
| FIRMS ingestion & dedup | OPERATIONAL — VERIFIED | provenance tests; unique index; 1299-row live DB |
| Spatial clustering | OPERATIONAL — VERIFIED | 1km Haversine; 161 sites live |
| Thermal behaviour metrics | OPERATIONAL — VERIFIED | `test_thermal_behavior.py` 11/11 |
| Rule-based classification | OPERATIONAL — VERIFIED | `test_classifier_correctness.py` 17/17 |
| Risk scoring & CAP alerting | OPERATIONAL — VERIFIED | CAP builder + 30 alerts; transition auth 401 |
| Human review & audit trail | OPERATIONAL — VERIFIED | `test_alert_reviews.py` 4/4; 0 rows in DB |
| Dashboard & public portal UI | OPERATIONAL (POC) | Phase 14 browser click-through + fixes `38ab7cc` |
| Satellite imagery acquisition | OPERATIONAL (POC) | 31/31 real chips Sentinel-2; tests 3/3 |
| Visual classification (not CNN) | RESEARCH / EXPERIMENTAL | P=0.25, N_test_pos=2; tests 3/3 |
| Thermal+visual fusion | OPERATIONAL (POC) | 19/31 conflicting live; tests 4/4 |
| Active learning retrain | RESEARCH / EXPERIMENTAL | Δ=+0.0000 logged; tests 3/3 |
| Priority policy (bandit) | RESEARCH / EXPERIMENTAL | heuristic proxy; alert_reviews=0; tests 3/3 |
| Security (API key + rate limit) | OPERATIONAL (POC) | 401/429 tested; not RBAC |
| Imagery static serving | OPERATIONAL (POC) | HTTP 200 browser + pytest |
| Alert click-to-locate | OPERATIONAL (POC) | 3/3 browser + wiring tests |
| Independent validation | OPERATIONAL — VERIFIED | Phase 12 + this 90/90 run |
| Final documentation (Phase 15) | OPERATIONAL — VERIFIED | this file + PPT map + changelog |

---

## 23. CURRENT LIMITATIONS

1. Visual model is **classical CV RF, not a CNN** (pretrained weight download blocked); precision 0.25 on N_test_pos=2.
2. Real imagery/visual-ML scope **N=31 sites**, Jharia-heavy — not geographically general.
3. **Zero** human confirm/dismiss outcomes in DB — bandit and active learning have not learned from real operators.
4. No full RBAC/per-user auth; service API key only.
5. Twilio SMS unconfigured (empty token); Web Push is the configured notify path (3 subscriptions).
6. Default dashboard provenance filter is “Real Satellite”; current 30 alerts are synthetic-side — operators must select **All** to see them (observed Phase 14).
7. `audit/` path is gitignored for new untracked files; historical audit scripts remain as previously committed.

---

## 24. FEATURE ROADMAP STATUS

| Feature | Status |
| :--- | :--- |
| Satellite thermal detection | OPERATIONAL — VERIFIED |
| Persistent site tracking | OPERATIONAL — VERIFIED |
| Thermal behaviour analysis | OPERATIONAL — VERIFIED |
| Evidence-based classification | OPERATIONAL — VERIFIED |
| Explainable risk & CAP alerts | OPERATIONAL — VERIFIED |
| Human review console + audit table | OPERATIONAL — VERIFIED |
| Imagery acquisition (Sentinel-2) | OPERATIONAL (POC) |
| Visual classification | RESEARCH / EXPERIMENTAL |
| Thermal + visual fusion | OPERATIONAL (POC) |
| Human feedback integration (UI + table) | OPERATIONAL — VERIFIED (0 real rows) |
| Active learning loop | RESEARCH / EXPERIMENTAL |
| RL / action prioritization | RESEARCH / EXPERIMENTAL (contextual bandit, offline) |
| API key auth + SOS rate limit | OPERATIONAL (POC) |
| Imagery static + click-to-locate UI | OPERATIONAL (POC) |
| Independent validation | OPERATIONAL — VERIFIED (90/90) |
| Final docs & PPT evidence map | OPERATIONAL — VERIFIED (Phase 15) |

---

## 25. FINAL A-to-Z SUMMARY

- **A. What NOCTRA is**: Dual-tier thermal anomaly detection → classification → CAP alerting system with optical evidence research layers.
- **B. Data**: NASA VIIRS (real + history + synthetic seed), OSM polygons, Sentinel-2 L2A chips.
- **C. Ingestion**: CSV + gated NRT scheduler; provenance on every row.
- **D. Sites**: 1 km Haversine clusters → `TG-…` IDs (161 live).
- **E. Thermal behaviour**: FRP stats/trend/persistence/duty cycle/expansion hull.
- **F. Classification**: Deterministic 4-class rules + Evidence; ML never overrides.
- **G. Risk/alerts**: FRP bands; ≥40 MW → CAP 1.2; 30 live alerts.
- **H. Evidence**: spatial/temporal/intensity/sufficiency + visual fusion field.
- **I. Human review**: confirm/dismiss + notes + append-only `alert_reviews` (0 rows yet).
- **J. Frontends**: React Leaflet console 5173; citizen portal 5174.
- **K. Backend**: FastAPI + API-key guards on mutations.
- **L. DB**: SQLite WAL; 10 tables; provenance indexes.
- **M. ML**: weak-label RF (POC); classical-CV visual RF (experimental); bandit (experimental); Phase 4D RF (research only).
- **N. Validation**: 90/90 pytest this session; audit scripts; Phase 14 browser evidence.
- **O. Tests**: 14 modules covering classifier, thermal, scheduler, success criteria, Phases 5–14.
- **P. Operational**: ingest, cluster, classify, CAP, dual UI, human review API, auth, rate limit.
- **Q. Experimental**: visual precision, fusion conflict rate, active learning Δ=0, bandit without human rewards.
- **R. Still weak / open**: real operator feedback volume, CNN transfer learning, RBAC, Twilio creds.
- **S. Security**: keys in `.env` only; mutations 401 without key; SOS 429 beyond limit; no RBAC.
- **T. Deploy**: Docker Compose + `start_demo.ps1`.
- **U. Architecture**: modular pipeline as in §21.
- **V. Provenance**: `is_synthetic`, `source`, `ingestion_batch` (+ imagery analogous columns).
- **W. Limitations**: see §23.
- **X. Working prototype evidence**: live health counts; 90 tests; browser imagery + locate screenshots recorded in Phase 14 report.
- **Y. Research metrics**: Phase 4D ROC-AUC 0.7585; visual RF Acc 0.40 / P 0.25 on N=10 test.
- **Z. Final status**: **OPERATIONAL PROTOTYPE — verified core pipeline; research layers honestly labeled; Phase 14 UI gaps fixed and browser-confirmed; Phase 15 documentation authoritative.**

---

*Supersedes the September 22, 2026 baseline audit for end-state claims. Cross-check: `docs/VALIDATION_REPORT.md`, `docs/PPT_EVIDENCE_MAP.md`, `docs/PHASE_CHANGELOG.md`.*
