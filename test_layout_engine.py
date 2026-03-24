#!/usr/bin/env python3
"""
Test script for LayoutEngine on Jetson.
Plays all three test videos through nvcompositor.
"""

import sys
import os

# Add src to path
sys.path.insert(0, '/home/skillz/jetson-media-player')

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

from src.player.layout_engine import LayoutEngine, create_fallback_layout


def main():
    # Test playlist - reordered to test 720p second
    playlist_items = [
        {'filename': '746e15bb-fdc8-4f5d-ae88-db56f8398a92.mp4', 'duration': 6},   # 1920x1080
        {'filename': '1a35901a-567f-4d8e-852b-c969d3465956.mp4', 'duration': 16},  # 1280x720 (no audio)
        {'filename': '20ac157e-9119-4347-9325-cba460c3400a.mp4', 'duration': 12},  # 1080x1920 portrait
    ]

    # Create layout
    layout = create_fallback_layout(playlist_items)
    print(f"Layout: {layout}")

    # Create GTK window
    window = Gtk.Window(title="Layout Engine Test")
    window.set_default_size(1920, 1080)
    window.fullscreen()

    # Drawing area for video
    video_area = Gtk.DrawingArea()
    video_area.set_size_request(1920, 1080)
    window.add(video_area)

    # Create engine
    engine = LayoutEngine(
        layout_json=layout,
        media_dir='/home/skillz/media'
    )

    def on_realize(widget):
        # Get X11 window ID
        gdk_window = widget.get_window()
        if gdk_window:
            xid = gdk_window.get_xid()
            print(f"Window XID: {xid}")
            engine.set_window_handle(xid)
            # Start playback
            if engine.start():
                print("LayoutEngine started successfully")
            else:
                print("ERROR: Failed to start LayoutEngine")
                Gtk.main_quit()

    video_area.connect('realize', on_realize)

    def on_key_press(widget, event):
        if event.keyval == Gdk.KEY_Escape or event.keyval == Gdk.KEY_q:
            print("Quit requested")
            engine.stop()
            Gtk.main_quit()
            return True
        return False

    window.connect('key-press-event', on_key_press)
    window.connect('destroy', lambda w: Gtk.main_quit())

    window.show_all()

    # Status timer
    def print_status():
        if engine.is_running:
            pos = engine.get_position()
            dur = engine.get_duration()
            print(f"Position: {pos:.1f}s / {dur:.1f}s | Transitions: {engine.transition_count}")
        return True

    GLib.timeout_add_seconds(5, print_status)

    print("Starting GTK main loop... Press Q or Escape to quit")
    Gtk.main()

    engine.cleanup()
    print("Test complete")


if __name__ == '__main__':
    main()
