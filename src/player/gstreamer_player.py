"""
GStreamer player module with NVIDIA hardware acceleration.
Uses playbin3 for gapless video playback on Jetson Orin Nano.
"""

import logging
import threading
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

# IMPORTANT: gi.require_version() MUST be called BEFORE importing from gi.repository
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gst, GstVideo, GLib


# Initialize GStreamer - REQUIRED before using any GStreamer elements
Gst.init(None)


from src.common.logger import setup_logger
logger = setup_logger(__name__)


class PlayerState(Enum):
    """Represents the state of the GStreamer player."""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    ERROR = "error"


class GStreamerPlayer:
    """
    Hardware-accelerated GStreamer player for Jetson Orin Nano.
    Uses playbin3 with nv3dsink for smooth, gapless video playback.
    """

    # Default media directory on Jetson devices
    DEFAULT_MEDIA_DIR = "/home/skillz/media"

    def __init__(
        self,
        media_dir: Optional[str] = None,
        on_about_to_finish: Optional[Callable[[], Optional[str]]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_eos: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the GStreamer player.

        Args:
            media_dir: Directory where media files are stored
            on_about_to_finish: Callback that returns the next URI for gapless playback.
                                Called ~2 seconds before current video ends.
            on_error: Callback for playback errors with error message
            on_eos: Callback for end-of-stream (when no next URI is queued)
        """
        self.media_dir = Path(media_dir) if media_dir else Path(self.DEFAULT_MEDIA_DIR)
        self._on_about_to_finish = on_about_to_finish
        self._on_error = on_error
        self._on_eos = on_eos

        self._player: Optional[Gst.Element] = None
        self._bus: Optional[Gst.Bus] = None
        self._loop: Optional[GLib.MainLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._state = PlayerState.STOPPED
        self._current_uri: Optional[str] = None
        self._next_uri_queued = False
        self._lock = threading.Lock()

        # Track last played URI for consecutive same video handling
        self._last_uri: Optional[str] = None

        # X11 window handle for embedding video in GTK
        self._window_xid: Optional[int] = None

        logger.info("GStreamerPlayer initialized with media_dir: %s", self.media_dir)

    def _create_player(self) -> Gst.Element:
        """
        Create and configure the GStreamer playbin3 element.

        Returns:
            Configured playbin3 element
        """
        # Use playbin3 for gapless playback support
        player = Gst.ElementFactory.make('playbin3', 'player')
        if player is None:
            raise RuntimeError("Failed to create playbin3 element. Is GStreamer installed?")

        # Configure video sink — must support GstVideoOverlay for GTK embedding.
        # nv3dsink renders to its own window and CANNOT embed in GTK.
        # Use xvimagesink which supports XOverlay and works with nvv4l2decoder.
        video_sink = None
        for sink_name in ('xvimagesink', 'nveglglessink', 'autovideosink'):
            video_sink = Gst.ElementFactory.make(sink_name, 'videosink')
            if video_sink is not None:
                logger.info("Using video sink: %s", sink_name)
                break

        if video_sink:
            video_sink.set_property('sync', True)
            player.set_property('video-sink', video_sink)

        # Connect about-to-finish signal for gapless playback
        # This signal fires from streaming thread ~2 seconds before track ends
        player.connect('about-to-finish', self._handle_about_to_finish)

        return player

    def _setup_bus(self) -> None:
        """Set up the GStreamer message bus for handling events."""
        if self._player is None:
            return

        self._bus = self._player.get_bus()
        if self._bus:
            self._bus.add_signal_watch()
            self._bus.connect('message::error', self._handle_error)
            self._bus.connect('message::eos', self._handle_eos)
            self._bus.connect('message::state-changed', self._handle_state_changed)

            # Enable sync message handling for GstVideoOverlay (window embedding)
            self._bus.enable_sync_message_emission()
            self._bus.connect('sync-message::element', self._handle_sync_message)

    def _start_main_loop(self) -> None:
        """Start the GLib main loop in a separate thread."""
        if self._loop is not None:
            return

        self._loop = GLib.MainLoop()
        self._loop_thread = threading.Thread(target=self._run_main_loop, daemon=True)
        self._loop_thread.start()
        logger.debug("GLib MainLoop started")

    def _run_main_loop(self) -> None:
        """Run the GLib main loop (called in thread)."""
        try:
            if self._loop:
                self._loop.run()
        except Exception as e:
            logger.error("MainLoop error: %s", e)

    def _stop_main_loop(self) -> None:
        """Stop the GLib main loop."""
        if self._loop:
            self._loop.quit()
            self._loop = None

        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=2.0)
            self._loop_thread = None

        logger.debug("GLib MainLoop stopped")

    def _handle_about_to_finish(self, player: Gst.Element) -> None:
        """
        Handle the about-to-finish signal for gapless playback.
        Called from streaming thread ~2 seconds before current video ends.

        Args:
            player: The playbin3 element
        """
        logger.debug("About to finish current video")

        if self._on_about_to_finish:
            next_uri = self._on_about_to_finish()
            if next_uri:
                # Handle consecutive same video by resetting pipeline state
                # This is a known GStreamer limitation
                if next_uri == self._current_uri:
                    logger.debug("Same video requested, will reset state after EOS")
                    self._next_uri_queued = False
                    return

                logger.info("Queuing next video: %s", next_uri)
                player.set_property('uri', next_uri)
                self._next_uri_queued = True
                self._current_uri = next_uri
            else:
                self._next_uri_queued = False
        else:
            self._next_uri_queued = False

    def _handle_error(self, bus: Gst.Bus, message: Gst.Message) -> None:
        """
        Handle GStreamer error messages.

        Args:
            bus: The message bus
            message: The error message
        """
        error, debug_info = message.parse_error()
        error_msg = f"GStreamer error: {error.message}"
        if debug_info:
            error_msg += f" (debug: {debug_info})"

        logger.error(error_msg)
        self._state = PlayerState.ERROR

        if self._on_error:
            self._on_error(error_msg)

    def _handle_eos(self, bus: Gst.Bus, message: Gst.Message) -> None:
        """
        Handle end-of-stream signal.

        Args:
            bus: The message bus
            message: The EOS message
        """
        logger.debug("End of stream reached")

        # If no next URI was queued, notify callback
        if not self._next_uri_queued:
            # Handle looping same video by resetting pipeline
            if self._on_about_to_finish:
                next_uri = self._on_about_to_finish()
                if next_uri:
                    logger.info("Playing next video after EOS: %s", next_uri)
                    self.play(next_uri)
                    return

            if self._on_eos:
                self._on_eos()

    def _handle_state_changed(self, bus: Gst.Bus, message: Gst.Message) -> None:
        """
        Handle pipeline state change messages.

        Args:
            bus: The message bus
            message: The state change message
        """
        if message.src != self._player:
            return

        old_state, new_state, pending_state = message.parse_state_changed()
        logger.debug(
            "State changed: %s -> %s (pending: %s)",
            old_state.value_nick,
            new_state.value_nick,
            pending_state.value_nick
        )

    def _handle_sync_message(self, bus: Gst.Bus, message: Gst.Message) -> None:
        """Handle sync messages — used to set XID when pipeline requests a window."""
        if message.get_structure() is None:
            return
        if message.get_structure().get_name() == 'prepare-window-handle':
            if self._window_xid:
                logger.info("Pipeline requested window — setting XID: %s", self._window_xid)
                GstVideo.VideoOverlay.set_window_handle(message.src, self._window_xid)

    def set_window_handle(self, xid: int) -> None:
        """
        Set the X11 window handle for video output.

        Uses GstVideo.VideoOverlay interface to embed video in a GTK DrawingArea.

        Args:
            xid: X11 window ID
        """
        self._window_xid = xid
        logger.info("Stored window XID for video overlay: %s", xid)

        # If player is already initialized, set it on the sink now
        if self._player is not None:
            video_sink = self._player.get_property('video-sink')
            if video_sink:
                GstVideo.VideoOverlay.set_window_handle(video_sink, xid)
                logger.info("Set video overlay window handle: %s", xid)

    def initialize(self) -> bool:
        """
        Initialize the GStreamer player components.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            with self._lock:
                if self._player is not None:
                    logger.warning("Player already initialized")
                    return True

                self._player = self._create_player()
                self._setup_bus()
                # Note: Do NOT start a separate GLib.MainLoop here.
                # GTK's main loop already handles GStreamer bus messages
                # via add_signal_watch(). A second loop causes X11 threading crashes.

            logger.info("GStreamer player initialized successfully")
            return True

        except Exception as e:
            logger.error("Failed to initialize player: %s", e)
            self._state = PlayerState.ERROR
            return False

    def play(self, uri: Optional[str] = None) -> bool:
        """
        Start playback of a video.

        Args:
            uri: URI of the video to play (file:// or http://).
                 If None, resumes current video.

        Returns:
            True if playback started successfully, False otherwise
        """
        with self._lock:
            if self._player is None:
                if not self.initialize():
                    return False

            if uri:
                # Store last URI for consecutive video handling
                self._last_uri = self._current_uri

                # Validate URI
                if not uri.startswith(('file://', 'http://', 'https://')):
                    # Assume local file path, convert to URI
                    file_path = Path(uri)
                    if not file_path.is_absolute():
                        file_path = self.media_dir / uri
                    uri = f"file://{file_path}"

                # Check if file exists for local files
                if uri.startswith('file://'):
                    file_path = Path(uri[7:])  # Remove 'file://' prefix
                    if not file_path.exists():
                        logger.error("Video file not found: %s", file_path)
                        if self._on_error:
                            self._on_error(f"File not found: {file_path}")
                        return False

                # Reset pipeline state for consecutive same video
                if uri == self._last_uri:
                    logger.debug("Same video as last, resetting pipeline state")
                    self._player.set_state(Gst.State.NULL)

                logger.info("Playing: %s", uri)
                self._player.set_property('uri', uri)
                self._current_uri = uri
                self._next_uri_queued = False

            # Set state to PLAYING
            ret = self._player.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                logger.error("Failed to set player state to PLAYING")
                self._state = PlayerState.ERROR
                return False

            self._state = PlayerState.PLAYING
            return True

    def play_file(self, filename: str) -> bool:
        """
        Play a video file from the media directory.

        Args:
            filename: Name of the video file in the media directory

        Returns:
            True if playback started successfully, False otherwise
        """
        file_path = self.media_dir / filename
        return self.play(str(file_path))

    def pause(self) -> bool:
        """
        Pause playback.

        Returns:
            True if pause successful, False otherwise
        """
        with self._lock:
            if self._player is None:
                return False

            ret = self._player.set_state(Gst.State.PAUSED)
            if ret == Gst.StateChangeReturn.FAILURE:
                logger.error("Failed to pause playback")
                return False

            self._state = PlayerState.PAUSED
            logger.info("Playback paused")
            return True

    def resume(self) -> bool:
        """
        Resume playback after pause.

        Returns:
            True if resume successful, False otherwise
        """
        return self.play()

    def stop(self) -> bool:
        """
        Stop playback and reset pipeline.

        Returns:
            True if stop successful, False otherwise
        """
        with self._lock:
            if self._player is None:
                return True

            ret = self._player.set_state(Gst.State.NULL)
            if ret == Gst.StateChangeReturn.FAILURE:
                logger.error("Failed to stop playback")
                return False

            self._state = PlayerState.STOPPED
            self._current_uri = None
            self._next_uri_queued = False
            logger.info("Playback stopped")
            return True

    def get_position(self) -> float:
        """
        Get current playback position in seconds.

        Returns:
            Current position in seconds, or -1.0 if unavailable
        """
        if self._player is None:
            return -1.0

        success, position = self._player.query_position(Gst.Format.TIME)
        if success:
            return position / Gst.SECOND
        return -1.0

    def get_duration(self) -> float:
        """
        Get duration of current video in seconds.

        Returns:
            Duration in seconds, or -1.0 if unavailable
        """
        if self._player is None:
            return -1.0

        success, duration = self._player.query_duration(Gst.Format.TIME)
        if success:
            return duration / Gst.SECOND
        return -1.0

    def seek(self, position: float) -> bool:
        """
        Seek to a position in the video.

        Args:
            position: Position in seconds to seek to

        Returns:
            True if seek successful, False otherwise
        """
        if self._player is None:
            return False

        position_ns = int(position * Gst.SECOND)
        return self._player.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            position_ns
        )

    @property
    def state(self) -> PlayerState:
        """Get current player state."""
        return self._state

    @property
    def current_uri(self) -> Optional[str]:
        """Get currently playing URI."""
        return self._current_uri

    @property
    def is_playing(self) -> bool:
        """Check if player is currently playing."""
        return self._state == PlayerState.PLAYING

    @property
    def is_initialized(self) -> bool:
        """Check if player has been initialized."""
        return self._player is not None

    def cleanup(self) -> None:
        """Clean up player resources."""
        logger.info("Cleaning up GStreamer player")

        self.stop()

        with self._lock:
            if self._bus:
                self._bus.remove_signal_watch()
                self._bus = None

            self._stop_main_loop()
            self._player = None

        logger.info("GStreamer player cleanup complete")

    def __enter__(self) -> 'GStreamerPlayer':
        """Context manager entry."""
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.cleanup()

    def __repr__(self) -> str:
        """String representation."""
        return f"GStreamerPlayer(state={self._state.value}, uri={self._current_uri})"


# Global player instance
_global_player: Optional[GStreamerPlayer] = None


def get_gstreamer_player(
    media_dir: Optional[str] = None,
    on_about_to_finish: Optional[Callable[[], Optional[str]]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    on_eos: Optional[Callable[[], None]] = None
) -> GStreamerPlayer:
    """
    Get the global GStreamer player instance.

    Args:
        media_dir: Directory where media files are stored (only used on first call)
        on_about_to_finish: Callback for gapless playback (only used on first call)
        on_error: Callback for errors (only used on first call)
        on_eos: Callback for end-of-stream (only used on first call)

    Returns:
        GStreamerPlayer instance
    """
    global _global_player

    if _global_player is None:
        _global_player = GStreamerPlayer(
            media_dir=media_dir,
            on_about_to_finish=on_about_to_finish,
            on_error=on_error,
            on_eos=on_eos
        )

    return _global_player
