"""
Kiosk UI framework for Jetson Media Player.
Provides fullscreen, always-on-top GTK3 window with keyboard and touch support.
"""

import threading
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

# IMPORTANT: gi.require_version() MUST be called BEFORE importing from gi.repository
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, Gdk, GLib


from src.common.logger import setup_logger


logger = setup_logger(__name__)


# Corner tap zone size in pixels (for touch input)
CORNER_TAP_ZONE_SIZE = 100

# Debounce time for menu toggle in milliseconds
MENU_DEBOUNCE_MS = 200

# Multi-tap to minimize settings
TRIPLE_TAP_COUNT = 10
TRIPLE_TAP_WINDOW_MS = 5000  # All taps must occur within this window


class KioskWindowState(Enum):
    """Represents the state of the kiosk window."""
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class KioskWindow(Gtk.Window):
    """
    Base class for fullscreen kiosk window with always-on-top behavior.

    Features:
    - Fullscreen mode without window decorations
    - Always-on-top window behavior
    - Keyboard input handling (Escape, F1 for menu)
    - Touch input handling (corner tap detection)
    - GLib main loop integration

    Usage:
        window = KioskWindow(on_menu_requested=my_menu_handler)
        window.show_all()
        window.run()  # Starts GTK main loop
    """

    def __init__(
        self,
        title: str = "Skillz Media Player",
        on_menu_requested: Optional[Callable[[], None]] = None,
        on_exit_requested: Optional[Callable[[], None]] = None,
        on_key_press: Optional[Callable[[str], bool]] = None,
    ):
        """
        Initialize the kiosk window.

        Args:
            title: Window title (not visible in kiosk mode)
            on_menu_requested: Callback when menu is requested (Escape/F1/corner tap)
            on_exit_requested: Callback when exit is requested
            on_key_press: Custom key press handler. Returns True if handled.
        """
        super().__init__(title=title)

        self._on_menu_requested = on_menu_requested
        self._on_exit_requested = on_exit_requested
        self._on_key_press = on_key_press

        self._state = KioskWindowState.INITIALIZING
        self._main_loop: Optional[GLib.MainLoop] = None
        self._lock = threading.Lock()

        # Track last menu toggle time for debouncing
        self._last_menu_toggle_time: int = 0

        # Triple-tap to minimize tracking
        self._tap_timestamps: List[int] = []
        self._minimized = False

        # Container for content widgets
        self._content_stack: Optional[Gtk.Stack] = None
        self._overlay: Optional[Gtk.Overlay] = None

        # Timer IDs for cleanup
        self._timer_ids: List[int] = []

        # Set up the window
        self._setup_window()
        self._setup_input_handlers()
        self._setup_containers()

        self._state = KioskWindowState.READY
        logger.info("KioskWindow initialized")

    def _setup_window(self) -> None:
        """Configure window for kiosk mode."""
        # Remove window decorations (titlebar, borders)
        self.set_decorated(False)

        # Always on top of other windows
        self.set_keep_above(True)

        # Make window fullscreen
        self.fullscreen()

        # Set window to use entire screen
        screen = Gdk.Screen.get_default()
        if screen:
            # Use primary monitor dimensions
            display = screen.get_display()
            monitor = display.get_primary_monitor()
            if monitor:
                geometry = monitor.get_geometry()
                self.set_default_size(geometry.width, geometry.height)
                logger.debug(
                    "Window size set to %dx%d",
                    geometry.width,
                    geometry.height
                )

        # Set black background
        self._set_background_color("#000000")

        # Handle window close event
        self.connect('delete-event', self._handle_delete_event)
        self.connect('destroy', self._handle_destroy)

        logger.debug("Window configured for kiosk mode")

    def _setup_input_handlers(self) -> None:
        """Set up keyboard and mouse/touch input handlers."""
        # Enable keyboard input
        self.add_events(Gdk.EventMask.KEY_PRESS_MASK)
        self.connect('key-press-event', self._handle_key_press)

        # Enable mouse/touch input for corner tap detection
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.TOUCH_MASK
        )
        self.connect('button-press-event', self._handle_button_press)

        logger.debug("Input handlers configured")

    def _setup_containers(self) -> None:
        """Set up container widgets for content management."""
        # Create overlay for layering content and menu
        self._overlay = Gtk.Overlay()
        self.add(self._overlay)

        # Create stack for switching between content screens
        self._content_stack = Gtk.Stack()
        self._content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._content_stack.set_transition_duration(300)
        self._overlay.add(self._content_stack)

        logger.debug("Container widgets created")

    def _set_background_color(self, color: str) -> None:
        """
        Set the window background color.

        Args:
            color: CSS color string (e.g., "#000000", "black")
        """
        css_provider = Gtk.CssProvider()
        css_data = f"""
            window {{
                background-color: {color};
            }}
        """
        css_provider.load_from_data(css_data.encode())

        style_context = self.get_style_context()
        style_context.add_provider(
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _handle_delete_event(self, widget: Gtk.Widget, event: Gdk.Event) -> bool:
        """
        Handle window close event.

        Args:
            widget: The widget that triggered the event
            event: The delete event

        Returns:
            True to prevent default close behavior
        """
        logger.debug("Window close event received")
        if self._on_exit_requested:
            self._on_exit_requested()
            return True  # Prevent default close, let callback handle it
        return False  # Allow default close

    def _handle_destroy(self, widget: Gtk.Widget) -> None:
        """
        Handle window destroy event.

        Args:
            widget: The widget being destroyed
        """
        logger.info("Window destroyed")
        self._cleanup_timers()
        self._state = KioskWindowState.STOPPED

    def _handle_key_press(self, widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        """
        Handle keyboard input.

        Args:
            widget: The widget that received the event
            event: The key press event

        Returns:
            True if the event was handled
        """
        keyval = event.keyval
        keyname = Gdk.keyval_name(keyval)

        logger.debug("Key pressed: %s", keyname)

        # Check for menu keys (Escape or F1)
        if keyname in ('Escape', 'F1'):
            return self._request_menu()

        # Check for Alt+F4 (emergency exit)
        if keyname == 'F4' and (event.state & Gdk.ModifierType.MOD1_MASK):
            logger.info("Alt+F4 pressed, requesting exit")
            if self._on_exit_requested:
                self._on_exit_requested()
            return True

        # Pass to custom handler if set
        if self._on_key_press:
            if self._on_key_press(keyname):
                return True

        return False

    def _handle_button_press(self, widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        """
        Handle mouse/touch button press for corner tap and triple-tap detection.

        Triple-tap anywhere on screen minimizes/restores the window.
        Corner taps toggle the menu overlay.

        Args:
            widget: The widget that received the event
            event: The button press event

        Returns:
            True if the event was handled
        """
        now = GLib.get_monotonic_time() // 1000  # microseconds to ms

        # Track tap for triple-tap detection
        self._tap_timestamps.append(now)
        # Keep only taps within the time window
        self._tap_timestamps = [
            t for t in self._tap_timestamps
            if (now - t) <= TRIPLE_TAP_WINDOW_MS
        ]

        if len(self._tap_timestamps) >= TRIPLE_TAP_COUNT:
            self._tap_timestamps.clear()
            self._toggle_minimize()
            return True

        x, y = event.x, event.y

        # Get window dimensions
        allocation = self.get_allocation()
        width = allocation.width
        height = allocation.height

        # Check if tap is in any corner zone
        if self._is_corner_tap(x, y, width, height):
            logger.debug("Corner tap detected at (%d, %d)", int(x), int(y))
            return self._request_menu()

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

    def _is_corner_tap(
        self,
        x: float,
        y: float,
        width: int,
        height: int
    ) -> bool:
        """
        Check if coordinates are in a corner zone.

        Args:
            x: X coordinate of tap
            y: Y coordinate of tap
            width: Window width
            height: Window height

        Returns:
            True if tap is in a corner zone
        """
        zone = CORNER_TAP_ZONE_SIZE

        # Top-left corner
        if x < zone and y < zone:
            return True

        # Top-right corner
        if x > (width - zone) and y < zone:
            return True

        # Bottom-left corner
        if x < zone and y > (height - zone):
            return True

        # Bottom-right corner
        if x > (width - zone) and y > (height - zone):
            return True

        return False

    def _request_menu(self) -> bool:
        """
        Request menu display with debouncing.

        Returns:
            True if menu request was processed
        """
        current_time = GLib.get_monotonic_time() // 1000  # Convert to ms

        # Debounce menu toggle
        if (current_time - self._last_menu_toggle_time) < MENU_DEBOUNCE_MS:
            logger.debug("Menu toggle debounced")
            return True

        self._last_menu_toggle_time = current_time

        if self._on_menu_requested:
            logger.info("Menu requested")
            self._on_menu_requested()

        return True

    def add_content(self, name: str, widget: Gtk.Widget) -> None:
        """
        Add a content widget to the stack.

        Args:
            name: Unique name for the content
            widget: Widget to add
        """
        if self._content_stack:
            self._content_stack.add_named(widget, name)
            logger.debug("Added content: %s", name)

    def show_content(self, name: str) -> bool:
        """
        Show a specific content widget.

        Args:
            name: Name of the content to show

        Returns:
            True if content was found and shown
        """
        if self._content_stack:
            child = self._content_stack.get_child_by_name(name)
            if child:
                self._content_stack.set_visible_child_name(name)
                logger.debug("Showing content: %s", name)
                return True
            else:
                logger.warning("Content not found: %s", name)
        return False

    def get_current_content(self) -> Optional[str]:
        """
        Get the name of the currently visible content.

        Returns:
            Name of visible content, or None
        """
        if self._content_stack:
            return self._content_stack.get_visible_child_name()
        return None

    def add_overlay_widget(self, widget: Gtk.Widget) -> None:
        """
        Add a widget as an overlay (on top of content).

        Args:
            widget: Widget to add as overlay
        """
        if self._overlay:
            self._overlay.add_overlay(widget)
            logger.debug("Added overlay widget")

    def remove_overlay_widget(self, widget: Gtk.Widget) -> None:
        """
        Remove an overlay widget.

        Args:
            widget: Widget to remove
        """
        if self._overlay:
            self._overlay.remove(widget)
            logger.debug("Removed overlay widget")

    def add_timeout(
        self,
        interval_ms: int,
        callback: Callable[[], bool],
        priority: int = GLib.PRIORITY_DEFAULT
    ) -> int:
        """
        Add a periodic timeout callback.

        Args:
            interval_ms: Interval in milliseconds
            callback: Function to call. Return True to continue, False to stop.
            priority: GLib priority level

        Returns:
            Timer ID for removal
        """
        timer_id = GLib.timeout_add(interval_ms, callback, priority=priority)
        self._timer_ids.append(timer_id)
        logger.debug("Added timeout with ID %d (interval: %dms)", timer_id, interval_ms)
        return timer_id

    def remove_timeout(self, timer_id: int) -> bool:
        """
        Remove a timeout callback.

        Args:
            timer_id: Timer ID returned by add_timeout

        Returns:
            True if timer was removed
        """
        if timer_id in self._timer_ids:
            GLib.source_remove(timer_id)
            self._timer_ids.remove(timer_id)
            logger.debug("Removed timeout with ID %d", timer_id)
            return True
        return False

    def schedule_callback(
        self,
        callback: Callable[[], None],
        priority: int = GLib.PRIORITY_DEFAULT
    ) -> int:
        """
        Schedule a one-time callback on the main thread.

        Args:
            callback: Function to call
            priority: GLib priority level

        Returns:
            Source ID
        """
        def wrapper() -> bool:
            callback()
            return False  # Don't repeat

        return GLib.idle_add(wrapper, priority=priority)

    def _cleanup_timers(self) -> None:
        """Remove all registered timers."""
        for timer_id in self._timer_ids[:]:  # Copy list to avoid modification during iteration
            try:
                GLib.source_remove(timer_id)
            except Exception as e:
                logger.warning("Failed to remove timer %d: %s", timer_id, e)
        self._timer_ids.clear()
        logger.debug("Cleaned up all timers")

    def run(self) -> None:
        """
        Start the GTK main loop.
        This blocks until quit() is called.
        """
        if self._state not in (KioskWindowState.READY, KioskWindowState.RUNNING):
            logger.error("Cannot run window in state: %s", self._state.value)
            return

        self._state = KioskWindowState.RUNNING
        logger.info("Starting GTK main loop")

        try:
            Gtk.main()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            self._state = KioskWindowState.STOPPED
            logger.info("GTK main loop stopped")

    def quit(self) -> None:
        """Stop the GTK main loop and close the window."""
        logger.info("Quitting kiosk window")
        self._cleanup_timers()
        self._state = KioskWindowState.STOPPED

        # Schedule quit on main thread to be safe
        GLib.idle_add(Gtk.main_quit)

    @property
    def state(self) -> KioskWindowState:
        """Get current window state."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Check if window is running."""
        return self._state == KioskWindowState.RUNNING

    @property
    def overlay(self) -> Optional[Gtk.Overlay]:
        """Get the overlay widget for adding layers."""
        return self._overlay

    @property
    def content_stack(self) -> Optional[Gtk.Stack]:
        """Get the content stack widget."""
        return self._content_stack

    def get_screen_size(self) -> Tuple[int, int]:
        """
        Get the screen dimensions.

        Returns:
            Tuple of (width, height)
        """
        screen = Gdk.Screen.get_default()
        if screen:
            display = screen.get_display()
            monitor = display.get_primary_monitor()
            if monitor:
                geometry = monitor.get_geometry()
                return (geometry.width, geometry.height)

        # Fallback to window allocation
        allocation = self.get_allocation()
        return (allocation.width, allocation.height)

    def __repr__(self) -> str:
        """String representation."""
        return f"KioskWindow(state={self._state.value})"


# Global kiosk window instance
_global_kiosk_window: Optional[KioskWindow] = None


def get_kiosk_window(
    title: str = "Skillz Media Player",
    on_menu_requested: Optional[Callable[[], None]] = None,
    on_exit_requested: Optional[Callable[[], None]] = None,
    on_key_press: Optional[Callable[[str], bool]] = None,
) -> KioskWindow:
    """
    Get the global kiosk window instance.

    Args:
        title: Window title (only used on first call)
        on_menu_requested: Menu request callback (only used on first call)
        on_exit_requested: Exit request callback (only used on first call)
        on_key_press: Custom key handler (only used on first call)

    Returns:
        KioskWindow instance
    """
    global _global_kiosk_window

    if _global_kiosk_window is None:
        _global_kiosk_window = KioskWindow(
            title=title,
            on_menu_requested=on_menu_requested,
            on_exit_requested=on_exit_requested,
            on_key_press=on_key_press,
        )

    return _global_kiosk_window
