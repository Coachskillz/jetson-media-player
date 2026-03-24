#!/usr/bin/env python3
"""Debug test for LayoutEngine transitions."""

import sys
sys.path.insert(0, "/home/skillz/jetson-media-player")

import gi
gi.require_version("Gst", "1.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Gst

import logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

from src.player.layout_engine import LayoutEngine, create_fallback_layout

def main():
    playlist_items = [
        {"filename": "746e15bb-fdc8-4f5d-ae88-db56f8398a92.mp4", "duration": 6},
        {"filename": "1a35901a-567f-4d8e-852b-c969d3465956.mp4", "duration": 16},
        {"filename": "20ac157e-9119-4347-9325-cba460c3400a.mp4", "duration": 12},
    ]

    layout = create_fallback_layout(playlist_items)
    
    window = Gtk.Window(title="Layout Debug")
    window.set_default_size(1920, 1080)
    window.fullscreen()

    video_area = Gtk.DrawingArea()
    video_area.set_size_request(1920, 1080)
    window.add(video_area)

    engine = LayoutEngine(
        layout_json=layout,
        media_dir="/home/skillz/media"
    )

    def on_realize(widget):
        gdk_window = widget.get_window()
        if gdk_window:
            xid = gdk_window.get_xid()
            print(f"Window XID: {xid}", flush=True)
            engine.set_window_handle(xid)
            if engine.start():
                print("LayoutEngine started", flush=True)
            else:
                print("ERROR: Failed to start", flush=True)
                Gtk.main_quit()

    video_area.connect("realize", on_realize)

    def on_key_press(widget, event):
        if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_q):
            print("Quit requested", flush=True)
            engine.stop()
            Gtk.main_quit()
            return True
        return False

    window.connect("key-press-event", on_key_press)
    window.connect("destroy", lambda w: Gtk.main_quit())

    window.show_all()

    status_count = [0]
    
    def print_status():
        status_count[0] += 1
        if engine.is_running:
            pos = engine.get_position()
            dur = engine.get_duration()
            active = engine._active
            state_str = "N/A"
            if active and active.pipeline:
                _, state, _ = active.pipeline.get_state(0)
                state_str = state.value_nick if state else "None"
            print(f"[{status_count[0]}] Pos: {pos:.2f}s / {dur:.2f}s | Trans: {engine.transition_count} | State: {state_str}", flush=True)
        else:
            print(f"[{status_count[0]}] Engine not running", flush=True)
        return True

    GLib.timeout_add(2000, print_status)  # Every 2 seconds

    print("Starting GTK main loop...", flush=True)
    Gtk.main()

    engine.cleanup()
    print("Test complete", flush=True)


if __name__ == "__main__":
    main()
