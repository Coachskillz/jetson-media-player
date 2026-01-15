"""
SkillzPlayer - Main player orchestrator for Jetson Orin Nano Media Player.
Coordinates all components: GStreamer playback, playlist management,
trigger handling, hub sync, and heartbeat reporting.
"""

import signal
import sys
import time
import threading
from typing import Any, Dict, Optional

from .config import PlayerConfig, get_player_config
from .gstreamer_player import GStreamerPlayer, PlayerState
from .playlist_manager import PlaylistManager, get_playlist_manager
from .trigger_listener import TriggerListener, get_trigger_listener
from .sync_service import SyncService, get_sync_service
from .heartbeat import HeartbeatReporter

from src.common.logger import setup_logger

logger = setup_logger(__name__)


class SkillzPlayer:
    """
    Main player orchestrator that:
    1. Loads configuration
    2. Initializes all components
    3. Starts playback IMMEDIATELY from cached content
    4. Runs background services (sync, heartbeat, trigger listener)
    5. Handles coordinated shutdown
    """

    def __init__(
        self,
        config_dir: Optional[str] = None,
        media_dir: Optional[str] = None,
        sync_interval: int = 300,
        heartbeat_interval: int = 60
    ):
        """
        Initialize the SkillzPlayer orchestrator.

        Args:
            config_dir: Path to config directory (uses default if None)
            media_dir: Path to media files directory (uses default if None)
            sync_interval: Seconds between hub sync attempts (default 300 = 5 min)
            heartbeat_interval: Seconds between heartbeats (default 60 = 1 min)
        """
        self._config_dir = config_dir
        self._media_dir = media_dir
        self._sync_interval = sync_interval
        self._heartbeat_interval = heartbeat_interval

        # Component state
        self._running = False
        self._started = False

        # Components (initialized in start())
        self._config: Optional[PlayerConfig] = None
        self._gst_player: Optional[GStreamerPlayer] = None
        self._playlist_manager: Optional[PlaylistManager] = None
        self._trigger_listener: Optional[TriggerListener] = None
        self._sync_service: Optional[SyncService] = None
        self._heartbeat: Optional[HeartbeatReporter] = None

        # Main loop event
        self._stop_event = threading.Event()

        logger.info("SkillzPlayer initialized")

    def _load_config(self) -> bool:
        """
        Load configuration from disk.

        Returns:
            True if config loaded successfully, False otherwise
        """
        try:
            self._config = get_player_config(self._config_dir)

            # Verify essential config
            if not self._config.screen_id:
                logger.warning("No screen_id configured - device may need registration")

            logger.info(
                "Configuration loaded - screen_id: %s, hub_url: %s",
                self._config.screen_id or "(not set)",
                self._config.hub_url
            )
            return True

        except Exception as e:
            logger.error("Failed to load configuration: %s", e)
            return False

    def _initialize_playlist_manager(self) -> bool:
        """
        Initialize and load playlist manager.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            self._playlist_manager = get_playlist_manager(
                config=self._config,
                media_dir=self._media_dir,
                on_playlist_changed=self._on_playlist_changed
            )

            # Load playlists from config
            if not self._playlist_manager.load_from_config():
                logger.warning("Failed to load playlists from config")
                # Continue anyway - may have empty playlist

            logger.info(
                "Playlist manager initialized - %d default items, %d triggered playlists",
                self._playlist_manager.default_playlist_length,
                len(self._playlist_manager._triggered_playlists)
            )
            return True

        except Exception as e:
            logger.error("Failed to initialize playlist manager: %s", e)
            return False

    def _initialize_gstreamer_player(self) -> bool:
        """
        Initialize GStreamer player with callbacks.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            self._gst_player = GStreamerPlayer(
                media_dir=self._media_dir,
                on_about_to_finish=self._get_next_uri,
                on_error=self._on_playback_error,
                on_eos=self._on_end_of_stream
            )

            if not self._gst_player.initialize():
                logger.error("Failed to initialize GStreamer player")
                return False

            logger.info("GStreamer player initialized")
            return True

        except Exception as e:
            logger.error("Failed to initialize GStreamer player: %s", e)
            return False

    def _initialize_trigger_listener(self) -> bool:
        """
        Initialize ZeroMQ trigger listener.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            self._trigger_listener = get_trigger_listener(
                on_trigger=self._on_trigger_received
            )

            logger.info("Trigger listener initialized")
            return True

        except Exception as e:
            logger.error("Failed to initialize trigger listener: %s", e)
            return False

    def _initialize_sync_service(self) -> bool:
        """
        Initialize hub sync service.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            self._sync_service = get_sync_service(
                config=self._config,
                media_dir=self._media_dir,
                sync_interval=self._sync_interval,
                on_sync_complete=self._on_sync_complete,
                on_content_updated=self._on_content_updated
            )

            logger.info("Sync service initialized")
            return True

        except Exception as e:
            logger.error("Failed to initialize sync service: %s", e)
            return False

    def _initialize_heartbeat(self) -> bool:
        """
        Initialize heartbeat reporter.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            self._heartbeat = HeartbeatReporter(
                hub_url=self._config.hub_url,
                screen_id=self._config.screen_id,
                interval=self._heartbeat_interval
            )

            # Set status callback
            self._heartbeat.set_status_callback(self._get_playback_status)

            logger.info("Heartbeat reporter initialized")
            return True

        except Exception as e:
            logger.error("Failed to initialize heartbeat reporter: %s", e)
            return False

    def _start_playback(self) -> bool:
        """
        Start video playback from the default playlist.

        Returns:
            True if playback started, False otherwise
        """
        if self._playlist_manager.default_playlist_length == 0:
            logger.warning("No playlist items available - nothing to play")
            return False

        # Get first URI
        first_uri = self._playlist_manager.get_first_uri()

        if not first_uri:
            logger.error("Could not get first URI from playlist")
            return False

        logger.info("Starting playback with: %s", first_uri)

        if not self._gst_player.play(first_uri):
            logger.error("Failed to start playback")
            return False

        logger.info("Playback started successfully")
        return True

    def _start_background_services(self) -> None:
        """Start all background services."""
        # Start trigger listener
        if self._trigger_listener:
            self._trigger_listener.start()
            logger.info("Trigger listener started")

        # Start sync service
        if self._sync_service:
            self._sync_service.start()
            logger.info("Sync service started")

        # Start heartbeat reporter
        if self._heartbeat:
            self._heartbeat.start()
            logger.info("Heartbeat reporter started")

    def _stop_background_services(self) -> None:
        """Stop all background services."""
        if self._heartbeat:
            self._heartbeat.stop()

        if self._sync_service:
            self._sync_service.stop()

        if self._trigger_listener:
            self._trigger_listener.stop()

        logger.info("Background services stopped")

    # -------------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------------

    def _get_next_uri(self) -> Optional[str]:
        """
        Callback for GStreamer to get next URI for gapless playback.
        Called ~2 seconds before current video ends.

        Returns:
            Next video URI or None
        """
        if self._playlist_manager:
            return self._playlist_manager.get_next_uri()
        return None

    def _on_playback_error(self, error_msg: str) -> None:
        """
        Callback for GStreamer playback errors.

        Args:
            error_msg: Error message from GStreamer
        """
        logger.error("Playback error: %s", error_msg)

        # Try to recover by playing next item
        if self._playlist_manager and self._gst_player:
            next_uri = self._playlist_manager.get_next_uri()
            if next_uri:
                logger.info("Attempting recovery - playing next: %s", next_uri)
                self._gst_player.play(next_uri)

    def _on_end_of_stream(self) -> None:
        """Callback for end of stream when no next URI was queued."""
        logger.debug("End of stream received")

        # This should rarely happen with gapless playback
        # Try to continue with next item
        if self._playlist_manager and self._gst_player:
            next_uri = self._playlist_manager.get_next_uri()
            if next_uri:
                logger.info("Continuing playback with: %s", next_uri)
                self._gst_player.play(next_uri)

    def _on_trigger_received(self, trigger_data: Dict[str, Any]) -> None:
        """
        Callback for trigger events from ZeroMQ.

        Args:
            trigger_data: Trigger event data
        """
        logger.debug("Trigger received: %s", trigger_data.get('type', 'unknown'))

        if self._playlist_manager:
            # Playlist manager handles matching and activation
            activated = self._playlist_manager.handle_trigger(trigger_data)

            if activated:
                logger.info("Triggered playlist activated")
                # Note: GStreamer's gapless mechanism will pick up
                # the new playlist items automatically

    def _on_playlist_changed(self, manager: PlaylistManager) -> None:
        """
        Callback when playlist mode changes.

        Args:
            manager: The playlist manager
        """
        mode = manager.mode.value
        logger.info("Playlist mode changed to: %s", mode)

    def _on_sync_complete(self, success: bool) -> None:
        """
        Callback after sync attempt.

        Args:
            success: Whether sync was successful
        """
        if success:
            logger.debug("Sync completed successfully")
        else:
            logger.debug("Sync failed - will retry")

    def _on_content_updated(self) -> None:
        """Callback when new content has been downloaded."""
        logger.info("New content downloaded - reloading playlists")

        if self._playlist_manager:
            self._playlist_manager.reload()

    def _get_playback_status(self) -> Dict[str, Any]:
        """
        Get current playback status for heartbeat.

        Returns:
            Dictionary with status and current_content
        """
        status = "unknown"
        current_content = ""

        if self._gst_player:
            player_state = self._gst_player.state
            if player_state == PlayerState.PLAYING:
                status = "playing"
            elif player_state == PlayerState.PAUSED:
                status = "paused"
            elif player_state == PlayerState.STOPPED:
                status = "stopped"
            elif player_state == PlayerState.ERROR:
                status = "error"

        if self._playlist_manager:
            current_content = self._playlist_manager.current_filename or ""

        return {
            "status": status,
            "current_content": current_content
        }

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def start(self) -> bool:
        """
        Start the player.

        Startup flow:
        1. Load configuration
        2. Initialize components
        3. Start playback IMMEDIATELY from cached content
        4. Start background services (sync, heartbeat, trigger listener)

        Returns:
            True if startup successful, False otherwise
        """
        if self._running:
            logger.warning("Player already running")
            return True

        logger.info("=" * 60)
        logger.info("Starting SkillzPlayer")
        logger.info("=" * 60)

        # Step 1: Load configuration
        if not self._load_config():
            logger.error("Failed to load config - cannot start")
            return False

        # Step 2: Initialize components
        if not self._initialize_playlist_manager():
            logger.error("Failed to initialize playlist manager")
            return False

        if not self._initialize_gstreamer_player():
            logger.error("Failed to initialize GStreamer player")
            return False

        if not self._initialize_trigger_listener():
            logger.warning("Failed to initialize trigger listener - continuing without")

        if not self._initialize_sync_service():
            logger.warning("Failed to initialize sync service - continuing without")

        if not self._initialize_heartbeat():
            logger.warning("Failed to initialize heartbeat - continuing without")

        # Step 3: Start playback IMMEDIATELY (before background services)
        playback_ok = self._start_playback()

        if not playback_ok:
            logger.warning("No content to play - waiting for sync")

        # Step 4: Start background services
        self._start_background_services()

        self._running = True
        self._started = True

        logger.info("SkillzPlayer started successfully")
        return True

    def stop(self) -> None:
        """Stop the player and all services."""
        if not self._running:
            return

        logger.info("Stopping SkillzPlayer...")

        self._running = False
        self._stop_event.set()

        # Stop background services first
        self._stop_background_services()

        # Stop playback
        if self._gst_player:
            self._gst_player.cleanup()

        logger.info("SkillzPlayer stopped")

    def run(self) -> None:
        """
        Run the player (blocking).

        This method blocks until stop() is called or a signal is received.
        Use this for running as a systemd service or main application.
        """
        # Set up signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        if not self.start():
            logger.error("Failed to start player")
            sys.exit(1)

        logger.info("Player running - press Ctrl+C to stop")

        # Wait for stop signal
        try:
            while self._running:
                # Use event wait for responsive shutdown
                if self._stop_event.wait(timeout=1.0):
                    break
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")

        self.stop()

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle system signals for graceful shutdown."""
        sig_name = signal.Signals(signum).name
        logger.info("Received signal: %s", sig_name)
        self._running = False
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        """Check if player is running."""
        return self._running

    @property
    def is_playing(self) -> bool:
        """Check if player is currently playing video."""
        if self._gst_player:
            return self._gst_player.is_playing
        return False

    def get_status(self) -> Dict[str, Any]:
        """
        Get comprehensive player status.

        Returns:
            Dictionary with status from all components
        """
        status = {
            "running": self._running,
            "playback": self._get_playback_status(),
            "playlist": None,
            "sync": None,
            "trigger_listener": None,
            "heartbeat": None
        }

        if self._playlist_manager:
            status["playlist"] = self._playlist_manager.get_playlist_info()

        if self._sync_service:
            status["sync"] = self._sync_service.get_status()

        if self._trigger_listener:
            status["trigger_listener"] = self._trigger_listener.get_status()

        if self._heartbeat:
            status["heartbeat"] = self._heartbeat.get_last_heartbeat_info()

        return status


# Global player instance
_global_player: Optional[SkillzPlayer] = None


def get_skillz_player(
    config_dir: Optional[str] = None,
    media_dir: Optional[str] = None,
    sync_interval: int = 300,
    heartbeat_interval: int = 60
) -> SkillzPlayer:
    """
    Get the global SkillzPlayer instance.

    Args:
        config_dir: Path to config directory (only used on first call)
        media_dir: Path to media files directory (only used on first call)
        sync_interval: Seconds between sync attempts (only used on first call)
        heartbeat_interval: Seconds between heartbeats (only used on first call)

    Returns:
        SkillzPlayer instance
    """
    global _global_player

    if _global_player is None:
        _global_player = SkillzPlayer(
            config_dir=config_dir,
            media_dir=media_dir,
            sync_interval=sync_interval,
            heartbeat_interval=heartbeat_interval
        )

    return _global_player


def main():
    """Main entry point for running the player."""
    logger.info("Jetson Media Player starting...")

    player = get_skillz_player()
    player.run()


if __name__ == "__main__":
    main()
