# NOCTRA Phase Report — Phase 2: Backend & Data Foundation Hardening

**Date**: September 23, 2026  
**Branch**: `thermalguard/classifier-correctness-validation`  
**Status**: OPERATIONAL — VERIFIED  

---

## 1. Executive Summary
- **Objective**: Harden backend infrastructure for subsequent phases by gating background schedulers safely behind environment flags, standardizing system-wide data provenance tracking, enforcing input validation on public routes, and verifying database WAL mode and spatial indexes.
- **Outcome**: Successfully implemented environment-gated lifespan scheduling (`ENABLE_FIRMS_SCHEDULER`), introduced a shared `provenance.py` module, updated Pydantic request models and error handling for `/api/needs` and `/api/dev`, verified SQLite WAL mode + indexes, and expanded the pytest suite from 46 to 53 passing tests (100% pass rate).

---

## 2. Audit Findings
- **FIRMS Scheduler**: `firms_scheduler.py` contained `start_scheduler()` and `stop_scheduler()`, but `main.py` did not invoke them in the FastAPI lifespan context.
- **Data Provenance**: Ingestion and detection pipelines handled `is_synthetic` and `source` manually across modules without a unified schema or datetime formatting contract.
- **Input Validation**: `/api/needs` and `/api/dev/detection` accepted raw floats without range boundaries (-90 to 90 lat, -180 to 180 lon) or structured exception detail formatting.
- **Database Storage**: SQLite database configuration in `db.py` sets `PRAGMA journal_mode=WAL` and maintains 4 performance and uniqueness indexes.

---

## 3. Implementation Details

### Files Created / Modified
1. `backend/app/provenance.py` `[NEW]`:
   - Introduced `Provenance` dataclass, `get_now_iso()`, `build_provenance_fields()`, and `normalize_provenance()`.
   - Standardized `is_synthetic` (coerced int 0/1), `source` (str), `ingestion_batch` (Optional[str]), and `created_at` (ISO 8601 UTC).

2. `backend/app/config.py` `[MODIFY]`:
   - Added `ENABLE_FIRMS_SCHEDULER` environment variable flag (default: `False`).

3. `backend/app/main.py` `[MODIFY]`:
   - Updated `lifespan` context manager to inspect `ENABLE_FIRMS_SCHEDULER`.
   - Starts BackgroundScheduler on startup when `ENABLE_FIRMS_SCHEDULER=true`, and shuts down cleanly on server exit.

4. `backend/app/models.py` `[MODIFY]`:
   - Added `Field` range constraints to `NeedIn` (`lat` -90..90, `lon` -180..180, `message` max 1000 chars).
   - Added `Field` range constraints to `RuntimeDetectionIn` (`lat` -90..90, `lon` -180..180, `frp` >= 0, `brightness` >= 0).

5. `backend/app/routers/needs.py` & `backend/app/routers/dev.py` `[MODIFY]`:
   - Wrapped database interactions in `try...except` blocks logging errors and returning standard `HTTPException` responses (500 status code with clear user detail).

6. `backend/tests/test_provenance.py` `[NEW]`:
   - Added unit tests for timestamp format, boolean/integer provenance coercion, record normalization, and live SQLite WAL mode / index integrity verification.

7. `backend/tests/test_firms_scheduler.py` `[MODIFY]`:
   - Added `test_lifespan_scheduler_toggle_off` and `test_lifespan_scheduler_toggle_on` tests using `TestClient`.

---

## 4. Test Results & Verification Metrics

- **Test Command**: `.venv\Scripts\python.exe -m pytest backend/tests -v`
- **Pass Rate**: 53 / 53 passed (100%)

| Test Subsystem | Pre-Phase Count | Post-Phase Count | Status |
| --- | --- | --- | --- |
| Provenance & DB WAL/Indexes (`test_provenance.py`) | 0 | 5 | OPERATIONAL — VERIFIED |
| Scheduler Lifespan Toggle (`test_firms_scheduler.py`) | 16 | 18 | OPERATIONAL — VERIFIED |
| Classifier Edge Cases (`test_classifier_correctness.py`) | 12 | 12 | OPERATIONAL — VERIFIED |
| Success Criteria & Ingestion (`test_success_criteria.py`) | 10 | 10 | OPERATIONAL — VERIFIED |
| Thermal Behavior (`test_thermal_behavior.py`) | 8 | 8 | OPERATIONAL — VERIFIED |
| **Total Test Suite** | **46** | **53** | **OPERATIONAL — VERIFIED** |

---

## 5. Status Label Assessment
- **FIRMS Scheduler Lifespan Toggle**: `OPERATIONAL — VERIFIED` (gated behind `ENABLE_FIRMS_SCHEDULER`, tested via FastAPI `TestClient`).
- **Provenance Module**: `OPERATIONAL — VERIFIED` (fully tested with unit tests, ready for Phases 7–11).
- **Database Engine**: `OPERATIONAL — VERIFIED` (WAL mode active, indexes verified).

---

## 6. Deferred Items
- **Phase 3**: Thermal Metric Formula locking tests.
- **Phase 5**: Alert audit review table and analyst note additions.
- **Phase 7**: AWS STAC Sentinel-2 imagery acquisition.

---

## 7. Rollback & Recovery Note
- **Commit Baseline**: `16e6520` (`[Phase 1] Fix test regressions and polygon fixture — 46/46 passed`)
- **To Roll Back Phase 2**:
  ```bash
  git checkout 16e6520 -- backend/app/main.py backend/app/config.py backend/app/models.py backend/app/routers/needs.py backend/app/routers/dev.py backend/tests/test_firms_scheduler.py
  rm backend/app/provenance.py backend/tests/test_provenance.py docs/PHASE_REPORTS/phase_2.md
  ```
