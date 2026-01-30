"""
Safety Service — orchestrates the NCMEC missing children pipeline.

Coordinates the safety camera, NCMEC database, and alert service.
Runs as an independent process from the commercial pipeline.

PRIVACY: The safety pipeline NEVER stores captured face images or
embeddings. It only compares against the NCMEC-provided index and
generates alerts with case references (no biometric data).
"""

import os
import logging
import time
import threading
from typing import Optional, Callable

logger = logging.getLogger(__name__)

NCMEC_RELOAD_INTERVAL = 6 * 3600  # 6 hours


class SafetyService:
    """
    Orchestrates the safety camera pipeline.

    Responsibilities:
    - Load NCMEC FAISS index to GPU
    - Start the safety camera (DeepStream)
    - Route match alerts to AlertService
    - Periodically check for NCMEC index updates
    """

    def __init__(
        self,
        device_id: str = "unknown",
        location_id: str = "unknown",
        models_path: str = "/opt/skillz/models",
        db_path: str = "/opt/skillz/detection/databases",
        alert_callback: Optional[Callable] = None,
    ):
        self.device_id = device_id
        self.location_id = location_id
        self.models_path = models_path
        self.db_path = db_path
        self._alert_callback = alert_callback

        self._running = False
        self._reload_thread: Optional[threading.Thread] = None

        # Lazy imports to avoid circular deps
        self._ncmec_db = None
        self._alert_service = None
        self._safety_camera = None

    def initialize(self) -> bool:
        """
        Initialize all safety pipeline components.

        Returns:
            True if all components initialized successfully.
        """
        from jetson_player.databases.ncmec_db import NCMECDatabase
        from jetson_player.services.alert_service import AlertService

        # Initialize NCMEC database
        self._ncmec_db = NCMECDatabase(db_path=self.db_path)
        if not self._ncmec_db.load():
            logger.error("Failed to load NCMEC database")
            return False

        # Initialize alert service
        self._alert_service = AlertService(
            device_id=self.device_id,
            location_id=self.location_id,
            forward_callback=self._alert_callback,
        )

        logger.info(
            f"Safety service initialized: "
            f"{self._ncmec_db.entry_count} NCMEC entries loaded"
        )
        return True

    def start(self) -> bool:
        """
        Start the safety pipeline.

        Returns:
            True if started successfully.
        """
        if not self._ncmec_db or not self._ncmec_db.is_loaded:
            logger.error("Cannot start: NCMEC database not loaded")
            return False

        self._running = True

        # Start periodic NCMEC index reload check
        self._reload_thread = threading.Thread(
            target=self._reload_loop, daemon=True
        )
        self._reload_thread.start()

        logger.info("Safety service started")
        return True

    def stop(self):
        """Stop the safety pipeline."""
        self._running = False
        if self._reload_thread:
            self._reload_thread.join(timeout=5)
        logger.info("Safety service stopped")

    def handle_match(self, ncmec_match: dict, camera_id: str = "safety"):
        """
        Handle a face match from the safety camera probe callback.

        Called by SafetyCamera when a FAISS match exceeds threshold.

        Args:
            ncmec_match: Match result from NCMECDatabase.search()
            camera_id: Camera identifier
        """
        if not self._alert_service:
            logger.error("Alert service not initialized")
            return

        self._alert_service.create_alert(
            ncmec_match=ncmec_match,
            camera_id=camera_id,
        )

    def flush_alerts(self) -> int:
        """Retry forwarding any pending alerts."""
        if self._alert_service:
            return self._alert_service.flush()
        return 0

    def _reload_loop(self):
        """Periodically check for NCMEC index updates."""
        interval = int(os.environ.get(
            "SKILLZ_NCMEC_RELOAD_INTERVAL", NCMEC_RELOAD_INTERVAL
        ))

        while self._running:
            time.sleep(interval)
            if not self._running:
                break

            try:
                if self._ncmec_db.reload():
                    logger.info(
                        f"NCMEC index reloaded: "
                        f"{self._ncmec_db.entry_count} entries"
                    )
            except Exception as e:
                logger.error(f"NCMEC reload failed: {e}")

    @property
    def ncmec_db(self):
        return self._ncmec_db

    @property
    def alert_service(self):
        return self._alert_service

    def get_status(self) -> dict:
        status = {
            "running": self._running,
            "device_id": self.device_id,
            "location_id": self.location_id,
        }
        if self._ncmec_db:
            status["ncmec_db"] = self._ncmec_db.get_status()
        if self._alert_service:
            status["alerts"] = self._alert_service.get_status()
        return status
