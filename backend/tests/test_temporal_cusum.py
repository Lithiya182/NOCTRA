"""Tests for NOCTRA Stage 6: gap-tolerant EWMA + tabular CUSUM.

Design notes for synthetic test series
---------------------------------------
sigma is computed from the **reference period** (all but the last
CUSUM_TAIL_DAYS=3 observed days), so recent anomalies cannot inflate their
own detection threshold.  Sigma is floored at max(CUSUM_SIGMA_FLOOR,
CUSUM_BASELINE_SIGMA_RATIO * baseline) to avoid over-sensitivity on short or
low-variance series.

CUSUM resets to 0 after each alarm; change_detected is True only if an alarm
fired within CUSUM_RECENT_DAYS=7 observed days (or is actively alarmed).
The reported cusum statistic is the peak value within the recent window
so cusum and change_detected agree.

* Steady site    : 20 days at ~20 MW → sigma floored; no alarm.
* Step increase  : 10 days at 20 + 10 days at 60 MW → alarm fires mid-step;
                   recency window still open; peak cusum > 0.
* Single spike   : 10 days at 20 + 1 day at 300 + 10 days at 20 →
                   only 1 spike day (consec never reaches 2); after 10 recovery
                   days (outside 7-day window) peak cusum < 5.
* Cloud gaps     : steady FRP with irregular 1-10 day gaps; gap-tolerant
                   alpha_eff prevents false alarms.
* No alarm ever  : 6 steady days (< CUSUM_RECENT_DAYS); no alarm ever fired;
                   verifies recent_alarm does not falsely trigger on short series.
* Insufficient   : 4 observed days → stage_status == "insufficient_history".
* Spike-recover  : 40 steady + 3-day spike + 20 normal → alarm fires during
                   spike, then 20 recovery days push it outside CUSUM_RECENT_DAYS
                   → change_detected=False as of the last day.
* Short detection: 10 steady + 3 high → sigma from first 10 (before the tail);
                   alarm fires within 3 anomaly days → change_detected=True.
* TG-30069 series: 69, 76, 95, 105, 157 MW → sigma from first 2 days allows
                   detecting the flare-up across the last 3 days.
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

        Series: [20]*10 + [60]*10  (n=20)
        sigma computed from first 17 days (excluding last 3 tail days).
        Alarm fires mid-step; cusum is the peak statistic within recent window.
        """
        frps = [20.0] * 10 + [60.0] * 10
        result = _run_compute(frps)
        self.assertTrue(
            result["change_detected"],
            f"Expected change_detected=True for sustained step; got result={result}",
        )
        self.assertEqual(result["stage_status"], "live")
        # Peak statistic within the recent window must be positive (not post-reset 0.0)
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

        Series: [20]*10 + [300] + [20]*10  (n=21)
        Only 1 consecutive spike day (never reaches 2), so no alarm fires.
        """
        frps = [20.0] * 10 + [300.0] + [20.0] * 10
        result = _run_compute(frps)
        self.assertFalse(
            result["change_detected"],
            f"Single spike must not trigger change_detected; got result={result}",
        )

    def test_spike_cusum_resets(self):
        """After the spike and 10 recovery days, CUSUM in recent window is near 0."""
        frps = [20.0] * 10 + [300.0] + [20.0] * 10
        result = _run_compute(frps)
        # cusum is the peak S in the recent 7-day window; after 10 recovery days it is 0
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

    def test_no_alarm_ever_short_series_does_not_alarm(self):
        """Regression test: when no alarm ever fired on a short series (< CUSUM_RECENT_DAYS),
        change_detected must be False.

        Catches the bug where obs_since_last_alarm was set to n (e.g. 6 < 7)
        and falsely treated as a recent alarm.
        """
        frps = [20.0] * 6
        result = _run_compute(frps)
        self.assertFalse(
            result["change_detected"],
            f"Short steady series must not flag change_detected; got {result}",
        )
        self.assertEqual(result["cusum"], 0.0)


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
# TC-7: Smoke tests on real DB sites
# ---------------------------------------------------------------------------

class TestSmokeRealSites(unittest.TestCase):
    """Run compute_change against the real database.

    Integration smoke tests: must not crash and output must validate against
    ChangeEvidence.
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
        self.assertIn(result["stage_status"], {"live", "insufficient_history"})


# ---------------------------------------------------------------------------
# TC-8: Spike + long recovery — change_detected False at as_of
# ---------------------------------------------------------------------------

class TestSpikeWithRecovery(unittest.TestCase):
    """40 steady days near 30 MW + 3-day spike to 70 MW + 20 normal days.

    As of the last observed day the alarm is stale (>CUSUM_RECENT_DAYS recovery
    observations), so change_detected must be False.
    """

    @staticmethod
    def _make_spike_recovery_rows() -> list[dict]:
        import random
        rng = random.Random(7)
        base = _BASE_DATE
        rows = []
        # 40 steady days near 30 MW
        for d in range(40):
            rows.append({
                "frp": 30.0 + rng.uniform(-2.0, 2.0),
                "acq_date": (base + datetime.timedelta(days=d)).strftime("%Y-%m-%d"),
            })
        # 3-day spike to 70 MW
        for d in range(40, 43):
            rows.append({
                "frp": 70.0 + rng.uniform(-1.0, 1.0),
                "acq_date": (base + datetime.timedelta(days=d)).strftime("%Y-%m-%d"),
            })
        # 20 recovery days back near 30 MW
        for d in range(43, 63):
            rows.append({
                "frp": 30.0 + rng.uniform(-2.0, 2.0),
                "acq_date": (base + datetime.timedelta(days=d)).strftime("%Y-%m-%d"),
            })
        return rows

    def test_spike_recover_false_at_asof(self):
        """After 20 recovery days, alarm is outside CUSUM_RECENT_DAYS → False."""
        rows = self._make_spike_recovery_rows()
        last_date = rows[-1]["acq_date"]
        with patch("backend.app.temporal_cusum.db.query", return_value=rows):
            result = compute_change("FAKE-SITE", as_of=last_date)
        self.assertFalse(
            result["change_detected"],
            f"Expected False after 20 recovery days; got {result}",
        )
        self.assertEqual(result["stage_status"], "live")

    def test_spike_recover_validates_contract(self):
        """Result must validate against ChangeEvidence."""
        rows = self._make_spike_recovery_rows()
        last_date = rows[-1]["acq_date"]
        with patch("backend.app.temporal_cusum.db.query", return_value=rows):
            result = compute_change("FAKE-SITE", as_of=last_date)
        ChangeEvidence.model_validate(result)

    def test_spike_itself_was_detected(self):
        """At as_of = last spike day, alarm should be live → True."""
        rows = self._make_spike_recovery_rows()
        # Third spike day is at index 42 → date = _BASE_DATE + 42 days
        spike_asof = (_BASE_DATE + datetime.timedelta(days=42)).strftime("%Y-%m-%d")
        with patch("backend.app.temporal_cusum.db.query", return_value=rows):
            result = compute_change("FAKE-SITE", as_of=spike_asof)
        self.assertTrue(
            result["change_detected"],
            f"Expected True while spike is live; got {result}",
        )


# ---------------------------------------------------------------------------
# TC-9: Short detection — sigma from reference period, not from anomaly tail
# ---------------------------------------------------------------------------

class TestShortDetection(unittest.TestCase):
    """10 steady days near 30 MW + 3 days at 67 MW → change_detected=True.

    Key property under test
    -----------------------
    sigma is computed from the first (13-3)=10 days only.  With sigma ≈ 1.1
    (natural variation around 30 MW), k ≈ 0.55 and h ≈ 4.4.  The anomaly
    days push S well above h in 2 consecutive observations → alarm fires.
    """

    @staticmethod
    def _make_short_detection_rows() -> list[dict]:
        import random
        rng = random.Random(13)
        base = _BASE_DATE
        rows = []
        # 10 steady days near 30 MW
        for d in range(10):
            rows.append({
                "frp": 30.0 + rng.uniform(-2.0, 2.0),
                "acq_date": (base + datetime.timedelta(days=d)).strftime("%Y-%m-%d"),
            })
        # 3 anomaly days at 67 MW
        for d in range(10, 13):
            rows.append({
                "frp": 67.0 + rng.uniform(-1.0, 1.0),
                "acq_date": (base + datetime.timedelta(days=d)).strftime("%Y-%m-%d"),
            })
        return rows

    def test_short_detection_true(self):
        """3 anomaly days above 67 MW → change_detected=True with tail sigma."""
        rows = self._make_short_detection_rows()
        with patch("backend.app.temporal_cusum.db.query", return_value=rows):
            result = compute_change("FAKE-SITE")
        self.assertTrue(
            result["change_detected"],
            f"Expected True with sigma from first 10 days; got {result}",
        )
        self.assertEqual(result["stage_status"], "live")

    def test_short_detection_validates(self):
        """Result must validate against ChangeEvidence."""
        rows = self._make_short_detection_rows()
        with patch("backend.app.temporal_cusum.db.query", return_value=rows):
            result = compute_change("FAKE-SITE")
        ChangeEvidence.model_validate(result)

    def test_cusum_nonzero_on_detection(self):
        """cusum field reports the peak statistic within recent window (not post-reset 0)."""
        rows = self._make_short_detection_rows()
        with patch("backend.app.temporal_cusum.db.query", return_value=rows):
            result = compute_change("FAKE-SITE")
        self.assertEqual(result["stage_status"], "live")
        self.assertTrue(result["change_detected"])
        self.assertGreater(result["cusum"], 0.0)


# ---------------------------------------------------------------------------
# TC-10: TG-30069-79181 diagnostic & series tests
# ---------------------------------------------------------------------------

class TestTG30069Diagnostic(unittest.TestCase):
    """Tests for TG-30069-79181 and similar short-history flare-up series."""

    _SITE = "TG-30069-79181"

    def test_tg30069_series_returns_true(self):
        """TG-30069-79181-style series 69, 76, 95, 105, 157 must return change_detected=True.

        With tail exclusion (observations before the last 3 days = [69.22, 76.60]),
        sigma is ~5.22 rather than ~34.78.  The subsequent readings (95, 105, 157 MW)
        are properly detected as an ongoing anomalous flare-up.
        """
        frps = [69.22, 76.60, 95.27, 105.43, 157.40]
        result = _run_compute(frps)
        self.assertTrue(
            result["change_detected"],
            f"Expected change_detected=True for flare series; got {result}",
        )
        self.assertEqual(result["stage_status"], "live")
        self.assertGreater(result["cusum"], 0.0)

    def test_real_db_tg30069_detected(self):
        """Real DB site TG-30069-79181 must have change_detected=True."""
        result = compute_change(self._SITE)
        validated = ChangeEvidence.model_validate(result)
        self.assertIsInstance(validated, ChangeEvidence)
        self.assertTrue(result["change_detected"])
        self.assertEqual(result["stage_status"], "live")
        self.assertGreater(result["cusum"], 0.0)

    def test_no_crash(self):
        result = compute_change(self._SITE)
        ChangeEvidence.model_validate(result)
        self.assertIn(result["stage_status"], {"live", "insufficient_history"})
        self.assertFalse(result["mock"])

    def test_deterministic(self):
        """Two calls return identical dicts."""
        r1 = compute_change(self._SITE)
        r2 = compute_change(self._SITE)
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
