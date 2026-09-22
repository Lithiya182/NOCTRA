# NOCTRA Phase Report — Phase 4: Classification & Evidence Review

**Date**: September 23, 2026  
**Branch**: `thermalguard/classifier-correctness-validation`  
**Status**: OPERATIONAL — VERIFIED  

---

## 1. Executive Summary
- **Objective**: Conduct a rigorous boundary and precedence-order review of the rule-based classification engine (`classifier.py`) and `Evidence` dataclass to ensure zero regressions or ambiguity before ML/visual downstream layers rely on classification outputs.
- **Outcome**: Verified that classification precedence order (Rule 1: Industrial Fire -> Rule 2: Agricultural Burn -> Rule 3: Wildfire -> Rule 4: Other) and evidence evaluation criteria are fully intact and deterministic. Expanded `test_classifier_correctness.py` with 5 new edge-case tests, bringing total test suite pass count to 61 / 61 passing (100% green).

---

## 2. Rule Engine Precedence & Edge Case Verification

```
[Site Detection & Spatial Input]
              │
              ▼
   ┌──────────────────────┐
   │  Rule 1: Industrial  │ ──(Inside polygon OR <=500m + Temporal)──► "industrial_fire" (Confidence 0.90/0.80)
   └──────────────────────┘
              │ (No match)
              ▼
   ┌──────────────────────┐
   │ Rule 2: Agri Burn    │ ──(Inside agri + <=3 consec days + Agri Month)──► "agricultural_burn" (Confidence 0.75)
   └──────────────────────┘
              │ (No match)
              ▼
   ┌──────────────────────┐
   │  Rule 3: Wildfire    │ ──(Cluster expanded + >50 MW + >500m from ind/agri)──► "wildfire" (Confidence 0.70-0.95)
   └──────────────────────┘
              │ (No match)
              ▼
   ┌──────────────────────┐
   │    Rule 4: Other     │ ──(Fallback / Default)──► "other" (Confidence 0.40)
   └──────────────────────┘
```

### Verified Edge Cases
1. **Industrial Distance Boundary (`IND_DIST_M = 500m`)**:
   - Sites at `<= 500m` with sufficient temporal evidence produce `industrial_fire` (proximity evidence).
   - Sites at `<= 500m` without sufficient temporal evidence are assigned `other` with explicit explanation detailing temporal requirement (`>= 3` observation days or `>= 3` active passes).
2. **Agricultural Season Month Boundaries (`AGR_MONTHS = {4, 5, 10, 11}`)**:
   - Multi-day burns crossing month boundaries (e.g. April 30 in month 4 to May 1 in month 5) are correctly recognized as agricultural season burns.
3. **Agricultural Streak Cap (`AGR_MAX_CONSEC_DAYS = 3`)**:
   - `consec_days = 3` classifies as `agricultural_burn`.
   - `consec_days = 4` exceeds agricultural threshold and falls through to `other`.
4. **Wildfire FRP Threshold (`WILDFIRE_FRP_MIN = 50.0 MW`)**:
   - `max_frp = 50.0 MW` is rejected (requires `> 50.0 MW`), preventing low-energy clusters from misclassifying as wildfires.
5. **Strict Precedence Order**:
   - Sites satisfying both industrial proximity and agricultural season/streak criteria strictly resolve to `industrial_fire`.

---

## 3. Implementation Details

### Files Modified
1. `backend/tests/test_classifier_correctness.py` `[MODIFY]`:
   - Added `test_edge_case_industrial_distance_boundary()`
   - Added `test_edge_case_agricultural_month_boundary()`
   - Added `test_edge_case_agricultural_consecutive_days_boundary()`
   - Added `test_edge_case_wildfire_frp_threshold()`
   - Added `test_edge_case_precedence_order()`

---

## 4. Test Results & Metrics Table

- **Test Command**: `.venv\Scripts\python.exe -m pytest backend/tests -v`
- **Pass Rate**: 61 / 61 passed (100%)

| Test Subsystem | Pre-Phase Count | Post-Phase Count | Status |
| --- | --- | --- | --- |
| Classifier Edge Cases (`test_classifier_correctness.py`) | 12 | 17 | OPERATIONAL — VERIFIED |
| Thermal Behavior (`test_thermal_behavior.py`) | 11 | 11 | OPERATIONAL — VERIFIED |
| Provenance & DB WAL/Indexes (`test_provenance.py`) | 5 | 5 | OPERATIONAL — VERIFIED |
| Scheduler Lifespan Toggle (`test_firms_scheduler.py`) | 18 | 18 | OPERATIONAL — VERIFIED |
| Success Criteria & Ingestion (`test_success_criteria.py`) | 10 | 10 | OPERATIONAL — VERIFIED |
| **Total Test Suite** | **56** | **61** | **OPERATIONAL — VERIFIED** |

---

## 5. Status Label Assessment
- **Rule-Based Fire Classifier**: `OPERATIONAL — VERIFIED`
- **Evidence Dataclass Engine**: `OPERATIONAL — VERIFIED`

---

## 6. Deferred Items
- **Phase 5**: Alert reviews audit table and analyst note endpoint fields.
- **Phase 7**: AWS STAC Sentinel-2 imagery integration.

---

## 7. Rollback & Recovery Note
- **Commit Baseline**: `1b28cc4` (`[Phase 3] Thermal intelligence review & formula locking regression tests — 56/56 passed`)
- **To Roll Back Phase 4**:
  ```bash
  git checkout 1b28cc4 -- backend/tests/test_classifier_correctness.py
  rm docs/PHASE_REPORTS/phase_4.md
  ```
