"""
SkillzPlayer - Main player orchestrator for Jetson Orin Nano Media Player.
Coordinates all components: GStreamer playback, playlist management,
trigger handling, hub sync, heartbeat reporting, and kiosk UI.
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
from .state_machine import PlayerStateMachine, PlayerMode, StateTransitionError

from src.common.logger import setup_logger
from src.common.cms_client import CMSClient
from src.common.device_id import get_device_info

logger = setup_logger(__name__)

# Flag to track if GTK is available (may not be on headless systems)
GTK_AVAILABLE = False
try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('GLib', '2.0')
    from gi.repository import Gtk, Gdk, GLib
    from .kiosk_ui import KioskWindow
    from .pairing_screen import PairingScreen
    from .menu_overlay import MenuOverlay
    GTK_AVAILABLE = True
except (ImportError, ValueError) as e:
    logger.warning("GTK not available, running in headless mode: %s", e)


class SkillzPlayer:
    """
    Main player orchestrator that:
    1. Loads configuration
    2. Initializes state machine and kiosk UI
    3. Manages pairing flow when device is not paired
    4. Starts playback when paired (from cached content)
    5. Runs background services (sync, heartbeat, trigger listener)
    6. Provides menu overlay for device management
    7. Handles coordinated shutdown
    """

    def __init__(
        self,
        config_dir: Optional[str] = None,
        media_dir: Optional[str] = None,
        sync_interval: int = 300,
        heartbeat_interval: int = 60,
        headless: bool = False
    ):
        """
        Initialize the SkillzPlayer orchestrator.

        Args:
            config_dir: Path to config directory (uses default if None)
            media_dir: Path to media files directory (uses default if None)
            sync_interval: Seconds between hub sync attempts (default 300 = 5 min)
            heartbeat_interval: Seconds between heartbeats (default 60 = 1 min)
            headless: If True, run without GTK UI (for testing/CLI mode)
        """
        self._config_dir = config_dir
        self._media_dir = media_dir
        self._sync_interval = sync_interval
        self._heartbeat_interval = heartbeat_interval
        self._headless = headless or not GTK_AVAILABLE

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

        # State machine for mode management
        self._state_machine: Optional[PlayerStateMachine] = None

        # Kiosk UI components (only when not headless)
        self._kiosk_window: Optional['KioskWindow'] = None
        self._pairing_screen: Optional['PairingScreen'] = None
        self._menu_overlay: Optional['MenuOverlay'] = None

        # CMS client for pairing
        self._cms_client: Optional[CMSClient] = None

        # Pairing state
        self._pairing_code: Optional[str] = None
        self._pairing_poll_timer: Optional[int] = None

        # CMS status polling state
        self._cms_poll_timer: Optional[int] = None
        self._cms_poll_interval: int = 30000  # 30 seconds default

        # Main loop event
        self._stop_event = threading.Event()

        logger.info("SkillzPlayer initialized (headless=%s)", self._headless)

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

    def _initialize_state_machine(self) -> bool:
        """
        Initialize player state machine.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            # Determine initial mode based on pairing status
            initial_mode = PlayerMode.PAIRING
            if self._config and self._config.paired:
                initial_mode = PlayerMode.PLAYBACK

            self._state_machine = PlayerStateMachine(
                initial_mode=initial_mode,
                on_mode_changed=self._on_mode_changed
            )

            logger.info("State machine initialized in %s mode", initial_mode.name)
            return True

        except Exception as e:
            logger.error("Failed to initialize state machine: %s", e)
            return False

    def _initialize_cms_client(self) -> bool:
        """
        Initialize CMS client for pairing operations.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            cms_url = self._config.cms_url if self._config else "http://localhost:5002"
            self._cms_client = CMSClient(cms_url=cms_url)

            logger.info("CMS client initialized (url: %s)", cms_url)
            return True

        except Exception as e:
            logger.error("Failed to initialize CMS client: %s", e)
            return False

    def _initialize_kiosk_ui(self) -> bool:
        """
        Initialize kiosk UI components (window, pairing screen, menu).

        Returns:
            True if initialization successful, False otherwise
        """
        if self._headless:
            logger.info("Skipping kiosk UI initialization (headless mode)")
            return True

        try:
            # Get device info for display
            device_info = get_device_info()
            device_id = device_info.get('device_id', 'Unknown')
            cms_url = self._config.cms_url if self._config else "http://localhost:5002"

            # Create pairing screen
            self._pairing_screen = PairingScreen(
                pairing_code="------",
                cms_url=cms_url,
                device_id=device_id
            )

            # Create menu overlay
            self._menu_overlay = MenuOverlay(
                on_close=self._on_menu_close,
                on_re_pair=self._on_re_pair_requested,
                on_refresh=self._on_manual_refresh,
                on_exit=self._on_exit_requested,
                on_camera_toggle=self._on_camera_toggle
            )

            # Create kiosk window
            self._kiosk_window = KioskWindow(
                title="Skillz Media Player",
                on_menu_requested=self._on_menu_requested,
                on_exit_requested=self._on_exit_requested
            )

            # Add content screens to window
            self._kiosk_window.add_content("pairing", self._pairing_screen)

            # Create a placeholder for playback (video will be rendered separately)
            if GTK_AVAILABLE:
                playback_placeholder = Gtk.Box()
                playback_placeholder.override_background_color(
                    Gtk.StateFlags.NORMAL,
                    Gdk.RGBA(0, 0, 0, 1)  # Black background
                )
                self._kiosk_window.add_content("playback", playback_placeholder)

            # Add menu overlay to window
            self._kiosk_window.add_overlay_widget(self._menu_overlay)
            self._menu_overlay.hide()  # Initially hidden

            logger.info("Kiosk UI initialized")
            return True

        except Exception as e:
            logger.error("Failed to initialize kiosk UI: %s", e)
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
    # State Machine and Kiosk UI Callbacks
    # -------------------------------------------------------------------------

    def _on_mode_changed(
        self,
        state_machine: PlayerStateMachine,
        old_mode: PlayerMode,
        new_mode: PlayerMode
    ) -> None:
        """
        Callback when player mode changes.

        Args:
            state_machine: The state machine
            old_mode: Previous mode
            new_mode: New mode
        """
        logger.info("Mode changed: %s -> %s", old_mode.name, new_mode.name)

        if self._headless:
            return

        # Update UI based on new mode
        if new_mode == PlayerMode.PAIRING:
            self._show_pairing_screen()
        elif new_mode == PlayerMode.PLAYBACK:
            self._show_playback_screen()
        elif new_mode == PlayerMode.MENU:
            self._show_menu_overlay()

    def _show_pairing_screen(self) -> None:
        """Show the pairing screen and start pairing flow."""
        if self._kiosk_window and self._pairing_screen:
            self._kiosk_window.show_content("pairing")
            self._menu_overlay.hide()

            # Start pairing if not already in progress
            self._start_pairing_flow()

    def _show_playback_screen(self) -> None:
        """Show the playback screen."""
        if self._kiosk_window:
            self._kiosk_window.show_content("playback")
            self._menu_overlay.hide()

            # Stop pairing poll if running
            self._stop_pairing_poll()

    def _show_menu_overlay(self) -> None:
        """Show the menu overlay."""
        if self._menu_overlay:
            # Update menu with current device info
            self._update_menu_info()
            self._menu_overlay.show_all()

    def _start_pairing_flow(self) -> None:
        """Start the device pairing flow."""
        if not self._cms_client:
            logger.error("Cannot start pairing - CMS client not initialized")
            return

        try:
            # First register the device if needed
            self._cms_client.register_device(mode=self._config.connection_mode if self._config else "direct")

            # Request pairing code
            code = self._cms_client.request_pairing()

            if code:
                self._pairing_code = code

                # Update pairing screen with code
                if self._pairing_screen:
                    self._pairing_screen.set_pairing_code(code)
                    self._pairing_screen.set_status("Waiting for approval...")

                # Save pairing code to config
                if self._config:
                    self._config.pairing_code = code
                    self._config.pairing_status = "pairing"
                    self._config.save_device()

                # Start polling for pairing status
                self._start_pairing_poll()

                logger.info("Pairing flow started with code: %s", code)
            else:
                logger.error("Failed to get pairing code from CMS")
                if self._pairing_screen:
                    self._pairing_screen.show_error("Failed to connect to CMS")

        except Exception as e:
            logger.error("Failed to start pairing flow: %s", e)
            if self._pairing_screen:
                self._pairing_screen.show_error(f"Error: {str(e)[:30]}")

    def _start_pairing_poll(self) -> None:
        """Start polling CMS for pairing status."""
        if self._headless:
            return

        # Stop existing poll if any
        self._stop_pairing_poll()

        # Poll every 5 seconds using GLib timer
        if GTK_AVAILABLE and self._kiosk_window:
            self._pairing_poll_timer = self._kiosk_window.add_timeout(
                5000,  # 5 seconds
                self._poll_pairing_status
            )
            logger.debug("Started pairing poll timer")

    def _stop_pairing_poll(self) -> None:
        """Stop the pairing status poll."""
        if self._pairing_poll_timer and self._kiosk_window:
            self._kiosk_window.remove_timeout(self._pairing_poll_timer)
            self._pairing_poll_timer = None
            logger.debug("Stopped pairing poll timer")

    def _poll_pairing_status(self) -> bool:
        """
        Poll CMS for pairing status.

        Returns:
            True to continue polling, False to stop
        """
        if not self._cms_client:
            return False

        try:
            if self._cms_client.check_pairing_status():
                # Device is now paired!
                logger.info("Device paired successfully!")

                if self._pairing_screen:
                    self._pairing_screen.show_success()

                # Update config
                if self._config:
                    self._config.set_paired(True)

                # Transition to playback mode after short delay
                if GTK_AVAILABLE and self._kiosk_window:
                    self._kiosk_window.schedule_callback(
                        lambda: self._transition_to_playback()
                    )

                return False  # Stop polling

        except Exception as e:
            logger.error("Error polling pairing status: %s", e)

        return True  # Continue polling

    def _start_cms_status_poll(self) -> None:
        """Start polling CMS for device status during playback."""
        if self._headless:
            return

        # Stop existing poll if any
        self._stop_cms_status_poll()

        # Poll every 30 seconds using GLib timer
        if GTK_AVAILABLE and self._kiosk_window:
            self._cms_poll_timer = self._kiosk_window.add_timeout(
                self._cms_poll_interval,
                self._poll_cms_status
            )
            logger.debug("Started CMS status poll timer")

    def _stop_cms_status_poll(self) -> None:
        """Stop the CMS status poll."""
        if self._cms_poll_timer and self._kiosk_window:
            self._kiosk_window.remove_timeout(self._cms_poll_timer)
            self._cms_poll_timer = None
            logger.debug("Stopped CMS status poll timer")

    def _poll_cms_status(self) -> bool:
        """
        Poll CMS for device status with automatic mode transition.

        Checks if the device is still paired and handles remote unpair.
        Can also receive mode commands from CMS in the future.

        Returns:
            True to continue polling, False to stop
        """
        if not self._cms_client or not self._running:
            return False

        try:
            # Check if device is still paired
            is_paired = self._cms_client.check_pairing_status()

            if not is_paired:
                # Device was unpaired remotely - transition to pairing mode
                logger.info("Device unpaired remotely - transitioning to pairing mode")

                # Update config
                if self._config:
                    self._config.set_paired(False)

                # Transition to pairing mode
                if GTK_AVAILABLE and self._kiosk_window:
                    self._kiosk_window.schedule_callback(
                        lambda: self._transition_to_pairing()
                    )

                return False  # Stop polling (pairing poll will take over)

            # Device is still paired - continue normal operation
            logger.debug("CMS status poll: device still paired")

        except Exception as e:
            logger.error("Error polling CMS status: %s", e)
            # Continue polling even on error - might be temporary network issue

        return True  # Continue polling

    def _transition_to_pairing(self) -> None:
        """Transition from playback to pairing mode due to remote unpair."""
        if self._state_machine:
            try:
                # If in menu mode, close it first
                if self._state_machine.is_menu:
                    self._state_machine.to_playback()

                # Now transition to pairing
                self._state_machine.to_pairing()

                # Stop CMS status poll (pairing poll will start)
                self._stop_cms_status_poll()

            except StateTransitionError as e:
                logger.error("Failed to transition to pairing: %s", e)

    def _transition_to_playback(self) -> None:
        """Transition from pairing to playback mode."""
        if self._state_machine:
            try:
                self._state_machine.to_playback()

                # Start playback
                self._start_playback()

                # Start CMS status polling to detect remote unpair
                self._start_cms_status_poll()

            except StateTransitionError as e:
                logger.error("Failed to transition to playback: %s", e)

    def _on_menu_requested(self) -> None:
        """Callback when menu is requested (Escape/F1/corner tap)."""
        if not self._state_machine:
            return

        try:
            # Only allow menu in playback mode (can toggle)
            if self._state_machine.is_playback:
                self._state_machine.to_menu()
            elif self._state_machine.is_menu:
                self._state_machine.to_playback()
            # Don't allow menu toggle in pairing mode

        except StateTransitionError as e:
            logger.debug("Cannot toggle menu: %s", e)

    def _on_menu_close(self) -> None:
        """Callback when menu close is requested."""
        if self._state_machine and self._state_machine.is_menu:
            try:
                self._state_machine.to_playback()
            except StateTransitionError as e:
                logger.error("Failed to close menu: %s", e)

    def _on_re_pair_requested(self) -> None:
        """Callback when re-pairing is requested from menu."""
        logger.info("Re-pair requested")

        # Clear pairing state
        if self._config:
            self._config.set_paired(False)

        # Transition to pairing mode
        if self._state_machine:
            try:
                if self._state_machine.is_menu:
                    # Go back to playback first (menu can only go to playback)
                    self._state_machine.to_playback()
                # Now transition to pairing
                self._state_machine.to_pairing()
            except StateTransitionError as e:
                logger.error("Failed to transition to pairing: %s", e)

    def _on_manual_refresh(self) -> None:
        """Callback for manual refresh request from menu."""
        logger.info("Manual refresh requested")

        # Trigger sync service refresh
        if self._sync_service:
            self._sync_service.sync_now()

        # Close menu
        self._on_menu_close()

    def _on_exit_requested(self) -> None:
        """Callback when exit is requested."""
        logger.info("Exit requested")
        self.stop()

    def _on_camera_toggle(self, enabled: bool) -> None:
        """Callback when camera is toggled from menu."""
        logger.info("Camera toggle: %s", "enabled" if enabled else "disabled")

        if self._config:
            self._config.camera_enabled = enabled
            self._config.save_settings()

    def _update_menu_info(self) -> None:
        """Update menu overlay with current device and network info."""
        if not self._menu_overlay:
            return

        device_info = get_device_info()
        device_id = device_info.get('device_id', 'Unknown')
        ip_address = device_info.get('ip_address', 'Unknown')

        screen_id = self._config.screen_id if self._config else ""
        connection_mode = self._config.connection_mode if self._config else "direct"
        cms_url = self._config.cms_url if self._config else ""
        camera_enabled = self._config.camera_enabled if self._config else True

        # Get current playback status
        playback_status = self._get_playback_status()
        status = playback_status.get("status", "unknown")
        current_content = playback_status.get("current_content", "None")

        # Determine network status
        network_status = "Unknown"
        if self._cms_client:
            try:
                # Quick check if CMS is reachable
                network_status = "Connected"
            except Exception:
                network_status = "Disconnected"

        self._menu_overlay.update_device_info(
            device_id=device_id,
            screen_id=screen_id,
            connection_mode=connection_mode,
            status=status,
            current_content=current_content,
            camera_enabled=camera_enabled,
            ip_address=ip_address,
            network_status=network_status,
            cms_url=cms_url
        )

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def start(self) -> bool:
        """
        Start the player.

        Startup flow:
        1. Load configuration
        2. Initialize state machine and CMS client
        3. Initialize kiosk UI (if not headless)
        4. Initialize playback components
        5. Start in appropriate mode (pairing or playback)
        6. Start background services (sync, heartbeat, trigger listener)

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

        # Step 2: Initialize state machine and CMS client
        if not self._initialize_state_machine():
            logger.error("Failed to initialize state machine")
            return False

        if not self._initialize_cms_client():
            logger.warning("Failed to initialize CMS client - pairing will not work")

        # Step 3: Initialize kiosk UI (if not headless)
        if not self._initialize_kiosk_ui():
            logger.warning("Failed to initialize kiosk UI - continuing in headless mode")
            self._headless = True

        # Step 4: Initialize playback components
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

        # Step 5: Start in appropriate mode
        if self._state_machine.is_pairing:
            # Show pairing screen and start pairing flow
            logger.info("Device not paired - starting in pairing mode")
            if not self._headless:
                self._show_pairing_screen()
        else:
            # Device is paired - start playback
            logger.info("Device paired - starting playback")
            playback_ok = self._start_playback()

            if not playback_ok:
                logger.warning("No content to play - waiting for sync")

            if not self._headless:
                self._show_playback_screen()

            # Start CMS status polling to detect remote unpair
            self._start_cms_status_poll()

        # Step 6: Start background services
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

        # Stop pairing poll timer if running
        self._stop_pairing_poll()

        # Stop CMS status poll timer if running
        self._stop_cms_status_poll()

        # Stop background services first
        self._stop_background_services()

        # Stop playback
        if self._gst_player:
            self._gst_player.cleanup()

        # Stop kiosk window
        if self._kiosk_window:
            self._kiosk_window.quit()

        logger.info("SkillzPlayer stopped")

    def run(self) -> None:
        """
        Run the player (blocking).

        This method blocks until stop() is called or a signal is received.
        Use this for running as a systemd service or main application.

        If running with kiosk UI, uses GTK main loop.
        Otherwise, uses simple event-based loop.
        """
        # Set up signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        if not self.start():
            logger.error("Failed to start player")
            sys.exit(1)

        logger.info("Player running - press Ctrl+C to stop")

        if not self._headless and self._kiosk_window:
            # Run GTK main loop (blocking)
            try:
                self._kiosk_window.show_all()
                self._kiosk_window.run()
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")
        else:
            # Wait for stop signal (headless mode)
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
            "headless": self._headless,
            "mode": None,
            "playback": self._get_playback_status(),
            "playlist": None,
            "sync": None,
            "trigger_listener": None,
            "heartbeat": None,
            "pairing": None
        }

        if self._state_machine:
            status["mode"] = self._state_machine.get_state_info()

        if self._playlist_manager:
            status["playlist"] = self._playlist_manager.get_playlist_info()

        if self._sync_service:
            status["sync"] = self._sync_service.get_status()

        if self._trigger_listener:
            status["trigger_listener"] = self._trigger_listener.get_status()

        if self._heartbeat:
            status["heartbeat"] = self._heartbeat.get_last_heartbeat_info()

        # Include pairing info if in pairing mode
        if self._state_machine and self._state_machine.is_pairing:
            status["pairing"] = {
                "code": self._pairing_code,
                "cms_url": self._cms_client.cms_url if self._cms_client else None
            }

        return status

    @property
    def state_machine(self) -> Optional[PlayerStateMachine]:
        """Get the player state machine."""
        return self._state_machine

    @property
    def mode(self) -> Optional[PlayerMode]:
        """Get current player mode."""
        if self._state_machine:
            return self._state_machine.mode
        return None


# Global player instance
_global_player: Optional[SkillzPlayer] = None


def get_skillz_player(
    config_dir: Optional[str] = None,
    media_dir: Optional[str] = None,
    sync_interval: int = 300,
    heartbeat_interval: int = 60,
    headless: bool = False
) -> SkillzPlayer:
    """
    Get the global SkillzPlayer instance.

    Args:
        config_dir: Path to config directory (only used on first call)
        media_dir: Path to media files directory (only used on first call)
        sync_interval: Seconds between sync attempts (only used on first call)
        heartbeat_interval: Seconds between heartbeats (only used on first call)
        headless: If True, run without GTK UI (only used on first call)

    Returns:
        SkillzPlayer instance
    """
    global _global_player

    if _global_player is None:
        _global_player = SkillzPlayer(
            config_dir=config_dir,
            media_dir=media_dir,
            sync_interval=sync_interval,
            heartbeat_interval=heartbeat_interval,
            headless=headless
        )

    return _global_player


def main():
    """Main entry point for running the player."""
    logger.info("Jetson Media Player starting...")

    player = get_skillz_player()
    player.run()


if __name__ == "__main__":
    main()
