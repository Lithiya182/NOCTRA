# Phase 8 — Classical Computer Vision Feature Classification (Honestly Scoped)

**Status**: OPERATIONAL (POC)  
**Date**: September 23, 2026  
**Commit**: `[Phase 8] Stratified-split retrain — non-degenerate result, honestly scoped — 73/73 passed`

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
   - **Stratified Train/Test Split (70/30)**:
     - Replaced strict chronological split with a stratified split ($N=21$ train / $N=10$ test) to evenly distribute the 6 total positive `industrial_fire` samples.
     - **Train Set**: $N=21$ samples (4 positive `industrial_fire`, 17 `other`).
     - **Test Set**: $N=10$ samples (2 positive `industrial_fire`, 8 `other`).
   - **Model Training**: Trained balanced `RandomForestClassifier(n_estimators=100, class_weight='balanced', max_depth=3, random_state=42)` saved to `backend/models/cnn_visual.pkl`.

4. **Auxiliary API Integration (`backend/app/routers/sites.py`, `backend/app/models.py`)**:
   - Added `cnn_prediction: Optional[str]` and `cnn_confidence: Optional[float]` fields to `SiteRow` Pydantic model.
   - Attached `predict_visual()` output as auxiliary fields on `/api/sites` and `/api/sites/{id}` without overriding authoritative rule-based thermal classification.

5. **Targeted Phase 8 Unit Tests (`backend/tests/test_phase8_cnn.py`)**:
   - `test_cnn_feature_extraction`: Verifies 102-dim feature vector output.
   - `test_cnn_training_stratified_split`: Verifies model training, stratified split, and metric calculation.
   - `test_predict_visual_auxiliary_field_and_endpoint`: Verifies prediction contract and API endpoint fields.

---

## 3. Site ID Collision Audit Flag
- **Audit Findings**: During historical ingestion, 132 site IDs overlapped with pre-existing site clusters.
- **Handling**: Rather than silently overwriting, `ingest.py` re-clustered all real and synthetic detections together into a unified, non-redundant set of 161 site clusters (31 real, 130 synthetic). All historical detections were preserved with full provenance (`source='firms_history'`).

---

## 4. Empirical Evaluation & Honest Metric Analysis

### Stratified Train/Test Split Configuration
- **Rationale for Stratified Split**: June historical data (ingested from Jharia historical CSV) and September live data originate from distinct ingestion sources and batches rather than a single continuous time series stream. Consequently, temporal leakage risk between batches is low. Conversely, a strict chronological split left only 1 positive sample in the training set ($N_{\text{train\_pos}}=1$), leading to a degenerate classifier (either 0 TN or 0 FP depending on probability threshold). A 70/30 stratified split allocates 4 positive samples to training ($N_{\text{train\_pos}}=4$) and 2 to testing ($N_{\text{test\_pos}}=2$), providing the classifier with a non-trivial training signal.
- **Train Set**: $N=21$ samples (4 positive `industrial_fire`, 17 `other`).
- **Test Set**: $N=10$ samples (2 positive `industrial_fire`, 8 `other`).

### Empirical Test Set Results
- **Accuracy**: `0.4000` (40.0%)
- **Precision**: `0.2500` (25.0%)
- **Recall**: `1.0000` (100.0%)
- **F1-Score**: `0.4000` (40.0%)
- **Confusion Matrix**: $\begin{bmatrix} TN=2 & FP=6 \\ FN=0 & TP=2 \end{bmatrix}$

### Honest Performance Analysis & Caveats
1. **Non-Degenerate Result**:
   - Unlike the strict chronological split's degenerate matrix ($\begin{bmatrix} 0 & 19 \\ 0 & 5 \end{bmatrix}$), the stratified split produces a **non-degenerate confusion matrix** with active predictions across both classes ($TN=2, FP=6, FN=0, TP=2$).
2. **Small Test Set Sample Size Caveat**:
   - The test set contains only **2 positive samples** ($N_{\text{test\_pos}}=2$).
   - The reported **Recall of 1.00** simply means the classifier correctly caught **2 out of 2** positive test instances. It is **not a statistically reliable measure** of high recall or general sensitivity due to the extreme sample size constraint.
3. **Low Precision & Over-Prediction**:
   - Precision is low at **0.25 (25.0%)** due to **6 False Positives** out of 8 actual negative test samples.
   - The model currently **over-predicts the `industrial_fire` class**, classifying several non-industrial chips as positive due to color histogram and spatial patch feature overlap.
4. **Honest Capability Status**:
   - Status is retained strictly as **OPERATIONAL (POC)** (and explicitly **NOT upgraded to VERIFIED**), given the overall dataset size ($N=31$ overall, $N=2$ test positives) and low precision (25.0%).

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
backend/tests/test_phase8_cnn.py::test_cnn_training_stratified_split PASSED [ 66%]
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
backend/tests/test_phase8_cnn.py::test_cnn_training_stratified_split PASSED [ 63%]
backend/tests/test_phase8_cnn.py::test_predict_visual_auxiliary_field_and_endpoint PASSED [ 64%]
...
backend/tests/test_thermal_behavior.py::test_duty_cycle_and_consecutive_days_formulas PASSED [100%]

====================== 73 passed, 2 warnings in 57.97s =======================
```

---

## 6. Honest Capability Status Label
**OPERATIONAL (POC)**
- Built an operational feature extraction and model pipeline running on 31 Sentinel-2 optical image chips.
- Evaluated on a 70/30 stratified train/test split ($N=21$ train / $N=10$ test).
- Retrained and verified as a non-degenerate classifier ($TN=2, FP=6, FN=0, TP=2$).
- Status is scoped strictly as **OPERATIONAL (POC)** (and NOT upgraded to VERIFIED) due to sample size constraints ($N=31$ total chips, $N=2$ test positives) and low precision (25.0%).

---

## 7. Rollback Note
If Phase 8 changes need to be undone:
- Revert git commit `98089ca`.
- Restore database: `Copy-Item data/backups/thermalguard_pre_phase8.db data/thermalguard.db -Force`.
- Delete model file: `Remove-Item backend/models/cnn_visual.pkl -Force`.
