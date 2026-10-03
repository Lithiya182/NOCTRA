"""NOCTRA Stage 6: Gap-tolerant EWMA + tabular CUSUM temporal change detection.

Algorithm notes
---------------
* Daily FRP series: max(FRP) per observed calendar day, from site_detections.

* EWMA baseline *B* is updated **after** CUSUM uses it, so the current
  observation cannot "hide" itself inside the baseline.

* Gap-tolerant: when the satellite did not observe a day, we do not insert
  zeros.  Instead the EWMA step size is scaled by
  ``alpha_eff = 1 - (1 - lambda) ** gap_days``, naturally accelerating the
  tracking to account for elapsed time.

* Sigma is derived from a **reference period** that excludes the most recent
  ``CUSUM_TAIL_DAYS`` observed days.  This prevents an ongoing anomaly from
  inflating its own detection threshold.  Specifically::

      tail = min(CUSUM_TAIL_DAYS, n - 2) if n >= 2 else 0
      sigma_data = daily_frps[:n - tail] if tail > 0 else daily_frps

  Sigma is floored at ``max(CUSUM_SIGMA_FLOOR, CUSUM_BASELINE_SIGMA_RATIO * baseline)``
  so very short or near-constant histories are not over-sensitive.

* One-sided tabular CUSUM: ``S = max(0, S + (x - B_prior - k))``.
  ``k = CUSUM_K_FACTOR * sigma`` (reference shift / slack value).
  Alarm threshold ``h = CUSUM_H_FACTOR * sigma``.

* After ``CUSUM_CONSECUTIVE_ALARMS`` consecutive observed days with S >= h,
  an alarm fires, ``last_alarm_idx`` is recorded, and **S is reset to 0**
  (standard tabular CUSUM reset).  This ensures a past transient spike does
  not keep ``change_detected`` True indefinitely.

* ``change_detected = True`` only if an alarm fired within the last
  ``CUSUM_RECENT_DAYS`` observed days (counted back from the final
  observation).  A single spike or flare that alarmed and then recovered
  will return False once the recovery window exceeds ``CUSUM_RECENT_DAYS``.
  ``recent_alarm`` is True ONLY if an alarm index actually exists
  (``last_alarm_idx >= 0``).

* The reported ``cusum`` value is the **PEAK statistic within the recent window**
  (not the post-reset 0.0), so ``cusum`` and ``change_detected`` agree when
  shown to a user.

* All parameters are configurable via environment variables (see config.py).
"""
from __future__ import annotations

import statistics
from datetime import datetime
from typing import Optional

from . import db
from .config import (
    CUSUM_BASELINE_SIGMA_RATIO,
    CUSUM_CONSECUTIVE_ALARMS,
    CUSUM_H_FACTOR,
    CUSUM_K_FACTOR,
    CUSUM_MIN_HISTORY_DAYS,
    CUSUM_RECENT_DAYS,
    CUSUM_SIGMA_FLOOR,
    CUSUM_TAIL_DAYS,
    EWMA_LAMBDA,
)
from contracts.evidence import ChangeEvidence


def compute_change(site_id: str, as_of: Optional[str] = None) -> dict:
    """Compute EWMA baseline and one-sided tabular CUSUM for *site_id*.

    Parameters
    ----------
    site_id:
        Canonical NOCTRA site identifier (e.g. ``"TG-23731-86324"``).
    as_of:
        Optional ISO-8601 date string (``"YYYY-MM-DD"``).  Only detections
        on or before this date are considered, enabling deterministic
        back-testing.

    Returns
    -------
    dict
        Validates against :class:`contracts.evidence.ChangeEvidence`.
        Keys: ``ewma_baseline``, ``cusum``, ``change_detected``,
        ``gap_tolerant``, ``stage_status``, ``mock``.
    """
    # ------------------------------------------------------------------
    # 1. Fetch raw detections ordered chronologically.
    # ------------------------------------------------------------------
    query = """
        SELECT d.frp, d.acq_date
        FROM detections d
        JOIN site_detections sd ON d.id = sd.detection_id
        WHERE sd.site_id = ?
        ORDER BY d.acq_date
    """
    rows = db.query(query, (site_id,))

    # Honour as_of cutoff (ISO date prefix comparison works for YYYY-MM-DD).
    if as_of:
        cutoff = as_of[:10]
        rows = [r for r in rows if r["acq_date"][:10] <= cutoff]

    # ------------------------------------------------------------------
    # 2. Handle empty history.
    # ------------------------------------------------------------------
    if not rows:
        result = {
            "ewma_baseline": None,
            "cusum": 0.0,
            "change_detected": False,
            "gap_tolerant": True,
            "stage_status": "insufficient_history",
            "mock": False,
        }
        ChangeEvidence.model_validate(result)
        return result

    # ------------------------------------------------------------------
    # 3. Aggregate to daily series (max FRP per observed day).
    # ------------------------------------------------------------------
    by_date: dict[str, float] = {}
    for r in rows:
        date_key = r["acq_date"][:10]
        frp = float(r["frp"]) if r["frp"] is not None else 0.0
        by_date[date_key] = max(by_date.get(date_key, 0.0), frp)

    dates = sorted(by_date.keys())
    daily_frps: list[float] = [by_date[d] for d in dates]
    n = len(daily_frps)

    # ------------------------------------------------------------------
    # 4. Insufficient history guard.
    # ------------------------------------------------------------------
    if n < CUSUM_MIN_HISTORY_DAYS:
        ewma_val = round(statistics.mean(daily_frps), 2) if daily_frps else None
        result = {
            "ewma_baseline": ewma_val,
            "cusum": 0.0,
            "change_detected": False,
            "gap_tolerant": True,
            "stage_status": "insufficient_history",
            "mock": False,
        }
        ChangeEvidence.model_validate(result)
        return result

    # ------------------------------------------------------------------
    # 5. Compute sigma from the reference period.
    #
    #    Exclude the most recent CUSUM_TAIL_DAYS observed days so that an
    #    active anomaly cannot inflate sigma and thereby raise its own
    #    detection threshold.  Floor sigma at max(CUSUM_SIGMA_FLOOR,
    #    CUSUM_BASELINE_SIGMA_RATIO * baseline) to avoid over-sensitivity.
    # ------------------------------------------------------------------
    tail = min(CUSUM_TAIL_DAYS, n - 2) if n >= 2 else 0
    sigma_data = daily_frps[: n - tail] if tail > 0 else daily_frps
    sigma_raw = statistics.stdev(sigma_data) if len(sigma_data) >= 2 else 0.0
    floor_val = max(CUSUM_SIGMA_FLOOR, CUSUM_BASELINE_SIGMA_RATIO * daily_frps[0])
    sigma = max(sigma_raw, floor_val)

    k = CUSUM_K_FACTOR * sigma   # slack / reference value
    h = CUSUM_H_FACTOR * sigma   # decision interval (alarm threshold)

    # ------------------------------------------------------------------
    # 6. Walk the series: EWMA baseline + one-sided tabular CUSUM.
    #    B is initialised to the first observation and updated *after*
    #    CUSUM so the current point cannot inflate the baseline it is
    #    tested against.
    #
    #    On alarm: S is reset to 0 and the alarm observation index is
    #    recorded.  change_detected is True only if the most recent alarm
    #    fired within the last CUSUM_RECENT_DAYS observed days.
    # ------------------------------------------------------------------
    dt_objs = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]

    B: float = daily_frps[0]      # EWMA baseline (starts at day-0 FRP)
    S: float = 0.0                 # CUSUM positive shift accumulator
    consec: int = 0                # consecutive observed days with S >= h
    last_alarm_idx: int = -1       # observed-day index of most recent alarm
    s_values: list[float] = [0.0]  # S at each observation day (pre-reset)

    for i in range(1, n):
        gap = max(1, (dt_objs[i] - dt_objs[i - 1]).days)
        alpha_eff = 1.0 - (1.0 - EWMA_LAMBDA) ** gap

        # CUSUM step uses B from BEFORE incorporating the current reading.
        S = max(0.0, S + (daily_frps[i] - B - k))
        s_values.append(S)

        if S >= h:
            consec += 1
            if consec >= CUSUM_CONSECUTIVE_ALARMS:
                # Alarm fires: record the event index and reset the
                # accumulator so past alarms don't affect current state.
                last_alarm_idx = i
                S = 0.0
                consec = 0
        else:
            consec = 0  # CUSUM drop resets the consecutive run counter

        # Update baseline AFTER CUSUM, so the anomaly cannot hide itself.
        B = (1.0 - alpha_eff) * B + alpha_eff * daily_frps[i]

    # change_detected is True only if an alarm fired recently enough.
    # "recently" = within the last CUSUM_RECENT_DAYS observed days.
    # recent_alarm is True ONLY if an alarm index actually exists.
    recent_alarm = (last_alarm_idx >= 0) and ((n - 1 - last_alarm_idx) < CUSUM_RECENT_DAYS)
    change_detected: bool = recent_alarm or (consec >= CUSUM_CONSECUTIVE_ALARMS)

    # The reported cusum value must be the PEAK statistic within the recent window
    # (not the post-reset 0.0), so cusum and change_detected agree when shown to a user.
    recent_s = s_values[-CUSUM_RECENT_DAYS:]
    reported_cusum = max(recent_s) if recent_s else 0.0

    # ------------------------------------------------------------------
    # 7. Build and validate result dict.
    # ------------------------------------------------------------------
    result = {
        "ewma_baseline": round(B, 2),
        "cusum": round(reported_cusum, 4),
        "change_detected": change_detected,
        "gap_tolerant": True,
        "stage_status": "live",
        "mock": False,
    }
    ChangeEvidence.model_validate(result)
    return result
