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
            daynight TEXT
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
            d_residential_m REAL
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
            created_at TEXT,
            updated_at TEXT
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

        CREATE INDEX IF NOT EXISTS idx_det_date ON detections(acq_date);
        CREATE INDEX IF NOT EXISTS idx_sites_class ON sites(classification);
        CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
        """
    )
    conn.commit()


def reset_all() -> None:
    """Wipe all tables so a re-ingest produces a deterministic demo state."""
    conn = get_conn()
    with _lock:
        conn.executescript(
            "DELETE FROM site_detections; DELETE FROM detections; DELETE FROM sites; "
            "DELETE FROM alerts; DELETE FROM needs; DELETE FROM push_subscriptions; "
            "DELETE FROM sites; DELETE FROM polygons;"
        )
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