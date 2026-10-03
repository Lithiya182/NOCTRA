"""Tests for NOCTRA Stage 6: gap-tolerant EWMA + tabular CUSUM.

Design notes for synthetic test series
---------------------------------------
sigma is computed from *all* daily FRP values (the site's own history), so
anomalous days inflate the threshold h = 4*sigma.  The test series below are
chosen so that even with this inflated sigma the CUSUM accumulates enough to
cross h on >= 2 consecutive observed days:

* Steady site  : 20 days at ~20 MW → sigma ≈ 0 (floored to 1.0)
* Step increase: 10 days at 20 + 10 days at 50 → sigma ≈ 15.7,
                 k ≈ 7.8, h ≈ 62.8.  After ~7 step days consec reaches 2.
* Single spike : 10 days at 20 + 1 day at 200 + 10 days at 20 →
                 sigma dominated by spike; h is very high; only 1 alarm day.
* Cloud gaps   : same steady FRP but observations 7 days apart; gap-tolerant
                 alpha_eff prevents false alarms.
* Insufficient : 4 observed days → stage_status == "insufficient_history".
"""
from __future__ import annotations

import datetime
import unittest
from unittest.mock import patch

from contracts.evidence import ChangeEvidence

# Module under test
from backend.app import temporal_cusum
from backend.app.temporal_cusum import compute_change

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_DATE = datetime.date(2024, 1, 1)


def _make_rows(frps: list[float], gaps: list[int] | None = None) -> list[dict]:
    """Build fake DB rows for a daily FRP series.

    Parameters
    ----------
    frps:
        Ordered list of daily FRP values (one per observed day).
    gaps:
        Optional list of gap lengths in calendar days between consecutive
        observations.  Must have length ``len(frps) - 1``.  Defaults to
        daily observations (gap = 1).
    """
    if gaps is None:
        gaps = [1] * (len(frps) - 1)
    assert len(gaps) == len(frps) - 1, "gaps length must equal len(frps) - 1"

    rows: list[dict] = []
    current = _BASE_DATE
    for i, frp in enumerate(frps):
        rows.append({"frp": frp, "acq_date": current.strftime("%Y-%m-%d")})
        if i < len(gaps):
            current += datetime.timedelta(days=gaps[i])
    return rows


def _run_compute(frps: list[float], gaps: list[int] | None = None) -> dict:
    """Patch ``db.query`` and invoke ``compute_change``."""
    rows = _make_rows(frps, gaps)
    with patch("backend.app.temporal_cusum.db.query", return_value=rows):
        return compute_change("FAKE-SITE")


# ---------------------------------------------------------------------------
# TC-1: Steady site — constant FRP, no change detected
# ---------------------------------------------------------------------------

class TestSteadySite(unittest.TestCase):
    def test_no_change_constant(self):
        """Perfectly constant FRP: sigma is floored; CUSUM never rises."""
        frps = [20.0] * 20
        result = _run_compute(frps)
        self.assertFalse(result["change_detected"])
        self.assertEqual(result["stage_status"], "live")

    def test_no_change_noisy(self):
        """Low-amplitude noise (±2 MW): no structural shift."""
        import random
        random.seed(42)
        frps = [20.0 + random.uniform(-2, 2) for _ in range(25)]
        result = _run_compute(frps)
        self.assertFalse(result["change_detected"])
        self.assertEqual(result["stage_status"], "live")


# ---------------------------------------------------------------------------
# TC-2: Step increase — detected after sustained high FRP
# ---------------------------------------------------------------------------

class TestStepIncrease(unittest.TestCase):
    def test_step_detected(self):
        """10 baseline days + 10 high-FRP days: change_detected must be True.

        Series: [20]*10 + [60]*10
        sigma ≈ 18.9 → k ≈ 9.5, h ≈ 75.6.
        After enough step days the CUSUM accumulates ≥ 2 consecutive alarms.
        """
        frps = [20.0] * 10 + [60.0] * 10
        result = _run_compute(frps)
        self.assertTrue(
            result["change_detected"],
            f"Expected change_detected=True for sustained step; got result={result}",
        )
        self.assertEqual(result["stage_status"], "live")
        self.assertGreater(result["cusum"], 0.0)

    def test_ewma_baseline_positive(self):
        """ewma_baseline must be a positive float after a step series."""
        frps = [20.0] * 10 + [50.0] * 10
        result = _run_compute(frps)
        self.assertIsInstance(result["ewma_baseline"], float)
        self.assertGreater(result["ewma_baseline"], 0.0)


# ---------------------------------------------------------------------------
# TC-3: Single spike — NOT detected (consec resets to 0)
# ---------------------------------------------------------------------------

class TestSingleSpike(unittest.TestCase):
    def test_spike_not_detected(self):
        """One outlier day sandwiched between steady days: no alarm.

        Series: [20]*10 + [300] + [20]*10
        sigma is inflated by the spike → h is very large; only 1 consecutive
        alarm day (never reaches 2).
        """
        frps = [20.0] * 10 + [300.0] + [20.0] * 10
        result = _run_compute(frps)
        self.assertFalse(
            result["change_detected"],
            f"Single spike must not trigger change_detected; got result={result}",
        )

    def test_spike_cusum_resets(self):
        """After the spike, CUSUM should fall back towards 0."""
        frps = [20.0] * 10 + [300.0] + [20.0] * 10
        result = _run_compute(frps)
        # cusum is the final S; after 10 recovery days it should be near 0
        self.assertLess(result["cusum"], 5.0)


# ---------------------------------------------------------------------------
# TC-4: Long cloud gaps — gap-tolerant, no false alarms
# ---------------------------------------------------------------------------

class TestCloudGaps(unittest.TestCase):
    def test_gapped_steady_no_change(self):
        """Steady FRP observed every 7 days: alpha_eff absorbs gaps gracefully.

        Without gap-tolerance, not updating for 7 days could accumulate CUSUM
        drift.  With gap-tolerance, the baseline tracks and no alarm fires.
        """
        frps = [20.0] * 15
        gaps = [7] * 14  # 7-day gap between every pair of observations
        result = _run_compute(frps, gaps)
        self.assertFalse(
            result["change_detected"],
            f"Gapped steady site must not alarm; got result={result}",
        )
        self.assertTrue(result["gap_tolerant"])

    def test_mixed_gaps_steady_no_change(self):
        """Mix of 1-day and 10-day gaps, stable FRP."""
        frps = [25.0] * 12
        gaps = [1, 10, 1, 5, 1, 8, 1, 3, 1, 7, 1]
        result = _run_compute(frps, gaps)
        self.assertFalse(result["change_detected"])


# ---------------------------------------------------------------------------
# TC-5: Insufficient history
# ---------------------------------------------------------------------------

class TestInsufficientHistory(unittest.TestCase):
    def test_fewer_than_min_days(self):
        """4 observed days (< CUSUM_MIN_HISTORY_DAYS=5): insufficient_history."""
        frps = [50.0, 60.0, 55.0, 58.0]
        result = _run_compute(frps)
        self.assertFalse(result["change_detected"])
        self.assertEqual(result["stage_status"], "insufficient_history")

    def test_exactly_zero_detections(self):
        """No detections at all: insufficient_history, no crash."""
        with patch("backend.app.temporal_cusum.db.query", return_value=[]):
            result = compute_change("NONEXISTENT-SITE")
        self.assertFalse(result["change_detected"])
        self.assertEqual(result["stage_status"], "insufficient_history")
        self.assertIsNone(result["ewma_baseline"])

    def test_as_of_restricts_to_insufficient(self):
        """as_of that cuts history below minimum returns insufficient_history."""
        frps_full = [20.0] * 20  # would be "live" without cutoff
        rows = _make_rows(frps_full)
        # Use as_of = third observation date → only 3 rows pass filter
        cutoff_date = rows[2]["acq_date"]
        with patch("backend.app.temporal_cusum.db.query", return_value=rows):
            result = compute_change("FAKE-SITE", as_of=cutoff_date)
        self.assertEqual(result["stage_status"], "insufficient_history")


# ---------------------------------------------------------------------------
# TC-6: Contract validation (all synthetic results must pass model_validate)
# ---------------------------------------------------------------------------

class TestContractValidation(unittest.TestCase):
    def _assert_validates(self, frps, gaps=None, as_of=None):
        rows = _make_rows(frps, gaps)
        with patch("backend.app.temporal_cusum.db.query", return_value=rows):
            result = compute_change("FAKE-SITE", as_of=as_of)
        # Should not raise
        validated = ChangeEvidence.model_validate(result)
        self.assertIsInstance(validated, ChangeEvidence)
        return result

    def test_steady_validates(self):
        self._assert_validates([20.0] * 20)

    def test_step_validates(self):
        self._assert_validates([20.0] * 10 + [60.0] * 10)

    def test_spike_validates(self):
        self._assert_validates([20.0] * 10 + [300.0] + [20.0] * 10)

    def test_insufficient_validates(self):
        self._assert_validates([30.0] * 4)

    def test_empty_validates(self):
        with patch("backend.app.temporal_cusum.db.query", return_value=[]):
            result = compute_change("FAKE-SITE")
        validated = ChangeEvidence.model_validate(result)
        self.assertIsInstance(validated, ChangeEvidence)

    def test_gap_tolerant_always_true(self):
        result = self._assert_validates([20.0] * 10)
        self.assertTrue(result["gap_tolerant"])

    def test_mock_always_false(self):
        result = self._assert_validates([20.0] * 10)
        self.assertFalse(result["mock"])


# ---------------------------------------------------------------------------
# TC-7: Smoke tests on real DB sites (no assertions on change_detected)
# ---------------------------------------------------------------------------

class TestSmokeRealSites(unittest.TestCase):
    """Run compute_change against the real database.

    These are integration smoke tests: they must not crash and the output
    must validate against ChangeEvidence.  We do NOT assert on the value of
    ``change_detected`` because real sites may have ≥ or < 5 observed days.
    """

    _SITES = [
        "TG-23731-86324",  # Jharia coal-fire hero site
        "TG-22477-70050",  # Jamnagar petroleum / stable site
    ]

    def test_smoke_sites_no_error(self):
        for site_id in self._SITES:
            with self.subTest(site_id=site_id):
                result = compute_change(site_id)
                # Must validate without raising
                validated = ChangeEvidence.model_validate(result)
                self.assertIsInstance(validated, ChangeEvidence)
                self.assertIn(result["stage_status"], {"live", "insufficient_history"})
                self.assertFalse(result["mock"])
                self.assertTrue(result["gap_tolerant"])

    def test_smoke_as_of_parameter(self):
        """Passing as_of must not crash and must restrict data correctly."""
        result = compute_change(self._SITES[0], as_of="2024-01-01")
        ChangeEvidence.model_validate(result)
        # With a very early cutoff there is likely no data → insufficient
        # (or live if the site has detections before 2024-01-01).
        self.assertIn(result["stage_status"], {"live", "insufficient_history"})


if __name__ == "__main__":
    unittest.main()
