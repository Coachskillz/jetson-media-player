"""
Base camera class for DeepStream CSI camera pipelines.

Provides common functionality for both safety and commercial cameras
including pipeline creation, lifecycle management, and health monitoring.
"""

import os
import logging
import threading
from abc import ABC, abstractmethod
from typing import Optional, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class PipelineState(Enum):
    """Pipeline lifecycle states."""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    STOPPED = "stopped"


class BaseCamera(ABC):
    """
    Abstract base class for DeepStream camera pipelines.

    Handles GStreamer/DeepStream pipeline lifecycle, bus message handling,
    and common configuration. Subclasses implement pipeline-specific
    elements and probe callbacks.
    """

    def __init__(
        self,
        sensor_id: int,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        config_path: Optional[str] = None,
    ):
        self.sensor_id = sensor_id
        self.width = width
        self.height = height
        self.fps = fps
        self.config_path = config_path

        self._state = PipelineState.IDLE
        self._pipeline = None
        self._main_loop = None
        self._loop_thread: Optional[threading.Thread] = None
        self._error_callback: Optional[Callable] = None
        self._restart_count = 0
        self._max_restarts = 5

        # Health metrics
        self.frames_processed = 0
        self.detections_count = 0
        self.errors_count = 0

    @property
    def state(self) -> PipelineState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == PipelineState.RUNNING

    @abstractmethod
    def _build_pipeline(self):
        """Build the DeepStream pipeline. Implemented by subclasses."""
        pass

    @abstractmethod
    def _attach_probes(self):
        """Attach probe callbacks to pipeline elements. Implemented by subclasses."""
        pass

    @abstractmethod
    def _get_pipeline_name(self) -> str:
        """Return a human-readable name for this pipeline."""
        pass

    def start(self):
        """Start the camera pipeline."""
        if self._state == PipelineState.RUNNING:
            logger.warning(f"{self._get_pipeline_name()}: Already running")
            return

        self._state = PipelineState.STARTING
        logger.info(f"{self._get_pipeline_name()}: Starting pipeline (sensor_id={self.sensor_id})")

        try:
            # Import GStreamer (may not be available on dev machines)
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst, GLib

            if not Gst.is_initialized():
                Gst.init(None)

            # Build pipeline
            self._pipeline = self._build_pipeline()
            if self._pipeline is None:
                raise RuntimeError("Pipeline build returned None")

            # Attach probe callbacks
            self._attach_probes()

            # Set up bus watch
            bus = self._pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message::error", self._on_error)
            bus.connect("message::eos", self._on_eos)
            bus.connect("message::warning", self._on_warning)
            bus.connect("message::state-changed", self._on_state_changed)

            # Start pipeline
            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("Failed to set pipeline to PLAYING")

            # Run GLib main loop in background thread
            self._main_loop = GLib.MainLoop()
            self._loop_thread = threading.Thread(
                target=self._main_loop.run,
                daemon=True,
                name=f"{self._get_pipeline_name()}-loop",
            )
            self._loop_thread.start()

            self._state = PipelineState.RUNNING
            self._restart_count = 0
            logger.info(f"{self._get_pipeline_name()}: Pipeline running")

        except ImportError:
            self._state = PipelineState.ERROR
            logger.error(
                f"{self._get_pipeline_name()}: GStreamer not available. "
                "Install GStreamer and PyGObject on the Jetson."
            )
        except Exception as e:
            self._state = PipelineState.ERROR
            self.errors_count += 1
            logger.error(f"{self._get_pipeline_name()}: Failed to start: {e}")
            if self._error_callback:
                self._error_callback(e)

    def stop(self):
        """Stop the camera pipeline gracefully."""
        if self._state in (PipelineState.IDLE, PipelineState.STOPPED):
            return

        logger.info(f"{self._get_pipeline_name()}: Stopping pipeline")

        try:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst

            if self._pipeline:
                self._pipeline.set_state(Gst.State.NULL)
                self._pipeline = None

            if self._main_loop and self._main_loop.is_running():
                self._main_loop.quit()
                self._main_loop = None

            if self._loop_thread and self._loop_thread.is_alive():
                self._loop_thread.join(timeout=5)
                self._loop_thread = None

        except Exception as e:
            logger.error(f"{self._get_pipeline_name()}: Error during stop: {e}")

        self._state = PipelineState.STOPPED
        logger.info(f"{self._get_pipeline_name()}: Pipeline stopped")

    def restart(self):
        """Restart the pipeline after an error."""
        if self._restart_count >= self._max_restarts:
            logger.error(
                f"{self._get_pipeline_name()}: Max restarts ({self._max_restarts}) exceeded"
            )
            return

        self._restart_count += 1
        logger.warning(
            f"{self._get_pipeline_name()}: Restarting (attempt {self._restart_count})"
        )
        self.stop()

        import time
        time.sleep(5)  # Wait before restart

        self.start()

    def set_error_callback(self, callback: Callable):
        """Set a callback for pipeline errors."""
        self._error_callback = callback

    def get_health(self) -> dict:
        """Return health metrics for this camera pipeline."""
        return {
            "pipeline": self._get_pipeline_name(),
            "state": self._state.value,
            "sensor_id": self.sensor_id,
            "resolution": f"{self.width}x{self.height}",
            "fps": self.fps,
            "frames_processed": self.frames_processed,
            "detections_count": self.detections_count,
            "errors_count": self.errors_count,
            "restart_count": self._restart_count,
        }

    # GStreamer bus message handlers

    def _on_error(self, bus, message):
        err, debug = message.parse_error()
        logger.error(f"{self._get_pipeline_name()}: Pipeline error: {err.message}")
        logger.debug(f"{self._get_pipeline_name()}: Debug: {debug}")
        self.errors_count += 1
        self._state = PipelineState.ERROR
        self.restart()

    def _on_eos(self, bus, message):
        logger.info(f"{self._get_pipeline_name()}: End of stream")
        # For live camera, EOS shouldn't happen - restart
        self.restart()

    def _on_warning(self, bus, message):
        warn, debug = message.parse_warning()
        logger.warning(f"{self._get_pipeline_name()}: {warn.message}")

    def _on_state_changed(self, bus, message):
        if message.src == self._pipeline:
            old, new, pending = message.parse_state_changed()
            logger.debug(
                f"{self._get_pipeline_name()}: State changed: "
                f"{old.value_nick} -> {new.value_nick}"
            )

    # Utility methods for subclasses

    def _create_element(self, factory_name: str, name: str, properties: dict = None):
        """Create a GStreamer element with optional properties."""
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        element = Gst.ElementFactory.make(factory_name, name)
        if element is None:
            raise RuntimeError(f"Failed to create element: {factory_name}")

        if properties:
            for key, value in properties.items():
                element.set_property(key, value)

        return element

    def _create_caps_filter(self, caps_string: str, name: str = "capsfilter"):
        """Create a capsfilter element."""
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        caps = Gst.Caps.from_string(caps_string)
        capsfilter = Gst.ElementFactory.make("capsfilter", name)
        capsfilter.set_property("caps", caps)
        return capsfilter
