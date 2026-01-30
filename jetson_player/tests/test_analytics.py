"""
Tests for AnalyticsAggregator.

Covers bucket management, export logic, crash recovery,
and retention cleanup.
"""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from jetson_player.processors.analytics import AnalyticsAggregator


@pytest.fixture
def tmp_analytics(tmp_path):
    """Create an aggregator with a temporary storage path."""
    return AnalyticsAggregator(
        device_id="test-device",
        storage_path=str(tmp_path),
    )


class TestAddBucket:
    """Test adding analytics buckets."""

    def test_adds_device_id_to_bucket(self, tmp_analytics):
        bucket = {"people_count": 5}
        tmp_analytics.add_bucket(bucket)

        assert tmp_analytics._pending_buckets[0]["device_id"] == "test-device"

    def test_bucket_persisted_to_disk(self, tmp_analytics, tmp_path):
        tmp_analytics.add_bucket({"people_count": 3})

        pending_file = tmp_path / "pending_buckets.json"
        assert pending_file.exists()

        with open(pending_file) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["people_count"] == 3

    def test_multiple_buckets_accumulate(self, tmp_analytics):
        tmp_analytics.add_bucket({"count": 1})
        tmp_analytics.add_bucket({"count": 2})
        tmp_analytics.add_bucket({"count": 3})

        assert len(tmp_analytics._pending_buckets) == 3


class TestExport:
    """Test export logic."""

    def test_export_returns_none_when_empty(self, tmp_analytics):
        result = tmp_analytics.export()
        assert result is None

    def test_export_with_callback(self, tmp_analytics):
        callback = MagicMock()
        tmp_analytics._export_callback = callback
        tmp_analytics.add_bucket({"count": 5})

        result = tmp_analytics.export()

        callback.assert_called_once()
        assert result is not None
        assert result["bucket_count"] == 1
        assert result["device_id"] == "test-device"
        assert len(tmp_analytics._pending_buckets) == 0

    def test_export_without_callback_saves_locally(self, tmp_analytics, tmp_path):
        tmp_analytics.add_bucket({"count": 5})
        result = tmp_analytics.export()

        assert result is not None
        # Should have an export file
        exports = list(tmp_path.glob("export_*.json"))
        assert len(exports) == 1

    def test_export_callback_failure_keeps_buckets(self, tmp_analytics):
        callback = MagicMock(side_effect=Exception("network error"))
        tmp_analytics._export_callback = callback
        tmp_analytics.add_bucket({"count": 5})

        result = tmp_analytics.export()

        assert result is None
        assert len(tmp_analytics._pending_buckets) == 1

    def test_export_updates_total_count(self, tmp_analytics):
        tmp_analytics.add_bucket({"count": 1})
        tmp_analytics.add_bucket({"count": 2})
        tmp_analytics.export()

        assert tmp_analytics._total_exported == 2


class TestAutoExport:
    """Test automatic export triggering."""

    def test_does_not_export_before_interval(self, tmp_analytics):
        callback = MagicMock()
        tmp_analytics._export_callback = callback
        tmp_analytics._export_interval = 3600  # 1 hour

        tmp_analytics.add_bucket({"count": 1})

        # Callback should not be called (just added, interval not elapsed)
        callback.assert_not_called()

    def test_exports_after_interval(self, tmp_analytics):
        callback = MagicMock()
        tmp_analytics._export_callback = callback
        tmp_analytics._export_interval = 60

        # Simulate last export was 2 minutes ago
        tmp_analytics._last_export_time = time.time() - 120

        tmp_analytics.add_bucket({"count": 1})

        callback.assert_called_once()


class TestCrashRecovery:
    """Test persistence and recovery of pending buckets."""

    def test_load_pending_recovers_data(self, tmp_path):
        # Simulate a crash: write pending data to disk
        pending_file = tmp_path / "pending_buckets.json"
        buckets = [{"count": 1}, {"count": 2}]
        with open(pending_file, "w") as f:
            json.dump(buckets, f)

        # Create new aggregator - should recover
        agg = AnalyticsAggregator(
            device_id="dev1",
            storage_path=str(tmp_path),
        )
        agg._load_pending()

        assert len(agg._pending_buckets) == 2
        assert agg._pending_buckets[0]["count"] == 1

    def test_load_pending_handles_missing_file(self, tmp_path):
        agg = AnalyticsAggregator(
            device_id="dev1",
            storage_path=str(tmp_path),
        )
        agg._load_pending()
        assert len(agg._pending_buckets) == 0

    def test_load_pending_handles_corrupt_file(self, tmp_path):
        pending_file = tmp_path / "pending_buckets.json"
        pending_file.write_text("not valid json{{{")

        agg = AnalyticsAggregator(
            device_id="dev1",
            storage_path=str(tmp_path),
        )
        agg._load_pending()
        assert len(agg._pending_buckets) == 0


class TestCleanup:
    """Test old export cleanup."""

    def test_removes_old_exports(self, tmp_path):
        agg = AnalyticsAggregator(
            device_id="dev1",
            storage_path=str(tmp_path),
        )
        agg._retention_days = 0  # Expire everything

        # Create a fake export file with old mtime
        old_file = tmp_path / "export_20240101_000000.json"
        old_file.write_text("{}")
        import os
        os.utime(old_file, (0, 0))  # Set mtime to epoch

        agg.cleanup_old_exports()

        assert not old_file.exists()

    def test_keeps_recent_exports(self, tmp_path):
        agg = AnalyticsAggregator(
            device_id="dev1",
            storage_path=str(tmp_path),
        )
        agg._retention_days = 365

        recent_file = tmp_path / "export_20260128_120000.json"
        recent_file.write_text("{}")

        agg.cleanup_old_exports()

        assert recent_file.exists()


class TestGetStatus:
    """Test status reporting."""

    def test_status_fields(self, tmp_analytics):
        status = tmp_analytics.get_status()

        assert status["device_id"] == "test-device"
        assert status["pending_buckets"] == 0
        assert status["total_exported"] == 0
        assert "last_export" in status
        assert "export_interval_minutes" in status
        assert "retention_days" in status
        assert "storage_path" in status
