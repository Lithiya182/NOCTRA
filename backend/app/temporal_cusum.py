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
* Sigma is derived from all observed daily FRP values (the site's own
  historic variance).  A sigma floor prevents division-by-zero on perfectly
  constant series.
* CUSUM alarm requires ``CUSUM_CONSECUTIVE_ALARMS`` (default 2) consecutive
  observed days above the detection threshold *h*, so a single spike never
  triggers ``change_detected = True``.
* All parameters are configurable via environment variables (see config.py).
"""
from __future__ import annotations

import statistics
from datetime import datetime
from typing import Optional

from . import db
from .config import (
    CUSUM_CONSECUTIVE_ALARMS,
    CUSUM_H_FACTOR,
    CUSUM_K_FACTOR,
    CUSUM_MIN_HISTORY_DAYS,
    CUSUM_SIGMA_FLOOR,
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
    # 5. Compute sigma from the site's full observed history.
    # ------------------------------------------------------------------
    sigma = statistics.stdev(daily_frps) if n >= 2 else 0.0
    sigma = max(sigma, CUSUM_SIGMA_FLOOR)

    k = CUSUM_K_FACTOR * sigma   # slack / reference value
    h = CUSUM_H_FACTOR * sigma   # decision interval (alarm threshold)

    # ------------------------------------------------------------------
    # 6. Walk the series: EWMA baseline + one-sided tabular CUSUM.
    #    B is initialised to the first observation and updated *after*
    #    CUSUM so the current point cannot inflate the baseline it is
    #    tested against.
    # ------------------------------------------------------------------
    dt_objs = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]

    B: float = daily_frps[0]   # EWMA baseline (starts at day-0 FRP)
    S: float = 0.0              # CUSUM positive shift accumulator
    consec: int = 0             # consecutive observed days with S >= h
    ever_alarmed: bool = False  # latched True once consec reaches the threshold

    for i in range(1, n):
        gap = max(1, (dt_objs[i] - dt_objs[i - 1]).days)
        alpha_eff = 1.0 - (1.0 - EWMA_LAMBDA) ** gap

        # CUSUM step uses B from BEFORE incorporating the current reading.
        S = max(0.0, S + (daily_frps[i] - B - k))

        if S >= h:
            consec += 1
            if consec >= CUSUM_CONSECUTIVE_ALARMS:
                ever_alarmed = True
        else:
            consec = 0  # CUSUM drop resets the consecutive run counter

        # Update baseline AFTER CUSUM, so the anomaly cannot hide itself.
        B = (1.0 - alpha_eff) * B + alpha_eff * daily_frps[i]

    change_detected: bool = ever_alarmed

    # ------------------------------------------------------------------
    # 7. Build and validate result dict.
    # ------------------------------------------------------------------
    result = {
        "ewma_baseline": round(B, 2),
        "cusum": round(S, 4),
        "change_detected": change_detected,
        "gap_tolerant": True,
        "stage_status": "live",
        "mock": False,
    }
    ChangeEvidence.model_validate(result)
    return result
