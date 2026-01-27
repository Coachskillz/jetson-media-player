#!/usr/bin/env python3
"""
Simple Fullscreen Media Player with Seamless Looping.
Uses GStreamer playbin3 with NVIDIA hardware acceleration.
"""

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# Initialize GStreamer
Gst.init(None)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_screen_resolution():
    """Get current screen resolution."""
    try:
        output = subprocess.check_output(
            ['xrandr', '--current'],
            env={**os.environ, 'DISPLAY': ':0'}
        ).decode()
        for line in output.split('\n'):
            if '*' in line:
                res = line.split()[0]
                w, h = res.split('x')
                return int(w), int(h)
    except Exception:
        pass
    return 1920, 1080


class SimplePlayer:
    """
    Simple fullscreen video player with seamless looping.
    """

    def __init__(self, video_path: str):
        self.video_path = Path(video_path).resolve()
        self.video_uri = f"file://{self.video_path}"

        self.screen_width, self.screen_height = get_screen_resolution()
        logger.info(f"Screen: {self.screen_width}x{self.screen_height}")

        self._player = None
        self._loop = None
        self._loop_count = 0
        self._running = False

    def _create_pipeline(self):
        """Create GStreamer pipeline."""
        self._player = Gst.ElementFactory.make('playbin3', 'player')
        if not self._player:
            raise RuntimeError("Failed to create playbin3")

        # Try nveglglessink first (best for fullscreen)
        video_sink = Gst.ElementFactory.make('nveglglessink', 'videosink')
        if video_sink:
            video_sink.set_property('sync', True)
            video_sink.set_property('window-x', 0)
            video_sink.set_property('window-y', 0)
            video_sink.set_property('window-width', self.screen_width)
            video_sink.set_property('window-height', self.screen_height)
            logger.info("Using nveglglessink (fullscreen hardware accelerated)")
        else:
            video_sink = Gst.ElementFactory.make('nv3dsink', 'videosink')
            if video_sink:
                logger.info("Using nv3dsink")
            else:
                video_sink = Gst.ElementFactory.make('autovideosink', 'videosink')
                logger.warning("Using autovideosink (fallback)")

        if video_sink:
            self._player.set_property('video-sink', video_sink)

        # Connect about-to-finish for gapless looping
        self._player.connect('about-to-finish', self._on_about_to_finish)

        # Setup bus
        bus = self._player.get_bus()
        bus.add_signal_watch()
        bus.connect('message::eos', self._on_eos)
        bus.connect('message::error', self._on_error)

    def _on_about_to_finish(self, player):
        """Queue same video for seamless loop."""
        self._loop_count += 1
        logger.info(f"Loop {self._loop_count}: Queueing video for seamless playback")
        # Set the same URI to loop seamlessly
        player.set_property('uri', self.video_uri)

    def _on_eos(self, bus, message):
        """Handle end of stream - shouldn't happen with about-to-finish."""
        logger.info("EOS - restarting playback")
        self._player.set_state(Gst.State.NULL)
        self._player.set_property('uri', self.video_uri)
        self._player.set_state(Gst.State.PLAYING)

    def _on_error(self, bus, message):
        """Handle errors."""
        error, debug = message.parse_error()
        logger.error(f"Error: {error.message}")
        # Try to recover
        GLib.timeout_add(1000, self._restart_playback)

    def _restart_playback(self):
        """Restart playback after error."""
        self._player.set_state(Gst.State.NULL)
        self._player.set_property('uri', self.video_uri)
        self._player.set_state(Gst.State.PLAYING)
        return False

    def start(self):
        """Start playback."""
        if not self.video_path.exists():
            logger.error(f"Video not found: {self.video_path}")
            return False

        logger.info(f"Playing: {self.video_path}")

        self._create_pipeline()
        self._player.set_property('uri', self.video_uri)

        ret = self._player.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error("Failed to start playback")
            return False

        self._running = True
        self._loop = GLib.MainLoop()
        return True

    def stop(self):
        """Stop playback."""
        self._running = False
        if self._player:
            self._player.set_state(Gst.State.NULL)
        if self._loop:
            self._loop.quit()

    def run(self):
        """Run player (blocking)."""
        def signal_handler(sig, frame):
            logger.info("Stopping...")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        if not self.start():
            sys.exit(1)

        logger.info("Player running. Press Ctrl+C to stop.")

        try:
            self._loop.run()
        except Exception as e:
            logger.error(f"Loop error: {e}")

        self.stop()


def main():
    default_video = '/home/nvidia/skillz-player/content/test_video.mp4'
    video_path = sys.argv[1] if len(sys.argv) > 1 else default_video

    print("=" * 50)
    print("Skillz Media Player - Fullscreen Seamless Loop")
    print("=" * 50)
    print(f"Video: {video_path}")
    print("Press Ctrl+C to stop")
    print("=" * 50)

    player = SimplePlayer(video_path)
    player.run()


if __name__ == '__main__':
    main()
