"""
Age Gating Service for content filtering.

Determines whether content is appropriate for the detected audience
based on age estimation from the commercial camera pipeline.
Triggers content switches when underage viewers are detected.
"""

import os
import logging
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# Buffer period before returning to age-restricted content
# after underage face exits the view
DEFAULT_BUFFER_SECONDS = 5


class AgeGatingService:
    """
    Determines appropriate content based on detected audience age.

    Uses the youngest detected face to make gating decisions.
    When an underage viewer is detected for age-restricted content,
    triggers a switch to family-friendly alternative content.
    """

    AGE_THRESHOLDS = {
        "general": 0,
        "teen": 13,
        "mature": 18,
        "alcohol": 21,
        "tobacco": 21,
        "gambling": 21,
    }

    def __init__(
        self,
        trigger_callback: Optional[Callable] = None,
        buffer_seconds: int = DEFAULT_BUFFER_SECONDS,
    ):
        self._trigger_callback = trigger_callback
        self._buffer_seconds = int(
            os.environ.get("SKILLZ_AGE_GATE_BUFFER_SECONDS", buffer_seconds)
        )

        # Current state
        self._current_content_rating: Optional[str] = None
        self._current_content_id: Optional[str] = None
        self._gate_active = False
        self._last_underage_seen: float = 0.0
        self._alternative_content_id: Optional[str] = None

    def set_current_content(self, content_id: str, rating: str,
                            alternative_id: Optional[str] = None):
        """
        Update the currently playing content and its rating.

        Called by the media player when content changes.

        Args:
            content_id: ID of the current content
            rating: Content rating category (general, teen, mature, alcohol, etc.)
            alternative_id: Family-friendly alternative content ID
        """
        self._current_content_rating = rating
        self._current_content_id = content_id
        self._alternative_content_id = alternative_id

    def evaluate(self, youngest_detected_age: Optional[int]) -> bool:
        """
        Evaluate whether current content is appropriate for the audience.

        Args:
            youngest_detected_age: Minimum age bucket of detected faces,
                                   or None if no faces detected.

        Returns:
            True if content should be switched (age gate triggered),
            False if current content is appropriate.
        """
        if self._current_content_rating is None:
            return False

        threshold = self.AGE_THRESHOLDS.get(self._current_content_rating, 0)

        # No age restriction
        if threshold == 0:
            return False

        current_time = time.time()

        if youngest_detected_age is not None and youngest_detected_age < threshold:
            # Underage viewer detected
            self._last_underage_seen = current_time

            if not self._gate_active:
                self._gate_active = True
                logger.info(
                    f"Age gate ACTIVATED: detected age ~{youngest_detected_age}, "
                    f"content requires {threshold}+ "
                    f"(rating: {self._current_content_rating})"
                )
                self._send_gate_trigger(youngest_detected_age, "activate")
                return True

        elif self._gate_active:
            # Check if buffer period has elapsed since last underage detection
            elapsed = current_time - self._last_underage_seen
            if elapsed >= self._buffer_seconds:
                self._gate_active = False
                logger.info(
                    f"Age gate DEACTIVATED: no underage viewers for "
                    f"{self._buffer_seconds}s"
                )
                self._send_gate_trigger(youngest_detected_age, "deactivate")

        return self._gate_active

    def should_show_content(self, content_rating: str,
                            youngest_detected_age: Optional[int]) -> bool:
        """
        Static check if content is appropriate for detected age.

        Args:
            content_rating: Content rating category
            youngest_detected_age: Minimum detected age, or None

        Returns:
            True if content is appropriate (should show),
            False if content should be blocked.
        """
        if youngest_detected_age is None:
            return True  # No one detected, show content

        threshold = self.AGE_THRESHOLDS.get(content_rating, 0)
        return youngest_detected_age >= threshold

    def get_alternative_content(self) -> Optional[str]:
        """
        Get the family-friendly alternative content ID.

        Returns:
            Alternative content ID or None if not configured.
        """
        return self._alternative_content_id

    def _send_gate_trigger(self, detected_age: Optional[int], action: str):
        """Send age gate trigger to media player."""
        if self._trigger_callback is None:
            return

        from datetime import datetime, timezone

        trigger = {
            "type": "trigger",
            "source": "commercial",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger_type": "age_gate",
            "data": {
                "youngest_detected": detected_age,
                "action": f"switch_to_{'alternative' if action == 'activate' else 'original'}",
                "content_rating": self._current_content_rating,
                "required_age": self.AGE_THRESHOLDS.get(
                    self._current_content_rating, 0
                ),
            },
            "content_id": (
                self._alternative_content_id if action == "activate"
                else self._current_content_id
            ),
            "priority": 100,  # Highest priority
        }

        self._trigger_callback(trigger)

    @property
    def is_gate_active(self) -> bool:
        return self._gate_active

    def get_status(self) -> dict:
        return {
            "gate_active": self._gate_active,
            "current_rating": self._current_content_rating,
            "current_content": self._current_content_id,
            "alternative_content": self._alternative_content_id,
            "buffer_seconds": self._buffer_seconds,
        }
