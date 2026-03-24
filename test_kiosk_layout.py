#!/usr/bin/env python3
"""Quick test of KioskPlayer with LayoutEngine."""

import sys
import os

# Enable layout engine
os.environ["USE_LAYOUT_ENGINE"] = "1"

sys.path.insert(0, "/home/skillz/jetson-media-player")

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

from src.player.kiosk_player import KioskPlayer


def main():
    print("Testing KioskPlayer with LayoutEngine...")
    env_val = os.environ.get("USE_LAYOUT_ENGINE", "not set")
    print(f"USE_LAYOUT_ENGINE env var: {env_val}")
    
    # Create player with test config
    player = KioskPlayer(
        config_dir="/home/skillz/config",
        media_dir="/home/skillz/media"
    )
    
    print(f"use_layout_engine flag: {player._use_layout_engine}")
    
    if not player._use_layout_engine:
        print("ERROR: Layout engine not enabled!")
        return 1
    
    print("Integration test PASSED - Layout engine flag is correctly set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
