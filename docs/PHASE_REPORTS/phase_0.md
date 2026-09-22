# Phase 0 Report — Baseline Freeze & Safety Net

**Phase Objective**: Establish a known-good, reversible starting point prior to executing the phased master execution prompt.

---

## 1. What Was Audited
- Existing Pytest test suite in `backend/tests/`.
- Current database state in `data/thermalguard.db`.
- Git status, existing tags, and `.gitignore` coverage.

---

## 2. What Was Executed & Built
1. **Full Baseline Test Run**: Executed `.venv\Scripts\python.exe -m pytest backend/tests -v`.
   - Result: **42 PASSED, 4 FAILED** (46 total test items).
   - Confirmed 4 existing failure regression baseline in `test_success_criteria.py` (`test_data_ingestion_matches_csv`, `test_registry_deduplicates_sites`, `test_polygons_and_filters`, `test_synthetic_reset_preserves_real_rows`).
2. **Database Backup**: Created a full timestamped copy of `data/thermalguard.db` to `data/backups/thermalguard_baseline.db` (331,776 bytes). Verified file exists and is intact.
3. **Git Baseline Tag**: Created git tag `noctra-baseline-pre-master-build` pointing to the exact starting commit.
4. **Gitignore Hardening**: Updated `.gitignore` to explicitly cover `data/backups/`, `backend/keys/`, `.env`, `.venv/`, and temporary audit scripts, ensuring zero credentials or database backups enter git history.

---

## 3. Exact Test Commands & Results
- **Command**: `.venv\Scripts\python.exe -m pytest backend/tests -v`
- **Output Summary**:
  ```
  collected 46 items
  backend/tests/test_classifier_correctness.py ............ [ 26%] (12 PASSED)
  backend/tests/test_firms_scheduler.py ................     [ 60%] (16 PASSED)
  backend/tests/test_success_criteria.py F..F...F.F           [ 82%] (6 PASSED, 4 FAILED)
  backend/tests/test_thermal_behavior.py ........             [100%] (8 PASSED)
  ================== 4 failed, 42 passed in 28.06s ==================
  ```

---

## 4. Current Status Labels
- **Baseline Test Suite**: `OPERATIONAL — VERIFIED` (42 tests passing, 4 known regressions documented for Phase 1 fix).
- **Safety Net & Backup**: `OPERATIONAL — VERIFIED` (Database backup verified at `data/backups/thermalguard_baseline.db`, git tag `noctra-baseline-pre-master-build` set).

---

## 5. Deferred Items
- Fixing the 4 failing tests in `test_success_criteria.py` (explicitly scheduled for **Phase 1**).

---

## 6. Rollback Note
- To revert back to the exact pre-build state:
  ```bash
  git checkout noctra-baseline-pre-master-build
  cp data/backups/thermalguard_baseline.db data/thermalguard.db
  ```
