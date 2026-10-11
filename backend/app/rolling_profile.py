"""NOCTRA Rolling Site Profile — daily stats, sliding DNA window, and learning step.

Tables created here (NOT in db.py):
- site_daily_stats   — per-site per-day EWMA/CUSUM/classification snapshot
- site_profile       — sliding ThermalDNA window as of a date
- learning_log       — audit trail of each daily_update run

All writes are upsert (INSERT OR REPLACE / INSERT OR IGNORE) so running
daily_update twice is idempotent.

CLI:
    python -m app.rolling_profile --as-of 2026-10-11
    python -m app.rolling_profile --replay-days 30
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from . import db
from .config import (
    DAILY_UPDATE_HOUR_UTC,  # noqa: F401 (exported for scheduler)
    LEARN_MIN_NEW_LABELS,
    PROFILE_WINDOW_DAYS,
    STALE_DAYS,
)
from .feature_utils import compute_thermal_dna
from .temporal_cusum import compute_change

log = logging.getLogger("thermalguard.rolling_profile")

# --------------------------------------------------------------------------- #
# 1. Table creation                                                            #
# --------------------------------------------------------------------------- #

_CREATE_SITE_DAILY_STATS = """
CREATE TABLE IF NOT EXISTS site_daily_stats (
    site_id        TEXT    NOT NULL,
    stat_date      TEXT    NOT NULL,
    n_detections   INTEGER NOT NULL DEFAULT 0,
    max_frp        REAL,
    mean_frp       REAL,
    ewma_baseline  REAL,
    cusum          REAL,
    change_detected INTEGER,
    severity       TEXT,
    classification TEXT,
    computed_at    TEXT    NOT NULL,
    PRIMARY KEY (site_id, stat_date)
)
"""

_CREATE_SITE_PROFILE = """
CREATE TABLE IF NOT EXISTS site_profile (
    site_id        TEXT NOT NULL,
    as_of_date     TEXT NOT NULL,
    window_start   TEXT NOT NULL,
    window_end     TEXT NOT NULL,
    typical_frp    REAL,
    median_frp     REAL,
    variability    REAL,
    typical_frequency REAL,
    active_hours   TEXT,
    typical_duration REAL,
    history_days   INTEGER,
    stage_status   TEXT,
    PRIMARY KEY (site_id, as_of_date)
)
"""

_CREATE_LEARNING_LOG = """
CREATE TABLE IF NOT EXISTS learning_log (
    run_date          TEXT NOT NULL PRIMARY KEY,
    new_detections    INTEGER NOT NULL DEFAULT 0,
    sites_updated     INTEGER NOT NULL DEFAULT 0,
    sites_with_change INTEGER NOT NULL DEFAULT 0,
    new_labels        INTEGER NOT NULL DEFAULT 0,
    retrained         INTEGER NOT NULL DEFAULT 0,
    note              TEXT
)
"""


def init_tables() -> None:
    """Create rolling-profile tables if they don't exist (idempotent)."""
    for ddl in (_CREATE_SITE_DAILY_STATS, _CREATE_SITE_PROFILE, _CREATE_LEARNING_LOG):
        db.execute(ddl)


# --------------------------------------------------------------------------- #
# 2. Severity helpers                                                          #
# --------------------------------------------------------------------------- #

def _recent_max_frp(site_id: str, as_of_str: str, stale_days: int) -> float:
    """Return the maximum FRP observed in the last *stale_days* days as of *as_of_str*.

    Used for alert-creation severity (Item 8): we look at recent FRP, not the
    lifetime max_frp stored in the sites table.
    """
    cutoff = as_of_str[:10]
    window_start = (
        datetime.strptime(cutoff, "%Y-%m-%d").date() - timedelta(days=stale_days)
    ).isoformat()
    rows = db.query(
        """
        SELECT MAX(d.frp) AS mf
        FROM detections d
        JOIN site_detections sd ON d.id = sd.detection_id
        WHERE sd.site_id = ?
          AND d.acq_date >= ?
          AND d.acq_date <= ?
        """,
        (site_id, window_start, cutoff),
    )
    if rows and rows[0]["mf"] is not None:
        return float(rows[0]["mf"])
    return 0.0


# --------------------------------------------------------------------------- #
# 3. Per-site staleness check                                                  #
# --------------------------------------------------------------------------- #

def _last_observed_date(site_id: str) -> Optional[str]:
    """Return the latest acq_date for a site (YYYY-MM-DD), or None."""
    rows = db.query(
        """
        SELECT MAX(d.acq_date) AS last_d
        FROM detections d
        JOIN site_detections sd ON d.id = sd.detection_id
        WHERE sd.site_id = ?
        """,
        (site_id,),
    )
    if rows and rows[0]["last_d"]:
        return rows[0]["last_d"][:10]
    return None


def _is_stale(site_id: str, as_of_str: str, stale_days: int) -> bool:
    """True if the site has no observation within the last *stale_days* days."""
    last = _last_observed_date(site_id)
    if last is None:
        return True
    as_of_d = datetime.strptime(as_of_str[:10], "%Y-%m-%d").date()
    last_d = datetime.strptime(last, "%Y-%m-%d").date()
    return (as_of_d - last_d).days > stale_days


# --------------------------------------------------------------------------- #
# 4. Daily stats for one date                                                  #
# --------------------------------------------------------------------------- #

def _daily_detections(site_id: str, stat_date_str: str) -> tuple[int, float | None, float | None]:
    """Return (n_detections, max_frp, mean_frp) for a site on *stat_date_str*.

    Detections from 3 different satellites on the same calendar day count as
    ONE observed day for that site — but we still report the aggregate stats.
    """
    rows = db.query(
        """
        SELECT d.frp
        FROM detections d
        JOIN site_detections sd ON d.id = sd.detection_id
        WHERE sd.site_id = ? AND d.acq_date = ?
        """,
        (site_id, stat_date_str),
    )
    if not rows:
        return 0, None, None
    frps = [float(r["frp"]) for r in rows if r["frp"] is not None]
    if not frps:
        return len(rows), None, None
    return len(rows), round(max(frps), 2), round(sum(frps) / len(frps), 2)


# --------------------------------------------------------------------------- #
# 5. Main daily_update                                                         #
# --------------------------------------------------------------------------- #

def daily_update(as_of: Optional[str] = None) -> dict:
    """Upsert rolling stats and profile for every active site as of *as_of*.

    Parameters
    ----------
    as_of:
        ISO date string (YYYY-MM-DD).  Defaults to today UTC.  Must always be
        passed explicitly from the scheduler so evaluation is deterministic.

    Returns
    -------
    dict with keys: sites_updated, sites_with_change, new_labels, retrained,
    sites_skipped_stale.
    """
    init_tables()

    as_of_str = (as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    as_of_date = datetime.strptime(as_of_str, "%Y-%m-%d").date()
    window_start_date = as_of_date - timedelta(days=PROFILE_WINDOW_DAYS)
    window_start_str = window_start_date.isoformat()
    computed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Active sites = had at least one detection within the window
    active_rows = db.query(
        """
        SELECT DISTINCT sd.site_id
        FROM site_detections sd
        JOIN detections d ON d.id = sd.detection_id
        WHERE d.acq_date >= ? AND d.acq_date <= ?
        """,
        (window_start_str, as_of_str),
    )
    active_site_ids = [r["site_id"] for r in active_rows]

    sites_updated = 0
    sites_with_change = 0
    sites_skipped_stale = 0

    for site_id in active_site_ids:
        # Item 7: evaluate AS OF the run date, not the site's last observed day
        stale = _is_stale(site_id, as_of_str, STALE_DAYS)
        if stale:
            sites_skipped_stale += 1
            continue

        # Write stats for ALL observed dates (full history), not just the window.
        # The window only controls which sites are 'active' and governs the DNA profile.
        # site_daily_stats is the complete historical record.
        date_rows = db.query(
            """
            SELECT DISTINCT d.acq_date
            FROM detections d
            JOIN site_detections sd ON d.id = sd.detection_id
            WHERE sd.site_id = ? AND d.acq_date <= ?
            ORDER BY d.acq_date
            """,
            (site_id, as_of_str),
        )
        obs_dates = [r["acq_date"][:10] for r in date_rows]

        # Compute CUSUM/EWMA once as of as_of (uses all history up to as_of)
        change_ev = compute_change(site_id, as_of=as_of_str)
        ewma_b = change_ev.get("ewma_baseline")
        cusum_v = change_ev.get("cusum")
        change_det = int(bool(change_ev.get("change_detected", False)))

        # Get site classification / severity
        site_rows = db.query(
            "SELECT classification, severity FROM sites WHERE site_id=?",
            (site_id,),
        )
        classification = site_rows[0]["classification"] if site_rows else None
        severity = site_rows[0]["severity"] if site_rows else None

        # Upsert one row per observed date that is not yet stored
        for obs_date in obs_dates:
            n_det, max_frp, mean_frp = _daily_detections(site_id, obs_date)
            db.execute(
                """
                INSERT OR REPLACE INTO site_daily_stats
                    (site_id, stat_date, n_detections, max_frp, mean_frp,
                     ewma_baseline, cusum, change_detected, severity,
                     classification, computed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (site_id, obs_date, n_det, max_frp, mean_frp,
                 ewma_b, cusum_v, change_det, severity, classification, computed_at),
            )

        # Refresh site_profile for as_of
        dna = compute_thermal_dna(site_id, as_of=as_of_str, window_days=PROFILE_WINDOW_DAYS)
        db.execute(
            """
            INSERT OR REPLACE INTO site_profile
                (site_id, as_of_date, window_start, window_end,
                 typical_frp, median_frp, variability, typical_frequency,
                 active_hours, typical_duration, history_days, stage_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                site_id, as_of_str, window_start_str, as_of_str,
                dna["typical_frp"], dna["median_frp"], dna["variability"],
                dna["typical_frequency"],
                json.dumps(dna["active_hours"]) if dna["active_hours"] is not None else None,
                dna["typical_duration"], dna["history_days"], dna["stage_status"],
            ),
        )

        sites_updated += 1
        if change_det:
            sites_with_change += 1

    # --- Item 4: Learning step ---
    last_run_row = db.query(
        "SELECT MAX(run_date) AS last_r FROM learning_log"
    )
    last_run_date = last_run_row[0]["last_r"] if last_run_row else None

    label_q = (
        "SELECT COUNT(*) AS cnt FROM alert_reviews WHERE feedback_label IS NOT NULL"
        + (" AND created_at > ?" if last_run_date else "")
    )
    label_rows = db.query(label_q, (last_run_date,) if last_run_date else ())
    new_labels = label_rows[0]["cnt"] if label_rows else 0

    # Count distinct classes in new labels
    class_q = (
        "SELECT COUNT(DISTINCT feedback_label) AS nc FROM alert_reviews "
        "WHERE feedback_label IS NOT NULL"
        + (" AND created_at > ?" if last_run_date else "")
    )
    class_rows = db.query(class_q, (last_run_date,) if last_run_date else ())
    n_classes = class_rows[0]["nc"] if class_rows else 0

    retrained = 0
    note = "no new labels, baselines updated only"

    if new_labels >= LEARN_MIN_NEW_LABELS and n_classes >= 2:
        try:
            from .active_learning import run_active_learning_cycle
            run_active_learning_cycle()
            retrained = 1
            note = f"retrained on {new_labels} new labels ({n_classes} classes)"
        except Exception as exc:
            log.warning("Active learning cycle failed: %s", exc)
            note = f"retrain attempted but failed: {exc}"
    else:
        log.info(
            "Skipping retrain: %d new labels (%d classes), need >=%d with >=2 classes",
            new_labels, n_classes, LEARN_MIN_NEW_LABELS,
        )

    # Hook for future severity / EBM retrain — called only if importable
    _run_severity_retrain_hook_if_available()
    _run_ebm_retrain_hook_if_available()

    # Count new detections since last run (informational)
    new_det_q = (
        "SELECT COUNT(*) AS cnt FROM detections"
        + (" WHERE rowid > (SELECT COALESCE(MAX(rowid),0) FROM detections WHERE acq_date < ?)" if last_run_date else "")
    )
    # Simplified: count detections on as_of date
    new_det_rows = db.query(
        "SELECT COUNT(*) AS cnt FROM detections WHERE acq_date = ?", (as_of_str,)
    )
    new_detections = new_det_rows[0]["cnt"] if new_det_rows else 0

    db.execute(
        """
        INSERT OR REPLACE INTO learning_log
            (run_date, new_detections, sites_updated, sites_with_change,
             new_labels, retrained, note)
        VALUES (?,?,?,?,?,?,?)
        """,
        (as_of_str, new_detections, sites_updated, sites_with_change,
         new_labels, retrained, note),
    )

    log.info(
        "daily_update as_of=%s: %d sites updated, %d with change, %d stale skipped",
        as_of_str, sites_updated, sites_with_change, sites_skipped_stale,
    )
    return {
        "as_of": as_of_str,
        "sites_updated": sites_updated,
        "sites_with_change": sites_with_change,
        "sites_skipped_stale": sites_skipped_stale,
        "new_labels": new_labels,
        "retrained": retrained,
        "note": note,
    }


# --------------------------------------------------------------------------- #
# 6. Future retrain hooks (called only if importable)                          #
# --------------------------------------------------------------------------- #

def _run_severity_retrain_hook_if_available() -> None:
    """Hook for future severity model retrain. Called only if the module is importable."""
    try:
        from .severity_retrain import run_severity_retrain  # type: ignore[import]
        run_severity_retrain()
    except ImportError:
        pass  # Not yet built; expected
    except Exception as exc:
        log.warning("Severity retrain hook failed: %s", exc)


def _run_ebm_retrain_hook_if_available() -> None:
    """Hook for future EBM shadow model retrain. Called only if the module is importable."""
    try:
        from .ebm_retrain import run_ebm_retrain  # type: ignore[import]
        run_ebm_retrain()
    except ImportError:
        pass  # Not yet built; expected
    except Exception as exc:
        log.warning("EBM retrain hook failed: %s", exc)


# --------------------------------------------------------------------------- #
# 7. CLI                                                                       #
# --------------------------------------------------------------------------- #

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="NOCTRA rolling profile — fill site_daily_stats and site_profile."
    )
    parser.add_argument("--as-of", metavar="YYYY-MM-DD", help="Target date (default: today)")
    parser.add_argument(
        "--replay-days",
        type=int,
        metavar="N",
        help="Back-fill the last N days, running daily_update for each day.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.replay_days:
        base_date = (
            datetime.strptime(args.as_of, "%Y-%m-%d").date()
            if args.as_of
            else datetime.now(timezone.utc).date()
        )
        for i in range(args.replay_days - 1, -1, -1):
            target = (base_date - timedelta(days=i)).isoformat()
            result = daily_update(as_of=target)
            print(
                f"{target}: updated={result['sites_updated']}"
                f"  changed={result['sites_with_change']}"
                f"  stale_skipped={result['sites_skipped_stale']}"
            )
    else:
        result = daily_update(as_of=args.as_of)
        import json as _json
        print(_json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli()
