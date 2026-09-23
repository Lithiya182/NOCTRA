# Phase 8 — Classical Computer Vision Feature Classification (Honestly Scoped)

**Status**: RESEARCH / EXPERIMENTAL  
**Date**: September 23, 2026  
**Commit**: `98089ca` (`[Phase 8] CNN visual classification on multi-date Sentinel-2 chips — 73/73 passed`)

---

## 1. Technique Audit & Methodological Clarity
- **Technique Used**: **Classical Computer Vision (RGB Patch Statistics & Color Histograms)**, NOT a deep CNN backbone.
- **Backbone Verification**: Image chips are parsed using PIL to compute a 102-dimensional spatial color vector (channel means/stds, $4 \times 4$ spatial patch grid means, 16-bin color channel histograms) fed into a Random Forest classifier (`class_weight='balanced'`). Deep CNN backbones (e.g. ResNet18/MobileNetV2 via `torchvision`) were not used due to network restrictions on model weight downloads.
- **Presentation & Slide Alignment**: All future references, reports, and SIH slides must accurately label this technique as **Classical Computer Vision (RGB/Histogram) Feature Classifier** rather than a deep Convolutional Neural Network.

---

## 2. What Was Built
1. **Historical Data Ingestion & Provenance Hardening**:
   - Ingested `data/firms_history_jharia.csv` via standard `ingest.py` pipeline.
   - Updated `_ingest_rows` to use `INSERT OR IGNORE INTO detections` and refresh derived site clusters (`sites`, `site_detections`) safely.
   - Expanded real site dataset to **31 real site clusters** with available Sentinel-2 optical imagery chips.

2. **Multi-Date Sentinel-2 Optical Imagery Acquisition (`backend/app/satellite_imagery.py`)**:
   - Acquired 31 real optical image chips from AWS Earth Search STAC API (`sentinel-2-l2a`):
     - `2026-06-12`: 1 chip
     - `2026-06-15`: 2 chips
     - `2026-06-25`: 4 chips
     - `2026-09-18`: 24 chips

3. **Classical CV Classifier Subsystem (`backend/app/cnn_visual.py`)**:
   - **Visual Feature Extractor (`extract_visual_features`)**: Resizes optical JPEG chips to $64 \times 64$, extracting 102-dimensional feature vectors (RGB channel means/stds, $4 \times 4$ spatial patch grid means, 16-bin color channel histograms).
   - **Strict Chronological Train/Test Split**:
     - **Train Set (Earlier Dates: June 12–25, 2026)**: $N=7$ samples (1 positive `industrial_fire`, 6 `other`).
     - **Test Set (Later Dates: September 18, 2026)**: $N=24$ samples (5 positive `industrial_fire`, 19 `other`).
   - **Model Training**: Trained balanced `RandomForestClassifier(n_estimators=100, class_weight='balanced', max_depth=3)` saved to `backend/models/cnn_visual.pkl`.

4. **Auxiliary API Integration (`backend/app/routers/sites.py`, `backend/app/models.py`)**:
   - Added `cnn_prediction: Optional[str]` and `cnn_confidence: Optional[float]` fields to `SiteRow` Pydantic model.
   - Attached `predict_visual()` output as auxiliary fields on `/api/sites` and `/api/sites/{id}` without overriding authoritative rule-based thermal classification.

5. **Targeted Phase 8 Unit Tests (`backend/tests/test_phase8_cnn.py`)**:
   - `test_cnn_feature_extraction`: Verifies 102-dim feature vector output.
   - `test_cnn_training_chronological_split`: Verifies model training, chronological split, and metric calculation.
   - `test_predict_visual_auxiliary_field_and_endpoint`: Verifies prediction contract and API endpoint fields.

---

## 3. Site ID Collision Audit Flag
- **Audit Findings**: During historical ingestion, 132 site IDs overlapped with pre-existing site clusters.
- **Handling**: Rather than silently overwriting, `ingest.py` re-clustered all real and synthetic detections together into a unified, non-redundant set of 161 site clusters (31 real, 130 synthetic). All historical detections were preserved with full provenance (`source='firms_history'`).

---

## 4. Empirical Evaluation & Honest Metric Analysis

### Chronological Train/Test Split Configuration
- **Train Set**: $N=7$ samples across acquisition dates `2026-06-12`, `2026-06-15`, `2026-06-25` (1 positive `industrial_fire`, 6 `other`).
- **Test Set**: $N=24$ samples across acquisition date `2026-09-18` (5 positive `industrial_fire`, 19 `other`).

### Empirical Test Set Results
- **Standard Threshold (0.5)**:
  - **Accuracy**: `0.7917` (79.17%)
  - **Precision**: `0.0000`
  - **Recall**: `0.0000`
  - **Confusion Matrix**: `[[19, 0], [5, 0]]` (Predicts majority `other` for all 24 test instances).
- **Balanced Threshold (0.2)**:
  - **Accuracy**: `0.2083` (20.83%)
  - **Precision**: `0.2083`
  - **Recall**: `1.0000`
  - **Confusion Matrix**: `[[0, 19], [0, 5]]` (Predicts positive `industrial_fire` for all 24 test instances).

### Honest Performance Analysis & Caveats
1. **Degenerate Classifier Warning**:
   - At a balanced threshold of 0.2, the confusion matrix `[[0, 19], [0, 5]]` confirms a **degenerate always-positive classifier** (0 True Negatives, 19 False Positives).
   - This represents trivial always-positive guessing, NOT a meaningful sensitivity/specificity tradeoff.
2. **Absence of Discriminative Visual Signal**:
   - With only 1 positive training sample ($N_{\text{train\_pos}}=1$), the model has **not learned a discriminative visual signal** for `industrial_fire` at any threshold.
   - **Neither accuracy number indicates genuine classification capability**:
     - The **79.17% accuracy** (at 0.5 threshold) is trivial majority-class guessing (predicting all negative).
     - The **20.83% accuracy** (at 0.2 threshold) is trivial always-positive guessing (predicting all positive).
     - Neither number should be cited on slides or reports as evidence of visual classification capability.

---

## 5. Exact Test Commands Run & Output

### Command 1: Targeted Phase 8 Unit Tests
```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests/test_phase8_cnn.py -v
```
**Output**:
```text
============================= test session starts =============================
collected 3 items

backend/tests/test_phase8_cnn.py::test_cnn_feature_extraction PASSED     [ 33%]
backend/tests/test_phase8_cnn.py::test_cnn_training_chronological_split PASSED [ 66%]
backend/tests/test_phase8_cnn.py::test_predict_visual_auxiliary_field_and_endpoint PASSED [100%]

======================== 3 passed, 2 warnings in 6.61s ========================
```

### Command 2: Full Pytest Suite (73/73 Passed)
```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests -v
```
**Output**:
```text
============================= test session starts =============================
collected 73 items

backend/tests/test_alert_reviews.py::test_existing_alerts_migration_and_structure PASSED [  1%]
...
backend/tests/test_phase8_cnn.py::test_cnn_feature_extraction PASSED     [ 61%]
backend/tests/test_phase8_cnn.py::test_cnn_training_chronological_split PASSED [ 63%]
backend/tests/test_phase8_cnn.py::test_predict_visual_auxiliary_field_and_endpoint PASSED [ 64%]
...
backend/tests/test_thermal_behavior.py::test_duty_cycle_and_consecutive_days_formulas PASSED [100%]

====================== 73 passed, 2 warnings in 57.97s =======================
```

---

## 6. Honest Capability Status Label
**RESEARCH / EXPERIMENTAL**
- Built an operational feature extraction and model pipeline running on 31 Sentinel-2 optical image chips.
- Evaluated on a strict chronological train/test split (June 2026 vs Sept 2026).
- Relabeled honestly as a **Classical Computer Vision (RGB/Histogram) Feature Classifier**.
- Status is scoped strictly as **RESEARCH / EXPERIMENTAL** because the model has not learned a discriminative visual signal ($N_{\text{train\_pos}}=1$), and metrics reflect a degenerate boundary rather than true visual classification capability.

---

## 7. Rollback Note
If Phase 8 changes need to be undone:
- Revert git commit `98089ca`.
- Restore database: `Copy-Item data/backups/thermalguard_pre_phase8.db data/thermalguard.db -Force`.
- Delete model file: `Remove-Item backend/models/cnn_visual.pkl -Force`.
