"""
Playback controller for Jetson Media Player.
Manages video playback state and content switching.
"""

from typing import Optional, Callable
from enum import Enum
from dataclasses import dataclass
import time
from src.playback_service.playlist import Playlist, MediaItem
from src.playback_service.content_manager import ContentManager
from src.common.logger import setup_logger

logger = setup_logger(__name__)


class PlaybackState(Enum):
    """Playback states."""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    SWITCHING = "switching"


@dataclass
class PlaybackStatus:
    """Current playback status."""
    state: PlaybackState
    current_item: Optional[MediaItem]
    position: float
    trigger: Optional[str]


class PlaybackController:
    """Controls video playback with trigger-based content switching."""
    
    def __init__(
        self,
        content_manager: ContentManager,
        playlist: Playlist,
        on_content_change: Optional[Callable] = None
    ):
        """Initialize playback controller."""
        self.content_manager = content_manager
        self.playlist = playlist
        self.on_content_change = on_content_change
        
        self.state = PlaybackState.STOPPED
        self.current_item: Optional[MediaItem] = None
        self.current_trigger: Optional[str] = None
        self.position = 0.0
        self.start_time = 0.0
        
        logger.info("Playback controller initialized")
    
    def start(self) -> bool:
        """Start playback with default content."""
        if self.state == PlaybackState.PLAYING:
            logger.warning("Already playing")
            return False
        
        item = self.playlist.get_default_item()
        if not item:
            logger.error("No default item in playlist")
            return False
        
        return self._play_item(item, trigger="default")
    
    def handle_trigger(self, trigger: str) -> bool:
        """Handle a trigger event (face detected with age estimate)."""
        logger.info(f"Received trigger: {trigger}")
        
        target_item = self.playlist.get_item_for_trigger(trigger)
        
        if not target_item:
            logger.warning(f"No content found for trigger: {trigger}")
            return False
        
        if self.current_item and self.current_item.id == target_item.id:
            logger.debug(f"Already playing content for trigger: {trigger}")
            return False
        
        logger.info(f"Switching content: {trigger} -> {target_item.filename}")
        return self._play_item(target_item, trigger=trigger)
    
    def _play_item(self, item: MediaItem, trigger: Optional[str] = None) -> bool:
        """Internal: Play a specific media item."""
        content_path = self.content_manager.get_content_path(item.id)
        if not content_path:
            content_path = item.path
            logger.warning(f"Content not in cache, using: {content_path}")
        
        self.state = PlaybackState.SWITCHING
        self.current_item = item
        self.current_trigger = trigger
        self.position = 0.0
        self.start_time = time.time()
        
        logger.info(f"Playing: {item.filename} (trigger: {trigger})")
        
        if self.on_content_change:
            self.on_content_change(item, trigger)
        
        self.state = PlaybackState.PLAYING
        
        return True
    
    def pause(self) -> bool:
        """Pause playback."""
        if self.state != PlaybackState.PLAYING:
            return False
        
        self.state = PlaybackState.PAUSED
        logger.info("Playback paused")
        return True
    
    def resume(self) -> bool:
        """Resume playback."""
        if self.state != PlaybackState.PAUSED:
            return False
        
        self.state = PlaybackState.PLAYING
        self.start_time = time.time() - self.position
        logger.info("Playback resumed")
        return True
    
    def stop(self) -> bool:
        """Stop playback."""
        if self.state == PlaybackState.STOPPED:
            return False
        
        self.state = PlaybackState.STOPPED
        self.current_item = None
        self.position = 0.0
        logger.info("Playback stopped")
        return True
    
    def get_status(self) -> PlaybackStatus:
        """Get current playback status."""
        if self.state == PlaybackState.PLAYING:
            self.position = time.time() - self.start_time
        
        return PlaybackStatus(
            state=self.state,
            current_item=self.current_item,
            position=self.position,
            trigger=self.current_trigger
        )
    
    def __repr__(self) -> str:
        """String representation."""
        return f"PlaybackController(state={self.state.value}, item={self.current_item.filename if self.current_item else 'None'})"
