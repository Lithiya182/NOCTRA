"""Phase 10 regression & unit tests: Human Feedback / Active Learning Loop."""
from __future__ import annotations

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.active_learning import LOG_FILE, analyze_correction_diversity, run_active_learning_cycle
from app.main import app

client = TestClient(app)


def test_correction_diversity_analysis():
    """Verify correction diversity breaks down the 19 conflicting sites into 17 near-duplicate vs 2 distinct cases."""
    div = analyze_correction_diversity()
    assert div["total_conflicts"] == 19
    assert div["near_duplicate_count"] == 17
    assert div["distinct_count"] == 2
    assert div["near_duplicate_pct"] == 89.5
    assert div["distinct_pct"] == 10.5


def test_run_active_learning_cycle_and_logging():
    """Verify active learning retraining cycle executes, computes deltas, and writes audit log."""
    res = run_active_learning_cycle()
    assert res["status"] == "OPERATIONAL (POC)"
    assert "timestamp" in res
    assert "diversity" in res
    assert "deltas" in res
    assert "diagnosis" in res
    assert os.path.exists(LOG_FILE)

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        log_content = f.read()

    assert "ACTIVE LEARNING RETRAIN EVENT" in log_content
    assert "Near-Duplicate Cases (conf ≈0.5391): 17 (89.5%)" in log_content
    assert "Distinct Disagreements: 2 (10.5%)" in log_content
    assert "Diagnostic Analysis:" in log_content


def test_dev_retrain_endpoint():
    """Verify POST /api/dev/retrain triggers active learning cycle and returns 200 OK."""
    res = client.post("/api/dev/retrain")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "OPERATIONAL (POC)"
    assert "diversity" in body
    assert "deltas" in body
