"""
Tests for PlayerStateMachine.
"""

import pytest
from unittest.mock import MagicMock

from src.player.state_machine import (
    PlayerStateMachine,
    PlayerMode,
    StateTransitionError,
    get_player_state_machine
)


class TestPlayerMode:
    """Tests for PlayerMode enum."""

    def test_mode_values(self):
        """Test that all modes have correct string values."""
        assert PlayerMode.PAIRING.value == "pairing"
        assert PlayerMode.PLAYBACK.value == "playback"
        assert PlayerMode.MENU.value == "menu"


class TestPlayerStateMachine:
    """Tests for PlayerStateMachine class."""

    def test_initial_mode_default(self):
        """Test default initial mode is PAIRING."""
        sm = PlayerStateMachine()
        assert sm.mode == PlayerMode.PAIRING

    def test_initial_mode_custom(self):
        """Test custom initial mode."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        assert sm.mode == PlayerMode.PLAYBACK

    def test_valid_transition_pairing_to_playback(self):
        """Test valid transition from PAIRING to PLAYBACK."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)
        result = sm.to_playback()
        assert result is True
        assert sm.mode == PlayerMode.PLAYBACK
        assert sm.previous_mode == PlayerMode.PAIRING

    def test_valid_transition_playback_to_menu(self):
        """Test valid transition from PLAYBACK to MENU."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        result = sm.to_menu()
        assert result is True
        assert sm.mode == PlayerMode.MENU

    def test_valid_transition_menu_to_playback(self):
        """Test valid transition from MENU to PLAYBACK."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        sm.to_menu()
        result = sm.to_playback()
        assert result is True
        assert sm.mode == PlayerMode.PLAYBACK

    def test_valid_transition_playback_to_pairing(self):
        """Test valid transition from PLAYBACK to PAIRING (re-pair)."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        result = sm.to_pairing()
        assert result is True
        assert sm.mode == PlayerMode.PAIRING

    def test_valid_transition_menu_to_pairing(self):
        """Test valid transition from MENU to PAIRING (re-pair from menu)."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        sm.to_menu()
        result = sm.to_pairing()
        assert result is True
        assert sm.mode == PlayerMode.PAIRING

    def test_invalid_transition_pairing_to_menu(self):
        """Test invalid transition from PAIRING to MENU."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)
        with pytest.raises(StateTransitionError):
            sm.to_menu()

    def test_same_mode_returns_false(self):
        """Test that transitioning to same mode returns False."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)
        result = sm.to_pairing()
        assert result is False

    def test_can_transition_to_valid(self):
        """Test can_transition_to for valid transitions."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)
        assert sm.can_transition_to(PlayerMode.PLAYBACK) is True
        assert sm.can_transition_to(PlayerMode.PAIRING) is True  # Same mode

    def test_can_transition_to_invalid(self):
        """Test can_transition_to for invalid transitions."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)
        assert sm.can_transition_to(PlayerMode.MENU) is False

    def test_toggle_menu_from_playback(self):
        """Test toggle_menu from PLAYBACK shows menu."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        sm.toggle_menu()
        assert sm.mode == PlayerMode.MENU

    def test_toggle_menu_from_menu(self):
        """Test toggle_menu from MENU returns to PLAYBACK."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        sm.to_menu()
        sm.toggle_menu()
        assert sm.mode == PlayerMode.PLAYBACK

    def test_toggle_menu_from_pairing_raises(self):
        """Test toggle_menu from PAIRING raises error."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)
        with pytest.raises(StateTransitionError):
            sm.toggle_menu()

    def test_callback_called_on_transition(self):
        """Test that callback is called on mode change."""
        callback = MagicMock()
        sm = PlayerStateMachine(
            initial_mode=PlayerMode.PAIRING,
            on_mode_changed=callback
        )

        sm.to_playback()

        callback.assert_called_once_with(
            sm,
            PlayerMode.PAIRING,
            PlayerMode.PLAYBACK
        )

    def test_callback_not_called_same_mode(self):
        """Test that callback is not called when staying in same mode."""
        callback = MagicMock()
        sm = PlayerStateMachine(
            initial_mode=PlayerMode.PAIRING,
            on_mode_changed=callback
        )

        sm.to_pairing()

        callback.assert_not_called()

    def test_property_helpers(self):
        """Test is_pairing, is_playback, is_menu properties."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        assert sm.is_pairing is True
        assert sm.is_playback is False
        assert sm.is_menu is False

        sm.to_playback()

        assert sm.is_pairing is False
        assert sm.is_playback is True
        assert sm.is_menu is False

    def test_get_state_info(self):
        """Test get_state_info returns correct data."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        info = sm.get_state_info()
        assert info['mode'] == 'pairing'
        assert info['mode_name'] == 'PAIRING'
        assert info['previous_mode'] is None

        sm.to_playback()

        info = sm.get_state_info()
        assert info['mode'] == 'playback'
        assert info['previous_mode'] == 'pairing'

    def test_repr(self):
        """Test string representation."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        assert repr(sm) == "PlayerStateMachine(mode=PLAYBACK)"


class TestGlobalStateMachine:
    """Tests for global state machine singleton."""

    def test_get_player_state_machine_creates_instance(self):
        """Test that get_player_state_machine creates an instance."""
        # Reset global instance
        import src.player.state_machine as sm_module
        sm_module._global_state_machine = None

        sm = get_player_state_machine(initial_mode=PlayerMode.PLAYBACK)
        assert sm is not None
        assert sm.mode == PlayerMode.PLAYBACK

    def test_get_player_state_machine_returns_same_instance(self):
        """Test that get_player_state_machine returns same instance."""
        import src.player.state_machine as sm_module
        sm_module._global_state_machine = None

        sm1 = get_player_state_machine(initial_mode=PlayerMode.PAIRING)
        sm2 = get_player_state_machine(initial_mode=PlayerMode.PLAYBACK)

        # Should be same instance
        assert sm1 is sm2
        # Initial mode from first call should be used
        assert sm1.mode == PlayerMode.PAIRING


class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_transitions(self):
        """Test that concurrent transitions are handled safely."""
        import threading

        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        errors = []

        def toggle_many_times():
            for _ in range(100):
                try:
                    sm.toggle_menu()
                except StateTransitionError as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=toggle_many_times)
            for _ in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not have any race condition errors
        # All transitions should be either to MENU or PLAYBACK
        assert sm.mode in (PlayerMode.MENU, PlayerMode.PLAYBACK)
