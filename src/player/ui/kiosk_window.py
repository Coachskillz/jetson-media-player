"""
KioskWindow - Base GTK3 fullscreen window for Jetson Media Player.
Provides kiosk mode with hidden cursor, fullscreen, and keyboard handling.
"""

import os
import subprocess

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')

from gi.repository import Gtk, Gdk, GLib
from typing import Callable, Optional

from src.common.logger import setup_logger

logger = setup_logger(__name__)


class KioskWindow(Gtk.Window):
    """
    Base kiosk window with fullscreen mode and input handling.

    Features:
    - Fullscreen kiosk mode
    - Hidden cursor
    - Keyboard shortcuts (Escape/F1 for menu)
    - Corner tap detection for touchscreen
    """

    # Corner tap detection area (pixels from corner)
    # Spec requires minimum 100x100px zones
    CORNER_TAP_SIZE = 100

    # Multi-tap to minimize
    TRIPLE_TAP_COUNT = 10
    TRIPLE_TAP_WINDOW_MS = 5000

    def __init__(
        self,
        title: str = "Skillz Media Player",
        on_menu_toggle: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the kiosk window.

        Args:
            title: Window title
            on_menu_toggle: Callback when menu should be toggled
        """
        super().__init__(title=title)

        self._on_menu_toggle = on_menu_toggle
        self._cursor_hidden = False
        self._tap_timestamps = []
        self._minimized = False

        # Configure window for kiosk mode
        self._setup_window()

        # Set up keyboard and mouse handling
        self._setup_input_handlers()

        logger.info("KioskWindow initialized")

    def _disable_screen_blanking(self) -> None:
        """Disable screen blanking, screensaver, and DPMS to prevent sleep."""
        try:
            subprocess.run(['xset', 's', 'off'], env={**os.environ}, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(['xset', 's', 'noblank'], env={**os.environ}, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(['xset', '-dpms'], env={**os.environ}, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info("Screen blanking and DPMS disabled")
        except Exception as e:
            logger.warning("Could not disable screen blanking: %s", e)

    def _setup_window(self) -> None:
        """Configure window for kiosk mode."""
        # Disable screen sleep/blanking
        self._disable_screen_blanking()

        # Remove window decorations
        self.set_decorated(False)

        # Skip the window manager taskbar/pager
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)

        # Always on top of other windows
        self.set_keep_above(True)

        # Set explicit size to full screen before requesting fullscreen
        screen = Gdk.Screen.get_default()
        if screen:
            self.set_default_size(screen.get_width(), screen.get_height())
            self.move(0, 0)
            self.resize(screen.get_width(), screen.get_height())

        # Set to fullscreen
        self.fullscreen()

        # Set dark background
        self.override_background_color(
            Gtk.StateFlags.NORMAL,
            Gdk.RGBA(0, 0, 0, 1)
        )

        # Connect destroy signal
        self.connect('destroy', self._on_destroy)

        # Connect realize signal to hide cursor after window is shown
        self.connect('realize', self._on_realize)

        # After window is mapped, re-assert fullscreen and raise above all
        self.connect('map-event', self._on_map_event)

    def _on_map_event(self, widget, event) -> bool:
        """Re-assert fullscreen and raise above desktop after window is mapped."""
        import subprocess as _sp
        try:
            _sp.Popen(
                ['bash', '-c',
                 'sleep 1; DISPLAY=:0 wmctrl -r "Skillz Media Player" -b add,fullscreen,above; '
                 'DISPLAY=:0 wmctrl -a "Skillz Media Player"'],
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL
            )
        except Exception:
            pass
        return False

    def _setup_input_handlers(self) -> None:
        """Set up keyboard and mouse input handlers."""
        # Enable events
        self.add_events(
            Gdk.EventMask.KEY_PRESS_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK
        )

        # Connect handlers
        self.connect('key-press-event', self._on_key_press)
        self.connect('button-press-event', self._on_button_press)

    def _on_realize(self, widget: Gtk.Widget) -> None:
        """Called when window is realized."""
        # Hide cursor after short delay to ensure window is fully visible
        GLib.timeout_add(100, self._hide_cursor)

    def _hide_cursor(self) -> bool:
        """Hide the mouse cursor."""
        try:
            window = self.get_window()
            if window:
                # Create blank cursor
                display = window.get_display()
                blank_cursor = Gdk.Cursor.new_from_name(display, "none")
                window.set_cursor(blank_cursor)
                self._cursor_hidden = True
                logger.debug("Cursor hidden")
        except Exception as e:
            logger.warning("Could not hide cursor: %s", e)

        return False  # Don't repeat

    def _show_cursor(self) -> None:
        """Show the mouse cursor."""
        try:
            window = self.get_window()
            if window:
                window.set_cursor(None)
                self._cursor_hidden = False
                logger.debug("Cursor shown")
        except Exception as e:
            logger.warning("Could not show cursor: %s", e)

    def _on_key_press(self, widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        """
        Handle key press events.

        Args:
            widget: The widget
            event: Key event

        Returns:
            True if event was handled, False otherwise
        """
        keyval = event.keyval

        # Escape or F1 toggles menu
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_F1):
            logger.debug("Menu toggle key pressed")
            if self._on_menu_toggle:
                self._on_menu_toggle()
            return True

        return False

    def _on_button_press(self, widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        """
        Handle mouse/touch press events.
        Triple-tap anywhere minimizes/restores. Corner taps toggle menu.

        Args:
            widget: The widget
            event: Button event

        Returns:
            True if event was handled, False otherwise
        """
        now = GLib.get_monotonic_time() // 1000  # microseconds to ms

        # Track tap for triple-tap detection
        self._tap_timestamps.append(now)
        self._tap_timestamps = [
            t for t in self._tap_timestamps
            if (now - t) <= self.TRIPLE_TAP_WINDOW_MS
        ]

        if len(self._tap_timestamps) >= self.TRIPLE_TAP_COUNT:
            self._tap_timestamps.clear()
            self._toggle_minimize()
            return True

        # Get window size
        allocation = self.get_allocation()
        width = allocation.width
        height = allocation.height

        # Get click position
        x = event.x
        y = event.y

        # Check if click is in top-right corner
        if (x >= width - self.CORNER_TAP_SIZE and
            y <= self.CORNER_TAP_SIZE):
            logger.debug("Corner tap detected - toggling menu")
            if self._on_menu_toggle:
                self._on_menu_toggle()
            return True

        return False

    def _toggle_minimize(self) -> None:
        """Toggle between minimized (iconified) and fullscreen."""
        if self._minimized:
            logger.info("Restoring fullscreen")
            self.deiconify()
            self.fullscreen()
            self.set_keep_above(True)
            self._minimized = False
        else:
            logger.info("Minimizing window")
            self.set_keep_above(False)
            self.unfullscreen()
            self.iconify()
            self._minimized = True

    def _on_destroy(self, widget: Gtk.Widget) -> None:
        """Handle window destroy."""
        logger.info("KioskWindow destroyed")

    def set_menu_toggle_callback(self, callback: Callable[[], None]) -> None:
        """
        Set the menu toggle callback.

        Args:
            callback: Function to call when menu should be toggled
        """
        self._on_menu_toggle = callback

    def show_cursor_temporarily(self, duration_ms: int = 3000) -> None:
        """
        Show cursor temporarily (for menu interaction).

        Args:
            duration_ms: How long to show cursor (milliseconds)
        """
        self._show_cursor()
        GLib.timeout_add(duration_ms, self._hide_cursor)

    def exit_kiosk_mode(self) -> None:
        """Exit kiosk mode (for development/debugging)."""
        self.unfullscreen()
        self._show_cursor()
        self.set_decorated(True)
        logger.info("Exited kiosk mode")

    def enter_kiosk_mode(self) -> None:
        """Enter kiosk mode."""
        self.set_decorated(False)
        self.fullscreen()
        self._hide_cursor()
        logger.info("Entered kiosk mode")
