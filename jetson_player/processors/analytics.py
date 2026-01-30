"""
Analytics Aggregator for commercial camera pipeline.

Collects people counting, dwell time, and demographic data
in time-bucketed windows. All data is anonymized and aggregated.
"""

import os
import logging
import json
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_BUCKET_MINUTES = 15
DEFAULT_EXPORT_INTERVAL_MINUTES = 60
DEFAULT_RETENTION_DAYS = 90


class AnalyticsAggregator:
    """
    Aggregates anonymous analytics data from the commercial camera.

    Stores completed analytics buckets locally and exports them
    to the hub on a configurable interval. All data is anonymized
    - no individual-level face data is stored.
    """

    def __init__(
        self,
        device_id: str = "unknown",
        storage_path: str = "/var/lib/skillz/analytics",
        export_callback=None,
    ):
        self.device_id = device_id
        self.storage_path = Path(
            os.environ.get("SKILLZ_ANALYTICS_PATH", storage_path)
        )
        self._export_callback = export_callback

        self._bucket_minutes = int(os.environ.get(
            "SKILLZ_ANALYTICS_BUCKET_MINUTES", DEFAULT_BUCKET_MINUTES
        ))
        self._export_interval = int(os.environ.get(
            "SKILLZ_ANALYTICS_EXPORT_INTERVAL_MINUTES", DEFAULT_EXPORT_INTERVAL_MINUTES
        )) * 60
        self._retention_days = int(os.environ.get(
            "SKILLZ_ANALYTICS_RETENTION_DAYS", DEFAULT_RETENTION_DAYS
        ))

        self._pending_buckets: List[dict] = []
        self._last_export_time: float = time.time()
        self._total_exported: int = 0

        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def add_bucket(self, bucket_data: dict):
        """
        Add a completed analytics bucket.

        Args:
            bucket_data: Aggregated analytics from AnalyticsBucket.to_dict()
        """
        bucket_data["device_id"] = self.device_id
        self._pending_buckets.append(bucket_data)

        # Persist to disk (in case of crash)
        self._save_pending()

        # Check if we should export
        if self._should_export():
            self.export()

    def export(self) -> Optional[dict]:
        """
        Export pending analytics buckets to the hub.

        Returns:
            Export result dict or None if nothing to export.
        """
        if not self._pending_buckets:
            return None

        export_data = {
            "device_id": self.device_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "bucket_count": len(self._pending_buckets),
            "buckets": list(self._pending_buckets),
        }

        if self._export_callback:
            try:
                self._export_callback(export_data)
                self._pending_buckets.clear()
                self._save_pending()
                self._last_export_time = time.time()
                self._total_exported += export_data["bucket_count"]
                logger.info(
                    f"Exported {export_data['bucket_count']} analytics buckets"
                )
                return export_data
            except Exception as e:
                logger.error(f"Analytics export failed: {e}")
                # Keep buckets for retry
                return None
        else:
            # No callback, just save locally
            self._save_export(export_data)
            self._pending_buckets.clear()
            self._save_pending()
            self._last_export_time = time.time()
            self._total_exported += export_data["bucket_count"]
            return export_data

    def _should_export(self) -> bool:
        elapsed = time.time() - self._last_export_time
        return elapsed >= self._export_interval

    def _save_pending(self):
        """Save pending buckets to disk for crash recovery."""
        pending_file = self.storage_path / "pending_buckets.json"
        try:
            with open(pending_file, "w") as f:
                json.dump(self._pending_buckets, f)
        except Exception as e:
            logger.error(f"Failed to save pending analytics: {e}")

    def _load_pending(self):
        """Load pending buckets from disk (crash recovery)."""
        pending_file = self.storage_path / "pending_buckets.json"
        if pending_file.exists():
            try:
                with open(pending_file, "r") as f:
                    self._pending_buckets = json.load(f)
                logger.info(
                    f"Recovered {len(self._pending_buckets)} pending analytics buckets"
                )
            except Exception as e:
                logger.error(f"Failed to load pending analytics: {e}")

    def _save_export(self, export_data: dict):
        """Save export to local storage."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        export_file = self.storage_path / f"export_{timestamp}.json"
        try:
            with open(export_file, "w") as f:
                json.dump(export_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save analytics export: {e}")

    def cleanup_old_exports(self):
        """Delete analytics exports older than retention period."""
        cutoff = time.time() - (self._retention_days * 86400)
        removed = 0

        for f in self.storage_path.glob("export_*.json"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1

        if removed:
            logger.info(f"Cleaned up {removed} old analytics exports")

    def get_status(self) -> dict:
        return {
            "device_id": self.device_id,
            "pending_buckets": len(self._pending_buckets),
            "total_exported": self._total_exported,
            "last_export": datetime.fromtimestamp(
                self._last_export_time, tz=timezone.utc
            ).isoformat(),
            "export_interval_minutes": self._export_interval // 60,
            "retention_days": self._retention_days,
            "storage_path": str(self.storage_path),
        }
