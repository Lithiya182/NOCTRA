"""SQLite access layer. GIS storage: lat/lon floats + haversine (no GIS extension)."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .config import DB_PATH

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        init_schema(_conn)
    return _conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            bright_ti4 REAL,
            scan REAL,
            track REAL,
            acq_date TEXT NOT NULL,
            acq_time TEXT,
            satellite TEXT,
            instrument TEXT,
            confidence REAL,
            version TEXT,
            bright_ti5 REAL,
            frp REAL DEFAULT 0,
            daynight TEXT,
            is_synthetic INTEGER DEFAULT 1,
            source TEXT DEFAULT 'synthetic',
            ingestion_batch TEXT
        );

        CREATE TABLE IF NOT EXISTS sites (
            site_id TEXT PRIMARY KEY,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            classification TEXT NOT NULL DEFAULT 'other',
            confidence REAL DEFAULT 0,
            explanation TEXT DEFAULT '',
            severity TEXT DEFAULT 'minor',
            is_anomalous INTEGER DEFAULT 0,
            status TEXT DEFAULT 'routine',
            first_seen TEXT,
            last_seen TEXT,
            max_frp REAL DEFAULT 0,
            brightness REAL DEFAULT 0,
            persistence INTEGER DEFAULT 0,
            consec_days INTEGER DEFAULT 0,
            duty_cycle_pct REAL DEFAULT 0,
            d_industrial_m REAL,
            d_agri_m REAL,
            d_residential_m REAL,
            coverage_status TEXT DEFAULT 'unknown',
            last_pass_date TEXT,
            days_since_last_pass INTEGER
        );

        CREATE TABLE IF NOT EXISTS site_detections (
            site_id TEXT,
            detection_id INTEGER,
            PRIMARY KEY (site_id, detection_id)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id TEXT NOT NULL,
            severity TEXT,
            is_anomalous INTEGER,
            status TEXT DEFAULT 'alert_triggered',
            public_notified INTEGER DEFAULT 0,
            cap_json TEXT,
            analyst_note TEXT,
            reviewed_by TEXT,
            feedback_label TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS alert_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER NOT NULL,
            site_id TEXT NOT NULL,
            action TEXT NOT NULL,
            previous_status TEXT,
            new_status TEXT NOT NULL,
            analyst_note TEXT,
            reviewed_by TEXT DEFAULT 'analyst',
            feedback_label TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (alert_id) REFERENCES alerts(id)
        );

        CREATE TABLE IF NOT EXISTS imagery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id TEXT NOT NULL,
            acquired_date TEXT,
            source TEXT DEFAULT 'sentinel2-l2a',
            cloud_cover_pct REAL,
            file_path TEXT,
            is_synthetic INTEGER DEFAULT 0,
            status TEXT DEFAULT 'available',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS needs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT,
            lat REAL,
            lon REAL,
            message TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint TEXT UNIQUE,
            p256dh TEXT,
            auth TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS polygons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            name TEXT,
            boundary_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reviewers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('reviewer', 'viewer')),
            token_hash TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_det_date ON detections(acq_date);
        CREATE INDEX IF NOT EXISTS idx_sites_class ON sites(classification);
        CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
        CREATE INDEX IF NOT EXISTS idx_alert_reviews_alert ON alert_reviews(alert_id);
        CREATE INDEX IF NOT EXISTS idx_alert_reviews_site ON alert_reviews(site_id);
        CREATE INDEX IF NOT EXISTS idx_imagery_site ON imagery(site_id);
        CREATE INDEX IF NOT EXISTS idx_reviewers_token_hash ON reviewers(token_hash);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_detection_natural_key
            ON detections(latitude, longitude, acq_date, acq_time, satellite);
        """
    )
    # Lightweight schema migration for existing tables
    table_info = conn.execute("PRAGMA table_info(alerts)").fetchall()
    col_names = [col["name"] for col in table_info]
    if "analyst_note" not in col_names:
        conn.execute("ALTER TABLE alerts ADD COLUMN analyst_note TEXT")
    if "reviewed_by" not in col_names:
        conn.execute("ALTER TABLE alerts ADD COLUMN reviewed_by TEXT")
    if "feedback_label" not in col_names:
        conn.execute("ALTER TABLE alerts ADD COLUMN feedback_label TEXT")

    table_info_rev = conn.execute("PRAGMA table_info(alert_reviews)").fetchall()
    col_names_rev = [col["name"] for col in table_info_rev]
    if "feedback_label" not in col_names_rev:
        conn.execute("ALTER TABLE alert_reviews ADD COLUMN feedback_label TEXT")

    conn.commit()


def reset_all() -> None:
    """Wipe all tables so a re-ingest produces a deterministic demo state."""
    conn = get_conn()
    with _lock:
        conn.executescript(
            "DELETE FROM site_detections; DELETE FROM detections; DELETE FROM sites; "
            "DELETE FROM alert_reviews; DELETE FROM alerts; DELETE FROM needs; "
            "DELETE FROM push_subscriptions; DELETE FROM polygons; DELETE FROM imagery;"
        )
        conn.commit()


def reset_synthetic_only() -> None:
    """Delete only synthetic detections and all derived tables.
    Real detections (is_synthetic=0) are preserved.
    Derived tables (sites, site_detections, alerts, needs, alert_reviews) are cleared and will be rebuilt.
    Polygons and push_subscriptions are preserved.
    """
    conn = get_conn()
    with _lock:
        # Delete synthetic detections only
        conn.execute("DELETE FROM detections WHERE is_synthetic = 1")
        # Clear all derived tables (they will be rebuilt from remaining real + new synthetic)
        conn.execute("DELETE FROM site_detections")
        conn.execute("DELETE FROM sites")
        conn.execute("DELETE FROM alert_reviews")
        conn.execute("DELETE FROM alerts")
        conn.execute("DELETE FROM needs")
        # Preserve: polygons, push_subscriptions, real detections
        conn.commit()


def reset_derived_tables() -> None:
    """Clear only derived tables (sites, site_detections, alerts, needs, alert_reviews).
    Preserves all detections (real + synthetic) and polygons/push_subscriptions.
    """
    conn = get_conn()
    with _lock:
        conn.execute("DELETE FROM site_detections")
        conn.execute("DELETE FROM sites")
        conn.execute("DELETE FROM alert_reviews")
        conn.execute("DELETE FROM alerts")
        conn.execute("DELETE FROM needs")
        # Preserve: polygons, push_subscriptions, real detections
        conn.commit()



def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = get_conn()
    with _lock:
        return conn.execute(sql, params).fetchall()


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    conn = get_conn()
    with _lock:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur


def executemany(sql: str, rows: list[tuple]) -> None:
    conn = get_conn()
    with _lock:
        conn.executemany(sql, rows)
        conn.commit()