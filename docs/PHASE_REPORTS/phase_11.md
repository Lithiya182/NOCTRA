# Phase 11 — RL-Based Action/Priority Policy (Contextual Bandit Formulation)

**Status**: RESEARCH / EXPERIMENTAL — architecture only, awaiting real feedback data  
**Date**: September 23, 2026  
**Commit**: `[Phase 11] RL contextual bandit action-prioritization policy — honest disclaimer & status update — 83/83 passed`

---

## 1. Explicit Scoping Disclaimer & Methodological Framing

> [!IMPORTANT]
> **Mandatory Scoping Disclaimer**:  
> *"This is a contextual-bandit action-prioritization architecture initialized against a rule-based severity/FRP heuristic proxy. No real human-review data currently exists in alert_reviews, so no learning from real human feedback has occurred yet; the model serves as a prioritization framework ready to learn from operator feedback as real reviews accumulate."*

- **Problem & Reward Formulation**: Formulated as an offline contextual bandit framework:
  - **Context ($\mathbf{x}$)**: 6-dimensional feature vector per site/alert ($FRP$, $duty\_cycle$, $d_{\text{industrial}}$, $confidence$, $persistence$, $is\_anomalous$).
  - **Actions ($a$)**: Priority tier selection $\in \{\text{"routine"}, \text{"watch"}, \text{"urgent"}\}$.
  - **Reward Proxy ($R$)**: An empirical database audit confirmed **0 confirmed alerts, 0 dismissed alerts, and 0 rows in `alert_reviews`**. Because zero real human review outcomes currently exist in the database, the policy was initialized against a rule-based severity/FRP heuristic proxy as a stand-in reward signal.

---

## 2. What Was Built
1. **Contextual Bandit Subsystem (`backend/app/rl_policy.py`)**:
   - Implemented `ContextualBanditPolicy` (LinUCB formulation with linear upper confidence bounds).
   - Built `extract_context()`, `compute_action_rewards()`, `train_policy()`, and `suggest_priority()`.
   - Serialized trained policy artifact to `backend/models/rl_policy.pkl`.

2. **API Schema & Response Integration (`backend/app/models.py`, `backend/app/routers/sites.py`, `backend/app/alert_engine.py`)**:
   - Added `suggested_priority: Optional[str]` and `suggested_priority_confidence: Optional[float]` fields to `SiteRow` and `AlertOut` Pydantic models.
   - Wired `rl_policy.suggest_priority()` into site and alert list resolution.
   - **Human-in-the-loop**: Policy outputs function purely as operator recommendations in the dashboard and never auto-execute actions.

3. **Targeted Unit & Regression Tests (`backend/tests/test_phase11_rl_policy.py`)**:
   - `test_rl_policy_training_and_disclaimer`: Verifies model training, artifact creation, sample counts, and corrected disclaimer text.
   - `test_suggest_priority_and_api_integration`: Verifies contract on `/api/sites` and `/api/alerts`.
   - `test_rl_policy_reward_derivation`: Verifies reward matrix logic for confirmed vs. dismissed reviews and heuristic fallback.

---

## 3. Empirical Evaluation & Policy Metrics

- **Total Sample Size**: $N=30$ alerts in dataset.
- **Reviewed Alerts**: $N_{\text{reviewed}}=0$ (0 confirmed, 0 dismissed stored in DB baseline; rewards derived via default severity/FRP proxy).
- **Action Distribution Across Alerts**:
  - `urgent`: **10** (33.3%)
  - `watch`: **5** (16.7%)
  - `routine`: **15** (50.0%)
- **Expected Mean Policy Reward**: `0.5833`
- **Zero Real Learning Caveat**: Because no real human reviews exist in the database, **no actual learning from human feedback has occurred yet**. The model serves purely as a rule-based prioritization scorer with bandit architecture ready to ingest feedback post-deployment.

---

## 4. Exact Test Commands Run & Output

### Command 1: Targeted Phase 11 Unit Tests
```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests/test_phase11_rl_policy.py -v
```
**Output**:
```text
============================= test session starts =============================
collected 3 items

backend/tests/test_phase11_rl_policy.py::test_rl_policy_training_and_disclaimer PASSED [ 33%]
backend/tests/test_phase11_rl_policy.py::test_suggest_priority_and_api_integration PASSED [ 66%]
backend/tests/test_phase11_rl_policy.py::test_rl_policy_reward_derivation PASSED [100%]

======================== 3 passed, 2 warnings in 6.04s ========================
```

### Command 2: Full Pytest Suite (83/83 Passed)
```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest backend/tests -v
```
**Output**:
```text
============================= test session starts =============================
collected 83 items

backend/tests/test_alert_reviews.py::test_existing_alerts_migration_and_structure PASSED [  1%]
...
backend/tests/test_phase11_rl_policy.py::test_rl_policy_training_and_disclaimer PASSED [ 51%]
backend/tests/test_phase11_rl_policy.py::test_suggest_priority_and_api_integration PASSED [ 53%]
backend/tests/test_phase11_rl_policy.py::test_rl_policy_reward_derivation PASSED [ 54%]
...
backend/tests/test_thermal_behavior.py::test_duty_cycle_and_consecutive_days_formulas PASSED [100%]

================== 83 passed, 2 warnings in 63.40s (0:01:03) ==================
```

---

## 5. Honest Capability Status Label
**RESEARCH / EXPERIMENTAL — architecture only, awaiting real feedback data**
- Built an operational LinUCB contextual bandit priority scoring framework wired to `/api/sites` and `/api/alerts`.
- Confirmed zero human review entries currently exist in `alert_reviews`, so initialized against a severity/FRP heuristic proxy as a stand-in.
- Status is scoped strictly as **RESEARCH / EXPERIMENTAL — architecture only, awaiting real feedback data** because no learning from real human feedback has occurred yet.

---

## 6. Rollback Note
If Phase 11 changes need to be undone:
- Revert git commit `[Phase 11 commit hash]`.
- Remove model artifact: `Remove-Item backend/models/rl_policy.pkl -Force`.
