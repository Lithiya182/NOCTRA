"""Unit and integration tests for scripts/backfill_firms.py."""
from __future__ import annotations

import csv
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.config import FIRMS_REGIONS, FIRMS_SOURCES
from scripts.backfill_firms import (
    determine_source_product,
    fetch_window_csv,
    generate_windows,
    parse_csv_text,
    run_backfill,
)

SAMPLE_CSV_HEADER = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,"
    "instrument,confidence,version,bright_ti5,frp,daynight\n"
)
SAMPLE_CSV_ROW_1 = "23.75,86.42,335.5,0.4,0.4,2026-06-10,1230,N,VIIRS,95,2.0,305.0,25.0,D\n"
SAMPLE_CSV_ROW_2 = "23.76,86.43,340.0,0.4,0.4,2026-06-11,1235,N,VIIRS,90,2.0,310.0,30.0,D\n"


@pytest.fixture
def temp_cache_dir(tmp_path):
    cache_dir = tmp_path / "firms_raw"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Use an isolated SQLite DB."""
    test_db = tmp_path / "test_backfill.db"
    # Copy current schema from main db
    conn_orig = db.get_conn()
    conn_new = sqlite3.connect(str(test_db))
    conn_orig.backup(conn_new)
    conn_new.close()

    monkeypatch.setattr("app.config.DB_PATH", test_db)
    monkeypatch.setattr("app.db.DB_PATH", test_db)
    monkeypatch.setattr("app.db._conn", None)

    # Clear detections for clean testing
    conn = db.get_conn()
    conn.execute("DELETE FROM detections")
    conn.execute("DELETE FROM site_detections")
    conn.execute("DELETE FROM sites")
    conn.commit()
    return test_db


class TestBackfillWindowing:
    """Test windowing logic and SP/NRT product selection."""

    def test_windowing_day_range(self):
        """30 days produces windows of at most 5 days each."""
        start = date(2026, 6, 1)
        end = date(2026, 6, 30)
        windows = generate_windows(start, end, day_range=5)
        assert len(windows) == 6
        for w_start, w_end in windows:
            assert (w_end - w_start).days + 1 <= 5
        assert windows[0][0] == start
        assert windows[-1][1] == end

    def test_windowing_cutoff_sp_vs_nrt(self):
        """Dates older than cutoff use *_SP, while recent dates use NRT."""
        cutoff = date(2026, 6, 15)
        old_window_start = date(2026, 5, 1)
        new_window_start = date(2026, 7, 1)

        sp_prod = determine_source_product("VIIRS_SNPP_NRT", old_window_start, cutoff)
        assert sp_prod == "VIIRS_SNPP_SP"

        nrt_prod = determine_source_product("VIIRS_SNPP_NRT", new_window_start, cutoff)
        assert nrt_prod == "VIIRS_SNPP_NRT"

    def test_windowing_invalid_days_raises(self):
        """Days outside 1..90 raises ValueError."""
        with pytest.raises(ValueError, match="between 1 and 90"):
            run_backfill(days=0)
        with pytest.raises(ValueError, match="between 1 and 90"):
            run_backfill(days=95)


class TestBackfillCaching:
    """Test raw CSV caching under data/firms_raw/."""

    def test_caching_writes_and_skips_network_on_hit(self, temp_cache_dir):
        """First fetch writes to cache; second fetch reuses cached file without calling requests.get."""
        cache_file = temp_cache_dir / "jharia_VIIRS_SNPP_SP_2026-06-01_2026-06-05.csv"
        fake_csv = SAMPLE_CSV_HEADER + SAMPLE_CSV_ROW_1

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = fake_csv

        with patch("requests.get", return_value=mock_resp) as mock_get:
            # First call: cache miss, makes HTTP request
            res1 = fetch_window_csv("KEY", "VIIRS_SNPP_SP", "86.2,22.7,86.7,23.9",
                                    date(2026, 6, 1), date(2026, 6, 5), cache_file)
            assert mock_get.call_count == 1
            assert cache_file.exists()
            assert res1 == fake_csv.strip()

            # Second call: cache hit, skips HTTP request
            res2 = fetch_window_csv("KEY", "VIIRS_SNPP_SP", "86.2,22.7,86.7,23.9",
                                    date(2026, 6, 1), date(2026, 6, 5), cache_file)
            assert mock_get.call_count == 1  # Unchanged!
            assert res2 == fake_csv.strip()

    def test_dry_run_does_not_fetch_or_ingest(self, temp_cache_dir, isolated_db):
        """Dry run does not perform network requests and inserts no rows."""
        with patch("requests.get") as mock_get:
            summary = run_backfill(
                days=10,
                regions=["jharia"],
                dry_run=True,
                raw_dir=temp_cache_dir,
                end_date=date(2026, 6, 10),
            )
            mock_get.assert_not_called()
            # Verify 0 detections in database
            count = db.query("SELECT count(*) as c FROM detections")[0]["c"]
            assert count == 0


class TestBackfillIdempotencyAndOverlap:
    """Test idempotent reruns and overlap re-fetch without duplicates."""

    def test_idempotent_rerun_zero_duplicates(self, temp_cache_dir, isolated_db):
        """Running backfill twice with identical data results in 0 duplicates."""
        fake_csv = SAMPLE_CSV_HEADER + SAMPLE_CSV_ROW_1 + SAMPLE_CSV_ROW_2

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = fake_csv

        with patch("requests.get", return_value=mock_resp), \
             patch("scripts.backfill_firms.get_firms_key", return_value="TEST_KEY"):
            # Run 1
            res1 = run_backfill(
                days=5,
                regions=["jharia"],
                sources=["VIIRS_SNPP_NRT"],
                raw_dir=temp_cache_dir,
                end_date=date(2026, 6, 15),
            )
            count1 = db.query("SELECT count(*) as c FROM detections")[0]["c"]
            assert count1 == 2
            assert res1["jharia"]["detections_added"] == 2

            # Run 2: identical window and data
            res2 = run_backfill(
                days=5,
                regions=["jharia"],
                sources=["VIIRS_SNPP_NRT"],
                raw_dir=temp_cache_dir,
                end_date=date(2026, 6, 15),
            )
            count2 = db.query("SELECT count(*) as c FROM detections")[0]["c"]
            # Total detections unchanged
            assert count2 == 2
            # 0 new detections added on rerun
            assert res2["jharia"]["detections_added"] == 0

    def test_overlap_refetch_dedup(self, temp_cache_dir, isolated_db):
        """Overlapping windows sharing a detection deduplicate via the natural key."""
        csv_w1 = SAMPLE_CSV_HEADER + SAMPLE_CSV_ROW_1
        csv_w2 = SAMPLE_CSV_HEADER + SAMPLE_CSV_ROW_1 + SAMPLE_CSV_ROW_2

        mock_resp1 = MagicMock(status_code=200, text=csv_w1)
        mock_resp2 = MagicMock(status_code=200, text=csv_w2)

        with patch("requests.get", side_effect=[mock_resp1, mock_resp2]), \
             patch("scripts.backfill_firms.get_firms_key", return_value="TEST_KEY"):
            # Fetch window 1 (5 days)
            run_backfill(
                days=5,
                regions=["jharia"],
                sources=["VIIRS_SNPP_NRT"],
                raw_dir=temp_cache_dir,
                end_date=date(2026, 6, 10),
            )
            assert db.query("SELECT count(*) as c FROM detections")[0]["c"] == 1

            # Fetch window 2 (overlapping by sharing ROW_1)
            # Bypass cache for window 2 to test DB dedup on overlapping rows
            cache_w2 = temp_cache_dir / "w2"
            run_backfill(
                days=5,
                regions=["jharia"],
                sources=["VIIRS_SNPP_NRT"],
                raw_dir=cache_w2,
                end_date=date(2026, 6, 15),
            )
            # Total unique detections must be 2, not 3
            assert db.query("SELECT count(*) as c FROM detections")[0]["c"] == 2


class TestBackfillFaultIsolationAndRedaction:
    """Test failure isolation across regions and key redaction."""

    def test_one_region_failure_does_not_block_others(self, temp_cache_dir, isolated_db):
        """When one region fails (HTTP 500), other regions continue and ingest successfully."""
        jamnagar_row = "22.45,70.05,335.5,0.4,0.4,2026-06-10,1230,N,VIIRS,95,2.0,305.0,25.0,D\n"
        resp_jharia_fail = MagicMock(status_code=500, text="Internal Server Error")
        resp_jamnagar_ok = MagicMock(status_code=200, text=SAMPLE_CSV_HEADER + jamnagar_row)

        def mock_get(url, *args, **kwargs):
            if "86.2,22.7,86.7,23.9" in url:
                return resp_jharia_fail
            return resp_jamnagar_ok

        with patch("requests.get", side_effect=mock_get), \
             patch("scripts.backfill_firms.get_firms_key", return_value="TEST_KEY"):
            summary = run_backfill(
                days=5,
                regions=["jharia", "jamnagar"],
                sources=["VIIRS_SNPP_NRT"],
                raw_dir=temp_cache_dir,
                end_date=date(2026, 6, 10),
            )

            # Jharia added 0 detections due to failure
            assert summary["jharia"]["detections_added"] == 0
            # Jamnagar succeeded and added detections
            assert summary["jamnagar"]["detections_added"] == 1

    def test_key_redaction_in_backfill(self, temp_cache_dir, caplog):
        """Verify API key is NEVER printed or logged."""
        secret_key = "SECRET_FIRMS_API_KEY_12345"
        mock_resp = MagicMock(status_code=401, text=f"Unauthorized access with {secret_key}")

        with patch("requests.get", return_value=mock_resp), \
             patch("scripts.backfill_firms.get_firms_key", return_value=secret_key):
            with caplog.at_level(logging.INFO):
                run_backfill(
                    days=5,
                    regions=["jharia"],
                    sources=["VIIRS_SNPP_NRT"],
                    raw_dir=temp_cache_dir,
                    end_date=date(2026, 6, 10),
                )

            captured_text = caplog.text
            assert secret_key not in captured_text
            assert "[KEY]" in captured_text
