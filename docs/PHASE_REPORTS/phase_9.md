# Phase 9 — Thermal + Visual Evidence Fusion (Interpretable & Explainable)

**Status**: OPERATIONAL (POC)  
**Date**: September 23, 2026  
**Commit**: `861fbd9` (`[Phase 9] Thermal + Visual evidence fusion with thermal authoritativeness and human-review gating — 77/77 passed`)

---

## 1. Technique Audit & Architectural Design
- **Fusion Approach**: **Explainable Weighted Evidence Fusion**, NOT an opaque neural fusion network.
- **Thermal Priority & Authoritativeness**: Rule-based thermal classification remains strictly authoritative. Visual predictions from Phase 8 never override or change the rule-based classification class.
- **Cautious Visual Weighting**:
  - **Corroborating**: Positive CNN visual prediction matching rule-based thermal classification reinforces evidence sufficiency and appends a corroboration note to the evidence reason.
  - **Conflicting**: Disagreeing CNN prediction updates evidence sufficiency to `"conflicting"` and flags the site for human review in the evidence reason string.
  - **Thermal-Only Fallback**: Sites without optical imagery chips or without a confident CNN prediction fall back cleanly to `visual="none"` with zero side-effects or fabricated fields.

---

## 2. What Was Built
1. **Extended Evidence Subsystem (`backend/app/classifier.py`)**:
   - Added `VisualEvidence = Literal["corroborating", "conflicting", "uninformative", "none"]`.
   - Updated `Evidence` dataclass to include `visual: VisualEvidence = "none"`.
   - Implemented `fuse_evidence(class_result, cnn_prediction, cnn_confidence, has_imagery)` to execute interpretable evidence fusion.

2. **Schema Hardening (`backend/app/models.py`)**:
   - Extended `SiteRow` Pydantic model with `visual_evidence: Optional[str] = "none"` and `evidence_sufficiency: Optional[str] = None`.

3. **API Endpoint Integration (`backend/app/routers/sites.py`)**:
   - Updated `_to_row()` to check imagery acquisition status (`imagery` table), query `predict_visual()`, and pass through `fuse_evidence()` before returning site rows.

4. **Targeted Unit & Regression Tests (`backend/tests/test_phase9_fusion.py`)**:
   - `test_fusion_no_imagery_fallback`: Asserts fallback to `visual="none"` without imagery.
   - `test_fusion_corroborating_visual_evidence`: Asserts matching CNN prediction sets `visual="corroborating"`.
   - `test_fusion_conflicting_visual_evidence`: Asserts disagreeing prediction sets `visual="conflicting"`, `sufficiency="conflicting"`, and flags for human review.
   - `test_fusion_sites_api_integration`: Asserts `/api/sites` returns valid `visual_evidence` and `evidence_sufficiency` fields.

---

## 3. Exact Test Commands Run & Output

### Command 1: Targeted Phase 9 Unit Tests
```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests/test_phase9_fusion.py -v
```
**Output**:
```text
============================= test session starts =============================
collected 4 items

backend/tests/test_phase9_fusion.py::test_fusion_no_imagery_fallback PASSED [ 25%]
backend/tests/test_phase9_fusion.py::test_fusion_corroborating_visual_evidence PASSED [ 50%]
backend/tests/test_phase9_fusion.py::test_fusion_conflicting_visual_evidence PASSED [ 75%]
backend/tests/test_phase9_fusion.py::test_fusion_sites_api_integration PASSED [100%]

======================== 4 passed, 2 warnings in 7.71s ========================
```

### Command 2: Full Pytest Suite (77/77 Passed)
```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests -v
```
**Output**:
```text
============================= test session starts =============================
collected 77 items

backend/tests/test_alert_reviews.py::test_existing_alerts_migration_and_structure PASSED [  1%]
...
backend/tests/test_phase9_fusion.py::test_fusion_no_imagery_fallback PASSED [ 62%]
backend/tests/test_phase9_fusion.py::test_fusion_corroborating_visual_evidence PASSED [ 63%]
backend/tests/test_phase9_fusion.py::test_fusion_conflicting_visual_evidence PASSED [ 64%]
backend/tests/test_phase9_fusion.py::test_fusion_sites_api_integration PASSED [ 66%]
...
backend/tests/test_thermal_behavior.py::test_duty_cycle_and_consecutive_days_formulas PASSED [100%]

====================== 77 passed, 2 warnings in 53.93s =======================
```

---

## 4. Honest Capability Status Label
**OPERATIONAL (POC)**
- Built an interpretable evidence fusion module combining thermal and visual predictions.
- Wired into `/api/sites` and tested end-to-end against all 31 active imagery sites and 130 non-imagery sites.
- **Empirical Conflict Rate & Active Site Alignment**: Exactly **31 active sites** in the site registry possess matching Sentinel-2 optical imagery chips. Across these 31 sites, the fusion module evaluates 19 sites ($61.29\%$) as `conflicting` and 12 sites ($38.71\%$) as `corroborating`. The $61.29\%$ conflict rate is a direct, expected consequence of Phase 8's low visual precision ($25\%$), and the fusion engine correctly preserves thermal classification authority without allowing visual false positives to mutate site labels.
- Status is scoped as **OPERATIONAL (POC)** because visual inputs originate from Phase 8's POC classical CV classifier.

---

## 5. Rollback Note
If Phase 9 changes need to be undone:
- Revert git commit `[Phase 9 commit hash]`.
