"""
Player State Machine for Jetson Media Player.
Manages player modes: pairing, playback, and menu overlay.
"""

import threading
from enum import Enum
from typing import Callable, Dict, List, Optional

from src.common.logger import setup_logger

logger = setup_logger(__name__)


class PlayerMode(Enum):
    """Represents the current mode of the player."""
    PAIRING = "pairing"      # Showing pairing screen, waiting for CMS approval
    PLAYBACK = "playback"    # Playing media content
    MENU = "menu"            # Showing menu overlay


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class PlayerStateMachine:
    """
    State machine for managing player modes.

    Handles transitions between:
    - PAIRING: Initial mode when device is not paired
    - PLAYBACK: Normal content playback mode
    - MENU: Menu overlay visible (pauses playback)

    Valid transitions:
    - PAIRING -> PLAYBACK (on CMS approval)
    - PLAYBACK -> MENU (on user input: Escape/F1/corner tap)
    - MENU -> PLAYBACK (on menu dismiss)
    - PLAYBACK -> PAIRING (on re-pair request)
    - MENU -> PAIRING (on re-pair from menu)
    """

    # Define valid state transitions
    VALID_TRANSITIONS: Dict[PlayerMode, List[PlayerMode]] = {
        PlayerMode.PAIRING: [PlayerMode.PLAYBACK],
        PlayerMode.PLAYBACK: [PlayerMode.MENU, PlayerMode.PAIRING],
        PlayerMode.MENU: [PlayerMode.PLAYBACK, PlayerMode.PAIRING],
    }

    def __init__(
        self,
        initial_mode: PlayerMode = PlayerMode.PAIRING,
        on_mode_changed: Optional[Callable[['PlayerStateMachine', PlayerMode, PlayerMode], None]] = None
    ):
        """
        Initialize the player state machine.

        Args:
            initial_mode: Starting mode (default: PAIRING)
            on_mode_changed: Callback when mode changes (self, old_mode, new_mode)
        """
        self._mode = initial_mode
        self._previous_mode: Optional[PlayerMode] = None
        self._on_mode_changed = on_mode_changed
        self._lock = threading.Lock()

        logger.info("PlayerStateMachine initialized in %s mode", self._mode.name)

    @property
    def mode(self) -> PlayerMode:
        """Get current player mode."""
        with self._lock:
            return self._mode

    @property
    def previous_mode(self) -> Optional[PlayerMode]:
        """Get previous player mode (before last transition)."""
        with self._lock:
            return self._previous_mode

    def can_transition_to(self, target_mode: PlayerMode) -> bool:
        """
        Check if transition to target mode is valid.

        Args:
            target_mode: Mode to transition to

        Returns:
            True if transition is valid, False otherwise
        """
        with self._lock:
            if self._mode == target_mode:
                return True  # Already in this mode
            return target_mode in self.VALID_TRANSITIONS.get(self._mode, [])

    def transition_to(self, target_mode: PlayerMode) -> bool:
        """
        Attempt to transition to a new mode.

        Args:
            target_mode: Mode to transition to

        Returns:
            True if transition successful, False if already in target mode

        Raises:
            StateTransitionError: If transition is not valid
        """
        with self._lock:
            old_mode = self._mode

            # Already in target mode
            if old_mode == target_mode:
                logger.debug("Already in %s mode", target_mode.name)
                return False

            # Check if transition is valid
            if target_mode not in self.VALID_TRANSITIONS.get(old_mode, []):
                raise StateTransitionError(
                    f"Invalid transition: {old_mode.name} -> {target_mode.name}"
                )

            # Perform transition
            self._previous_mode = old_mode
            self._mode = target_mode

            logger.info(
                "Mode transition: %s -> %s",
                old_mode.name,
                target_mode.name
            )

        # Call callback outside lock to prevent deadlocks
        if self._on_mode_changed:
            try:
                self._on_mode_changed(self, old_mode, target_mode)
            except Exception as e:
                logger.error("Error in mode change callback: %s", e)

        return True

    def to_pairing(self) -> bool:
        """
        Transition to pairing mode.

        Returns:
            True if transition successful, False if already in pairing mode

        Raises:
            StateTransitionError: If transition is not valid from current mode
        """
        return self.transition_to(PlayerMode.PAIRING)

    def to_playback(self) -> bool:
        """
        Transition to playback mode.

        Returns:
            True if transition successful, False if already in playback mode

        Raises:
            StateTransitionError: If transition is not valid from current mode
        """
        return self.transition_to(PlayerMode.PLAYBACK)

    def to_menu(self) -> bool:
        """
        Transition to menu mode.

        Returns:
            True if transition successful, False if already in menu mode

        Raises:
            StateTransitionError: If transition is not valid from current mode
        """
        return self.transition_to(PlayerMode.MENU)

    def toggle_menu(self) -> bool:
        """
        Toggle menu overlay on/off.

        When in PLAYBACK mode, shows menu.
        When in MENU mode, returns to PLAYBACK.

        Returns:
            True if toggle successful

        Raises:
            StateTransitionError: If toggle is not valid from current mode
        """
        with self._lock:
            current = self._mode

        if current == PlayerMode.PLAYBACK:
            return self.to_menu()
        elif current == PlayerMode.MENU:
            return self.to_playback()
        else:
            raise StateTransitionError(
                f"Cannot toggle menu from {current.name} mode"
            )

    @property
    def is_pairing(self) -> bool:
        """Check if currently in pairing mode."""
        return self.mode == PlayerMode.PAIRING

    @property
    def is_playback(self) -> bool:
        """Check if currently in playback mode."""
        return self.mode == PlayerMode.PLAYBACK

    @property
    def is_menu(self) -> bool:
        """Check if currently in menu mode."""
        return self.mode == PlayerMode.MENU

    def get_state_info(self) -> Dict[str, str]:
        """
        Get information about current state.

        Returns:
            Dictionary with mode, previous_mode info
        """
        with self._lock:
            return {
                "mode": self._mode.value,
                "mode_name": self._mode.name,
                "previous_mode": self._previous_mode.value if self._previous_mode else None,
                "previous_mode_name": self._previous_mode.name if self._previous_mode else None,
            }

    def __repr__(self) -> str:
        """String representation."""
        return f"PlayerStateMachine(mode={self.mode.name})"


# Global state machine instance
_global_state_machine: Optional[PlayerStateMachine] = None


def get_player_state_machine(
    initial_mode: PlayerMode = PlayerMode.PAIRING,
    on_mode_changed: Optional[Callable[[PlayerStateMachine, PlayerMode, PlayerMode], None]] = None
) -> PlayerStateMachine:
    """
    Get the global player state machine instance.

    Args:
        initial_mode: Starting mode (only used on first call)
        on_mode_changed: Callback when mode changes (only used on first call)

    Returns:
        PlayerStateMachine instance
    """
    global _global_state_machine

    if _global_state_machine is None:
        _global_state_machine = PlayerStateMachine(
            initial_mode=initial_mode,
            on_mode_changed=on_mode_changed
        )

    return _global_state_machine
