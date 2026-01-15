"""
Playlist management for Jetson Media Player.
Handles trigger rule matching, position tracking, and gapless URI provision.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import PlayerConfig, get_player_config


logger = logging.getLogger(__name__)


class PlaylistMode(Enum):
    """Represents the current playlist mode."""
    DEFAULT = "default"
    TRIGGERED = "triggered"


@dataclass
class PlaylistItem:
    """Represents a single media item in a playlist."""

    content_id: str
    filename: str
    duration: float  # seconds
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_uri(self, media_dir: Path) -> str:
        """
        Get the file URI for this item.

        Args:
            media_dir: Path to the media directory

        Returns:
            File URI string
        """
        file_path = media_dir / self.filename
        return f"file://{file_path}"

    def file_exists(self, media_dir: Path) -> bool:
        """
        Check if the media file exists.

        Args:
            media_dir: Path to the media directory

        Returns:
            True if file exists, False otherwise
        """
        file_path = media_dir / self.filename
        return file_path.exists()


@dataclass
class TriggerRule:
    """Represents a trigger matching rule."""

    rule_type: str  # "demographic" or "loyalty"
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    gender: Optional[str] = None  # "male", "female", "any", or None
    member_id: Optional[str] = None  # For loyalty triggers

    def matches(self, trigger_data: Dict[str, Any]) -> bool:
        """
        Check if trigger data matches this rule.

        Args:
            trigger_data: Dictionary with trigger information
                         (type, age, gender, confidence, member_id, etc.)

        Returns:
            True if trigger matches this rule
        """
        trigger_type = trigger_data.get('type', '')

        if trigger_type != self.rule_type:
            return False

        if self.rule_type == 'demographic':
            return self._matches_demographic(trigger_data)
        elif self.rule_type == 'loyalty':
            return self._matches_loyalty(trigger_data)

        return False

    def _matches_demographic(self, trigger_data: Dict[str, Any]) -> bool:
        """Check if demographic trigger matches."""
        age = trigger_data.get('age')
        gender = trigger_data.get('gender')

        # Check age range
        if age is not None:
            if self.age_min is not None and age < self.age_min:
                return False
            if self.age_max is not None and age > self.age_max:
                return False

        # Check gender
        if self.gender is not None and self.gender != 'any':
            if gender is not None and gender != self.gender:
                return False

        return True

    def _matches_loyalty(self, trigger_data: Dict[str, Any]) -> bool:
        """Check if loyalty trigger matches."""
        # If member_id rule is None, any loyalty member matches
        if self.member_id is None:
            return trigger_data.get('member_id') is not None

        # Otherwise, check for specific member
        return trigger_data.get('member_id') == self.member_id


@dataclass
class TriggeredPlaylist:
    """Represents a triggered playlist with its matching rule."""

    playlist_id: str
    rule: TriggerRule
    items: List[PlaylistItem]

    def matches_trigger(self, trigger_data: Dict[str, Any]) -> bool:
        """
        Check if this playlist matches the given trigger.

        Args:
            trigger_data: Trigger event data

        Returns:
            True if trigger matches this playlist's rule
        """
        return self.rule.matches(trigger_data)


class PlaylistManager:
    """
    Manages playlists with trigger-based selection for the media player.
    Handles position tracking and gapless URI provision.
    """

    # Default media directory on Jetson devices
    DEFAULT_MEDIA_DIR = "/home/skillz/media"

    def __init__(
        self,
        config: Optional[PlayerConfig] = None,
        media_dir: Optional[str] = None,
        on_playlist_changed: Optional[Callable[['PlaylistManager'], None]] = None
    ):
        """
        Initialize the playlist manager.

        Args:
            config: PlayerConfig instance (uses global if None)
            media_dir: Path to media files directory
            on_playlist_changed: Callback when playlist changes
        """
        self._config = config or get_player_config()
        self.media_dir = Path(media_dir) if media_dir else Path(self.DEFAULT_MEDIA_DIR)
        self._on_playlist_changed = on_playlist_changed

        # Default playlist items and position
        self._default_items: List[PlaylistItem] = []
        self._default_index: int = 0

        # Triggered playlists
        self._triggered_playlists: List[TriggeredPlaylist] = []

        # Current triggered playlist state
        self._current_triggered: Optional[TriggeredPlaylist] = None
        self._triggered_index: int = 0

        # Current mode
        self._mode = PlaylistMode.DEFAULT

        # Track currently playing item
        self._current_item: Optional[PlaylistItem] = None

        logger.info("PlaylistManager initialized with media_dir: %s", self.media_dir)

    def load_from_config(self) -> bool:
        """
        Load playlists from the player configuration.

        Returns:
            True if playlists loaded successfully, False otherwise
        """
        try:
            # Load default playlist
            default_playlist = self._config.default_playlist
            self._default_items = self._parse_playlist_items(
                default_playlist.get('items', [])
            )
            self._default_index = 0

            # Load triggered playlists
            triggered_configs = self._config.triggered_playlists
            self._triggered_playlists = self._parse_triggered_playlists(
                triggered_configs
            )

            logger.info(
                "Loaded %d default items and %d triggered playlists",
                len(self._default_items),
                len(self._triggered_playlists)
            )

            return True

        except Exception as e:
            logger.error("Failed to load playlists from config: %s", e)
            return False

    def _parse_playlist_items(
        self,
        items_data: List[Dict[str, Any]]
    ) -> List[PlaylistItem]:
        """
        Parse playlist items from config data.

        Args:
            items_data: List of item dictionaries

        Returns:
            List of PlaylistItem objects
        """
        items = []
        for item_data in items_data:
            item = PlaylistItem(
                content_id=item_data.get('content_id', ''),
                filename=item_data.get('filename', ''),
                duration=float(item_data.get('duration', 0)),
                metadata=item_data.get('metadata', {})
            )
            items.append(item)
        return items

    def _parse_triggered_playlists(
        self,
        playlists_data: List[Dict[str, Any]]
    ) -> List[TriggeredPlaylist]:
        """
        Parse triggered playlists from config data.

        Args:
            playlists_data: List of triggered playlist dictionaries

        Returns:
            List of TriggeredPlaylist objects
        """
        playlists = []
        for playlist_data in playlists_data:
            # Parse the rule
            rule_data = playlist_data.get('rule', {})
            rule = TriggerRule(
                rule_type=rule_data.get('type', ''),
                age_min=rule_data.get('age_min'),
                age_max=rule_data.get('age_max'),
                gender=rule_data.get('gender'),
                member_id=rule_data.get('member_id')
            )

            # Parse items
            items = self._parse_playlist_items(
                playlist_data.get('items', [])
            )

            playlist = TriggeredPlaylist(
                playlist_id=playlist_data.get('playlist_id', ''),
                rule=rule,
                items=items
            )
            playlists.append(playlist)

        return playlists

    def get_next_uri(self) -> Optional[str]:
        """
        Get the next URI for gapless playback.
        Called by GStreamer player in about-to-finish callback.

        Returns:
            File URI string or None if no more items
        """
        next_item = self._get_next_item()

        if next_item is None:
            logger.warning("No next item available")
            return None

        # Check if file exists
        if not next_item.file_exists(self.media_dir):
            logger.error("Media file not found: %s", next_item.filename)
            # Try to skip to next item
            return self._skip_missing_and_get_next()

        self._current_item = next_item
        uri = next_item.get_uri(self.media_dir)
        logger.debug("Next URI: %s", uri)
        return uri

    def _skip_missing_and_get_next(self) -> Optional[str]:
        """
        Skip missing files and get next available URI.

        Returns:
            Next available URI or None
        """
        max_attempts = self._get_current_playlist_length()

        for _ in range(max_attempts):
            next_item = self._get_next_item()
            if next_item and next_item.file_exists(self.media_dir):
                self._current_item = next_item
                return next_item.get_uri(self.media_dir)

        logger.error("No valid media files found in playlist")
        return None

    def _get_current_playlist_length(self) -> int:
        """Get the length of the current active playlist."""
        if self._mode == PlaylistMode.TRIGGERED and self._current_triggered:
            return len(self._current_triggered.items)
        return len(self._default_items)

    def _get_next_item(self) -> Optional[PlaylistItem]:
        """
        Get the next item from the current playlist.
        Advances the position index.

        Returns:
            Next PlaylistItem or None
        """
        if self._mode == PlaylistMode.TRIGGERED:
            return self._get_next_triggered_item()
        else:
            return self._get_next_default_item()

    def _get_next_default_item(self) -> Optional[PlaylistItem]:
        """
        Get next item from default playlist (circular).

        Returns:
            Next PlaylistItem or None if empty
        """
        if not self._default_items:
            return None

        item = self._default_items[self._default_index]
        self._default_index = (self._default_index + 1) % len(self._default_items)
        return item

    def _get_next_triggered_item(self) -> Optional[PlaylistItem]:
        """
        Get next item from triggered playlist.
        Returns to default mode when triggered playlist ends.

        Returns:
            Next PlaylistItem or None
        """
        if not self._current_triggered or not self._current_triggered.items:
            # No triggered playlist active, fall back to default
            self._switch_to_default()
            return self._get_next_default_item()

        if self._triggered_index >= len(self._current_triggered.items):
            # Triggered playlist ended, return to default
            logger.info(
                "Triggered playlist %s completed, returning to default",
                self._current_triggered.playlist_id
            )
            self._switch_to_default()
            return self._get_next_default_item()

        item = self._current_triggered.items[self._triggered_index]
        self._triggered_index += 1
        return item

    def _switch_to_default(self) -> None:
        """Switch back to default playlist mode."""
        self._mode = PlaylistMode.DEFAULT
        self._current_triggered = None
        self._triggered_index = 0

        if self._on_playlist_changed:
            self._on_playlist_changed(self)

    def handle_trigger(self, trigger_data: Dict[str, Any]) -> bool:
        """
        Handle an incoming trigger event.
        Matches against triggered playlists and switches if a match is found.

        Args:
            trigger_data: Trigger event data (type, age, gender, member_id, etc.)

        Returns:
            True if a matching playlist was activated, False otherwise
        """
        trigger_type = trigger_data.get('type', '')
        logger.debug("Handling trigger: %s", trigger_type)

        # Ignore NCMEC alerts (only log, don't change playlist)
        if trigger_type == 'ncmec_alert':
            logger.warning(
                "NCMEC alert received - case_id: %s",
                trigger_data.get('case_id', 'unknown')
            )
            return False

        # Find matching triggered playlist
        for playlist in self._triggered_playlists:
            if playlist.matches_trigger(trigger_data):
                self._activate_triggered_playlist(playlist, trigger_data)
                return True

        logger.debug("No matching triggered playlist for trigger: %s", trigger_type)
        return False

    def _activate_triggered_playlist(
        self,
        playlist: TriggeredPlaylist,
        trigger_data: Dict[str, Any]
    ) -> None:
        """
        Activate a triggered playlist.

        Args:
            playlist: The triggered playlist to activate
            trigger_data: The trigger event data that caused activation
        """
        logger.info(
            "Activating triggered playlist: %s (trigger: %s)",
            playlist.playlist_id,
            trigger_data.get('type', 'unknown')
        )

        self._mode = PlaylistMode.TRIGGERED
        self._current_triggered = playlist
        self._triggered_index = 0

        if self._on_playlist_changed:
            self._on_playlist_changed(self)

    def get_first_uri(self) -> Optional[str]:
        """
        Get the first URI to start playback.
        Used for initial playback start.

        Returns:
            File URI string or None if playlist is empty
        """
        if not self._default_items:
            logger.warning("Default playlist is empty")
            return None

        item = self._default_items[0]
        self._default_index = 1 % len(self._default_items)

        # Check if file exists
        if not item.file_exists(self.media_dir):
            logger.error("First media file not found: %s", item.filename)
            return self._skip_missing_and_get_next()

        self._current_item = item
        return item.get_uri(self.media_dir)

    @property
    def mode(self) -> PlaylistMode:
        """Get current playlist mode."""
        return self._mode

    @property
    def current_item(self) -> Optional[PlaylistItem]:
        """Get currently playing item."""
        return self._current_item

    @property
    def current_filename(self) -> Optional[str]:
        """Get filename of currently playing item."""
        return self._current_item.filename if self._current_item else None

    @property
    def default_playlist_length(self) -> int:
        """Get number of items in default playlist."""
        return len(self._default_items)

    @property
    def default_position(self) -> int:
        """Get current position in default playlist (0-indexed)."""
        # Return the previous position (what was last played)
        if not self._default_items:
            return 0
        pos = (self._default_index - 1) % len(self._default_items)
        return pos

    @property
    def is_triggered(self) -> bool:
        """Check if currently playing a triggered playlist."""
        return self._mode == PlaylistMode.TRIGGERED

    @property
    def triggered_playlist_id(self) -> Optional[str]:
        """Get ID of currently playing triggered playlist."""
        if self._current_triggered:
            return self._current_triggered.playlist_id
        return None

    def get_playlist_info(self) -> Dict[str, Any]:
        """
        Get information about current playlist state.
        Useful for status reporting.

        Returns:
            Dictionary with playlist information
        """
        return {
            'mode': self._mode.value,
            'default_items': len(self._default_items),
            'default_position': self.default_position,
            'current_filename': self.current_filename,
            'is_triggered': self.is_triggered,
            'triggered_playlist_id': self.triggered_playlist_id,
            'triggered_playlists_count': len(self._triggered_playlists)
        }

    def reload(self) -> bool:
        """
        Reload playlists from config.
        Does not interrupt current playback.

        Returns:
            True if reload successful, False otherwise
        """
        logger.info("Reloading playlists from config")

        # Reload config from disk
        self._config.load_playlist()

        # Re-parse playlists
        return self.load_from_config()

    def set_default_items(self, items: List[PlaylistItem]) -> None:
        """
        Set default playlist items directly (for testing).

        Args:
            items: List of PlaylistItem objects
        """
        self._default_items = items
        self._default_index = 0
        logger.debug("Set %d default playlist items", len(items))

    def set_triggered_playlists(
        self,
        playlists: List[TriggeredPlaylist]
    ) -> None:
        """
        Set triggered playlists directly (for testing).

        Args:
            playlists: List of TriggeredPlaylist objects
        """
        self._triggered_playlists = playlists
        logger.debug("Set %d triggered playlists", len(playlists))

    def reset_position(self) -> None:
        """Reset playlist position to the beginning."""
        self._default_index = 0
        self._triggered_index = 0
        self._current_item = None
        logger.debug("Playlist position reset")

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"PlaylistManager(mode={self._mode.value}, "
            f"default_items={len(self._default_items)}, "
            f"triggered_playlists={len(self._triggered_playlists)})"
        )


# Global playlist manager instance
_global_playlist_manager: Optional[PlaylistManager] = None


def get_playlist_manager(
    config: Optional[PlayerConfig] = None,
    media_dir: Optional[str] = None,
    on_playlist_changed: Optional[Callable[[PlaylistManager], None]] = None
) -> PlaylistManager:
    """
    Get the global playlist manager instance.

    Args:
        config: PlayerConfig instance (only used on first call)
        media_dir: Path to media files directory (only used on first call)
        on_playlist_changed: Callback when playlist changes (only used on first call)

    Returns:
        PlaylistManager instance
    """
    global _global_playlist_manager

    if _global_playlist_manager is None:
        _global_playlist_manager = PlaylistManager(
            config=config,
            media_dir=media_dir,
            on_playlist_changed=on_playlist_changed
        )

    return _global_playlist_manager
