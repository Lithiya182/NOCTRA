"""Phase 11 regression & unit tests: RL-Based Action/Priority Policy."""
from __future__ import annotations

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rl_policy import DISCLAIMER, MODEL_PATH, suggest_priority, train_policy

client = TestClient(app)


def test_rl_policy_training_and_disclaimer():
    """Verify train_policy executes, saves model artifact, and includes mandatory disclaimer."""
    res = train_policy()
    assert res["status"] == "RESEARCH / EXPERIMENTAL — architecture only, awaiting real feedback data"
    assert res["total_alerts"] >= 30
    assert "action_distribution" in res
    assert "expected_mean_reward" in res
    assert res["disclaimer"] == DISCLAIMER
    assert os.path.exists(MODEL_PATH)


def test_suggest_priority_and_api_integration():
    """Verify suggest_priority returns priority tier and surfaces on /api/sites and /api/alerts APIs."""
    train_policy()

    # Query /api/sites
    res_sites = client.get("/api/sites")
    assert res_sites.status_code == 200
    sites = res_sites.json()
    assert len(sites) > 0
    first_site = sites[0]
    assert "suggested_priority" in first_site
    assert first_site["suggested_priority"] in ("urgent", "watch", "routine")
    assert "suggested_priority_confidence" in first_site

    # Query /api/alerts
    res_alerts = client.get("/api/alerts")
    assert res_alerts.status_code == 200
    alerts = res_alerts.json()
    assert len(alerts) > 0
    first_alert = alerts[0]
    assert "suggested_priority" in first_alert
    assert first_alert["suggested_priority"] in ("urgent", "watch", "routine")
    assert "suggested_priority_confidence" in first_alert


def test_rl_policy_reward_derivation():
    """Verify contextual bandit reward derivation for confirmed vs dismissed human reviews."""
    from app.rl_policy import compute_action_rewards

    confirmed_item = {"status": "confirmed", "max_frp": 120.0, "site_id": "test_site_1"}
    dismissed_item = {"status": "dismissed", "max_frp": 10.0, "site_id": "test_site_2"}

    r_conf = compute_action_rewards(confirmed_item, [])
    assert r_conf["urgent"] > r_conf["routine"]

    r_dism = compute_action_rewards(dismissed_item, [])
    assert r_dism["routine"] > r_dism["urgent"]
