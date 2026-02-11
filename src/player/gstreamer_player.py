"""
GStreamer player module with NVIDIA hardware acceleration.
Custom pipeline for Jetson Orin Nano — no playbin.

Pipeline:
  filesrc → qtdemux → { video: h264parse → nvv4l2decoder → nvvidconv → xvimagesink
                         audio: queue → avdec_aac → audioconvert → pulsesink }

Strategy:
 1. Pre-fetch: A position watchdog fires ~2s before EOS and asks the playlist
    for the next URI (stored in _next_uri).
 2. On EOS: restart immediately via GLib.idle_add with READY state.
    Same-video loops use seek-to-zero for seamless replay.

playbin is NOT used because it inserts software videoconvert between
nvv4l2decoder and the sink, causing 80%+ CPU on Jetson.
"""

import logging
import threading
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gst, GstVideo, GLib

Gst.init(None)

from src.common.logger import setup_logger
logger = setup_logger(__name__)


class PlayerState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    ERROR = "error"


class GStreamerPlayer:
    """
    Hardware-accelerated GStreamer player for Jetson Orin Nano.
    Uses a custom pipeline with nvv4l2decoder + nvvidconv for ~15% CPU
    (vs ~85% with playbin's software path).
    """

    DEFAULT_MEDIA_DIR = "/home/skillz/media"
    _WATCHDOG_INTERVAL_MS = 500
    _PREQUEUE_SECONDS = 2.0

    def __init__(
        self,
        media_dir: Optional[str] = None,
        on_about_to_finish: Optional[Callable[[], Optional[str]]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_eos: Optional[Callable[[], None]] = None
    ):
        self.media_dir = Path(media_dir) if media_dir else Path(self.DEFAULT_MEDIA_DIR)
        self._on_about_to_finish = on_about_to_finish
        self._on_error = on_error
        self._on_eos = on_eos

        self._pipeline: Optional[Gst.Pipeline] = None
        self._filesrc: Optional[Gst.Element] = None
        self._videosink: Optional[Gst.Element] = None
        self._bus: Optional[Gst.Bus] = None
        self._state = PlayerState.STOPPED
        self._lock = threading.Lock()

        # --- URI tracking ---
        self._playing_uri: Optional[str] = None
        self._next_uri: Optional[str] = None
        self._prefetched = False

        # X11 window handle for embedding video in GTK
        self._window_xid: Optional[int] = None

        # Position watchdog timer ID
        self._watchdog_id: Optional[int] = None

        logger.info("GStreamerPlayer initialized with media_dir: %s", self.media_dir)

    # ------------------------------------------------------------------
    # Pipeline creation
    # ------------------------------------------------------------------

    def _create_pipeline(self, filepath: str) -> Gst.Pipeline:
        """
        Build: filesrc → qtdemux → { video branch, audio branch }

        Audio is optional — if the file has no audio track, the pipeline
        still works because qtdemux simply won't link the audio pad.
        """
        pipeline = Gst.Pipeline.new('player')

        # Source + demuxer
        self._filesrc = Gst.ElementFactory.make('filesrc', 'filesrc')
        qtdemux = Gst.ElementFactory.make('qtdemux', 'demux')

        # Video branch: h264parse → nvv4l2decoder → nvvidconv → xvimagesink
        vqueue = Gst.ElementFactory.make('queue', 'vqueue')
        h264parse = Gst.ElementFactory.make('h264parse', 'h264parse')
        nvdecoder = Gst.ElementFactory.make('nvv4l2decoder', 'nvdecoder')
        nvvidconv = Gst.ElementFactory.make('nvvidconv', 'nvvidconv')
        self._videosink = Gst.ElementFactory.make('xvimagesink', 'videosink')

        if not all([self._filesrc, qtdemux, vqueue, h264parse, nvdecoder, nvvidconv, self._videosink]):
            # Fallback: try without HW decoder
            logger.warning("Some HW elements unavailable, trying software fallback")
            return self._create_fallback_pipeline(filepath)

        self._videosink.set_property('sync', True)

        # Audio branch: queue → avdec_aac → audioconvert → audioresample → pulsesink
        aqueue = Gst.ElementFactory.make('queue', 'aqueue')
        aac_dec = Gst.ElementFactory.make('avdec_aac', 'aacdec')
        audioconv = Gst.ElementFactory.make('audioconvert', 'audioconv')
        audioresamp = Gst.ElementFactory.make('audioresample', 'audioresamp')
        audiosink = Gst.ElementFactory.make('pulsesink', 'audiosink')
        if not audiosink:
            audiosink = Gst.ElementFactory.make('autoaudiosink', 'audiosink')

        has_audio = all([aqueue, aac_dec, audioconv, audioresamp, audiosink])
        if audiosink:
            audiosink.set_property('sync', True)

        # Set file location
        self._filesrc.set_property('location', filepath)

        # Add all elements to pipeline
        for el in [self._filesrc, qtdemux, vqueue, h264parse, nvdecoder, nvvidconv, self._videosink]:
            pipeline.add(el)

        if has_audio:
            for el in [aqueue, aac_dec, audioconv, audioresamp, audiosink]:
                pipeline.add(el)

        # Link static elements
        self._filesrc.link(qtdemux)
        vqueue.link(h264parse)
        h264parse.link(nvdecoder)
        nvdecoder.link(nvvidconv)
        nvvidconv.link(self._videosink)

        if has_audio:
            aqueue.link(aac_dec)
            aac_dec.link(audioconv)
            audioconv.link(audioresamp)
            audioresamp.link(audiosink)

        # Dynamic pad linking from qtdemux
        def on_pad_added(demux, pad):
            pad_name = pad.get_name()
            caps = pad.get_current_caps()
            struct_name = caps.get_structure(0).get_name() if caps else ""

            if "video" in struct_name or "video" in pad_name:
                sink_pad = vqueue.get_static_pad('sink')
                if not sink_pad.is_linked():
                    pad.link(sink_pad)
                    logger.info("Linked video pad: %s", pad_name)
            elif "audio" in struct_name or "audio" in pad_name:
                if has_audio:
                    sink_pad = aqueue.get_static_pad('sink')
                    if not sink_pad.is_linked():
                        pad.link(sink_pad)
                        logger.info("Linked audio pad: %s", pad_name)

        qtdemux.connect('pad-added', on_pad_added)

        # Apply window handle if already set
        if self._window_xid:
            GstVideo.VideoOverlay.set_window_handle(self._videosink, self._window_xid)

        logger.info("Pipeline created: filesrc → qtdemux → nvv4l2decoder → nvvidconv → xvimagesink (HW accelerated)")
        return pipeline

    def _create_fallback_pipeline(self, filepath: str) -> Gst.Pipeline:
        """Fallback: use playbin if HW elements are unavailable."""
        pipeline_str = f'playbin uri=file://{filepath}'
        pipeline = Gst.parse_launch(pipeline_str)
        if not isinstance(pipeline, Gst.Pipeline):
            wrapper = Gst.Pipeline.new('player')
            wrapper.add(pipeline)
            pipeline = wrapper
        logger.warning("Using playbin fallback (no HW acceleration)")
        return pipeline

    def _setup_bus(self) -> None:
        if self._pipeline is None:
            return
        self._bus = self._pipeline.get_bus()
        if self._bus:
            self._bus.add_signal_watch()
            self._bus.connect('message::error', self._handle_error)
            self._bus.connect('message::eos', self._handle_eos)
            self._bus.connect('message::state-changed', self._handle_state_changed)
            self._bus.enable_sync_message_emission()
            self._bus.connect('sync-message::element', self._handle_sync_message)

    # ------------------------------------------------------------------
    # Pre-fetch: get the next URI before EOS arrives
    # ------------------------------------------------------------------

    def _prefetch_next(self, source: str) -> None:
        if self._prefetched:
            return
        self._prefetched = True

        if not self._on_about_to_finish:
            return

        next_uri = self._on_about_to_finish()
        if next_uri:
            self._next_uri = next_uri
            name = Path(next_uri).name if next_uri.startswith('file://') else next_uri
            logger.info("Pre-fetched next (%s): %s", source, name)
        else:
            logger.info("Pre-fetch (%s): no next URI available", source)

    # ------------------------------------------------------------------
    # Position watchdog
    # ------------------------------------------------------------------

    def _start_watchdog(self) -> None:
        self._cancel_watchdog()
        self._watchdog_id = GLib.timeout_add(self._WATCHDOG_INTERVAL_MS, self._watchdog_tick)

    def _cancel_watchdog(self) -> None:
        if self._watchdog_id is not None:
            GLib.source_remove(self._watchdog_id)
            self._watchdog_id = None

    def _watchdog_tick(self) -> bool:
        if self._state != PlayerState.PLAYING or self._pipeline is None:
            return True

        if self._prefetched:
            return True

        ok_pos, position = self._pipeline.query_position(Gst.Format.TIME)
        ok_dur, duration = self._pipeline.query_duration(Gst.Format.TIME)

        if not ok_pos or not ok_dur or duration <= 0:
            return True

        remaining = (duration - position) / Gst.SECOND
        if remaining <= self._PREQUEUE_SECONDS:
            logger.info("Watchdog: %.1fs remaining — pre-fetching next", remaining)
            self._prefetch_next("watchdog")

        return True

    # ------------------------------------------------------------------
    # Bus message handlers
    # ------------------------------------------------------------------

    def _handle_error(self, bus: Gst.Bus, message: Gst.Message) -> None:
        error, debug_info = message.parse_error()
        error_msg = f"GStreamer error: {error.message}"
        if debug_info:
            error_msg += f" (debug: {debug_info})"
        logger.error(error_msg)
        self._state = PlayerState.ERROR
        if self._on_error:
            self._on_error(error_msg)

    def _handle_eos(self, bus: Gst.Bus, message: Gst.Message) -> None:
        playing = self._playing_uri
        logger.info("EOS reached (playing=%s)",
                     Path(playing).name if playing and playing.startswith('file://') else playing)

        next_uri = self._next_uri
        if next_uri:
            logger.info("EOS: using pre-fetched URI")
        elif self._on_about_to_finish:
            next_uri = self._on_about_to_finish()
            if next_uri:
                logger.info("EOS: got next URI from playlist (no pre-fetch)")

        if next_uri:
            GLib.idle_add(self._restart_with_uri, next_uri)
        elif self._on_eos:
            logger.warning("EOS with no next video available")
            self._on_eos()

    def _uri_to_filepath(self, uri: str) -> str:
        """Convert file:// URI to local path."""
        if uri.startswith('file://'):
            return uri[7:]
        return uri

    def _restart_with_uri(self, uri: str) -> bool:
        """
        Restart pipeline with a new URI.  Called via GLib.idle_add.

        Same video  → seek to 0 (seamless, no pipeline rebuild).
        Different   → rebuild pipeline with new filesrc location.

        Returns False (GLib: don't repeat).
        """
        if self._pipeline is None:
            return False

        with self._lock:
            if uri == self._playing_uri:
                # Same video — seek to start
                self._pipeline.seek_simple(
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    0
                )
                logger.info("Looping (seek): %s",
                             Path(uri).name if uri.startswith('file://') else uri)
            else:
                # Different video — rebuild pipeline
                filepath = self._uri_to_filepath(uri)
                self._pipeline.set_state(Gst.State.NULL)

                # Clean up old bus
                if self._bus:
                    self._bus.remove_signal_watch()
                    self._bus = None

                self._pipeline = self._create_pipeline(filepath)
                self._setup_bus()

                ret = self._pipeline.set_state(Gst.State.PLAYING)
                if ret == Gst.StateChangeReturn.FAILURE:
                    logger.error("Failed to start pipeline for: %s", uri)
                    self._state = PlayerState.ERROR
                    return False
                logger.info("Playing: %s",
                             Path(uri).name if uri.startswith('file://') else uri)

            self._playing_uri = uri
            self._next_uri = None
            self._prefetched = False
            self._state = PlayerState.PLAYING

        self._start_watchdog()
        return False

    def _handle_state_changed(self, bus: Gst.Bus, message: Gst.Message) -> None:
        if message.src != self._pipeline:
            return
        old_state, new_state, pending_state = message.parse_state_changed()
        logger.debug("State changed: %s -> %s (pending: %s)",
                     old_state.value_nick, new_state.value_nick, pending_state.value_nick)

    def _handle_sync_message(self, bus: Gst.Bus, message: Gst.Message) -> None:
        if message.get_structure() is None:
            return
        if message.get_structure().get_name() == 'prepare-window-handle':
            if self._window_xid:
                logger.info("Pipeline requested window — setting XID: %s", self._window_xid)
                GstVideo.VideoOverlay.set_window_handle(message.src, self._window_xid)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_window_handle(self, xid: int) -> None:
        self._window_xid = xid
        logger.info("Stored window XID for video overlay: %s", xid)
        if self._videosink:
            GstVideo.VideoOverlay.set_window_handle(self._videosink, xid)
            logger.info("Set video overlay window handle: %s", xid)

    def initialize(self) -> bool:
        try:
            with self._lock:
                if self._pipeline is not None:
                    logger.warning("Player already initialized")
                    return True
                # Create a dummy pipeline — actual pipeline built on play()
                self._pipeline = Gst.Pipeline.new('player')
                self._setup_bus()
            logger.info("GStreamer player initialized successfully")
            return True
        except Exception as e:
            logger.error("Failed to initialize player: %s", e)
            self._state = PlayerState.ERROR
            return False

    def play(self, uri: Optional[str] = None) -> bool:
        with self._lock:
            if uri:
                if not uri.startswith(('file://', 'http://', 'https://')):
                    file_path = Path(uri)
                    if not file_path.is_absolute():
                        file_path = self.media_dir / uri
                    uri = f"file://{file_path}"

                filepath = self._uri_to_filepath(uri)
                if not Path(filepath).exists():
                    logger.error("Video file not found: %s", filepath)
                    if self._on_error:
                        self._on_error(f"File not found: {filepath}")
                    return False

                # Tear down old pipeline
                if self._pipeline:
                    self._pipeline.set_state(Gst.State.NULL)
                if self._bus:
                    self._bus.remove_signal_watch()
                    self._bus = None

                # Build new pipeline for this file
                self._pipeline = self._create_pipeline(filepath)
                self._setup_bus()
                self._playing_uri = uri
                self._next_uri = None
                self._prefetched = False

                logger.info("Playing: %s", Path(filepath).name)

            if self._pipeline is None:
                logger.error("No pipeline to play")
                return False

            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                logger.error("Failed to set pipeline to PLAYING")
                self._state = PlayerState.ERROR
                return False

            self._state = PlayerState.PLAYING

        self._start_watchdog()
        return True

    def play_file(self, filename: str) -> bool:
        file_path = self.media_dir / filename
        return self.play(str(file_path))

    def pause(self) -> bool:
        with self._lock:
            if self._pipeline is None:
                return False
            ret = self._pipeline.set_state(Gst.State.PAUSED)
            if ret == Gst.StateChangeReturn.FAILURE:
                logger.error("Failed to pause playback")
                return False
            self._state = PlayerState.PAUSED
            logger.info("Playback paused")
            return True

    def resume(self) -> bool:
        with self._lock:
            if self._pipeline is None:
                return False
            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                return False
            self._state = PlayerState.PLAYING
        return True

    def stop(self) -> bool:
        self._cancel_watchdog()
        with self._lock:
            if self._pipeline is None:
                return True
            ret = self._pipeline.set_state(Gst.State.NULL)
            if ret == Gst.StateChangeReturn.FAILURE:
                logger.error("Failed to stop playback")
                return False
            self._state = PlayerState.STOPPED
            self._playing_uri = None
            self._next_uri = None
            self._prefetched = False
            logger.info("Playback stopped")
            return True

    def get_position(self) -> float:
        if self._pipeline is None:
            return -1.0
        success, position = self._pipeline.query_position(Gst.Format.TIME)
        if success:
            return position / Gst.SECOND
        return -1.0

    def get_duration(self) -> float:
        if self._pipeline is None:
            return -1.0
        success, duration = self._pipeline.query_duration(Gst.Format.TIME)
        if success:
            return duration / Gst.SECOND
        return -1.0

    def seek(self, position: float) -> bool:
        if self._pipeline is None:
            return False
        position_ns = int(position * Gst.SECOND)
        return self._pipeline.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            position_ns
        )

    @property
    def state(self) -> PlayerState:
        return self._state

    @property
    def current_uri(self) -> Optional[str]:
        return self._playing_uri

    @property
    def is_playing(self) -> bool:
        return self._state == PlayerState.PLAYING

    @property
    def is_initialized(self) -> bool:
        return self._pipeline is not None

    def cleanup(self) -> None:
        logger.info("Cleaning up GStreamer player")
        self._cancel_watchdog()
        self.stop()
        with self._lock:
            if self._bus:
                self._bus.remove_signal_watch()
                self._bus = None
            self._pipeline = None
            self._filesrc = None
            self._videosink = None
        logger.info("GStreamer player cleanup complete")

    def __enter__(self) -> 'GStreamerPlayer':
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()

    def __repr__(self) -> str:
        return f"GStreamerPlayer(state={self._state.value}, uri={self._playing_uri})"


# Global player instance
_global_player: Optional[GStreamerPlayer] = None


def get_gstreamer_player(
    media_dir: Optional[str] = None,
    on_about_to_finish: Optional[Callable[[], Optional[str]]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    on_eos: Optional[Callable[[], None]] = None
) -> GStreamerPlayer:
    global _global_player
    if _global_player is None:
        _global_player = GStreamerPlayer(
            media_dir=media_dir,
            on_about_to_finish=on_about_to_finish,
            on_error=on_error,
            on_eos=on_eos
        )
    return _global_player
