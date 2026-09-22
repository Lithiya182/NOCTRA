"""Unit tests for firms_scheduler.py - Phase 6A safety behavior."""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest
import requests

# Ensure we can import from the app
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.firms_scheduler import (
    fetch_new_data,
    fetch_and_ingest_job,
    get_last_fetch_date,
    set_last_fetch_date,
    run_once,
    STATE_FILE,
    DAY_RANGE,
    JHARIA_BBOX,
)


# ============================================================================
# MOCK FIXTURES
# ============================================================================

@pytest.fixture
def mock_firms_key(monkeypatch):
    """Ensure get_firms_key returns a fake key and never reads real env."""
    import app.firms_scheduler as sched
    monkeypatch.setattr(sched, "get_firms_key", lambda: "TEST_KEY")


@pytest.fixture
def temp_state_file(tmp_path, monkeypatch):
    """Redirect STATE_FILE to a temporary file for isolation."""
    temp_state = tmp_path / "firms_last_fetch.txt"
    import app.firms_scheduler as sched
    monkeypatch.setattr(sched, "STATE_FILE", temp_state)
    return temp_state


@pytest.fixture
def mock_requests_get(monkeypatch):
    """Mock requests.get at the exact call site in firms_scheduler."""
    import app.firms_scheduler as sched
    mock = MagicMock()
    monkeypatch.setattr(sched.requests, "get", mock)
    return mock


@pytest.fixture
def mock_ingest_nrt_rows(monkeypatch):
    """Mock ingest_nrt_rows to avoid DB access."""
    import app.firms_scheduler as sched
    mock = MagicMock(return_value={"detections": 0, "sites": 0, "alerts_created": 0})
    monkeypatch.setattr(sched, "ingest_nrt_rows", mock)
    return mock


@pytest.fixture
def mock_load_polygons(monkeypatch):
    """Mock load_polygons to return empty list."""
    import app.firms_scheduler as sched
    mock = MagicMock(return_value=[])
    monkeypatch.setattr(sched, "load_polygons", mock)
    return mock


# ============================================================================
# TESTS
# ============================================================================

class TestFetchNewData:
    """Tests for fetch_new_data function."""

    def test_valid_empty_window_continues(
        self, mock_firms_key, mock_requests_get, temp_state_file
    ):
        """Test that a valid empty-CSV window continues to the next window."""
        # First window: valid header-only CSV (empty)
        # Second window: has data
        mock_response_1 = MagicMock()
        mock_response_1.status_code = 200
        mock_response_1.text = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"

        mock_response_2 = MagicMock()
        mock_response_2.status_code = 200
        mock_response_2.text = (
            "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
            "23.0,86.0,300.0,0.4,0.4,2026-09-16,1200,N,VIIRS,90,1.0,290.0,10.0,D\n"
        )

        mock_response_3 = MagicMock()
        mock_response_3.status_code = 200
        mock_response_3.text = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"

        mock_requests_get.side_effect = [mock_response_1, mock_response_2, mock_response_3]

        # Fetch range covering two windows (each 5 days)
        from datetime import date
        rows = fetch_new_data(date(2026, 9, 1), date(2026, 9, 15))

        # Should have called requests.get 3 times (2 windows + 1 extra that returns empty to end loop)
        assert mock_requests_get.call_count >= 2
        # Should have the data from the second window
        assert len(rows) == 1
        assert rows[0]["latitude"] == "23.0"

    def test_http_failure_stops_fetch(self, mock_firms_key, mock_requests_get):
        """HTTP error on second window raises RuntimeError."""
        mock_response_1 = MagicMock()
        mock_response_1.status_code = 200
        mock_response_1.text = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n23.0,86.0,300.0,0.4,0.4,2026-09-01,1200,N,VIIRS,90,1.0,290.0,10.0,D\n"

        mock_response_2 = MagicMock()
        mock_response_2.status_code = 400
        mock_response_2.text = "Invalid MAP_KEY"

        mock_requests_get.side_effect = [mock_response_1, mock_response_2]

        from datetime import date
        with pytest.raises(RuntimeError, match="FIRMS request failed"):
            fetch_new_data(date(2026, 9, 1), date(2026, 9, 15))

        assert mock_requests_get.call_count == 2

    def test_http_failure_first_window(self, mock_firms_key, mock_requests_get):
        """HTTP error on first window raises immediately."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_requests_get.return_value = mock_response

        from datetime import date
        with pytest.raises(RuntimeError, match="FIRMS request failed"):
            fetch_new_data(date(2026, 9, 1), date(2026, 9, 5))

        mock_requests_get.assert_called_once()

    def test_empty_csv_is_valid(self, mock_firms_key, mock_requests_get):
        """Valid empty CSV (header only) returns empty list and continues."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
        mock_requests_get.return_value = mock_response

        from datetime import date
        rows = fetch_new_data(date(2026, 9, 1), date(2026, 9, 1))
        assert rows == []

    def test_malformed_csv_raises(self, mock_firms_key, mock_requests_get):
        """Malformed CSV (missing required columns) raises RuntimeError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "foo,bar,baz\n1,2,3\n"
        mock_requests_get.return_value = mock_response

        from datetime import date
        with pytest.raises(RuntimeError, match="Malformed CSV"):
            fetch_new_data(date(2026, 9, 1), date(2026, 9, 1))

    def test_empty_response_raises(self, mock_firms_key, mock_requests_get):
        """Empty response body raises RuntimeError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""
        mock_requests_get.return_value = mock_response

        from datetime import date
        with pytest.raises(RuntimeError, match="Empty response body"):
            fetch_new_data(date(2026, 9, 1), date(2026, 9, 1))

    def test_network_error_raises(self, mock_firms_key, mock_requests_get):
        """Network error raises RuntimeError."""
        import requests
        mock_requests_get.side_effect = requests.RequestException("Connection timeout")
        
        from datetime import date
        with pytest.raises(RuntimeError, match="FIRMS request failed"):
            fetch_new_data(date(2026, 9, 1), date(2026, 9, 5))


class TestFetchAndIngestJob:
    """Tests for fetch_and_ingest_job function."""

    def test_failed_fetch_does_not_advance_state(
        self, mock_firms_key, temp_state_file, mock_ingest_nrt_rows, mock_load_polygons
    ):
        """Failed fetch does not advance the state file."""
        import app.firms_scheduler as sched
        
        # Mock fetch_new_data to raise RuntimeError on first window
        with patch.object(sched, "fetch_new_data", side_effect=RuntimeError("API down")):
            fetch_and_ingest_job()

        # State file should not be created/modified
        from app.firms_scheduler import STATE_FILE
        assert not STATE_FILE.exists(), "State file should not be created on fetch failure"

    def test_failed_fetch_does_not_ingest(
        self, mock_firms_key, temp_state_file, mock_ingest_nrt_rows, mock_load_polygons
    ):
        """Failed fetch does not call ingestion."""
        import app.firms_scheduler as sched
        
        with patch.object(sched, "fetch_new_data", side_effect=RuntimeError("API down")):
            fetch_and_ingest_job()
        
        # ingest_nrt_rows should never be called
        sched.ingest_nrt_rows.assert_not_called()

    def test_valid_empty_fetch_advances_state(
        self, mock_firms_key, temp_state_file, mock_ingest_nrt_rows, mock_load_polygons
    ):
        """Valid empty fetch (zero rows) advances state file."""
        import app.firms_scheduler as sched
        
        with patch.object(sched, "fetch_new_data", return_value=[]):
            fetch_and_ingest_job()

        # State file should be advanced to max_date
        from app.firms_scheduler import STATE_FILE
        assert STATE_FILE.exists()
        content = STATE_FILE.read_text().strip()
        from datetime import datetime, timezone
        assert content == datetime.now(timezone.utc).date().isoformat()

    def test_valid_fetch_advances_state(
        self, mock_firms_key, temp_state_file, mock_ingest_nrt_rows, mock_load_polygons
    ):
        """Valid fetch with data advances state after successful ingestion."""
        import app.firms_scheduler as sched
        from datetime import datetime, timezone
        
        mock_rows = [{
            "latitude": "23.0", "longitude": "86.0", "bright_ti4": "300.0",
            "scan": "0.4", "track": "0.4", "acq_date": "2026-09-16",
            "acq_time": "1200", "satellite": "N", "instrument": "VIIRS",
            "confidence": "90", "version": "2.0", "bright_ti5": "290.0",
            "frp": "10.0", "daynight": "D"
        }]
        
        with patch.object(sched, "fetch_new_data", return_value=mock_rows):
            fetch_and_ingest_job()
        
        from app.firms_scheduler import STATE_FILE
        assert STATE_FILE.exists()
        content = STATE_FILE.read_text().strip()
        assert content == datetime.now(timezone.utc).date().isoformat()

    def test_ingestion_failure_does_not_advance_state(
        self, mock_firms_key, temp_state_file, mock_load_polygons
    ):
        """If ingest_nrt_rows raises, state does not advance."""
        import app.firms_scheduler as sched
        
        with patch.object(sched, "fetch_new_data", return_value=[{"latitude": "23.0", "longitude": "86.0"}]):
            with patch.object(sched, "ingest_nrt_rows", side_effect=RuntimeError("DB error")):
                fetch_and_ingest_job()
        
        from app.firms_scheduler import STATE_FILE
        assert not STATE_FILE.exists(), "State file should not advance on ingestion failure"

    def test_run_once_calls_job(self, mock_firms_key, temp_state_file, mock_ingest_nrt_rows, mock_load_polygons):
        """run_once() calls fetch_and_ingest_job once."""
        import app.firms_scheduler as sched
        
        with patch.object(sched, "fetch_and_ingest_job") as mock_job:
            result = run_once()
            mock_job.assert_called_once()
            assert result == {"status": "completed"}


class TestSchedulerConfiguration:
    """Tests for scheduler configuration."""

    def test_scheduler_not_auto_started(self):
        """Scheduler is not started on module import."""
        from app.firms_scheduler import get_scheduler
        scheduler = get_scheduler()
        assert not scheduler.running

    def test_scheduler_config(self):
        """Verify scheduler configuration."""
        from app.firms_scheduler import create_scheduler, FETCH_INTERVAL_HOURS
        scheduler = create_scheduler()
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.id == "firms_nrt_ingestion"
        assert job.name == "FIRMS NRT Jharia Ingestion"
        # IntervalTrigger uses timedelta, check total hours
        assert job.trigger.interval.total_seconds() == FETCH_INTERVAL_HOURS * 3600

    def test_scheduler_not_started_on_import(self):
        """Scheduler is not started on module import."""
        import importlib
        import sys
        
        # Reload module to test
        if "app.firms_scheduler" in sys.modules:
            importlib.reload(sys.modules["app.firms_scheduler"])
        else:
            import app.firms_scheduler
        
        from app.firms_scheduler import _scheduler
        assert _scheduler is None or not _scheduler.running

    def test_lifespan_scheduler_toggle_off(self, monkeypatch):
        """Verify scheduler remains stopped when ENABLE_FIRMS_SCHEDULER=false."""
        monkeypatch.setenv("ENABLE_FIRMS_SCHEDULER", "false")
        from app.firms_scheduler import stop_scheduler, get_scheduler
        stop_scheduler()
        
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app):
            assert not get_scheduler().running

    def test_lifespan_scheduler_toggle_on(self, monkeypatch):
        """Verify scheduler starts during lifespan when ENABLE_FIRMS_SCHEDULER=true."""
        monkeypatch.setenv("ENABLE_FIRMS_SCHEDULER", "true")
        from app.firms_scheduler import stop_scheduler, get_scheduler
        stop_scheduler()

        try:
            from fastapi.testclient import TestClient
            from app.main import app
            with TestClient(app):
                assert get_scheduler().running
        finally:
            stop_scheduler()


# ============================================================================
# TEST CONFIGURATION
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])