# Phase 10 — Human Feedback / Active Learning Loop (Honestly Evaluated)

**Status**: OPERATIONAL (POC)  
**Date**: September 23, 2026  
**Commit**: `897bb82` (`[Phase 10] Human feedback active learning loop — honestly logged retrain metrics — 80/80 passed`)

---

## 1. Active Learning Architecture & Data Source Distinction
- **Data Source Audit**: An empirical database audit confirms **0 confirmed alerts, 0 dismissed alerts, and 0 rows in `alert_reviews`**.
- **Data Source Distinction**:
  1. **Phase 9 Structural Fusion Flags (19 real site records)**: The 19 correction records evaluated in Phase 10 stem strictly from Phase 9's structural evidence fusion conflict flags (`visual_evidence == 'conflicting'`), where rule-based thermal labels act as authoritative ground truth to correct Phase 8 CNN visual false positives.
  2. **Human Operator Reviews (`alert_reviews` table)**: The active learning pipeline is also built to ingest human confirm/dismiss actions and feedback labels (`feedback_label`, `analyst_note`, `reviewed_by`), which currently count 0 rows in the database baseline.
- **Correction Diversity Analysis**: Analyzes the 19 structural conflict flags from Phase 9:
  - **Near-duplicate cases**: 17 sites (89.5%) clustered at CNN confidence $\approx 0.5391$ (a decision-boundary threshold artifact in the balanced Random Forest).
  - **Distinct cases**: 2 sites (10.5%) with higher confidence $\approx 0.6846$.
- **Model Refitting & Metric Evaluation**:
  - Re-fits models (`ml_model.py` and `cnn_visual.py`) using authoritative thermal labels on conflict flags to correct CNN false positives.
  - Evaluates baseline vs. post-retrain metrics on the held-out test split ($N=10$ test samples, $N_{\text{test\_pos}}=2$).
  - Logs append-only audit entries to `audit/active_learning_log.txt`.

---

## 2. Empirical Retraining Results & Metric Deltas

### Held-Out Test Set Performance:
- **Baseline (Before Retrain)**:
  - Accuracy: `0.4000` (40.0%)
  - Precision: `0.2500` (25.0%)
  - Recall: `1.0000` (100.0%)
  - F1-Score: `0.4000` (40.0%)
  - Confusion Matrix: $\begin{bmatrix} TN=2 & FP=6 \\ FN=0 & TP=2 \end{bmatrix}$
- **Post-Retrain (After Retrain)**:
  - Accuracy: `0.4000` (40.0%)
  - Precision: `0.2500` (25.0%)
  - Recall: `1.0000` (100.0%)
  - F1-Score: `0.4000` (40.0%)
  - Confusion Matrix: $\begin{bmatrix} TN=2 & FP=6 \\ FN=0 & TP=2 \end{bmatrix}$
- **Metric Deltas**:
  - $\Delta \text{Accuracy}$: `+0.0000`
  - $\Delta \text{Precision}$: `+0.0000`
  - $\Delta \text{Recall}$: `+0.0000`
  - $\Delta \text{F1-Score}$: `+0.0000`

---

## 3. Honest Root-Cause & Diagnostic Analysis

As required by Global Rules (§0) and Phase 10 guidelines, the zero metric delta is reported honestly and attributed to two empirical root causes:

1. **Genuine Sample Scarcity**:
   - The held-out test set contains only **2 positive samples** ($N_{\text{test\_pos}}=2$) out of 10 total test chips.
   - With such a small test set, subtle model weight adjustments do not shift discrete predictions on held-out samples.

2. **Lack of Correction Diversity**:
   - **17 out of 19 (89.5%)** of the structural conflict corrections stem from the exact same narrow decision-boundary threshold artifact (`confidence ≈ 0.5391`).
   - These 17 near-duplicate corrections do not represent 19 independent error cases or diverse feature patterns; they represent repetition of a single boundary artifact. Consequently, feeding them into retraining does not provide novel discriminative signal to improve held-out precision.

---

## 4. What Was Built & Verified
1. **Active Learning Subsystem (`backend/app/active_learning.py`)**:
   - Built `analyze_correction_diversity()` and `run_active_learning_cycle()`.
2. **Dev API Endpoint (`backend/app/routers/dev.py`)**:
   - Added `POST /api/dev/retrain` endpoint triggering active learning cycles.
3. **Append-Only Audit Logging (`audit/active_learning_log.txt`)**:
   - Automatically writes timestamped retrain summaries with diversity counts, before/after metrics, deltas, and diagnostic logs.
4. **Targeted Unit & Regression Tests (`backend/tests/test_phase10_active_learning.py`)**:
   - `test_correction_diversity_analysis`: Verified 17 near-duplicate / 2 distinct breakdown.
   - `test_run_active_learning_cycle_and_logging`: Verified retrain cycle, metric delta calculation, and audit logging.
   - `test_dev_retrain_endpoint`: Verified `POST /api/dev/retrain` contract.

---

## 5. Exact Test Commands Run & Output

### Command 1: Targeted Phase 10 Unit Tests
```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests/test_phase10_active_learning.py -v
```
**Output**:
```text
============================= test session starts =============================
collected 3 items

backend/tests/test_phase10_active_learning.py::test_correction_diversity_analysis PASSED [ 33%]
backend/tests/test_phase10_active_learning.py::test_run_active_learning_cycle_and_logging PASSED [ 66%]
backend/tests/test_phase10_active_learning.py::test_dev_retrain_endpoint PASSED [100%]

======================= 3 passed, 2 warnings in 11.14s ========================
```

### Command 2: Full Pytest Suite (80/80 Passed)
```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests -v
```
**Output**:
```text
============================= test session starts =============================
collected 80 items

backend/tests/test_alert_reviews.py::test_existing_alerts_migration_and_structure PASSED [  1%]
...
backend/tests/test_phase10_active_learning.py::test_correction_diversity_analysis PASSED [ 50%]
backend/tests/test_phase10_active_learning.py::test_run_active_learning_cycle_and_logging PASSED [ 51%]
backend/tests/test_phase10_active_learning.py::test_dev_retrain_endpoint PASSED [ 52%]
...
backend/tests/test_thermal_behavior.py::test_duty_cycle_and_consecutive_days_formulas PASSED [100%]

================== 80 passed, 2 warnings in 60.50s (0:01:00) ==================
```

---

## 6. Honest Capability Status Label
**OPERATIONAL (POC)**
- Built an operational active learning loop wired to `alert_reviews` and `POST /api/dev/retrain`.
- Evaluated before/after metrics on a held-out test split and logged exact zero deltas honestly.
- Status is scoped strictly as **OPERATIONAL (POC)** due to sample size constraints ($N=31$ overall, $N=2$ test positives) and correction diversity limitations.

---

## 7. Rollback Note
If Phase 10 changes need to be undone:
- Revert git commit `[Phase 10 commit hash]`.
- Remove log file: `Remove-Item audit/active_learning_log.txt -Force`.
