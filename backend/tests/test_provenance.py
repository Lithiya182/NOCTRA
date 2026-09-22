"""Unit tests for provenance.py and database WAL/index verification."""
from __future__ import annotations

import sqlite3
import pytest
from app import db
from app.provenance import (
    Provenance,
    build_provenance_fields,
    get_now_iso,
    normalize_provenance,
)


def test_get_now_iso_format():
    timestamp = get_now_iso()
    assert isinstance(timestamp, str)
    assert timestamp.endswith("Z")
    assert "T" in timestamp
    # ISO format validation YYYY-MM-DDTHH:MM:SSZ
    assert len(timestamp) == 20


def test_provenance_dataclass_coercion():
    # Test boolean true -> 1
    p1 = Provenance(is_synthetic=True, source="test_src", ingestion_batch="batch_1")
    assert p1.is_synthetic == 1
    assert p1.source == "test_src"
    assert p1.ingestion_batch == "batch_1"
    assert isinstance(p1.created_at, str)

    # Test boolean false -> 0
    p2 = Provenance(is_synthetic=False, source="firms")
    assert p2.is_synthetic == 0

    # Test integer coercion
    p3 = Provenance(is_synthetic=0)
    assert p3.is_synthetic == 0

    p4 = Provenance(is_synthetic=1)
    assert p4.is_synthetic == 1


def test_build_provenance_fields():
    fields = build_provenance_fields(
        is_synthetic=False, source="sentinel2-l2a", ingestion_batch="batch_2026"
    )
    assert fields["is_synthetic"] == 0
    assert fields["source"] == "sentinel2-l2a"
    assert fields["ingestion_batch"] == "batch_2026"
    assert "created_at" in fields
    assert fields["created_at"].endswith("Z")


def test_normalize_provenance_record():
    raw_record = {"lat": 23.8, "lon": 86.4, "source": "cnn_model"}
    norm = normalize_provenance(raw_record, default_source="fallback")
    assert norm["is_synthetic"] == 1
    assert norm["source"] == "cnn_model"
    assert norm["ingestion_batch"] is None
    assert "created_at" in norm
    assert norm["lat"] == 23.8

    # Test default fallback when source is missing
    raw_record2 = {"lat": 23.8, "is_synthetic": 0}
    norm2 = normalize_provenance(raw_record2, default_source="fallback_src")
    assert norm2["is_synthetic"] == 0
    assert norm2["source"] == "fallback_src"


def test_database_wal_mode_and_indexes():
    """Verify SQLite WAL mode and expected database indexes are intact."""
    conn = db.get_conn()
    
    # Check WAL mode
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal", f"Expected WAL journal mode, got {mode}"

    # Check indexes on detections
    det_idx_rows = conn.execute("PRAGMA index_list('detections')").fetchall()
    det_idx_names = {r[1] for r in det_idx_rows}
    assert "idx_det_date" in det_idx_names
    assert "uq_detection_natural_key" in det_idx_names

    # Check indexes on sites
    site_idx_rows = conn.execute("PRAGMA index_list('sites')").fetchall()
    site_idx_names = {r[1] for r in site_idx_rows}
    assert "idx_sites_class" in site_idx_names

    # Check indexes on alerts
    alert_idx_rows = conn.execute("PRAGMA index_list('alerts')").fetchall()
    alert_idx_names = {r[1] for r in alert_idx_rows}
    assert "idx_alerts_status" in alert_idx_names
