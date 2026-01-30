"""
Alert Service for routing NCMEC match alerts.

Handles alert creation, local queuing (for offline resilience),
and forwarding to the local hub / central hub.

PRIVACY: Alerts contain ONLY the NCMEC case reference and match
confidence. NO captured images or embeddings are included in alerts
unless explicitly configured with SKILLZ_ALERT_INCLUDE_SNAPSHOT=true,
in which case images are encrypted before storage.
"""

import os
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, List

logger = logging.getLogger(__name__)

DEFAULT_ALERT_PATH = "/opt/skillz/detection/alerts/pending"
MAX_QUEUE_SIZE = 1000


class AlertService:
    """
    Manages NCMEC match alert lifecycle.

    Alerts are queued locally and forwarded to the hub.
    If the hub is unreachable, alerts persist on disk
    and are retried on the next attempt.
    """

    def __init__(
        self,
        device_id: str = "unknown",
        location_id: str = "unknown",
        alert_path: str = DEFAULT_ALERT_PATH,
        forward_callback: Optional[Callable] = None,
    ):
        self.device_id = device_id
        self.location_id = location_id
        self.alert_path = Path(
            os.environ.get("SKILLZ_ALERT_PATH", alert_path)
        )
        self._forward_callback = forward_callback

        self._include_snapshot = os.environ.get(
            "SKILLZ_ALERT_INCLUDE_SNAPSHOT", "false"
        ).lower() == "true"

        self._pending_alerts: List[dict] = []
        self._total_alerts: int = 0
        self._total_forwarded: int = 0

        self.alert_path.mkdir(parents=True, exist_ok=True)
        self._load_pending()

    def create_alert(
        self,
        ncmec_match: dict,
        camera_id: str = "safety",
        snapshot_path: Optional[str] = None,
    ) -> dict:
        """
        Create and queue an NCMEC match alert.

        Args:
            ncmec_match: Match result from NCMECDatabase.search()
            camera_id: Which camera triggered the alert
            snapshot_path: Optional path to encrypted snapshot

        Returns:
            The created alert dict.
        """
        alert = {
            "alert_id": str(uuid.uuid4()),
            "type": "ncmec",
            "device_id": self.device_id,
            "location_id": self.location_id,
            "camera_id": camera_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ncmec_id": ncmec_match.get("ncmec_id"),
            "case_number": ncmec_match.get("case_number"),
            "confidence": ncmec_match.get("similarity"),
            "status": "pending",
        }

        if self._include_snapshot and snapshot_path:
            alert["snapshot_path"] = snapshot_path

        self._pending_alerts.append(alert)
        self._total_alerts += 1
        self._save_pending()

        logger.warning(
            f"NCMEC ALERT: case={alert['case_number']}, "
            f"confidence={alert['confidence']:.3f}, "
            f"alert_id={alert['alert_id']}"
        )

        # Attempt immediate forwarding
        self._try_forward(alert)

        return alert

    def flush(self) -> int:
        """
        Attempt to forward all pending alerts.

        Returns:
            Number of successfully forwarded alerts.
        """
        if not self._forward_callback:
            return 0

        forwarded = 0
        remaining = []

        for alert in self._pending_alerts:
            if self._try_forward(alert):
                forwarded += 1
            else:
                remaining.append(alert)

        self._pending_alerts = remaining
        self._save_pending()
        return forwarded

    def _try_forward(self, alert: dict) -> bool:
        """Attempt to forward a single alert to the hub."""
        if not self._forward_callback:
            return False

        try:
            self._forward_callback(alert)
            alert["status"] = "forwarded"
            alert["forwarded_at"] = datetime.now(timezone.utc).isoformat()
            self._total_forwarded += 1

            # Remove from pending
            self._pending_alerts = [
                a for a in self._pending_alerts
                if a["alert_id"] != alert["alert_id"]
            ]
            self._save_pending()

            # Save to forwarded log
            self._log_forwarded(alert)

            logger.info(
                f"Alert forwarded: {alert['alert_id']} "
                f"(case: {alert.get('case_number')})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to forward alert {alert['alert_id']}: {e}")
            return False

    def _save_pending(self):
        """Persist pending alerts to disk."""
        pending_file = self.alert_path / "pending_alerts.json"
        try:
            # Enforce queue size limit
            if len(self._pending_alerts) > MAX_QUEUE_SIZE:
                logger.warning(
                    f"Alert queue exceeds {MAX_QUEUE_SIZE}, trimming oldest"
                )
                self._pending_alerts = self._pending_alerts[-MAX_QUEUE_SIZE:]

            with open(pending_file, "w") as f:
                json.dump(self._pending_alerts, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save pending alerts: {e}")

    def _load_pending(self):
        """Load pending alerts from disk (crash recovery)."""
        pending_file = self.alert_path / "pending_alerts.json"
        if pending_file.exists():
            try:
                with open(pending_file, "r") as f:
                    self._pending_alerts = json.load(f)
                if self._pending_alerts:
                    logger.info(
                        f"Recovered {len(self._pending_alerts)} pending alerts"
                    )
            except Exception as e:
                logger.error(f"Failed to load pending alerts: {e}")

    def _log_forwarded(self, alert: dict):
        """Append forwarded alert to audit log."""
        log_file = self.alert_path.parent / "forwarded_log.jsonl"
        try:
            with open(log_file, "a") as f:
                f.write(json.dumps(alert) + "\n")
        except Exception as e:
            logger.error(f"Failed to log forwarded alert: {e}")

    @property
    def pending_count(self) -> int:
        return len(self._pending_alerts)

    def get_status(self) -> dict:
        return {
            "device_id": self.device_id,
            "location_id": self.location_id,
            "pending_alerts": len(self._pending_alerts),
            "total_alerts": self._total_alerts,
            "total_forwarded": self._total_forwarded,
            "include_snapshot": self._include_snapshot,
            "alert_path": str(self.alert_path),
        }
