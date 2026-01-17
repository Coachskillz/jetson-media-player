"""
KioskPlayer - Production-ready Jetson Media Player with GTK3 kiosk interface.
Integrates state machine, pairing flow, video playback, and menu overlay.
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')

from gi.repository import Gtk, Gdk, GLib
import signal
import sys
import threading
import os
from typing import Optional

from .config import PlayerConfig, get_player_config
from .state_machine import PlayerStateMachine, PlayerMode, get_player_state_machine
from .ui.kiosk_window import KioskWindow
from .ui.pairing_screen import PairingScreen
from .ui.menu_overlay import MenuOverlay
from .gstreamer_player import GStreamerPlayer, PlayerState
from .playlist_manager import PlaylistManager, get_playlist_manager
from .sync_service import SyncService, get_sync_service
from .heartbeat import HeartbeatReporter

from src.common.cms_client import CMSClient
from src.common.device_id import get_device_info
from src.common.logger import setup_logger

logger = setup_logger(__name__)


class KioskPlayer:
    """
    Production-ready media player with kiosk interface.

    Startup flow:
    1. Check pairing status from config
    2. If not paired: Show pairing screen with 6-digit code
    3. Poll CMS for pairing approval
    4. Once paired: Start video playback
    5. Menu accessible via Escape/F1/corner tap
    """

    # Pairing check interval (milliseconds)
    PAIRING_CHECK_INTERVAL_MS = 5000

    def __init__(
        self,
        config_dir: Optional[str] = None,
        media_dir: Optional[str] = None,
        cms_url: Optional[str] = None,
        sync_interval: int = 300,
        heartbeat_interval: int = 60
    ):
        """
        Initialize the kiosk player.

        Args:
            config_dir: Path to config directory
            media_dir: Path to media files directory
            cms_url: CMS URL override (uses config if None)
            sync_interval: Seconds between hub sync attempts
            heartbeat_interval: Seconds between heartbeats
        """
        self._config_dir = config_dir
        self._media_dir = media_dir
        self._cms_url_override = cms_url
        self._sync_interval = sync_interval
        self._heartbeat_interval = heartbeat_interval

        # State
        self._running = False
        self._pairing_check_id: Optional[int] = None

        # Components (initialized in start())
        self._config: Optional[PlayerConfig] = None
        self._state_machine: Optional[PlayerStateMachine] = None
        self._cms_client: Optional[CMSClient] = None
        self._device_info: dict = {}

        # GTK components
        self._window: Optional[KioskWindow] = None
        self._stack: Optional[Gtk.Stack] = None
        self._pairing_screen: Optional[PairingScreen] = None
        self._menu_overlay: Optional[MenuOverlay] = None
        self._video_area: Optional[Gtk.DrawingArea] = None
        self._overlay: Optional[Gtk.Overlay] = None

        # Playback components
        self._gst_player: Optional[GStreamerPlayer] = None
        self._playlist_manager: Optional[PlaylistManager] = None
        self._sync_service: Optional[SyncService] = None
        self._heartbeat: Optional[HeartbeatReporter] = None

        logger.info("KioskPlayer initialized")

    def _load_config(self) -> bool:
        """Load configuration from disk."""
        try:
            self._config = get_player_config(self._config_dir)
            self._device_info = get_device_info()

            # Override CMS URL if provided
            if self._cms_url_override:
                self._config.cms_url = self._cms_url_override

            logger.info(
                "Config loaded - paired: %s, cms_url: %s",
                self._config.paired,
                self._config.cms_url
            )
            return True
        except Exception as e:
            logger.error("Failed to load config: %s", e)
            return False

    def _initialize_state_machine(self) -> None:
        """Initialize the player state machine."""
        # Determine initial mode based on pairing status
        initial_mode = PlayerMode.PLAYBACK if self._config.paired else PlayerMode.PAIRING

        self._state_machine = get_player_state_machine(
            initial_mode=initial_mode,
            on_mode_changed=self._on_mode_changed
        )

        logger.info("State machine initialized in %s mode", self._state_machine.mode.name)

    def _initialize_cms_client(self) -> None:
        """Initialize CMS client for pairing."""
        self._cms_client = CMSClient(cms_url=self._config.cms_url)

    def _build_ui(self) -> None:
        """Build the GTK UI."""
        # Create main window
        self._window = KioskWindow(
            title="Skillz Media Player",
            on_menu_toggle=self._toggle_menu
        )

        # Create stack for switching between pairing and playback views
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(500)

        # Create pairing screen
        self._pairing_screen = PairingScreen(
            pairing_code="------",
            cms_url=self._config.cms_url,
            device_id=self._device_info.get('device_id', '')
        )
        self._stack.add_named(self._pairing_screen, "pairing")

        # Create overlay for video + menu
        self._overlay = Gtk.Overlay()

        # Video area (black background for GStreamer to draw on)
        self._video_area = Gtk.DrawingArea()
        self._video_area.override_background_color(
            Gtk.StateFlags.NORMAL,
            Gdk.RGBA(0, 0, 0, 1)
        )
        self._overlay.add(self._video_area)

        # Menu overlay (initially hidden)
        self._menu_overlay = MenuOverlay(
            on_close=self._close_menu,
            on_re_pair=self._request_re_pair,
            on_restart=self._restart_player,
            on_camera_toggle=self._toggle_camera
        )
        self._menu_overlay.set_halign(Gtk.Align.CENTER)
        self._menu_overlay.set_valign(Gtk.Align.CENTER)
        self._menu_overlay.set_no_show_all(True)  # Don't show with show_all()
        self._overlay.add_overlay(self._menu_overlay)

        self._stack.add_named(self._overlay, "playback")

        # Add stack to window
        self._window.add(self._stack)

        # Connect window destroy to cleanup
        self._window.connect('destroy', self._on_window_destroy)

    def _initialize_playback_components(self) -> bool:
        """Initialize GStreamer and playback components."""
        try:
            # Initialize playlist manager
            self._playlist_manager = get_playlist_manager(
                config=self._config,
                media_dir=self._media_dir,
                on_playlist_changed=self._on_playlist_changed
            )
            self._playlist_manager.load_from_config()

            # Initialize GStreamer player
            self._gst_player = GStreamerPlayer(
                media_dir=self._media_dir,
                on_about_to_finish=self._get_next_uri,
                on_error=self._on_playback_error,
                on_eos=self._on_end_of_stream
            )

            if not self._gst_player.initialize():
                logger.error("Failed to initialize GStreamer")
                return False

            # Set video output window ID
            if self._video_area:
                self._video_area.realize()
                window = self._video_area.get_window()
                if window:
                    xid = window.get_xid()
                    self._gst_player.set_window_handle(xid)
                    logger.info("Set video window XID: %s", xid)

            # Initialize sync service
            self._sync_service = get_sync_service(
                config=self._config,
                media_dir=self._media_dir,
                sync_interval=self._sync_interval,
                on_sync_complete=self._on_sync_complete,
                on_content_updated=self._on_content_updated
            )

            # Initialize heartbeat
            self._heartbeat = HeartbeatReporter(
                hub_url=self._config.hub_url,
                screen_id=self._config.screen_id,
                interval=self._heartbeat_interval
            )
            self._heartbeat.set_status_callback(self._get_playback_status)

            logger.info("Playback components initialized")
            return True

        except Exception as e:
            logger.error("Failed to initialize playback: %s", e)
            return False

    def _start_pairing_flow(self) -> None:
        """Start the device pairing flow."""
        logger.info("Starting pairing flow")

        # Show pairing screen
        self._stack.set_visible_child_name("pairing")

        # Register device first
        device_data = self._cms_client.register_device(mode='direct')

        if device_data:
            logger.info("Device registered: %s", device_data.get('device_id'))

        # Request pairing code
        code = self._cms_client.request_pairing()

        if code:
            self._config.pairing_code = code
            self._config.save_device()
            self._pairing_screen.set_pairing_code(code)
            self._pairing_screen.set_status("Waiting for approval...")

            # Start polling for approval
            self._start_pairing_check()
        else:
            logger.error("Failed to get pairing code")
            self._pairing_screen.show_error("Could not connect to CMS")

    def _start_pairing_check(self) -> None:
        """Start periodic pairing status checks."""
        if self._pairing_check_id:
            GLib.source_remove(self._pairing_check_id)

        self._pairing_check_id = GLib.timeout_add(
            self.PAIRING_CHECK_INTERVAL_MS,
            self._check_pairing_status
        )

    def _stop_pairing_check(self) -> None:
        """Stop pairing status checks."""
        if self._pairing_check_id:
            GLib.source_remove(self._pairing_check_id)
            self._pairing_check_id = None

    def _check_pairing_status(self) -> bool:
        """
        Check if pairing has been approved.

        Returns:
            True to continue checking, False to stop
        """
        if not self._running:
            return False

        if self._cms_client.check_pairing_status():
            logger.info("Pairing approved!")

            # Update config
            self._config.set_paired(True)

            # Show success and transition
            self._pairing_screen.show_success()

            # Transition to playback after short delay
            GLib.timeout_add(1500, self._transition_to_playback)

            return False  # Stop checking

        return True  # Continue checking

    def _transition_to_playback(self) -> bool:
        """Transition from pairing to playback mode."""
        logger.info("Transitioning to playback mode")

        self._state_machine.to_playback()

        # Initialize playback if not done
        if not self._gst_player:
            self._initialize_playback_components()

        # Start playback
        self._start_playback()

        # Show playback view
        self._stack.set_visible_child_name("playback")

        # Start background services
        self._start_background_services()

        return False  # Don't repeat

    def _start_playback(self) -> bool:
        """Start video playback."""
        if self._playlist_manager.default_playlist_length == 0:
            logger.warning("No content available")
            return False

        first_uri = self._playlist_manager.get_first_uri()
        if first_uri:
            logger.info("Starting playback: %s", first_uri)
            return self._gst_player.play(first_uri)

        return False

    def _start_background_services(self) -> None:
        """Start sync and heartbeat services."""
        if self._sync_service:
            self._sync_service.start()

        if self._heartbeat:
            self._heartbeat.start()

        logger.info("Background services started")

    def _stop_background_services(self) -> None:
        """Stop background services."""
        if self._heartbeat:
            self._heartbeat.stop()

        if self._sync_service:
            self._sync_service.stop()

    # -------------------------------------------------------------------------
    # State Machine Callbacks
    # -------------------------------------------------------------------------

    def _on_mode_changed(
        self,
        state_machine: PlayerStateMachine,
        old_mode: PlayerMode,
        new_mode: PlayerMode
    ) -> None:
        """Handle state machine mode changes."""
        logger.info("Mode changed: %s -> %s", old_mode.name, new_mode.name)

        # Use GLib.idle_add for thread-safe UI updates
        GLib.idle_add(self._update_ui_for_mode, new_mode)

    def _update_ui_for_mode(self, mode: PlayerMode) -> bool:
        """Update UI for the given mode."""
        if mode == PlayerMode.PAIRING:
            self._stack.set_visible_child_name("pairing")
            if self._gst_player:
                self._gst_player.pause()

        elif mode == PlayerMode.PLAYBACK:
            self._stack.set_visible_child_name("playback")
            self._menu_overlay.hide()
            if self._gst_player and self._gst_player.state == PlayerState.PAUSED:
                self._gst_player.play()

        elif mode == PlayerMode.MENU:
            # Update menu info
            self._update_menu_info()
            self._menu_overlay.show()
            self._window.show_cursor_temporarily(30000)  # Show cursor for 30s

        return False  # Don't repeat

    def _update_menu_info(self) -> None:
        """Update menu overlay with current device info."""
        status = "Playing" if self._gst_player and self._gst_player.is_playing else "Idle"
        current = self._playlist_manager.current_filename if self._playlist_manager else ""

        self._menu_overlay.update_device_info(
            device_id=self._device_info.get('device_id', ''),
            screen_id=self._config.screen_id,
            connection_mode=self._config.connection_mode,
            status=status,
            current_content=current,
            camera_enabled=self._config.camera_enabled
        )

    # -------------------------------------------------------------------------
    # Menu Actions
    # -------------------------------------------------------------------------

    def _toggle_menu(self) -> None:
        """Toggle menu overlay visibility."""
        if self._state_machine.mode == PlayerMode.PAIRING:
            return  # No menu in pairing mode

        try:
            self._state_machine.toggle_menu()
        except Exception as e:
            logger.warning("Could not toggle menu: %s", e)

    def _close_menu(self) -> None:
        """Close the menu overlay."""
        if self._state_machine.is_menu:
            self._state_machine.to_playback()

    def _request_re_pair(self) -> None:
        """Handle re-pairing request from menu."""
        logger.info("Re-pair requested")

        # Reset pairing state
        self._config.set_paired(False, '')

        # Stop playback
        if self._gst_player:
            self._gst_player.stop()

        # Transition to pairing
        self._state_machine.to_pairing()

        # Restart pairing flow
        self._pairing_screen.reset()
        self._start_pairing_flow()

    def _restart_player(self) -> None:
        """Restart the player application."""
        logger.info("Restart requested")
        self.stop()
        # Exit with code that tells systemd to restart
        sys.exit(0)

    def _toggle_camera(self, enabled: bool) -> None:
        """Toggle camera enable state."""
        logger.info("Camera toggle: %s", enabled)
        self._config.camera_enabled = enabled
        self._config.save_settings()
        # TODO: Notify detection service

    # -------------------------------------------------------------------------
    # Playback Callbacks
    # -------------------------------------------------------------------------

    def _get_next_uri(self) -> Optional[str]:
        """Get next URI for gapless playback."""
        if self._playlist_manager:
            return self._playlist_manager.get_next_uri()
        return None

    def _on_playback_error(self, error_msg: str) -> None:
        """Handle playback errors."""
        logger.error("Playback error: %s", error_msg)
        # Try next item
        if self._playlist_manager and self._gst_player:
            next_uri = self._playlist_manager.get_next_uri()
            if next_uri:
                self._gst_player.play(next_uri)

    def _on_end_of_stream(self) -> None:
        """Handle end of stream."""
        if self._playlist_manager and self._gst_player:
            next_uri = self._playlist_manager.get_next_uri()
            if next_uri:
                self._gst_player.play(next_uri)

    def _on_playlist_changed(self, manager: PlaylistManager) -> None:
        """Handle playlist changes."""
        logger.debug("Playlist changed")

    def _on_sync_complete(self, success: bool) -> None:
        """Handle sync completion."""
        logger.debug("Sync complete: %s", success)

    def _on_content_updated(self) -> None:
        """Handle new content downloaded."""
        if self._playlist_manager:
            self._playlist_manager.reload()

    def _get_playback_status(self) -> dict:
        """Get playback status for heartbeat."""
        status = "unknown"
        if self._gst_player:
            if self._gst_player.is_playing:
                status = "playing"
            elif self._gst_player.state == PlayerState.PAUSED:
                status = "paused"

        content = ""
        if self._playlist_manager:
            content = self._playlist_manager.current_filename or ""

        return {"status": status, "current_content": content}

    # -------------------------------------------------------------------------
    # Window Events
    # -------------------------------------------------------------------------

    def _on_window_destroy(self, widget: Gtk.Widget) -> None:
        """Handle window destroy."""
        self.stop()
        Gtk.main_quit()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def start(self) -> bool:
        """
        Start the kiosk player.

        Returns:
            True if started successfully
        """
        if self._running:
            return True

        logger.info("=" * 60)
        logger.info("Starting KioskPlayer")
        logger.info("=" * 60)

        # Load configuration
        if not self._load_config():
            return False

        # Initialize state machine
        self._initialize_state_machine()

        # Initialize CMS client
        self._initialize_cms_client()

        # Build UI
        self._build_ui()

        # Initialize playback components (but don't start yet)
        if self._config.paired:
            self._initialize_playback_components()

        self._running = True

        # Show window
        self._window.show_all()
        self._menu_overlay.hide()  # Ensure menu starts hidden

        # Start appropriate flow based on pairing status
        if self._config.paired:
            logger.info("Device is paired - starting playback")
            self._stack.set_visible_child_name("playback")
            self._start_playback()
            self._start_background_services()
        else:
            logger.info("Device not paired - starting pairing flow")
            self._start_pairing_flow()

        return True

    def stop(self) -> None:
        """Stop the kiosk player."""
        if not self._running:
            return

        logger.info("Stopping KioskPlayer")
        self._running = False

        # Stop pairing checks
        self._stop_pairing_check()

        # Stop background services
        self._stop_background_services()

        # Stop playback
        if self._gst_player:
            self._gst_player.cleanup()

        logger.info("KioskPlayer stopped")

    def run(self) -> None:
        """
        Run the kiosk player (blocking).

        This is the main entry point for production use.
        """
        # Set up signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        if not self.start():
            logger.error("Failed to start kiosk player")
            sys.exit(1)

        # Run GTK main loop
        try:
            Gtk.main()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")

        self.stop()

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle system signals."""
        logger.info("Received signal: %s", signal.Signals(signum).name)
        GLib.idle_add(self._shutdown_from_signal)

    def _shutdown_from_signal(self) -> bool:
        """Shutdown triggered by signal."""
        self.stop()
        Gtk.main_quit()
        return False


def main():
    """Main entry point for the kiosk player."""
    import argparse

    parser = argparse.ArgumentParser(description="Skillz Media Kiosk Player")
    parser.add_argument('--config-dir', help="Config directory path")
    parser.add_argument('--media-dir', help="Media directory path")
    parser.add_argument('--cms-url', help="CMS URL override")
    parser.add_argument('--no-kiosk', action='store_true', help="Disable kiosk mode")

    args = parser.parse_args()

    logger.info("Skillz Media Kiosk Player starting...")

    player = KioskPlayer(
        config_dir=args.config_dir,
        media_dir=args.media_dir,
        cms_url=args.cms_url
    )

    player.run()


if __name__ == "__main__":
    main()
