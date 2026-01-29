#!/usr/bin/env python3
"""
Test Media Player - Demonstrates seamless video looping.

Run with: python3 test_player.py [video_file]
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Gst', '1.0')

from gi.repository import Gtk, Gdk, GLib, Gst
import logging
import os
import signal
import subprocess
import sys
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


class SeamlessVideoPlayer:
    """
    Video player with seamless looping using GStreamer playbin3.
    Uses about-to-finish signal for gapless playback.
    """

    def __init__(self, video_path: str):
        self.video_path = Path(video_path).resolve()
        self.video_uri = f"file://{self.video_path}"

        # Get screen size
        self.screen_width, self.screen_height = get_screen_resolution()
        logger.info(f"Screen resolution: {self.screen_width}x{self.screen_height}")

        # GStreamer
        self._player = None
        self._bus = None
        self._loop_count = 0
        self._next_queued = False

        # GTK
        self._window = None

    def _create_player(self):
        """Create GStreamer playbin3 with hardware acceleration."""
        self._player = Gst.ElementFactory.make('playbin3', 'player')
        if not self._player:
            raise RuntimeError("Failed to create playbin3")

        # Try NVIDIA hardware-accelerated sink
        video_sink = Gst.ElementFactory.make('nveglglessink', 'videosink')
        if video_sink:
            video_sink.set_property('sync', True)
            # Set fullscreen dimensions
            video_sink.set_property('window-x', 0)
            video_sink.set_property('window-y', 0)
            video_sink.set_property('window-width', self.screen_width)
            video_sink.set_property('window-height', self.screen_height)
            logger.info("Using nveglglessink (hardware accelerated)")
        else:
            # Fallback to nv3dsink
            video_sink = Gst.ElementFactory.make('nv3dsink', 'videosink')
            if video_sink:
                video_sink.set_property('sync', True)
                logger.info("Using nv3dsink (hardware accelerated)")
            else:
                # Final fallback
                video_sink = Gst.ElementFactory.make('autovideosink', 'videosink')
                logger.warning("Using autovideosink (software)")

        if video_sink:
            self._player.set_property('video-sink', video_sink)

        # Connect about-to-finish for seamless looping
        self._player.connect('about-to-finish', self._on_about_to_finish)

        # Setup message bus
        self._bus = self._player.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect('message::eos', self._on_eos)
        self._bus.connect('message::error', self._on_error)
        self._bus.connect('message::state-changed', self._on_state_changed)

    def _on_about_to_finish(self, player):
        """
        Handle about-to-finish signal for seamless looping.
        This is called ~2 seconds before the video ends.
        """
        logger.info(f"About to finish - queueing same video for seamless loop (loop #{self._loop_count + 1})")

        # For seamless looping of same video, we need to handle this differently
        # Setting the same URI doesn't work well with playbin3
        # Instead, we'll let it go to EOS and restart quickly
        self._next_queued = False  # Let EOS handler restart

    def _on_eos(self, bus, message):
        """Handle end of stream - seamless restart for looping."""
        self._loop_count += 1
        logger.info(f"End of stream - seamless restart (loop #{self._loop_count})")

        # For seamless loop, seek back to start instead of stopping
        # This provides smoother transition than stopping and restarting
        self._player.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            0
        )

    def _on_error(self, bus, message):
        """Handle playback errors."""
        error, debug = message.parse_error()
        logger.error(f"Playback error: {error.message}")
        if debug:
            logger.error(f"Debug: {debug}")

    def _on_state_changed(self, bus, message):
        """Handle state changes."""
        if message.src != self._player:
            return
        old, new, pending = message.parse_state_changed()
        if new == Gst.State.PLAYING:
            logger.info("Playback started")

    def _create_window(self):
        """Create fullscreen GTK window."""
        self._window = Gtk.Window(title="Skillz Media Player - Seamless Loop Test")
        self._window.fullscreen()
        self._window.set_decorated(False)

        # Black background
        css = Gtk.CssProvider()
        css.load_from_data(b"window { background-color: black; }")
        self._window.get_style_context().add_provider(
            css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Keyboard controls
        self._window.connect('key-press-event', self._on_key_press)
        self._window.connect('destroy', lambda w: Gtk.main_quit())

        # Status overlay
        overlay = Gtk.Overlay()

        # Video area (black background)
        video_area = Gtk.DrawingArea()
        video_area.set_size_request(self.screen_width, self.screen_height)
        overlay.add(video_area)

        # Status label
        self._status_label = Gtk.Label()
        self._status_label.set_markup(
            '<span foreground="white" font="Sans Bold 24">Seamless Loop Test</span>'
        )
        self._status_label.set_halign(Gtk.Align.START)
        self._status_label.set_valign(Gtk.Align.START)
        self._status_label.set_margin_start(20)
        self._status_label.set_margin_top(20)
        overlay.add_overlay(self._status_label)

        self._window.add(overlay)

        # Update status periodically
        GLib.timeout_add(1000, self._update_status)

    def _update_status(self):
        """Update status display."""
        if self._player and self._status_label:
            pos = self._get_position()
            dur = self._get_duration()
            self._status_label.set_markup(
                f'<span foreground="white" font="Sans Bold 18">'
                f'Loop: {self._loop_count} | '
                f'Position: {pos:.1f}s / {dur:.1f}s | '
                f'Press ESC to minimize, Q to quit'
                f'</span>'
            )
        return True  # Continue updating

    def _get_position(self):
        """Get current position in seconds."""
        if not self._player:
            return 0
        success, pos = self._player.query_position(Gst.Format.TIME)
        return pos / Gst.SECOND if success else 0

    def _get_duration(self):
        """Get video duration in seconds."""
        if not self._player:
            return 0
        success, dur = self._player.query_duration(Gst.Format.TIME)
        return dur / Gst.SECOND if success else 0

    def _on_key_press(self, widget, event):
        """Handle keyboard input."""
        if event.keyval == Gdk.KEY_Escape:
            self._window.iconify()
            return True
        elif event.keyval == Gdk.KEY_q or event.keyval == Gdk.KEY_Q:
            self.stop()
            Gtk.main_quit()
            return True
        elif event.keyval == Gdk.KEY_f or event.keyval == Gdk.KEY_F11:
            if self._window.get_window().get_state() & Gdk.WindowState.FULLSCREEN:
                self._window.unfullscreen()
            else:
                self._window.fullscreen()
            return True
        elif event.keyval == Gdk.KEY_space:
            # Toggle pause
            if self._player:
                _, state, _ = self._player.get_state(0)
                if state == Gst.State.PLAYING:
                    self._player.set_state(Gst.State.PAUSED)
                    logger.info("Paused")
                else:
                    self._player.set_state(Gst.State.PLAYING)
                    logger.info("Playing")
            return True
        return False

    def start(self):
        """Start the player."""
        if not self.video_path.exists():
            logger.error(f"Video file not found: {self.video_path}")
            return False

        logger.info(f"Starting seamless loop player")
        logger.info(f"Video: {self.video_path}")

        self._create_player()
        self._create_window()

        # Set video URI and start playing
        self._player.set_property('uri', self.video_uri)
        self._player.set_state(Gst.State.PLAYING)

        self._window.show_all()

        # Hide status after 5 seconds
        GLib.timeout_add(5000, lambda: self._status_label.hide() or False)

        return True

    def stop(self):
        """Stop the player."""
        if self._player:
            self._player.set_state(Gst.State.NULL)
        if self._bus:
            self._bus.remove_signal_watch()

    def run(self):
        """Run the player (blocking)."""
        signal.signal(signal.SIGINT, lambda s, f: GLib.idle_add(Gtk.main_quit))
        signal.signal(signal.SIGTERM, lambda s, f: GLib.idle_add(Gtk.main_quit))

        if not self.start():
            sys.exit(1)

        try:
            Gtk.main()
        except KeyboardInterrupt:
            pass

        self.stop()


def main():
    # Default video path
    default_video = '/home/nvidia/skillz-player/content/test_video.mp4'

    video_path = sys.argv[1] if len(sys.argv) > 1 else default_video

    print("=" * 60)
    print("Skillz Media Player - Seamless Loop Test")
    print("=" * 60)
    print(f"Video: {video_path}")
    print()
    print("Controls:")
    print("  ESC    - Minimize window")
    print("  F / F11 - Toggle fullscreen")
    print("  SPACE  - Pause/Resume")
    print("  Q      - Quit")
    print("=" * 60)

    player = SeamlessVideoPlayer(video_path)
    player.run()


if __name__ == '__main__':
    main()
