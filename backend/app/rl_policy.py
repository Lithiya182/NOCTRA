"""Phase 11: RL-Based Action/Priority Policy (Contextual Bandit Formulation).

EXPLICIT DISCLAIMER:
"This is a contextual-bandit action-prioritization architecture initialized against a
rule-based severity/FRP heuristic proxy. No real human-review data currently exists in
alert_reviews, so no learning from real human feedback has occurred yet; the model serves
as a prioritization framework ready to learn from operator feedback as real reviews accumulate."

Context: Site/Alert features [FRP, duty_cycle, d_industrial, confidence, persistence, is_anomalous]
Action: Alert priority tier ["routine", "watch", "urgent"]
Reward: Derived from rule-based severity/FRP heuristic proxy pending real human review feedback.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from . import db

log = logging.getLogger("thermalguard.rl_policy")

ACTIONS = ["routine", "watch", "urgent"]
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_PATH = MODEL_DIR / "rl_policy.pkl"

DISCLAIMER = (
    "This is a contextual-bandit action-prioritization architecture initialized against a "
    "rule-based severity/FRP heuristic proxy. No real human-review data currently exists in "
    "alert_reviews, so no learning from real human feedback has occurred yet; the model serves "
    "as a prioritization framework ready to learn from operator feedback as real reviews accumulate."
)


class ContextualBanditPolicy:
    """Linear Upper Confidence Bound (LinUCB) Contextual Bandit Policy."""

    def __init__(self, d: int = 6, alpha: float = 0.5):
        self.d = d
        self.alpha = alpha
        self.actions = ACTIONS
        self.k = len(ACTIONS)
        # Initialize LinUCB parameters per action: A = I, b = 0
        self.A = [np.eye(d, dtype=np.float64) for _ in range(self.k)]
        self.b = [np.zeros(d, dtype=np.float64) for _ in range(self.k)]

    def fit_sample(self, x: np.ndarray, action_idx: int, reward: float) -> None:
        """Update LinUCB parameters for a context-action-reward tuple."""
        x_col = x.reshape(-1, 1)
        self.A[action_idx] += x_col @ x_col.T
        self.b[action_idx] += reward * x

    def predict(self, x: np.ndarray) -> Tuple[str, float, Dict[str, float]]:
        """Predict priority tier, confidence, and action probabilities for context vector x."""
        scores = np.zeros(self.k)
        for i in range(self.k):
            A_inv = np.linalg.pinv(self.A[i])
            theta = A_inv @ self.b[i]
            expected_reward = float(x @ theta)
            var = float(x @ A_inv @ x)
            ucb = expected_reward + self.alpha * np.sqrt(max(0.0, var))
            scores[i] = ucb

        # Softmax over scores for action probabilities
        exp_scores = np.exp(scores - np.max(scores))
        probs = exp_scores / np.sum(exp_scores)
        prob_dict = {self.actions[i]: round(float(probs[i]), 4) for i in range(self.k)}

        best_idx = int(np.argmax(scores))
        chosen_action = self.actions[best_idx]
        confidence = round(float(probs[best_idx]), 4)

        return chosen_action, confidence, prob_dict


def extract_context(site_or_alert: dict) -> np.ndarray:
    """Extract normalized feature context vector (dimension 6)."""
    frp = float(site_or_alert.get("max_frp") or site_or_alert.get("frp") or 0.0)
    duty_cycle = float(site_or_alert.get("duty_cycle_pct") or 0.0)
    d_ind = float(site_or_alert.get("d_industrial_m") or site_or_alert.get("d_industrial") or 10000.0)
    conf = float(site_or_alert.get("confidence") or 0.5)
    pers = float(site_or_alert.get("persistence") or 0.0)
    anom = 1.0 if bool(site_or_alert.get("is_anomalous")) else 0.0

    return np.array([
        min(frp, 200.0) / 200.0,
        min(duty_cycle, 100.0) / 100.0,
        min(d_ind, 10000.0) / 10000.0,
        min(max(conf, 0.0), 1.0),
        min(pers, 5.0) / 5.0,
        anom,
    ], dtype=np.float64)


def compute_action_rewards(site_or_alert: dict, reviews: List[dict]) -> Dict[str, float]:
    """Compute rewards R(a) for each priority tier derived from human review outcomes."""
    status = site_or_alert.get("status")
    classification = site_or_alert.get("classification", "other")
    frp = float(site_or_alert.get("max_frp") or 0.0)

    # Check review audit table for explicit feedback
    site_id = site_or_alert.get("site_id")
    site_reviews = [r for r in reviews if r.get("site_id") == site_id]
    latest_review = site_reviews[0] if site_reviews else None

    if latest_review and latest_review.get("action") == "confirm" or status == "confirmed":
        return {"urgent": 1.0, "watch": 0.5, "routine": -0.8}
    if latest_review and latest_review.get("action") == "dismiss" or status == "dismissed":
        return {"urgent": -1.0, "watch": -0.3, "routine": 1.0}

    # Unreviewed default rewards based on severity & classification
    if classification == "industrial_fire" or frp >= 50.0:
        return {"urgent": 0.8, "watch": 0.4, "routine": -0.5}
    if classification == "agricultural_burn" or classification == "wildfire" or frp >= 20.0:
        return {"urgent": 0.3, "watch": 0.7, "routine": 0.0}
    return {"urgent": -0.4, "watch": 0.3, "routine": 0.6}


def train_policy() -> Dict[str, Any]:
    """Train contextual bandit action-prioritization policy on historical alerts & human reviews."""
    alerts = [dict(r) for r in db.query("SELECT * FROM alerts")]
    reviews = [dict(r) for r in db.query("SELECT * FROM alert_reviews ORDER BY created_at DESC")]

    policy = ContextualBanditPolicy(d=6, alpha=0.5)
    rewards_accum: List[float] = []
    action_counts = {"urgent": 0, "watch": 0, "routine": 0}

    reviewed_count = 0
    for a in alerts:
        # Load site info if missing
        if "max_frp" not in a:
            s_rows = db.query("SELECT * FROM sites WHERE site_id=?", (a["site_id"],))
            if s_rows:
                s = dict(s_rows[0])
                a.update(s)

        ctx = extract_context(a)
        rewards_map = compute_action_rewards(a, reviews)

        if a.get("status") in ("confirmed", "dismissed") or any(r.get("site_id") == a.get("site_id") for r in reviews):
            reviewed_count += 1

        # Train policy on all context-action-reward pairs
        for act_idx, act_name in enumerate(ACTIONS):
            r_val = rewards_map[act_name]
            policy.fit_sample(ctx, act_idx, r_val)

        # Predict policy action
        pred_act, pred_conf, _ = policy.predict(ctx)
        action_counts[pred_act] += 1
        rewards_accum.append(rewards_map[pred_act])

    # Save model artifact
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(policy, f)

    mean_reward = round(float(np.mean(rewards_accum)), 4) if rewards_accum else 0.0

    return {
        "status": "RESEARCH / EXPERIMENTAL — architecture only, awaiting real feedback data",
        "total_alerts": len(alerts),
        "reviewed_alerts": reviewed_count,
        "unreviewed_alerts": len(alerts) - reviewed_count,
        "action_distribution": action_counts,
        "expected_mean_reward": mean_reward,
        "disclaimer": DISCLAIMER,
        "model_file": str(MODEL_PATH),
    }


_cached_policy: ContextualBanditPolicy | None = None


def load_policy() -> ContextualBanditPolicy:
    global _cached_policy
    if _cached_policy is not None:
        return _cached_policy
    if MODEL_PATH.exists():
        try:
            with open(MODEL_PATH, "rb") as f:
                _cached_policy = pickle.load(f)
                return _cached_policy
        except Exception as exc:
            log.warning(f"Failed to load RL policy model: {exc}")
    # Train default policy if artifact missing
    train_policy()
    return load_policy()


def suggest_priority(site_or_alert: dict) -> Tuple[str, float]:
    """Suggest priority tier ('routine', 'watch', 'urgent') and confidence using bandit policy."""
    policy = load_policy()
    ctx = extract_context(site_or_alert)
    action, conf, _ = policy.predict(ctx)
    return action, conf
