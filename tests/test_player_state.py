"""
Unit tests for Player State Machine.

Tests state transitions: pairing -> playback -> menu
as specified in the QA acceptance criteria.
"""

import pytest
import threading
from unittest.mock import MagicMock, call

from src.player.state_machine import (
    PlayerStateMachine,
    PlayerMode,
    StateTransitionError,
    get_player_state_machine
)


class TestPlayerModeEnum:
    """Tests for PlayerMode enum values."""

    def test_pairing_mode_value(self):
        """PAIRING mode should have value 'pairing'."""
        assert PlayerMode.PAIRING.value == "pairing"

    def test_playback_mode_value(self):
        """PLAYBACK mode should have value 'playback'."""
        assert PlayerMode.PLAYBACK.value == "playback"

    def test_menu_mode_value(self):
        """MENU mode should have value 'menu'."""
        assert PlayerMode.MENU.value == "menu"

    def test_all_modes_exist(self):
        """All required modes should exist."""
        modes = [mode.value for mode in PlayerMode]
        assert "pairing" in modes
        assert "playback" in modes
        assert "menu" in modes


class TestStateMachineInitialization:
    """Tests for state machine initialization."""

    def test_default_initial_mode_is_pairing(self):
        """Default initial mode should be PAIRING."""
        sm = PlayerStateMachine()
        assert sm.mode == PlayerMode.PAIRING

    def test_custom_initial_mode_playback(self):
        """Can initialize with PLAYBACK mode."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        assert sm.mode == PlayerMode.PLAYBACK

    def test_custom_initial_mode_menu(self):
        """Can initialize with MENU mode."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.MENU)
        assert sm.mode == PlayerMode.MENU

    def test_previous_mode_initially_none(self):
        """Previous mode should be None on initialization."""
        sm = PlayerStateMachine()
        assert sm.previous_mode is None


class TestPairingToPlaybackTransition:
    """Tests for PAIRING -> PLAYBACK transition (on CMS approval)."""

    def test_pairing_to_playback_succeeds(self):
        """Transition from PAIRING to PLAYBACK should succeed."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        result = sm.to_playback()

        assert result is True
        assert sm.mode == PlayerMode.PLAYBACK
        assert sm.previous_mode == PlayerMode.PAIRING

    def test_transition_to_method(self):
        """transition_to method should work for PAIRING -> PLAYBACK."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        result = sm.transition_to(PlayerMode.PLAYBACK)

        assert result is True
        assert sm.mode == PlayerMode.PLAYBACK

    def test_can_transition_to_playback_from_pairing(self):
        """can_transition_to should return True for PAIRING -> PLAYBACK."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        assert sm.can_transition_to(PlayerMode.PLAYBACK) is True


class TestPlaybackToMenuTransition:
    """Tests for PLAYBACK -> MENU transition (on user input)."""

    def test_playback_to_menu_succeeds(self):
        """Transition from PLAYBACK to MENU should succeed."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)

        result = sm.to_menu()

        assert result is True
        assert sm.mode == PlayerMode.MENU
        assert sm.previous_mode == PlayerMode.PLAYBACK

    def test_can_transition_to_menu_from_playback(self):
        """can_transition_to should return True for PLAYBACK -> MENU."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)

        assert sm.can_transition_to(PlayerMode.MENU) is True


class TestMenuToPlaybackTransition:
    """Tests for MENU -> PLAYBACK transition (on menu dismiss)."""

    def test_menu_to_playback_succeeds(self):
        """Transition from MENU to PLAYBACK should succeed."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        sm.to_menu()  # First go to menu

        result = sm.to_playback()

        assert result is True
        assert sm.mode == PlayerMode.PLAYBACK
        assert sm.previous_mode == PlayerMode.MENU

    def test_toggle_menu_from_menu_returns_to_playback(self):
        """toggle_menu from MENU should return to PLAYBACK."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        sm.to_menu()

        sm.toggle_menu()

        assert sm.mode == PlayerMode.PLAYBACK


class TestInvalidTransitions:
    """Tests for invalid state transitions."""

    def test_pairing_to_menu_fails(self):
        """Transition from PAIRING to MENU should fail (must go through playback)."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        with pytest.raises(StateTransitionError):
            sm.to_menu()

    def test_cannot_transition_to_menu_from_pairing(self):
        """can_transition_to should return False for PAIRING -> MENU."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        assert sm.can_transition_to(PlayerMode.MENU) is False

    def test_toggle_menu_from_pairing_fails(self):
        """toggle_menu from PAIRING should fail."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        with pytest.raises(StateTransitionError):
            sm.toggle_menu()


class TestRepairTransitions:
    """Tests for re-pair transitions (PLAYBACK/MENU -> PAIRING)."""

    def test_playback_to_pairing_succeeds(self):
        """Transition from PLAYBACK to PAIRING (re-pair) should succeed."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)

        result = sm.to_pairing()

        assert result is True
        assert sm.mode == PlayerMode.PAIRING

    def test_menu_to_pairing_succeeds(self):
        """Transition from MENU to PAIRING (re-pair from menu) should succeed."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        sm.to_menu()

        result = sm.to_pairing()

        assert result is True
        assert sm.mode == PlayerMode.PAIRING


class TestSameModeTransition:
    """Tests for transitioning to the same mode."""

    def test_pairing_to_pairing_returns_false(self):
        """Transitioning to same mode should return False (no change)."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        result = sm.to_pairing()

        assert result is False
        assert sm.mode == PlayerMode.PAIRING

    def test_playback_to_playback_returns_false(self):
        """Transitioning to same mode should return False (no change)."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)

        result = sm.to_playback()

        assert result is False


class TestModeCallbacks:
    """Tests for mode change callbacks."""

    def test_callback_called_on_transition(self):
        """Callback should be called when mode changes."""
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
        """Callback should NOT be called when staying in same mode."""
        callback = MagicMock()
        sm = PlayerStateMachine(
            initial_mode=PlayerMode.PAIRING,
            on_mode_changed=callback
        )

        sm.to_pairing()

        callback.assert_not_called()

    def test_multiple_transitions_callback_order(self):
        """Callback should be called in order for multiple transitions."""
        callback = MagicMock()
        sm = PlayerStateMachine(
            initial_mode=PlayerMode.PAIRING,
            on_mode_changed=callback
        )

        sm.to_playback()
        sm.to_menu()
        sm.to_playback()

        assert callback.call_count == 3
        callback.assert_has_calls([
            call(sm, PlayerMode.PAIRING, PlayerMode.PLAYBACK),
            call(sm, PlayerMode.PLAYBACK, PlayerMode.MENU),
            call(sm, PlayerMode.MENU, PlayerMode.PLAYBACK),
        ])


class TestPropertyHelpers:
    """Tests for is_pairing, is_playback, is_menu property helpers."""

    def test_is_pairing_true_in_pairing_mode(self):
        """is_pairing should be True in PAIRING mode."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        assert sm.is_pairing is True
        assert sm.is_playback is False
        assert sm.is_menu is False

    def test_is_playback_true_in_playback_mode(self):
        """is_playback should be True in PLAYBACK mode."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)

        assert sm.is_pairing is False
        assert sm.is_playback is True
        assert sm.is_menu is False

    def test_is_menu_true_in_menu_mode(self):
        """is_menu should be True in MENU mode."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.MENU)

        assert sm.is_pairing is False
        assert sm.is_playback is False
        assert sm.is_menu is True


class TestStateInfo:
    """Tests for get_state_info method."""

    def test_state_info_initial(self):
        """get_state_info should return correct data for initial state."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        info = sm.get_state_info()

        assert info['mode'] == 'pairing'
        assert info['mode_name'] == 'PAIRING'
        assert info['previous_mode'] is None
        assert info['previous_mode_name'] is None

    def test_state_info_after_transition(self):
        """get_state_info should include previous mode after transition."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)
        sm.to_playback()

        info = sm.get_state_info()

        assert info['mode'] == 'playback'
        assert info['mode_name'] == 'PLAYBACK'
        assert info['previous_mode'] == 'pairing'
        assert info['previous_mode_name'] == 'PAIRING'


class TestStringRepresentation:
    """Tests for string representation."""

    def test_repr_pairing(self):
        """__repr__ should show current mode."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        assert repr(sm) == "PlayerStateMachine(mode=PAIRING)"

    def test_repr_playback(self):
        """__repr__ should update after mode change."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)

        assert repr(sm) == "PlayerStateMachine(mode=PLAYBACK)"


class TestToggleMenu:
    """Tests for toggle_menu method."""

    def test_toggle_menu_shows_menu_from_playback(self):
        """toggle_menu from PLAYBACK should show MENU."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)

        result = sm.toggle_menu()

        assert result is True
        assert sm.mode == PlayerMode.MENU

    def test_toggle_menu_hides_menu_from_menu(self):
        """toggle_menu from MENU should return to PLAYBACK."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        sm.to_menu()

        result = sm.toggle_menu()

        assert result is True
        assert sm.mode == PlayerMode.PLAYBACK

    def test_toggle_menu_from_pairing_raises(self):
        """toggle_menu from PAIRING should raise error."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        with pytest.raises(StateTransitionError) as exc_info:
            sm.toggle_menu()

        assert "Cannot toggle menu from PAIRING mode" in str(exc_info.value)


class TestValidTransitionsTable:
    """Tests to verify the valid transitions table."""

    def test_pairing_valid_transitions(self):
        """PAIRING should only allow transition to PLAYBACK."""
        valid = PlayerStateMachine.VALID_TRANSITIONS[PlayerMode.PAIRING]

        assert PlayerMode.PLAYBACK in valid
        assert PlayerMode.MENU not in valid
        assert PlayerMode.PAIRING not in valid

    def test_playback_valid_transitions(self):
        """PLAYBACK should allow transitions to MENU and PAIRING."""
        valid = PlayerStateMachine.VALID_TRANSITIONS[PlayerMode.PLAYBACK]

        assert PlayerMode.MENU in valid
        assert PlayerMode.PAIRING in valid
        assert PlayerMode.PLAYBACK not in valid

    def test_menu_valid_transitions(self):
        """MENU should allow transitions to PLAYBACK and PAIRING."""
        valid = PlayerStateMachine.VALID_TRANSITIONS[PlayerMode.MENU]

        assert PlayerMode.PLAYBACK in valid
        assert PlayerMode.PAIRING in valid
        assert PlayerMode.MENU not in valid


class TestFullStateFlow:
    """Integration tests for full state flows."""

    def test_full_pairing_to_playback_to_menu_flow(self):
        """Test complete flow: PAIRING -> PLAYBACK -> MENU -> PLAYBACK."""
        callback = MagicMock()
        sm = PlayerStateMachine(
            initial_mode=PlayerMode.PAIRING,
            on_mode_changed=callback
        )

        # Start in PAIRING
        assert sm.is_pairing

        # CMS approves - transition to PLAYBACK
        sm.to_playback()
        assert sm.is_playback
        assert sm.previous_mode == PlayerMode.PAIRING

        # User presses Escape - show MENU
        sm.to_menu()
        assert sm.is_menu
        assert sm.previous_mode == PlayerMode.PLAYBACK

        # User dismisses menu - back to PLAYBACK
        sm.to_playback()
        assert sm.is_playback
        assert sm.previous_mode == PlayerMode.MENU

        # Verify callbacks
        assert callback.call_count == 3

    def test_repair_flow_from_playback(self):
        """Test re-pair flow: PAIRING -> PLAYBACK -> PAIRING."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        # Initially paired
        sm.to_playback()
        assert sm.is_playback

        # User requests re-pair
        sm.to_pairing()
        assert sm.is_pairing
        assert sm.previous_mode == PlayerMode.PLAYBACK

    def test_repair_flow_from_menu(self):
        """Test re-pair from menu: PLAYBACK -> MENU -> PAIRING."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)

        # User opens menu
        sm.to_menu()
        assert sm.is_menu

        # User selects "Re-pair Device"
        sm.to_pairing()
        assert sm.is_pairing
        assert sm.previous_mode == PlayerMode.MENU


class TestThreadSafety:
    """Tests for thread-safe state transitions."""

    def test_concurrent_transitions_no_corruption(self):
        """Concurrent transitions should not corrupt state."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        errors = []

        def toggle_many_times():
            for _ in range(50):
                try:
                    sm.toggle_menu()
                except StateTransitionError:
                    # Expected if we're not in a valid state for toggle
                    pass
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=toggle_many_times)
            for _ in range(4)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No unexpected errors
        assert len(errors) == 0
        # State should be valid
        assert sm.mode in (PlayerMode.MENU, PlayerMode.PLAYBACK)

    def test_concurrent_reads_safe(self):
        """Concurrent reads should be safe."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        results = []

        def read_state():
            for _ in range(100):
                results.append(sm.mode)
                results.append(sm.is_playback)
                results.append(sm.is_menu)

        threads = [
            threading.Thread(target=read_state)
            for _ in range(4)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All reads should have completed without error
        assert len(results) == 4 * 100 * 3


class TestGlobalStateMachineInstance:
    """Tests for the global state machine singleton."""

    def test_get_player_state_machine_returns_instance(self):
        """get_player_state_machine should return an instance."""
        # Reset global instance
        import src.player.state_machine as sm_module
        original = sm_module._global_state_machine
        sm_module._global_state_machine = None

        try:
            sm = get_player_state_machine(initial_mode=PlayerMode.PLAYBACK)

            assert sm is not None
            assert isinstance(sm, PlayerStateMachine)
            assert sm.mode == PlayerMode.PLAYBACK
        finally:
            sm_module._global_state_machine = original

    def test_get_player_state_machine_singleton(self):
        """get_player_state_machine should return same instance."""
        import src.player.state_machine as sm_module
        original = sm_module._global_state_machine
        sm_module._global_state_machine = None

        try:
            sm1 = get_player_state_machine(initial_mode=PlayerMode.PAIRING)
            sm2 = get_player_state_machine(initial_mode=PlayerMode.PLAYBACK)

            # Should be same instance
            assert sm1 is sm2
            # Initial mode from first call should be used
            assert sm1.mode == PlayerMode.PAIRING
        finally:
            sm_module._global_state_machine = original
