"""Tests for rolling_profile: idempotency, sliding window, label threshold,
mocked retrain, no-notification, staleness gating, and FRP alert logic.

All tests run against a fresh in-memory (file) SQLite DB populated with controlled data.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    latitude REAL, longitude REAL, bright_ti4 REAL DEFAULT 0,
    scan REAL DEFAULT 0.4, track REAL DEFAULT 0.4,
    acq_date TEXT, acq_time TEXT DEFAULT '1200', satellite TEXT DEFAULT 'SNPP',
    instrument TEXT DEFAULT 'VIIRS', confidence REAL DEFAULT 80,
    version TEXT DEFAULT '2.0NRT', bright_ti5 REAL DEFAULT 305,
    frp REAL, daynight TEXT DEFAULT 'D',
    is_synthetic INTEGER DEFAULT 0, source TEXT DEFAULT 'firms',
    ingestion_batch TEXT DEFAULT 'test'
);
CREATE UNIQUE INDEX uq_detection_natural_key
    ON detections (latitude, longitude, acq_date, acq_time, satellite);
CREATE TABLE sites (
    site_id TEXT PRIMARY KEY, lat REAL, lon REAL,
    first_seen TEXT, last_seen TEXT,
    max_frp REAL DEFAULT 0, brightness REAL DEFAULT 0,
    classification TEXT DEFAULT 'other', confidence REAL DEFAULT 0.0,
    explanation TEXT DEFAULT '', severity TEXT DEFAULT 'minor',
    is_anomalous INTEGER DEFAULT 0, persistence INTEGER DEFAULT 0,
    consec_days INTEGER DEFAULT 0, duty_cycle_pct REAL DEFAULT 0.0,
    d_industrial_m REAL, d_agri_m REAL, d_residential_m REAL, status TEXT
);
CREATE TABLE site_detections (
    site_id TEXT, detection_id INTEGER,
    PRIMARY KEY (site_id, detection_id)
);
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT, severity TEXT, is_anomalous INTEGER DEFAULT 0,
    status TEXT DEFAULT 'alert_triggered', cap_json TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE alert_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER, site_id TEXT, action TEXT, previous_status TEXT,
    new_status TEXT, analyst_note TEXT, reviewed_by TEXT,
    created_at TEXT, feedback_label TEXT
);
"""


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """Fresh SQLite DB with schema, isolated from the module-level singleton."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()

    import app.db as db_mod
    monkeypatch.setattr(db_mod, "_conn", conn)

    yield conn
    conn.close()


def _add_site(conn, site_id: str, lat: float = 23.5, lon: float = 86.4,
              severity: str = "minor", classification: str = "other") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sites "
        "(site_id, lat, lon, first_seen, last_seen, max_frp, severity, classification) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (site_id, lat, lon, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
         0.0, severity, classification),
    )
    conn.commit()


def _add_detection(conn, site_id: str, acq_date: str, frp: float,
                   lat: float = 23.5, lon: float = 86.4,
                   satellite: str = "SNPP") -> None:
    cur = conn.execute(
        "INSERT OR IGNORE INTO detections "
        "(latitude, longitude, acq_date, acq_time, frp, satellite) VALUES (?,?,?,?,?,?)",
        (lat, lon, acq_date, "1200", frp, satellite),
    )
    det_id = cur.lastrowid
    if det_id:
        conn.execute(
            "INSERT OR IGNORE INTO site_detections (site_id, detection_id) VALUES (?,?)",
            (site_id, det_id),
        )
    conn.commit()


def _add_review_label(conn, site_id: str, label: str, created_at: str | None = None) -> None:
    conn.execute(
        "INSERT INTO alert_reviews (site_id, action, feedback_label, created_at) "
        "VALUES (?,?,?,?)",
        (site_id, "feedback", label, created_at or datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Item 1 — Tables created by init_tables                                      #
# --------------------------------------------------------------------------- #

def test_init_tables_creates_tables(isolated_db):
    from app.rolling_profile import init_tables
    init_tables()
    tables = {r[0] for r in isolated_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "site_daily_stats" in tables
    assert "site_profile" in tables
    assert "learning_log" in tables


def test_init_tables_idempotent(isolated_db):
    from app.rolling_profile import init_tables
    init_tables()
    init_tables()  # must not raise


# --------------------------------------------------------------------------- #
# Item 3 — Idempotency                                                        #
# --------------------------------------------------------------------------- #

def test_daily_update_idempotent(isolated_db):
    """Running daily_update twice with the same as_of produces identical row counts."""
    from app.rolling_profile import daily_update, init_tables
    init_tables()

    today = date.today().isoformat()
    site_id = "TG-TEST-IDEMPOTENT"
    _add_site(isolated_db, site_id)
    for i in range(8):
        d = (date.today() - timedelta(days=i)).isoformat()
        _add_detection(isolated_db, site_id, d, 25.0)

    r1 = daily_update(as_of=today)
    cnt_before = isolated_db.execute(
        "SELECT COUNT(*) FROM site_daily_stats WHERE site_id=?", (site_id,)
    ).fetchone()[0]

    r2 = daily_update(as_of=today)
    cnt_after = isolated_db.execute(
        "SELECT COUNT(*) FROM site_daily_stats WHERE site_id=?", (site_id,)
    ).fetchone()[0]

    assert cnt_before == cnt_after  # second run adds no new rows
    assert cnt_before > 0


# --------------------------------------------------------------------------- #
# Item 3 — Sliding window: day 31 stays in stats, not in 30-day DNA profile  #
# --------------------------------------------------------------------------- #

def test_sliding_window_day31_stays_in_stats(isolated_db):
    """Detection 31 days ago is written to site_daily_stats (full history)."""
    from app.rolling_profile import daily_update, init_tables
    init_tables()

    today = date.today()
    site_id = "TG-TEST-WINDOW"
    _add_site(isolated_db, site_id)

    # Detection 31 days ago — outside 30-day DNA window
    old_date = (today - timedelta(days=31)).isoformat()
    _add_detection(isolated_db, site_id, old_date, 50.0)
    # Recent detections within window
    for i in range(1, 6):
        d = (today - timedelta(days=i)).isoformat()
        _add_detection(isolated_db, site_id, d, 20.0)

    daily_update(as_of=today.isoformat())

    # Old date should be in site_daily_stats (full history preserved)
    stats_row = isolated_db.execute(
        "SELECT * FROM site_daily_stats WHERE site_id=? AND stat_date=?",
        (site_id, old_date),
    ).fetchone()
    assert stats_row is not None

    # Profile window_start should be today - 30 days, not covering old_date
    profile_row = isolated_db.execute(
        "SELECT window_start FROM site_profile WHERE site_id=? AND as_of_date=?",
        (site_id, today.isoformat()),
    ).fetchone()
    assert profile_row is not None
    ws = profile_row[0]
    assert ws > old_date  # 31-days-ago is before window_start


# --------------------------------------------------------------------------- #
# Item 4 — Label threshold: retrain NOT called (below threshold)              #
# --------------------------------------------------------------------------- #

def test_retrain_not_called_below_threshold(isolated_db):
    """Fewer than LEARN_MIN_NEW_LABELS labels → retrain NOT called."""
    from app.rolling_profile import daily_update, init_tables
    init_tables()

    site_id = "TG-TEST-LABELS-LOW"
    _add_site(isolated_db, site_id)
    for i in range(5):
        _add_detection(isolated_db, site_id, (date.today() - timedelta(days=i)).isoformat(), 20.0)
    # Only 5 labels (below threshold of 10)
    for _ in range(5):
        _add_review_label(isolated_db, site_id, "industrial_fire")

    mock_cycle = MagicMock(return_value={"status": "ok"})
    with patch("app.active_learning.run_active_learning_cycle", mock_cycle):
        result = daily_update(as_of=date.today().isoformat())

    mock_cycle.assert_not_called()
    assert result["retrained"] == 0
    assert "no new labels" in result["note"]


# --------------------------------------------------------------------------- #
# Item 4 — Label threshold: retrain IS called (above threshold)               #
# --------------------------------------------------------------------------- #

def test_retrain_called_above_threshold(isolated_db):
    """>=10 labels with >=2 classes → retrain IS called (mocked)."""
    from app.rolling_profile import daily_update, init_tables
    init_tables()

    site_id = "TG-TEST-LABELS-HIGH"
    _add_site(isolated_db, site_id)
    for i in range(8):
        _add_detection(isolated_db, site_id, (date.today() - timedelta(days=i)).isoformat(), 20.0)

    # 10 labels across 2 distinct classes
    for _ in range(7):
        _add_review_label(isolated_db, site_id, "industrial_fire")
    for _ in range(3):
        _add_review_label(isolated_db, site_id, "wildfire")

    mock_cycle = MagicMock(return_value={"status": "ok"})
    with patch("app.active_learning.run_active_learning_cycle", mock_cycle):
        result = daily_update(as_of=date.today().isoformat())

    mock_cycle.assert_called_once()
    assert result["retrained"] == 1
    assert "retrained" in result["note"]


# --------------------------------------------------------------------------- #
# Item 5 — No notification from daily_update or scheduler wrapper             #
# --------------------------------------------------------------------------- #

def test_daily_update_never_calls_dispatch(isolated_db):
    """daily_update must never call dispatch_public or send_sms (create=True guards)."""
    from app.rolling_profile import daily_update, init_tables
    init_tables()

    site_id = "TG-TEST-NODISPATCH"
    _add_site(isolated_db, site_id)
    for i in range(5):
        _add_detection(isolated_db, site_id, (date.today() - timedelta(days=i)).isoformat(), 30.0)

    mock_dispatch = MagicMock()
    mock_sms = MagicMock()
    # create=True so the patch works even if the attribute doesn't exist yet on the module
    with patch("app.routers.alerts.dispatch_public", mock_dispatch, create=True), \
         patch("app.routers.alerts.send_sms", mock_sms, create=True):
        daily_update(as_of=date.today().isoformat())

    mock_dispatch.assert_not_called()
    mock_sms.assert_not_called()


def test_scheduler_wrapper_dispatch_not_called(isolated_db):
    """_run_daily_update (scheduler wrapper) must not call dispatch_public."""
    from app.firms_scheduler import _run_daily_update

    mock_dispatch = MagicMock()
    mock_sms = MagicMock()

    with patch("app.rolling_profile.daily_update", return_value={
        "as_of": "2026-10-11", "sites_updated": 0, "sites_with_change": 0,
        "sites_skipped_stale": 0, "new_labels": 0, "retrained": 0, "note": "ok",
    }):
        with patch("app.routers.alerts.dispatch_public", mock_dispatch, create=True), \
             patch("app.routers.alerts.send_sms", mock_sms, create=True):
            _run_daily_update()

    mock_dispatch.assert_not_called()
    mock_sms.assert_not_called()


# --------------------------------------------------------------------------- #
# Item 7 — Staleness: site 10 months ago not flagged today                   #
# --------------------------------------------------------------------------- #

def test_stale_site_not_processed(isolated_db):
    """A site last seen 300 days ago (>STALE_DAYS=10) is skipped and not change-flagged."""
    from app.rolling_profile import daily_update, init_tables
    init_tables()

    site_id = "TG-TEST-STALE"
    _add_site(isolated_db, site_id)
    # Detection 300 days ago — outside both STALE_DAYS and PROFILE_WINDOW_DAYS
    old = (date.today() - timedelta(days=300)).isoformat()
    _add_detection(isolated_db, site_id, old, 80.0)

    result = daily_update(as_of=date.today().isoformat())

    # Site should have been skipped (stale) and NOT counted as having change
    assert result["sites_skipped_stale"] >= 1
    assert result["sites_with_change"] == 0


def test_fresh_site_processed(isolated_db):
    """A site seen yesterday is not stale and gets processed."""
    from app.rolling_profile import daily_update, init_tables
    init_tables()

    site_id = "TG-TEST-FRESH"
    _add_site(isolated_db, site_id)
    today = date.today()
    for i in range(1, 7):
        _add_detection(isolated_db, site_id, (today - timedelta(days=i)).isoformat(), 25.0)

    result = daily_update(as_of=today.isoformat())
    assert result["sites_updated"] >= 1
    assert result["sites_skipped_stale"] == 0


# --------------------------------------------------------------------------- #
# Item 8 — Alert severity uses recent FRP, not lifetime max                   #
# --------------------------------------------------------------------------- #

def test_old_150mw_new_3mw_no_extreme_alert(isolated_db):
    """Old 150 MW flare (>STALE_DAYS ago) + new 3 MW detection → recent FRP=3 MW (minor)."""
    from app.ingest import _recent_max_frp_for_site
    from app.classifier import severity_for_frp

    site_id = "TG-TEST-OLDHIGH"
    _add_site(isolated_db, site_id)

    # Old detection 12 days ago (outside STALE_DAYS=10)
    old_date = (date.today() - timedelta(days=12)).isoformat()
    _add_detection(isolated_db, site_id, old_date, 150.0)

    # Recent detection 2 days ago (inside STALE_DAYS=10)
    recent_date = (date.today() - timedelta(days=2)).isoformat()
    _add_detection(isolated_db, site_id, recent_date, 3.0)

    recent_frp = _recent_max_frp_for_site(site_id)
    assert recent_frp == pytest.approx(3.0), f"Expected 3.0 got {recent_frp}"
    assert severity_for_frp(recent_frp) == "minor"


def test_new_120mw_creates_extreme_severity(isolated_db):
    """New 120 MW detection (recent) → recent FRP=120 MW → severity=extreme."""
    from app.ingest import _recent_max_frp_for_site
    from app.classifier import severity_for_frp

    site_id = "TG-TEST-NEWHIGH"
    _add_site(isolated_db, site_id, severity="extreme")
    recent_date = (date.today() - timedelta(days=1)).isoformat()
    _add_detection(isolated_db, site_id, recent_date, 120.0)

    recent_frp = _recent_max_frp_for_site(site_id)
    assert recent_frp == pytest.approx(120.0)
    assert severity_for_frp(recent_frp) == "extreme"
