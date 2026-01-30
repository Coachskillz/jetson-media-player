"""
Tests for AgeGatingService.

Covers threshold evaluation, gate activation/deactivation,
buffer period, and content switching triggers.
"""

import time
import pytest
from unittest.mock import MagicMock

from jetson_player.processors.age_gating import AgeGatingService


class TestAgeThresholds:
    """Verify age threshold lookups for each content rating."""

    def test_general_content_has_zero_threshold(self):
        svc = AgeGatingService()
        assert svc.AGE_THRESHOLDS["general"] == 0

    def test_teen_content_requires_13(self):
        svc = AgeGatingService()
        assert svc.AGE_THRESHOLDS["teen"] == 13

    def test_mature_content_requires_18(self):
        svc = AgeGatingService()
        assert svc.AGE_THRESHOLDS["mature"] == 18

    def test_alcohol_content_requires_21(self):
        svc = AgeGatingService()
        assert svc.AGE_THRESHOLDS["alcohol"] == 21

    def test_tobacco_content_requires_21(self):
        svc = AgeGatingService()
        assert svc.AGE_THRESHOLDS["tobacco"] == 21

    def test_gambling_content_requires_21(self):
        svc = AgeGatingService()
        assert svc.AGE_THRESHOLDS["gambling"] == 21


class TestEvaluate:
    """Test the evaluate() gate activation logic."""

    def test_no_content_set_returns_false(self):
        svc = AgeGatingService()
        assert svc.evaluate(youngest_detected_age=10) is False

    def test_general_content_never_gates(self):
        svc = AgeGatingService()
        svc.set_current_content("c1", "general")
        assert svc.evaluate(youngest_detected_age=5) is False

    def test_mature_content_gates_on_minor(self):
        svc = AgeGatingService()
        svc.set_current_content("c1", "mature", alternative_id="alt1")
        result = svc.evaluate(youngest_detected_age=15)
        assert result is True
        assert svc.is_gate_active is True

    def test_mature_content_allows_adult(self):
        svc = AgeGatingService()
        svc.set_current_content("c1", "mature")
        result = svc.evaluate(youngest_detected_age=25)
        assert result is False
        assert svc.is_gate_active is False

    def test_alcohol_content_gates_on_under_21(self):
        svc = AgeGatingService()
        svc.set_current_content("c1", "alcohol")
        result = svc.evaluate(youngest_detected_age=19)
        assert result is True

    def test_alcohol_content_allows_21_plus(self):
        svc = AgeGatingService()
        svc.set_current_content("c1", "alcohol")
        result = svc.evaluate(youngest_detected_age=21)
        assert result is False

    def test_no_faces_detected_does_not_gate(self):
        svc = AgeGatingService()
        svc.set_current_content("c1", "mature")
        result = svc.evaluate(youngest_detected_age=None)
        assert result is False

    def test_exact_threshold_age_does_not_gate(self):
        """Age exactly at threshold should be allowed."""
        svc = AgeGatingService()
        svc.set_current_content("c1", "teen")
        result = svc.evaluate(youngest_detected_age=13)
        assert result is False


class TestGateDeactivation:
    """Test buffer period and gate deactivation."""

    def test_gate_deactivates_after_buffer(self):
        svc = AgeGatingService(buffer_seconds=1)
        svc.set_current_content("c1", "mature")

        # Activate gate
        svc.evaluate(youngest_detected_age=15)
        assert svc.is_gate_active is True

        # Simulate buffer period elapsed
        svc._last_underage_seen = time.time() - 2

        # Evaluate with no faces — should deactivate
        svc.evaluate(youngest_detected_age=None)
        assert svc.is_gate_active is False

    def test_gate_stays_active_during_buffer(self):
        svc = AgeGatingService(buffer_seconds=10)
        svc.set_current_content("c1", "mature")

        svc.evaluate(youngest_detected_age=15)
        assert svc.is_gate_active is True

        # No faces but buffer not elapsed
        svc.evaluate(youngest_detected_age=None)
        assert svc.is_gate_active is True

    def test_gate_reactivates_on_new_underage(self):
        svc = AgeGatingService(buffer_seconds=1)
        svc.set_current_content("c1", "mature")

        # Activate and deactivate
        svc.evaluate(youngest_detected_age=15)
        svc._last_underage_seen = time.time() - 2
        svc.evaluate(youngest_detected_age=None)
        assert svc.is_gate_active is False

        # New underage detection
        result = svc.evaluate(youngest_detected_age=12)
        assert result is True
        assert svc.is_gate_active is True


class TestTriggerCallback:
    """Test that trigger callbacks fire correctly."""

    def test_activate_trigger_fires(self):
        callback = MagicMock()
        svc = AgeGatingService(trigger_callback=callback)
        svc.set_current_content("c1", "mature", alternative_id="alt1")

        svc.evaluate(youngest_detected_age=15)

        callback.assert_called_once()
        trigger = callback.call_args[0][0]
        assert trigger["trigger_type"] == "age_gate"
        assert trigger["data"]["action"] == "switch_to_alternative"
        assert trigger["content_id"] == "alt1"
        assert trigger["priority"] == 100

    def test_deactivate_trigger_fires(self):
        callback = MagicMock()
        svc = AgeGatingService(trigger_callback=callback, buffer_seconds=0)
        svc.set_current_content("c1", "mature", alternative_id="alt1")

        svc.evaluate(youngest_detected_age=15)
        callback.reset_mock()

        # Force buffer elapsed
        svc._last_underage_seen = time.time() - 1
        svc.evaluate(youngest_detected_age=None)

        callback.assert_called_once()
        trigger = callback.call_args[0][0]
        assert trigger["data"]["action"] == "switch_to_original"
        assert trigger["content_id"] == "c1"

    def test_no_callback_does_not_crash(self):
        svc = AgeGatingService(trigger_callback=None)
        svc.set_current_content("c1", "mature")
        # Should not raise
        svc.evaluate(youngest_detected_age=15)


class TestShouldShowContent:
    """Test the static content appropriateness check."""

    def test_no_viewer_always_shows(self):
        svc = AgeGatingService()
        assert svc.should_show_content("alcohol", None) is True

    def test_underage_blocks_alcohol(self):
        svc = AgeGatingService()
        assert svc.should_show_content("alcohol", 18) is False

    def test_of_age_shows_alcohol(self):
        svc = AgeGatingService()
        assert svc.should_show_content("alcohol", 21) is True

    def test_unknown_rating_defaults_to_show(self):
        svc = AgeGatingService()
        assert svc.should_show_content("unknown_rating", 5) is True


class TestGetStatus:
    """Test status reporting."""

    def test_status_contains_expected_fields(self):
        svc = AgeGatingService()
        svc.set_current_content("c1", "mature", alternative_id="alt1")
        status = svc.get_status()

        assert "gate_active" in status
        assert "current_rating" in status
        assert "current_content" in status
        assert "alternative_content" in status
        assert "buffer_seconds" in status
        assert status["current_rating"] == "mature"
        assert status["current_content"] == "c1"
        assert status["alternative_content"] == "alt1"
