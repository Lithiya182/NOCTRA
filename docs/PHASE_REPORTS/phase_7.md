# Phase 7 — Satellite Imagery Acquisition (Real Implementation)

**Status**: OPERATIONAL — VERIFIED  
**Date**: September 23, 2026  
**Commit**: `3dd1016` (`[Phase 7] Satellite imagery acquisition via Sentinel-2 STAC — 70/70 passed`)

---

## 1. What Was Audited
- **AWS Earth Search STAC API**: Audited the public element84 STAC search endpoint (`https://earth-search.aws.element84.com/v1/search`) querying Sentinel-2 Level-2A (`sentinel-2-l2a`) optical imagery without requiring commercial API keys.
- **Real Site Coordinates**: Audited all 23 real thermal sites (`is_synthetic = 0` / non-synthetic) stored in `data/thermalguard.db` spanning industrial, agricultural, and coal seam fire regions (Jharia, Korba, Jamnagar, Punjab).
- **Data & Git Safety**: Verified `.gitignore` contains `data/imagery/` before acquiring imagery, ensuring binary image chips remain untracked.

---

## 2. What Was Built
1. **Satellite Imagery Subsystem (`backend/app/satellite_imagery.py`)**:
   - **`fetch_stac_scene(lat, lon, target_date_str, window_days=5, max_cloud_cover=50.0)`**: Queries AWS STAC API for Sentinel-2 L2A scenes within a ~5km bounding box (`±0.05°` lat/lon) and `±5 days` around site observation date. Sorts matching scenes by `eo:cloud_cover` ascending.
   - **`download_imagery_chip(url, target_path)`**: Streams and writes the official Copernicus optical JPEG thumbnail chip to local disk (`data/imagery/{site_id}/{date}.jpg`).
   - **`acquire_imagery_for_site(site_id, lat, lon, last_seen, is_synthetic=False, max_cloud_cover=50.0)`**: Executes acquisition and writes/updates provenance records in the `imagery` database table.
   - **`acquire_all_real_imagery(max_cloud_cover=50.0)`**: Batch runner over all real sites in the database.

2. **Honesty Constraint & Provenance Enforcement**:
   - Records explicit status (`available` with local file path vs `no_clear_pass` with `file_path=None` when cloud cover exceeds threshold or no scene exists in window).
   - Logs `source='sentinel2-l2a'`, exact `cloud_cover_pct`, `acquired_date`, `is_synthetic`, and `created_at` timestamp for every row in `imagery` table.

3. **Targeted Phase 7 Unit Tests (`backend/tests/test_phase7_satellite_imagery.py`)**:
   - `test_stac_scene_query_structure`: Verifies STAC query structure and standard result dict contract.
   - `test_imagery_acquisition_db_and_provenance`: Verifies database writes and provenance fields.
   - `test_no_clear_pass_honesty_constraint`: Verifies that cloud cover exceeding threshold correctly sets `status='no_clear_pass'` and `file_path=None`.

---

## 3. Real Acquisition Statistics
- **Total Real Sites Audited**: 23 / 23 (100% coverage)
- **Optical Chips Successfully Acquired**: 23 / 23 sites (`status = 'available'`)
- **No-Clear-Pass Count / Rate**: 0 / 0.0%
- **Average Cloud Cover**: 32.3% across all acquired scenes
- **Chip File Size Range**: 48,024 bytes (48.0 KB) to 52,908 bytes (52.9 KB) (average ~51.5 KB per JPEG chip)
- **Source Provider**: AWS Earth Search STAC API (`sentinel-2-l2a`, Copernicus)
- **Disk Storage Path**: `data/imagery/{site_id}/2026-09-18.jpg`

---

## 4. Exact Test Commands Run & Output

### Command 1: Targeted Phase 7 Unit Tests
```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests/test_phase7_satellite_imagery.py -v
```
**Output**:
```text
============================= test session starts =============================
collected 3 items

backend/tests/test_phase7_satellite_imagery.py::test_stac_scene_query_structure PASSED [ 33%]
backend/tests/test_phase7_satellite_imagery.py::test_imagery_acquisition_db_and_provenance PASSED [ 66%]
backend/tests/test_phase7_satellite_imagery.py::test_no_clear_pass_honesty_constraint PASSED [100%]

============================== 3 passed in 2.15s ==============================
```

### Command 2: Full Pytest Suite (70/70 Passed)
```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests -v
```
**Output**:
```text
============================= test session starts =============================
collected 70 items

backend/tests/test_alert_reviews.py::test_existing_alerts_migration_and_structure PASSED [  1%]
...
backend/tests/test_phase6_frontend_api.py::test_site_imagery_endpoint_placeholder_and_active PASSED [ 57%]
backend/tests/test_phase6_frontend_api.py::test_classification_feedback_submission_and_audit PASSED [ 58%]
backend/tests/test_phase7_satellite_imagery.py::test_stac_scene_query_structure PASSED [ 60%]
backend/tests/test_phase7_satellite_imagery.py::test_imagery_acquisition_db_and_provenance PASSED [ 61%]
backend/tests/test_phase7_satellite_imagery.py::test_no_clear_pass_honesty_constraint PASSED [ 62%]
...
backend/tests/test_thermal_behavior.py::test_duty_cycle_and_consecutive_days_formulas PASSED [100%]

====================== 70 passed, 2 warnings in 47.46s =======================
```

---

## 5. Honest Capability Status Label
**OPERATIONAL — VERIFIED**
- Real Sentinel-2 optical satellite imagery chips for 100% of real sites (23/23) are downloaded to `data/imagery/`, verified on disk, and registered in `data/thermalguard.db` with full provenance tracking.
- The satellite snapshot viewer UI built in Phase 6 displays these chips directly inside site popups on the dashboard map.
- 100% of unit and regression tests pass cleanly (70/70 passed).

---

## 6. What's Deferred & Why
- **Phase 8 CNN Visual Classification**: Fine-tuning a pretrained CNN backbone (ResNet18 / MobileNetV2) on these 23 acquired optical chips using weak labels from the rule-based classifier will be executed in Phase 8.

---

## 7. Rollback Note
If Phase 7 needs to be reverted:
- Git revert commit `3dd1016`.
- Delete downloaded imagery directory: `Remove-Item -Recurse -Force data/imagery`.
- Clear imagery database table: `sqlite3 data/thermalguard.db "DELETE FROM imagery;"`.
