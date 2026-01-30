"""
Commercial Service — orchestrates the commercial camera pipeline.

Coordinates the commercial camera, loyalty database, age gating,
analytics aggregation, and ZeroMQ trigger delivery to the media player.

PRIVACY: The commercial pipeline stores ONLY anonymized aggregate
data (people counts, age/gender distributions). Individual-level
face data is never persisted. Loyalty matching is opt-in only.
"""

import os
import json
import logging
import time
import threading
from datetime import datetime, timezone
from typing import Optional, Callable, Dict

logger = logging.getLogger(__name__)

DEFAULT_ZMQ_ENDPOINT = "tcp://127.0.0.1:5556"


class CommercialService:
    """
    Orchestrates the commercial camera pipeline.

    Responsibilities:
    - Load loyalty FAISS index to GPU
    - Start the commercial camera (DeepStream)
    - Run age gating evaluation
    - Aggregate anonymized analytics
    - Send triggers to media player via ZeroMQ
    """

    def __init__(
        self,
        device_id: str = "unknown",
        location_id: str = "unknown",
        models_path: str = "/opt/skillz/models",
        db_path: str = "/opt/skillz/detection/databases",
        zmq_endpoint: str = DEFAULT_ZMQ_ENDPOINT,
        export_callback: Optional[Callable] = None,
    ):
        self.device_id = device_id
        self.location_id = location_id
        self.models_path = models_path
        self.db_path = db_path
        self.zmq_endpoint = os.environ.get(
            "SKILLZ_ZMQ_ENDPOINT", zmq_endpoint
        )
        self._export_callback = export_callback

        self._running = False
        self._zmq_socket = None

        # Lazy initialized components
        self._loyalty_db = None
        self._age_gating = None
        self._analytics = None

    def initialize(self) -> bool:
        """
        Initialize all commercial pipeline components.

        Returns:
            True if core components initialized (loyalty DB is optional).
        """
        from jetson_player.databases.loyalty_db import LoyaltyDatabase
        from jetson_player.processors.age_gating import AgeGatingService
        from jetson_player.processors.analytics import AnalyticsAggregator

        # Initialize loyalty database (optional — may not exist yet)
        self._loyalty_db = LoyaltyDatabase(db_path=self.db_path)
        loyalty_loaded = self._loyalty_db.load()
        if not loyalty_loaded:
            logger.info("No loyalty database available (optional)")

        # Initialize age gating
        self._age_gating = AgeGatingService(
            trigger_callback=self._send_trigger,
        )

        # Initialize analytics aggregator
        self._analytics = AnalyticsAggregator(
            device_id=self.device_id,
            export_callback=self._export_callback,
        )

        # Initialize ZeroMQ publisher
        self._init_zmq()

        logger.info(
            f"Commercial service initialized: "
            f"loyalty={'loaded' if loyalty_loaded else 'unavailable'}"
        )
        return True

    def start(self) -> bool:
        """Start the commercial pipeline."""
        self._running = True
        logger.info("Commercial service started")
        return True

    def stop(self):
        """Stop the commercial pipeline and export remaining analytics."""
        self._running = False

        # Final analytics export
        if self._analytics:
            self._analytics.export()

        # Close ZeroMQ
        if self._zmq_socket:
            self._zmq_socket.close()

        logger.info("Commercial service stopped")

    def set_content(self, content_id: str, rating: str,
                    alternative_id: Optional[str] = None):
        """
        Notify the service of current content for age gating.

        Called by the media player when content changes.
        """
        if self._age_gating:
            self._age_gating.set_current_content(
                content_id, rating, alternative_id
            )

    def handle_frame_result(self, result: dict):
        """
        Process a frame result from the commercial camera probe.

        Expected result format:
        {
            "faces": [{"age": int, "gender": str, "track_id": int, ...}],
            "people_count": int,
            "timestamp": float,
        }
        """
        faces = result.get("faces", [])
        people_count = result.get("people_count", 0)

        # Age gating evaluation
        if faces:
            youngest = min(f.get("age", 99) for f in faces)
            self._age_gating.evaluate(youngest)
        else:
            self._age_gating.evaluate(None)

        # Demographic trigger (non-age-gate)
        if faces and not self._age_gating.is_gate_active:
            self._evaluate_demographic_trigger(faces)

    def handle_loyalty_match(self, match: dict):
        """
        Handle a loyalty database match from the commercial camera.

        Sends a trigger to the media player with the matched
        member's preferences for personalized content.
        """
        trigger = {
            "type": "trigger",
            "source": "commercial",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger_type": "loyalty",
            "data": {
                "member_id": match.get("member_id"),
                "advertiser_id": match.get("advertiser_id"),
                "tier": match.get("tier"),
                "preferences": match.get("preferences", {}),
            },
            "priority": 80,
        }
        self._send_trigger(trigger)

    def add_analytics_bucket(self, bucket_data: dict):
        """Forward a completed analytics bucket to the aggregator."""
        if self._analytics:
            self._analytics.add_bucket(bucket_data)

    def _evaluate_demographic_trigger(self, faces: list):
        """Evaluate if demographic data should trigger content."""
        if not faces:
            return

        # Compute aggregate demographics
        ages = [f.get("age", 0) for f in faces if f.get("age")]
        genders = [f.get("gender", "unknown") for f in faces]

        if not ages:
            return

        avg_age = sum(ages) / len(ages)

        # Determine age bucket
        if avg_age < 18:
            age_range = "under-18"
        elif avg_age < 25:
            age_range = "18-24"
        elif avg_age < 35:
            age_range = "25-34"
        elif avg_age < 50:
            age_range = "35-49"
        else:
            age_range = "50+"

        # Majority gender
        male_count = genders.count("male")
        female_count = genders.count("female")
        if male_count > female_count:
            majority_gender = "male"
        elif female_count > male_count:
            majority_gender = "female"
        else:
            majority_gender = "mixed"

        trigger = {
            "type": "trigger",
            "source": "commercial",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger_type": "demographic",
            "data": {
                "age_range": age_range,
                "gender": majority_gender,
                "audience_size": len(faces),
            },
            "priority": 50,
        }
        self._send_trigger(trigger)

    def _send_trigger(self, trigger: dict):
        """Send trigger to media player via ZeroMQ."""
        if self._zmq_socket:
            try:
                msg = json.dumps(trigger).encode("utf-8")
                self._zmq_socket.send(msg, flags=1)  # NOBLOCK
            except Exception as e:
                logger.debug(f"ZMQ send failed (player may be offline): {e}")

    def _init_zmq(self):
        """Initialize ZeroMQ publisher socket."""
        try:
            import zmq
            ctx = zmq.Context.instance()
            self._zmq_socket = ctx.socket(zmq.PUB)
            self._zmq_socket.bind(self.zmq_endpoint)
            logger.info(f"ZMQ publisher bound to {self.zmq_endpoint}")
        except ImportError:
            logger.warning("ZeroMQ not available - triggers disabled")
        except Exception as e:
            logger.error(f"Failed to init ZMQ: {e}")

    @property
    def loyalty_db(self):
        return self._loyalty_db

    @property
    def age_gating(self):
        return self._age_gating

    @property
    def analytics(self):
        return self._analytics

    def get_status(self) -> dict:
        status = {
            "running": self._running,
            "device_id": self.device_id,
            "location_id": self.location_id,
            "zmq_endpoint": self.zmq_endpoint,
        }
        if self._loyalty_db:
            status["loyalty_db"] = self._loyalty_db.get_status()
        if self._age_gating:
            status["age_gating"] = self._age_gating.get_status()
        if self._analytics:
            status["analytics"] = self._analytics.get_status()
        return status
