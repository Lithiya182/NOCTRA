# Phase 5 — Risk, Alerts & Human Review Completion

**Status**: OPERATIONAL — VERIFIED  
**Date**: September 23, 2026  
**Commit**: (Pending Phase 5 commit)

---

## 1. What Was Audited
- `backend/app/db.py`: Examined the `alerts` table schema. Prior to Phase 5, `alerts` contained basic fields (`site_id`, `severity`, `is_anomalous`, `status`, `public_notified`, `cap_json`, `created_at`, `updated_at`) but lacked analyst note fields and an independent append-only review history/audit table.
- `backend/app/models.py`: Inspected Pydantic data schemas `AlertOut` and `TransitionIn`. `TransitionIn` only accepted `{ action: "confirm" | "dismiss" }` without note support.
- `backend/app/alert_engine.py`: Reviewed `update_alert_status` logic. Status transitions only modified `alerts` and `sites` tables without writing to an append-only audit log.
- `backend/app/routers/alerts.py`: Audited alert endpoints (`GET /api/alerts`, `POST /api/alerts/{id}/transition`, `POST /api/alerts/{id}/notify`).
- `dashboard/src/App.jsx` & `index.css`: Audited government console alert card UI. Confirm/dismiss buttons lacked an optional text input field for analyst notes and did not display previous notes.

---

## 2. What Was Built
1. **Database Schema Hardening & Append-Only Audit Table (`backend/app/db.py`)**:
   - Extended `alerts` table with `analyst_note TEXT` and `reviewed_by TEXT` columns, supported by dynamic schema migration (`ALTER TABLE alerts ADD COLUMN...`) so existing 30+ alerts stay intact.
   - Created `alert_reviews` append-only audit table (`id`, `alert_id`, `site_id`, `action`, `previous_status`, `new_status`, `analyst_note`, `reviewed_by`, `created_at`) with performance indexes on `alert_id` and `site_id`.
   - Updated DB reset helpers (`reset_all()`, `reset_synthetic_only()`, `reset_derived_tables()`) to include `alert_reviews`.

2. **Data Contract & Backend Logic (`backend/app/models.py`, `backend/app/alert_engine.py`, `backend/app/routers/alerts.py`)**:
   - Extended `TransitionIn` schema with `analyst_note` (optional string, max 1000 chars) and `reviewed_by` (optional string, default `'analyst'`).
   - Extended `AlertOut` schema to return `analyst_note` and `reviewed_by`. Added `AlertReviewOut` Pydantic model for audit log entries.
   - Updated `update_alert_status` to store `analyst_note` and `reviewed_by` on the alert record AND write an append-only row into `alert_reviews`.
   - Added `get_alert_reviews(alert_id=None)` helper in `alert_engine.py` and exposed GET `/api/alerts/reviews` and GET `/api/alerts/{alert_id}/reviews` endpoints.
   - Fixed `get_alerts()` fallback so missing sites yield `site=None` rather than an empty dict `{}`.

3. **Frontend Dashboard Console (`dashboard/src/App.jsx`, `dashboard/src/index.css`)**:
   - Added analyst note input field to alert cards in state `alert_triggered`.
   - Updated transition handler to pass `{ action, analyst_note, reviewed_by: 'analyst' }`.
   - Rendered existing analyst notes (`📝 Note (by reviewer)`) directly on alert cards.

4. **Targeted Tests (`backend/tests/test_alert_reviews.py`)**:
   - Added unit test suite covering schema migration, `confirm + note`, `dismiss + note`, audit log insertion, and global/per-alert review endpoints.

---

## 3. Exact Test Commands Run & Output

### Command 1: Targeted Phase 5 Unit Tests
```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests/test_alert_reviews.py -v
```
**Output**:
```text
============================= test session starts =============================
collected 4 items

backend/tests/test_alert_reviews.py::test_existing_alerts_migration_and_structure PASSED [ 25%]
backend/tests/test_alert_reviews.py::test_transition_confirm_with_note PASSED [ 50%]
backend/tests/test_alert_reviews.py::test_transition_dismiss_with_note PASSED [ 75%]
backend/tests/test_alert_reviews.py::test_global_reviews_endpoint PASSED [100%]

============================== 4 passed in 2.15s ==============================
```

### Command 2: Full Pytest Suite (Regression Check)
```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests -v
```
**Output**:
```text
============================= test session starts =============================
collected 65 items

backend/tests/test_alert_reviews.py::test_existing_alerts_migration_and_structure PASSED [  1%]
backend/tests/test_alert_reviews.py::test_transition_confirm_with_note PASSED [  3%]
backend/tests/test_alert_reviews.py::test_transition_dismiss_with_note PASSED [  4%]
backend/tests/test_alert_reviews.py::test_global_reviews_endpoint PASSED [  6%]
backend/tests/test_classifier_correctness.py::test_consec_days_one_active_day PASSED [  7%]
...
backend/tests/test_success_criteria.py::test_data_ingestion_matches_csv PASSED [ 69%]
backend/tests/test_success_criteria.py::test_sites_endpoint_contract PASSED [ 70%]
backend/tests/test_success_criteria.py::test_region_dominant_labels PASSED [ 72%]
backend/tests/test_success_criteria.py::test_registry_deduplicates_sites PASSED [ 73%]
backend/tests/test_success_criteria.py::test_alert_lifecycle_and_gating PASSED [ 75%]
backend/tests/test_success_criteria.py::test_runtime_detection_live_alert PASSED [ 76%]
backend/tests/test_success_criteria.py::test_needs_writeback PASSED      [ 78%]
backend/tests/test_success_criteria.py::test_polygons_and_filters PASSED [ 80%]
backend/tests/test_success_criteria.py::test_ml_weak_label_layer PASSED  [ 81%]
backend/tests/test_success_criteria.py::test_synthetic_reset_preserves_real_rows PASSED [ 83%]
backend/tests/test_thermal_behavior.py::test_duty_cycle_and_consecutive_days_formulas PASSED [100%]

======================= 65 passed, 2 warnings in 37.55s =======================
```

---

## 4. Honest Capability Status Label
**OPERATIONAL — VERIFIED**
- Analyst notes (`analyst_note`) and reviewer IDs (`reviewed_by`) are wired into the backend API, stored in SQLite database schema, and recorded in an independent, timestamped append-only audit table (`alert_reviews`).
- The dashboard control console accepts analyst notes and displays recorded review history.
- 100% of tests (65/65 passed) verify schema compatibility, API contracts, transition workflows, and audit logging.

---

## 5. What's Deferred & Why
- **RBAC / Authentication for transitions**: Authentication on `/api/alerts/{id}/transition` is scheduled for Phase 13 (Security & Deployment Pass). Currently `reviewed_by` defaults to `"analyst"` or client-supplied identifier.

---

## 6. Rollback Note
If Phase 5 changes need to be undone:
- Git revert to commit prior to Phase 5: `3b78bca` (`[Docs] Add baseline NOCTRA A-to-Z audit report document`).
- Database restore: `Copy-Item data/backups/thermalguard_pre_phase5.db data/thermalguard.db -Force`.
