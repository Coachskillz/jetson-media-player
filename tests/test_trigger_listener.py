"""Unit tests for the TriggerListener module.

Tests trigger message handling, callback invocation, legacy trigger conversion,
statistics tracking, and background thread lifecycle.
"""

import pytest
import time
import threading
from unittest import mock
from typing import Dict, Any

from src.player.trigger_listener import (
    TriggerListener,
    get_trigger_listener,
)
from src.common.ipc import Message, MessageType


@pytest.fixture
def reset_global_trigger_listener():
    """Reset the global trigger listener instance before and after tests."""
    import src.player.trigger_listener as tl_module
    original = tl_module._global_trigger_listener
    tl_module._global_trigger_listener = None
    yield
    tl_module._global_trigger_listener = original


@pytest.fixture
def mock_config():
    """Create a mock config for testing."""
    with mock.patch('src.player.trigger_listener.get_config') as mock_get_config:
        config = mock.MagicMock()
        config.get.return_value = 5556
        mock_get_config.return_value = config
        yield config


@pytest.fixture
def trigger_listener(mock_config):
    """Create a TriggerListener instance for testing."""
    listener = TriggerListener(
        host="localhost",
        port=5556
    )
    yield listener
    # Cleanup
    if listener.is_running:
        listener.stop()


class TestTriggerListenerInit:
    """Tests for TriggerListener initialization."""

    def test_init_with_default_port(self, mock_config):
        """Test initialization with default port from config."""
        listener = TriggerListener(host="localhost")
        assert listener.host == "localhost"
        assert listener.port == 5556

    def test_init_with_custom_port(self, mock_config):
        """Test initialization with custom port."""
        listener = TriggerListener(host="localhost", port=5557)
        assert listener.port == 5557

    def test_init_with_callback(self, mock_config):
        """Test initialization with callback function."""
        callback = mock.MagicMock()
        listener = TriggerListener(
            host="localhost",
            port=5556,
            on_trigger=callback
        )
        assert listener._on_trigger is callback

    def test_init_stats_initialized(self, trigger_listener):
        """Test that statistics are initialized."""
        stats = trigger_listener.stats
        assert stats["demographic_count"] == 0
        assert stats["loyalty_count"] == 0
        assert stats["ncmec_count"] == 0
        assert stats["unknown_count"] == 0
        assert stats["last_trigger_time"] is None

    def test_init_not_running(self, trigger_listener):
        """Test that listener is not running initially."""
        assert trigger_listener.is_running is False

    def test_repr(self, trigger_listener):
        """Test string representation."""
        repr_str = repr(trigger_listener)
        assert "TriggerListener" in repr_str
        assert "host=localhost" in repr_str
        assert "port=5556" in repr_str


class TestTriggerListenerCallback:
    """Tests for callback handling."""

    def test_set_callback(self, trigger_listener):
        """Test setting callback after initialization."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)
        assert trigger_listener._on_trigger is callback

    def test_invoke_callback_calls_function(self, trigger_listener):
        """Test that callback is invoked with trigger data."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        trigger_data = {"type": "demographic", "age": 25, "gender": "male"}
        trigger_listener._invoke_callback(trigger_data)

        callback.assert_called_once_with(trigger_data)

    def test_invoke_callback_no_callback_set(self, trigger_listener):
        """Test invoke_callback when no callback is set."""
        # Should not raise
        trigger_listener._invoke_callback({"type": "demographic"})

    def test_invoke_callback_handles_exception(self, trigger_listener):
        """Test that callback exceptions are caught."""
        callback = mock.MagicMock(side_effect=Exception("Test error"))
        trigger_listener.set_callback(callback)

        # Should not raise
        trigger_listener._invoke_callback({"type": "demographic"})


class TestHandleDemographicTrigger:
    """Tests for demographic trigger handling."""

    def test_handle_demographic_trigger(self, trigger_listener):
        """Test handling demographic trigger."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        trigger_data = {
            "type": "demographic",
            "age": 30,
            "gender": "female",
            "confidence": 0.95
        }
        trigger_listener._handle_demographic_trigger(trigger_data)

        assert trigger_listener.stats["demographic_count"] == 1
        callback.assert_called_once_with(trigger_data)

    def test_handle_demographic_trigger_increments_counter(self, trigger_listener):
        """Test that demographic count increments correctly."""
        for i in range(5):
            trigger_listener._handle_demographic_trigger({
                "type": "demographic",
                "age": 25 + i,
                "gender": "male"
            })

        assert trigger_listener.stats["demographic_count"] == 5


class TestHandleLoyaltyTrigger:
    """Tests for loyalty trigger handling."""

    def test_handle_loyalty_trigger(self, trigger_listener):
        """Test handling loyalty trigger."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        trigger_data = {
            "type": "loyalty",
            "member_id": "member-12345",
            "member_name": "John Doe",
            "playlist_id": "vip-playlist"
        }
        trigger_listener._handle_loyalty_trigger(trigger_data)

        assert trigger_listener.stats["loyalty_count"] == 1
        callback.assert_called_once_with(trigger_data)


class TestHandleNcmecTrigger:
    """Tests for NCMEC trigger handling."""

    def test_handle_ncmec_trigger(self, trigger_listener):
        """Test handling NCMEC trigger."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        trigger_data = {
            "type": "ncmec_alert",
            "case_id": "case-001"
        }
        trigger_listener._handle_ncmec_trigger(trigger_data)

        assert trigger_listener.stats["ncmec_count"] == 1
        callback.assert_called_once_with(trigger_data)


class TestHandleMessage:
    """Tests for message handling."""

    def test_handle_message_demographic(self, trigger_listener):
        """Test handling demographic message."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        message = Message(
            msg_type=MessageType.TRIGGER,
            data={"type": "demographic", "age": 25, "gender": "male", "confidence": 0.9},
            sender="trigger_service"
        )
        trigger_listener._handle_message(message)

        assert trigger_listener.stats["demographic_count"] == 1

    def test_handle_message_loyalty(self, trigger_listener):
        """Test handling loyalty message."""
        message = Message(
            msg_type=MessageType.TRIGGER,
            data={"type": "loyalty", "member_id": "member-001"},
            sender="trigger_service"
        )
        trigger_listener._handle_message(message)

        assert trigger_listener.stats["loyalty_count"] == 1

    def test_handle_message_ncmec(self, trigger_listener):
        """Test handling NCMEC message."""
        message = Message(
            msg_type=MessageType.TRIGGER,
            data={"type": "ncmec_alert", "case_id": "case-001"},
            sender="trigger_service"
        )
        trigger_listener._handle_message(message)

        assert trigger_listener.stats["ncmec_count"] == 1

    def test_handle_message_unknown_type(self, trigger_listener):
        """Test handling message with unknown trigger type."""
        message = Message(
            msg_type=MessageType.TRIGGER,
            data={"type": "unknown_type"},
            sender="trigger_service"
        )
        trigger_listener._handle_message(message)

        assert trigger_listener.stats["unknown_count"] == 1

    def test_handle_message_ignores_non_trigger(self, trigger_listener):
        """Test that non-trigger messages are ignored."""
        message = Message(
            msg_type=MessageType.HEARTBEAT,
            data={"status": "ok"},
            sender="some_service"
        )
        trigger_listener._handle_message(message)

        # No stats should change
        assert trigger_listener.stats["demographic_count"] == 0
        assert trigger_listener.stats["loyalty_count"] == 0
        assert trigger_listener.stats["ncmec_count"] == 0

    def test_handle_message_updates_last_trigger_time(self, trigger_listener):
        """Test that last_trigger_time is updated."""
        message = Message(
            msg_type=MessageType.TRIGGER,
            data={"type": "demographic", "age": 25, "gender": "male"},
            sender="trigger_service"
        )

        assert trigger_listener.stats["last_trigger_time"] is None
        trigger_listener._handle_message(message)
        assert trigger_listener.stats["last_trigger_time"] is not None


class TestLegacyTriggerHandling:
    """Tests for legacy trigger format handling."""

    def test_handle_legacy_trigger_age_child(self, trigger_listener):
        """Test handling legacy age:child trigger."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        trigger_data = {
            "trigger": "age:child",
            "confidence": 0.92
        }
        trigger_listener._handle_legacy_trigger(trigger_data)

        callback.assert_called_once()
        call_args = callback.call_args[0][0]
        assert call_args["type"] == "demographic"
        assert call_args["age"] == 8
        assert call_args["confidence"] == 0.92

    def test_handle_legacy_trigger_age_teen(self, trigger_listener):
        """Test handling legacy age:teen trigger."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        trigger_data = {
            "trigger": "age:teen",
            "confidence": 0.85
        }
        trigger_listener._handle_legacy_trigger(trigger_data)

        call_args = callback.call_args[0][0]
        assert call_args["age"] == 16

    def test_handle_legacy_trigger_age_adult(self, trigger_listener):
        """Test handling legacy age:adult trigger."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        trigger_data = {
            "trigger": "age:adult",
            "confidence": 0.88
        }
        trigger_listener._handle_legacy_trigger(trigger_data)

        call_args = callback.call_args[0][0]
        assert call_args["age"] == 35

    def test_handle_legacy_trigger_age_senior(self, trigger_listener):
        """Test handling legacy age:senior trigger."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        trigger_data = {
            "trigger": "age:senior",
            "confidence": 0.78
        }
        trigger_listener._handle_legacy_trigger(trigger_data)

        call_args = callback.call_args[0][0]
        assert call_args["age"] == 70

    def test_handle_legacy_trigger_age_default_no_callback(self, trigger_listener):
        """Test handling legacy age:default trigger (no callback)."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        trigger_data = {
            "trigger": "age:default",
            "confidence": 0.5
        }
        trigger_listener._handle_legacy_trigger(trigger_data)

        callback.assert_not_called()

    def test_convert_legacy_trigger_empty_string(self, trigger_listener):
        """Test converting empty trigger string."""
        result = trigger_listener._convert_legacy_trigger("", 0.9)
        assert result is None

    def test_convert_legacy_trigger_invalid_format(self, trigger_listener):
        """Test converting invalid trigger format."""
        result = trigger_listener._convert_legacy_trigger("invalid", 0.9)
        assert result is None

    def test_convert_legacy_trigger_unknown_value(self, trigger_listener):
        """Test converting unknown age value."""
        result = trigger_listener._convert_legacy_trigger("age:unknown", 0.9)
        assert result is None

    def test_handle_message_legacy_format(self, trigger_listener):
        """Test handling message with legacy format."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        message = Message(
            msg_type=MessageType.TRIGGER,
            data={"trigger": "age:child", "confidence": 0.92},
            sender="trigger_service"
        )
        trigger_listener._handle_message(message)

        callback.assert_called_once()


class TestTriggerListenerLifecycle:
    """Tests for start/stop lifecycle."""

    def test_start_sets_running_flag(self, mock_config):
        """Test that start sets running flag."""
        with mock.patch('src.player.trigger_listener.MessageSubscriber'):
            listener = TriggerListener(host="localhost", port=5556)

            # Mock the listen loop to return immediately
            listener._listen_loop = mock.MagicMock()

            listener.start()
            time.sleep(0.1)

            assert listener._running is True

    def test_start_already_running_warns(self, trigger_listener):
        """Test that starting again warns."""
        trigger_listener._running = True

        with mock.patch('src.player.trigger_listener.logger') as mock_logger:
            trigger_listener.start()
            mock_logger.warning.assert_called()

    def test_stop_clears_running_flag(self, mock_config):
        """Test that stop clears running flag."""
        listener = TriggerListener(host="localhost", port=5556)
        listener._running = True
        listener._thread = None

        listener.stop()

        assert listener._running is False

    def test_stop_closes_subscriber(self, mock_config):
        """Test that stop closes subscriber."""
        listener = TriggerListener(host="localhost", port=5556)
        listener._running = True
        listener._thread = None
        mock_subscriber = mock.MagicMock()
        listener._subscriber = mock_subscriber

        listener.stop()

        mock_subscriber.close.assert_called_once()

    def test_stop_handles_subscriber_close_error(self, mock_config):
        """Test that stop handles subscriber close error."""
        listener = TriggerListener(host="localhost", port=5556)
        listener._running = True
        listener._thread = None
        mock_subscriber = mock.MagicMock()
        mock_subscriber.close.side_effect = Exception("Close error")
        listener._subscriber = mock_subscriber

        # Should not raise
        listener.stop()


class TestTriggerListenerProperties:
    """Tests for property accessors."""

    def test_is_running_property(self, trigger_listener):
        """Test is_running property."""
        assert trigger_listener.is_running is False
        trigger_listener._running = True
        assert trigger_listener.is_running is True

    def test_stats_property_returns_copy(self, trigger_listener):
        """Test that stats returns a copy."""
        stats1 = trigger_listener.stats
        stats2 = trigger_listener.stats

        # Modify one, other should be unchanged
        stats1["demographic_count"] = 100
        assert stats2["demographic_count"] == 0

    def test_get_status(self, trigger_listener):
        """Test get_status returns correct data."""
        status = trigger_listener.get_status()

        assert status["running"] is False
        assert status["host"] == "localhost"
        assert status["port"] == 5556
        assert "stats" in status


class TestGlobalTriggerListener:
    """Tests for global trigger listener instance."""

    def test_get_trigger_listener_creates_instance(
        self, mock_config, reset_global_trigger_listener
    ):
        """Test that get_trigger_listener creates a new instance."""
        listener = get_trigger_listener(host="localhost", port=5556)
        assert listener is not None
        assert isinstance(listener, TriggerListener)

    def test_get_trigger_listener_returns_same_instance(
        self, mock_config, reset_global_trigger_listener
    ):
        """Test that get_trigger_listener returns the same instance."""
        listener1 = get_trigger_listener(host="localhost", port=5556)
        listener2 = get_trigger_listener()
        listener3 = get_trigger_listener(host="different", port=5557)

        assert listener1 is listener2
        assert listener2 is listener3

    def test_get_trigger_listener_with_callback(
        self, mock_config, reset_global_trigger_listener
    ):
        """Test get_trigger_listener with callback."""
        callback = mock.MagicMock()
        listener = get_trigger_listener(
            host="localhost",
            port=5556,
            on_trigger=callback
        )

        assert listener._on_trigger is callback


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_handle_message_with_missing_type(self, trigger_listener):
        """Test handling message without type field."""
        message = Message(
            msg_type=MessageType.TRIGGER,
            data={"age": 25},  # No type field
            sender="trigger_service"
        )
        trigger_listener._handle_message(message)

        assert trigger_listener.stats["unknown_count"] == 1

    def test_demographic_trigger_with_missing_fields(self, trigger_listener):
        """Test demographic trigger with missing optional fields."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        trigger_data = {
            "type": "demographic"
            # Missing age, gender, confidence
        }
        trigger_listener._handle_demographic_trigger(trigger_data)

        # Should still call callback
        callback.assert_called_once_with(trigger_data)

    def test_loyalty_trigger_with_missing_fields(self, trigger_listener):
        """Test loyalty trigger with missing optional fields."""
        callback = mock.MagicMock()
        trigger_listener.set_callback(callback)

        trigger_data = {
            "type": "loyalty"
            # Missing member_id, member_name, playlist_id
        }
        trigger_listener._handle_loyalty_trigger(trigger_data)

        callback.assert_called_once_with(trigger_data)

    def test_ncmec_trigger_with_missing_case_id(self, trigger_listener):
        """Test NCMEC trigger with missing case_id."""
        trigger_data = {
            "type": "ncmec_alert"
            # Missing case_id
        }
        # Should not raise
        trigger_listener._handle_ncmec_trigger(trigger_data)

        assert trigger_listener.stats["ncmec_count"] == 1
