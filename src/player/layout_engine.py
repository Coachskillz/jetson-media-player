"""
Layout Rendering Engine for NVIDIA Jetson Orin Nano.

Hardware-accelerated video playback with aspect ratio preservation.
For Phase 1 (April launch), single-zone full-screen support.

Architecture (single-zone):
    filesrc → qtdemux → nvv4l2decoder → nvvidconv → nveglglessink

    At EOS, destroy old pipeline and build new one for next video.
    xvimagesink with force-aspect-ratio=true handles letterbox/pillarbox.

Performance targets:
    - CPU: <15% sustained
    - NVIDIA memory: flat, no growth
    - Zero errors over 8+ hours
"""

import json
import logging
import resource
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gst, GstVideo, GLib

Gst.init(None)

logger = logging.getLogger(__name__)


class _ZonePipeline:
    """
    Single GStreamer pipeline for one video.
    Built fresh every time. Destroyed completely after use.

    Pipeline (single-zone):
        filesrc → qtdemux → h264parse → nvv4l2decoder → nvvidconv → nveglglessink

    nveglglessink uses EGL for efficient X11 rendering with lower GPU overhead
    than xvimagesink, leaving headroom for AI/camera processing.
    """

    def __init__(
        self,
        filepath: str,
        zone_x: int,
        zone_y: int,
        zone_width: int,
        zone_height: int,
        window_xid: Optional[int] = None
    ):
        self.filepath = filepath
        self.zone_x = zone_x
        self.zone_y = zone_y
        self.zone_width = zone_width
        self.zone_height = zone_height
        self.window_xid = window_xid

        self.pipeline: Optional[Gst.Pipeline] = None
        self.bus: Optional[Gst.Bus] = None
        self._on_eos: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._built = False
        self._videosink = None

    def build(self) -> bool:
        """Build complete pipeline: decode → nvvidconv → nvdrmvideosink.

        Uses nvdrmvideosink for direct DRM rendering to minimize GPU usage.
        This leaves more GPU headroom for AI/camera processing.
        """
        pipeline = Gst.Pipeline.new(None)

        # === Input: file decode ===
        filesrc = Gst.ElementFactory.make("filesrc", None)
        qtdemux = Gst.ElementFactory.make("qtdemux", None)
        vqueue = Gst.ElementFactory.make("queue", "vqueue")
        h264parse = Gst.ElementFactory.make("h264parse", None)
        nvdecoder = Gst.ElementFactory.make("nvv4l2decoder", None)
        nvvidconv = Gst.ElementFactory.make("nvvidconv", "conv")

        # === Output: nveglglessink for EGL/GLES rendering ===
        videosink = Gst.ElementFactory.make("nveglglessink", "sink")

        # === Audio drain (only if video has audio) ===
        # Use queue2 with max-size-buffers=0 to not block if no audio
        aqueue = Gst.ElementFactory.make("queue", "aqueue")
        fakesink = Gst.ElementFactory.make("fakesink", "audio-drain")
        # Store for dynamic addition
        self._audio_queue = aqueue
        self._audio_sink = fakesink
        self._audio_linked = False

        if not all([filesrc, qtdemux, vqueue, h264parse, nvdecoder,
                    nvvidconv, videosink, aqueue, fakesink]):
            logger.error("Failed to create GStreamer elements: %s", self.filepath)
            return False

        # Configure input
        filesrc.set_property("location", self.filepath)

        # Configure nveglglessink
        videosink.set_property("sync", True)
        # Force aspect ratio preservation
        if videosink.find_property("force-aspect-ratio"):
            videosink.set_property("force-aspect-ratio", True)
        self._videosink = videosink

        # Audio drain
        fakesink.set_property("sync", False)

        # Add video elements only - audio added dynamically if present
        elements = [filesrc, qtdemux, vqueue, h264parse, nvdecoder,
                   nvvidconv, videosink]
        for el in elements:
            pipeline.add(el)

        # Link static chain: decode → nvvidconv → nveglglessink
        filesrc.link(qtdemux)
        vqueue.link(h264parse)
        h264parse.link(nvdecoder)
        nvdecoder.link(nvvidconv)
        nvvidconv.link(videosink)

        # Dynamic pad linking for demuxer (audio added only if present)
        def on_pad_added(demux, pad):
            pad_name = pad.get_name()
            caps = pad.get_current_caps()
            struct_name = caps.get_structure(0).get_name() if caps else ""

            if "video" in struct_name or "video" in pad_name:
                sink_pad = vqueue.get_static_pad("sink")
                if sink_pad and not sink_pad.is_linked():
                    pad.link(sink_pad)
                    logger.debug("Linked video pad: %s", pad_name)
            elif "audio" in struct_name or "audio" in pad_name:
                # Dynamically add audio drain only if audio track exists
                if not self._audio_linked:
                    pipeline.add(self._audio_queue)
                    pipeline.add(self._audio_sink)
                    self._audio_queue.link(self._audio_sink)
                    self._audio_queue.sync_state_with_parent()
                    self._audio_sink.sync_state_with_parent()
                    self._audio_linked = True
                sink_pad = self._audio_queue.get_static_pad("sink")
                if sink_pad and not sink_pad.is_linked():
                    pad.link(sink_pad)
                    logger.debug("Linked audio to drain: %s", pad_name)

        qtdemux.connect("pad-added", on_pad_added)

        # nveglglessink uses EGL/GLES for efficient rendering
        # Supports window embedding via GstVideoOverlay interface

        # Setup bus
        self.bus = pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message::eos", self._handle_eos)
        self.bus.connect("message::error", self._handle_error)

        self.pipeline = pipeline
        self._built = True
        logger.debug("Built pipeline: %s", Path(self.filepath).name)
        return True

    def preroll(self) -> bool:
        """Set to PAUSED - decoder initializes, first frame ready.

        Uses blocking wait - only call from non-GLib contexts.
        """
        if not self.pipeline:
            return False
        ret = self.pipeline.set_state(Gst.State.PAUSED)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error("Failed to pre-roll (immediate): %s", Path(self.filepath).name)
            return False
        # Wait for state change (up to 10 seconds)
        result = self.pipeline.get_state(10 * Gst.SECOND)
        ret_code = result[0]
        actual_state = result[1]
        if ret_code == Gst.StateChangeReturn.FAILURE:
            logger.error("Pre-roll failed: %s", Path(self.filepath).name)
            return False
        if ret_code == Gst.StateChangeReturn.ASYNC:
            logger.error("Pre-roll timeout (ASYNC): %s", Path(self.filepath).name)
            return False
        if actual_state != Gst.State.PAUSED:
            logger.error("Pre-roll wrong state: %s (got %s)", Path(self.filepath).name, actual_state.value_nick)
            return False
        logger.info("Pre-rolled: %s", Path(self.filepath).name)
        return True

    def play(self) -> bool:
        """Set to PLAYING - video starts immediately (already pre-rolled)."""
        if not self.pipeline:
            return False
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error("Failed to play: %s", Path(self.filepath).name)
            return False
        # Don't block - async state change is OK for PAUSED→PLAYING
        logger.info("Playing: %s", Path(self.filepath).name)
        return True

    def destroy(self) -> None:
        """Full teardown - waits for NULL state, frees all resources."""
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline.get_state(5 * Gst.SECOND)
        if self.bus:
            self.bus.remove_signal_watch()
            self.bus = None
        self.pipeline = None
        self._built = False
        logger.info("Destroyed: %s", Path(self.filepath).name)

    def get_position(self) -> float:
        if not self.pipeline:
            return -1.0
        ok, pos = self.pipeline.query_position(Gst.Format.TIME)
        return pos / Gst.SECOND if ok else -1.0

    def get_duration(self) -> float:
        if not self.pipeline:
            return -1.0
        ok, dur = self.pipeline.query_duration(Gst.Format.TIME)
        return dur / Gst.SECOND if ok else -1.0

    def set_window_and_restart(self, xid: int) -> bool:
        """Restart pipeline for swap.

        nvdrmvideosink uses direct DRM rendering, no X11 window needed.
        Just restart the pipeline to PLAYING state.
        """
        if not self.pipeline or not self._videosink:
            return False

        # Go to PLAYING (GStreamer handles state transition)
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error("Failed to restart: %s", Path(self.filepath).name)
            return False
        logger.info("Restarted: %s", Path(self.filepath).name)
        return True

    def set_window(self, xid: int) -> None:
        """Set X11 window handle for video overlay."""
        if self._videosink and xid:
            try:
                self._videosink.set_window_handle(xid)
            except Exception:
                pass  # Some sinks don't support window handle

    def set_eos_callback(self, callback: Callable) -> None:
        self._on_eos = callback

    def set_error_callback(self, callback: Callable) -> None:
        self._on_error = callback

    def _handle_eos(self, bus, message) -> None:
        logger.info("EOS: %s", Path(self.filepath).name)
        if self._on_eos:
            self._on_eos()

    def _handle_error(self, bus, message) -> None:
        error, debug = message.parse_error()
        logger.error("Error (%s): %s", Path(self.filepath).name, error.message)
        if self._on_error:
            self._on_error(error.message)


class LayoutEngine:
    """
    Hardware-accelerated video player for single-zone layouts.

    Manages video pipeline lifecycle: build, preroll, play, destroy.
    Uses nveglglessink for efficient X11/EGL rendering with lower GPU overhead
    than xvimagesink, leaving headroom for AI/camera processing.

    Flow:
    1. Build pipeline with window handle
    2. Preroll to PAUSED (decoder initializes)
    3. Play video
    4. At EOS: destroy old, build new, repeat
    """

    DEFAULT_MEDIA_DIR = "/home/skillz/media"

    def __init__(
        self,
        layout_json: dict,
        media_dir: Optional[str] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_eos: Optional[Callable[[], None]] = None
    ):
        self.layout_json = layout_json
        self.media_dir = Path(media_dir) if media_dir else Path(self.DEFAULT_MEDIA_DIR)
        self._on_error = on_error
        self._on_eos = on_eos

        # Parse first layer as primary zone
        layers = layout_json.get("layers", [])
        if layers:
            layer = layers[0]
            self.zone_x = layer.get("x", 0)
            self.zone_y = layer.get("y", 0)
            self.zone_width = layer.get("width", 1920)
            self.zone_height = layer.get("height", 1080)
            self._playlist_items = layer.get("items", [])
        else:
            # Fallback full-screen
            self.zone_x = 0
            self.zone_y = 0
            self.zone_width = 1920
            self.zone_height = 1080
            self._playlist_items = []

        self._active: Optional[_ZonePipeline] = None
        self._standby: Optional[_ZonePipeline] = None  # Pre-built pipeline for smooth transitions
        self._standby_filepath: Optional[str] = None

        self._playlist_index = 0
        self._playlist_reload_pending = False
        self._new_playlist_items: Optional[List[dict]] = None

        self._window_xid: Optional[int] = None
        self._lock = threading.Lock()
        self._running = False

        # Diagnostics
        self._transition_count = 0
        self._pipelines_created = 0
        self._start_time: Optional[float] = None

        logger.info(
            "LayoutEngine: zone (%d,%d) %dx%d, %d items",
            self.zone_x, self.zone_y, self.zone_width, self.zone_height,
            len(self._playlist_items)
        )

    def _get_next_uri(self) -> Optional[str]:
        """Get next video URI from playlist (advances index)."""
        # Check for pending playlist reload
        if self._playlist_reload_pending and self._new_playlist_items is not None:
            self._playlist_items = self._new_playlist_items
            self._new_playlist_items = None
            self._playlist_reload_pending = False
            self._playlist_index = 0
            logger.info("Playlist reloaded: %d items", len(self._playlist_items))

        if not self._playlist_items:
            return None

        if self._playlist_index >= len(self._playlist_items):
            self._playlist_index = 0

        item = self._playlist_items[self._playlist_index]
        self._playlist_index += 1

        filename = item.get("filename")
        if filename:
            return str(self.media_dir / filename)
        return None

    def _peek_next_uri(self) -> Optional[str]:
        """Peek at next video URI without advancing index."""
        if not self._playlist_items:
            return None

        peek_index = self._playlist_index
        if peek_index >= len(self._playlist_items):
            peek_index = 0

        item = self._playlist_items[peek_index]
        filename = item.get("filename")
        if filename:
            return str(self.media_dir / filename)
        return None

    def _build_pipeline(self, filepath: str, window_xid: Optional[int] = None) -> Optional[_ZonePipeline]:
        """Build a pipeline (without pre-roll)."""
        pipe = _ZonePipeline(
            filepath=filepath,
            zone_x=self.zone_x,
            zone_y=self.zone_y,
            zone_width=self.zone_width,
            zone_height=self.zone_height,
            window_xid=window_xid
        )
        if not pipe.build():
            return None
        self._pipelines_created += 1
        return pipe

    def _build_and_preroll(self, filepath: str, window_xid: Optional[int] = None) -> Optional[_ZonePipeline]:
        """Build a pipeline and pre-roll it.

        For nvcompositor pipelines, preroll requires window attachment.
        """
        pipe = self._build_pipeline(filepath, window_xid=window_xid)
        if not pipe:
            return None
        if not pipe.preroll():
            pipe.destroy()
            return None
        return pipe

    def _prepare_next(self) -> None:
        """Pre-build the next pipeline for faster transitions.

        Build pipeline only (no preroll) to minimize GPU usage.
        Preroll happens at swap time for minimal GPU overhead during playback.
        """
        if self._standby is not None:
            return

        filepath = self._peek_next_uri()
        if not filepath:
            return

        if not Path(filepath).exists():
            logger.warning("Next file not found: %s", Path(filepath).name)
            return

        # Build only - NO preroll to save GPU for AI/camera work
        pipe = self._build_pipeline(filepath, window_xid=None)
        if pipe:
            self._standby = pipe
            self._standby_filepath = filepath
            logger.info("Standby built: %s", Path(filepath).name)
        else:
            logger.warning("Failed to build standby: %s", Path(filepath).name)

    def _on_active_eos(self) -> bool:
        """Handle EOS - schedule swap on idle to avoid state changes in callback."""
        logger.info("EOS received - scheduling swap")
        GLib.idle_add(self._do_swap)
        return False

    def _do_swap(self) -> bool:
        """Execute the actual swap. Called from idle to avoid callback issues.

        Uses pre-built standby pipeline for faster transitions:
        1. Destroy old pipeline (releases window)
        2. Set window on pre-built standby, preroll, and play
        3. Falls back to building new pipeline if no standby
        """
        with self._lock:
            self._transition_count += 1
            old_active = self._active
            self._active = None

            # Destroy old pipeline FIRST to release window
            if old_active:
                old_active.destroy()

            # Try to use pre-built standby (faster path - already built)
            if self._standby is not None:
                pipe = self._standby
                filepath = self._standby_filepath
                self._standby = None
                self._standby_filepath = None

                # Set window, preroll, and play
                pipe.set_eos_callback(lambda: GLib.idle_add(self._on_active_eos))
                pipe.set_error_callback(lambda msg: GLib.idle_add(self._on_active_error, msg))
                pipe.set_window(self._window_xid)

                # Preroll and play
                if pipe.preroll() and pipe.play():
                    self._active = pipe
                    # Advance playlist index since we used the peeked item
                    self._playlist_index += 1
                    if self._playlist_index >= len(self._playlist_items):
                        self._playlist_index = 0
                    logger.info("Transition #%d: playing %s (fast)", self._transition_count, Path(filepath).name)
                else:
                    logger.error("Transition #%d: failed to start standby", self._transition_count)
                    pipe.destroy()
                    # Fall through to build new pipeline
                    pipe = None

            # Fallback: build new pipeline (slower path)
            if self._active is None:
                filepath = self._get_next_uri()
                if filepath and Path(filepath).exists():
                    pipe = self._build_and_preroll(filepath, window_xid=self._window_xid)
                    if pipe:
                        pipe.set_eos_callback(lambda: GLib.idle_add(self._on_active_eos))
                        pipe.set_error_callback(lambda msg: GLib.idle_add(self._on_active_error, msg))
                        pipe.play()
                        self._active = pipe
                        logger.info("Transition #%d: playing %s (fallback)", self._transition_count, Path(filepath).name)
                    else:
                        logger.error("Transition #%d: failed to build pipeline", self._transition_count)
                else:
                    logger.error("Transition #%d: no next video available", self._transition_count)

            # Log performance every 100 transitions
            if self._transition_count % 100 == 0:
                self._log_performance()

        # Prepare next standby immediately
        GLib.idle_add(self._prepare_next_idle)
        return False

    def _prepare_next_idle(self) -> bool:
        self._prepare_next()
        return False

    def _on_active_error(self, error_msg: str) -> bool:
        """Handle error - try to skip to next."""
        logger.error("Pipeline error: %s", error_msg)
        if self._on_error:
            self._on_error(error_msg)
        self._on_active_eos()
        return False

    def _log_performance(self) -> None:
        """Log performance metrics."""
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
        runtime = time.time() - self._start_time if self._start_time else 0
        logger.info(
            "Perf - transitions: %d, pipelines: %d, RSS: %dMB, runtime: %.1fh",
            self._transition_count, self._pipelines_created,
            rss_mb, runtime / 3600
        )

    # === Public API ===

    def set_window_handle(self, xid: int) -> None:
        """Set X11 window handle."""
        self._window_xid = xid
        if self._active:
            self._active.set_window(xid)

    def start(self) -> bool:
        """Start playback."""
        with self._lock:
            if self._running:
                return True

            uri = self._get_next_uri()
            if not uri or not Path(uri).exists():
                logger.error("No content to play")
                return False

            # Initial pipeline: build with window, preroll, play
            pipe = self._build_pipeline(uri, window_xid=self._window_xid)
            if not pipe:
                return False

            pipe.set_eos_callback(lambda: GLib.idle_add(self._on_active_eos))
            pipe.set_error_callback(lambda msg: GLib.idle_add(self._on_active_error, msg))

            # Initial start uses blocking preroll (not in GLib callback yet)
            if not pipe.preroll():
                pipe.destroy()
                return False
            if not pipe.play():
                pipe.destroy()
                return False

            self._active = pipe

            self._running = True
            self._start_time = time.time()
            logger.info("LayoutEngine started")

        # Prepare standby
        GLib.idle_add(self._prepare_next_idle)
        return True

    def stop(self) -> None:
        """Stop playback."""
        with self._lock:
            if self._active:
                self._active.destroy()
                self._active = None
            if self._standby:
                self._standby.destroy()
                self._standby = None
            self._standby_filepath = None
            self._running = False
            self._log_performance()
            logger.info("LayoutEngine stopped")

    def update_layout(self, new_layout_json: dict) -> None:
        """Queue layout update - applies at next transition."""
        layers = new_layout_json.get("layers", [])
        if layers:
            items = layers[0].get("items", [])
            self._new_playlist_items = items
            self._playlist_reload_pending = True
            logger.info("Layout update queued: %d items", len(items))

    def get_position(self) -> float:
        if self._active:
            return self._active.get_position()
        return -1.0

    def get_duration(self) -> float:
        if self._active:
            return self._active.get_duration()
        return -1.0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def transition_count(self) -> int:
        return self._transition_count

    def cleanup(self) -> None:
        """Full cleanup on shutdown."""
        self.stop()

    def __repr__(self) -> str:
        return (f"LayoutEngine(running={self._running}, "
                f"transitions={self._transition_count})")


# === Utility functions ===

def load_layout_from_file(filepath: str) -> Optional[dict]:
    """Load layout JSON from file."""
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load layout: %s - %s", filepath, e)
        return None


def create_fallback_layout(playlist_items: List[dict]) -> dict:
    """Create single-zone full-screen layout from playlist items."""
    return {
        "canvas_width": 1920,
        "canvas_height": 1080,
        "background_color": "#000000",
        "layers": [{
            "name": "default",
            "x": 0,
            "y": 0,
            "width": 1920,
            "height": 1080,
            "content_source": "playlist",
            "items": playlist_items
        }]
    }


def load_playlist_items_from_file(filepath: str) -> List[dict]:
    """Load playlist items from playlist.json."""
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
            return data.get("items", [])
    except Exception as e:
        logger.warning("Failed to load playlist: %s - %s", filepath, e)
        return []
