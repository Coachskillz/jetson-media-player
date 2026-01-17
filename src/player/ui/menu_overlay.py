"""
MenuOverlay - GTK3 semi-transparent menu overlay for Jetson Media Player.
Provides device info, settings, and re-pairing options.
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')

from gi.repository import Gtk, Gdk, Pango
from typing import Callable, Dict, Any, Optional

from src.common.logger import setup_logger

logger = setup_logger(__name__)


class MenuOverlay(Gtk.Box):
    """
    Semi-transparent menu overlay with device info and actions.

    Layout:
    - Device info section (ID, location, connection status, network info)
    - Settings toggle switches
    - Action buttons (re-pair, refresh, exit)
    - Close button

    Keyboard support: Escape or F1 to toggle menu
    Touch support: Corner tap detection (100x100px zones)
    """

    # Colors
    BG_COLOR = Gdk.RGBA(0, 0, 0, 0.85)  # Semi-transparent black
    TEXT_COLOR = Gdk.RGBA(1, 1, 1, 1)  # White
    ACCENT_COLOR = Gdk.RGBA(0.2, 0.8, 1, 1)  # Cyan
    SECONDARY_COLOR = Gdk.RGBA(0.7, 0.7, 0.7, 1)  # Light gray
    DANGER_COLOR = Gdk.RGBA(1, 0.3, 0.3, 1)  # Red
    SUCCESS_COLOR = Gdk.RGBA(0.3, 0.8, 0.3, 1)  # Green

    def __init__(
        self,
        on_close: Optional[Callable[[], None]] = None,
        on_re_pair: Optional[Callable[[], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        on_camera_toggle: Optional[Callable[[bool], None]] = None,
        on_restart: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the menu overlay.

        Args:
            on_close: Callback when menu should close
            on_re_pair: Callback when re-pair is requested
            on_refresh: Callback when manual refresh is requested
            on_exit: Callback when exit is requested (exits the application)
            on_camera_toggle: Callback when camera is toggled (bool = new state)
            on_restart: Callback when restart is requested (deprecated, use on_refresh)
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=15)

        self._on_close = on_close
        self._on_re_pair = on_re_pair
        self._on_refresh = on_refresh or on_restart  # Support legacy on_restart
        self._on_exit = on_exit
        self._on_camera_toggle = on_camera_toggle

        # Device info storage
        self._device_info: Dict[str, Any] = {}

        # Build UI
        self._build_ui()

        logger.info("MenuOverlay initialized")

    def _build_ui(self) -> None:
        """Build the menu overlay UI."""
        # Set background
        self.override_background_color(Gtk.StateFlags.NORMAL, self.BG_COLOR)

        # Set size and position
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_size_request(500, -1)

        # Add padding
        self.set_margin_start(30)
        self.set_margin_end(30)
        self.set_margin_top(30)
        self.set_margin_bottom(30)

        # Header with close button
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header_box.set_homogeneous(False)

        title_label = Gtk.Label(label="Device Menu")
        title_label.override_color(Gtk.StateFlags.NORMAL, self.TEXT_COLOR)
        title_label.override_font(Pango.FontDescription("Sans Bold 20"))
        title_label.set_halign(Gtk.Align.START)
        header_box.pack_start(title_label, True, True, 0)

        close_button = Gtk.Button(label="✕")
        close_button.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
        close_button.connect('clicked', self._on_close_clicked)
        close_button.set_relief(Gtk.ReliefStyle.NONE)
        header_box.pack_end(close_button, False, False, 0)

        self.pack_start(header_box, False, False, 0)

        # Separator
        self.pack_start(Gtk.Separator(), False, False, 5)

        # Device Info Section
        info_frame = Gtk.Frame(label="Device Information")
        info_frame.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        info_box.set_margin_start(10)
        info_box.set_margin_end(10)
        info_box.set_margin_top(10)
        info_box.set_margin_bottom(10)

        # Device ID
        self._device_id_label = self._create_info_row("Device ID:", "Unknown")
        info_box.pack_start(self._device_id_label, False, False, 0)

        # Screen ID
        self._screen_id_label = self._create_info_row("Screen ID:", "Unknown")
        info_box.pack_start(self._screen_id_label, False, False, 0)

        # Connection Mode
        self._connection_label = self._create_info_row("Connection:", "Unknown")
        info_box.pack_start(self._connection_label, False, False, 0)

        # Status
        self._status_label = self._create_info_row("Status:", "Unknown")
        info_box.pack_start(self._status_label, False, False, 0)

        # Current Content
        self._content_label = self._create_info_row("Playing:", "None")
        info_box.pack_start(self._content_label, False, False, 0)

        info_frame.add(info_box)
        self.pack_start(info_frame, False, False, 5)

        # Network Info Section
        network_frame = Gtk.Frame(label="Network Info")
        network_frame.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)

        network_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        network_box.set_margin_start(10)
        network_box.set_margin_end(10)
        network_box.set_margin_top(10)
        network_box.set_margin_bottom(10)

        # IP Address
        self._ip_address_label = self._create_info_row("IP Address:", "Unknown")
        network_box.pack_start(self._ip_address_label, False, False, 0)

        # Network Status
        self._network_status_label = self._create_info_row("Network:", "Unknown")
        network_box.pack_start(self._network_status_label, False, False, 0)

        # CMS URL
        self._cms_url_label = self._create_info_row("CMS URL:", "Unknown")
        network_box.pack_start(self._cms_url_label, False, False, 0)

        network_frame.add(network_box)
        self.pack_start(network_frame, False, False, 5)

        # Settings Section
        settings_frame = Gtk.Frame(label="Settings")
        settings_frame.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)

        settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        settings_box.set_margin_start(10)
        settings_box.set_margin_end(10)
        settings_box.set_margin_top(10)
        settings_box.set_margin_bottom(10)

        # Camera toggle
        camera_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        camera_label = Gtk.Label(label="Camera Enabled:")
        camera_label.override_color(Gtk.StateFlags.NORMAL, self.TEXT_COLOR)
        camera_label.set_halign(Gtk.Align.START)
        camera_row.pack_start(camera_label, True, True, 0)

        self._camera_switch = Gtk.Switch()
        self._camera_switch.set_active(True)
        self._camera_switch.connect('notify::active', self._on_camera_toggled)
        camera_row.pack_end(self._camera_switch, False, False, 0)

        settings_box.pack_start(camera_row, False, False, 0)

        settings_frame.add(settings_box)
        self.pack_start(settings_frame, False, False, 5)

        # Action Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        button_box.set_margin_top(10)

        # Manual Refresh button
        refresh_button = Gtk.Button(label="Manual Refresh")
        refresh_button.connect('clicked', self._on_refresh_clicked)
        self._style_button(refresh_button, self.SUCCESS_COLOR)
        button_box.pack_start(refresh_button, False, False, 0)

        # Re-pair button
        re_pair_button = Gtk.Button(label="Re-pair Device")
        re_pair_button.connect('clicked', self._on_re_pair_clicked)
        self._style_button(re_pair_button, self.ACCENT_COLOR)
        button_box.pack_start(re_pair_button, False, False, 0)

        # Exit button
        exit_button = Gtk.Button(label="Exit Player")
        exit_button.connect('clicked', self._on_exit_clicked)
        self._style_button(exit_button, self.DANGER_COLOR)
        button_box.pack_start(exit_button, False, False, 0)

        self.pack_start(button_box, False, False, 5)

        # Keyboard hint
        hint_label = Gtk.Label(label="Press Escape or tap top-right corner to close")
        hint_label.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
        hint_label.override_font(Pango.FontDescription("Sans Italic 10"))
        hint_label.set_margin_top(15)
        self.pack_start(hint_label, False, False, 0)

    def _create_info_row(self, label: str, value: str) -> Gtk.Box:
        """
        Create an info row with label and value.

        Args:
            label: Row label
            value: Initial value

        Returns:
            Box containing the row
        """
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        label_widget = Gtk.Label(label=label)
        label_widget.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
        label_widget.override_font(Pango.FontDescription("Sans 12"))
        label_widget.set_halign(Gtk.Align.START)
        row.pack_start(label_widget, False, False, 0)

        value_widget = Gtk.Label(label=value)
        value_widget.override_color(Gtk.StateFlags.NORMAL, self.TEXT_COLOR)
        value_widget.override_font(Pango.FontDescription("Sans 12"))
        value_widget.set_halign(Gtk.Align.END)
        value_widget.set_line_wrap(True)
        value_widget.set_max_width_chars(30)
        row.pack_end(value_widget, False, False, 0)

        # Store reference to value label for updates
        row._value_label = value_widget

        return row

    def _style_button(self, button: Gtk.Button, color: Gdk.RGBA) -> None:
        """
        Style a button with the given color.

        Args:
            button: Button to style
            color: Text color
        """
        button.override_color(Gtk.StateFlags.NORMAL, color)
        button.set_size_request(-1, 40)

    def _on_close_clicked(self, button: Gtk.Button) -> None:
        """Handle close button click."""
        if self._on_close:
            self._on_close()

    def _on_re_pair_clicked(self, button: Gtk.Button) -> None:
        """Handle re-pair button click."""
        logger.info("Re-pair requested from menu")
        if self._on_re_pair:
            self._on_re_pair()

    def _on_refresh_clicked(self, button: Gtk.Button) -> None:
        """Handle manual refresh button click."""
        logger.info("Manual refresh requested from menu")
        if self._on_refresh:
            self._on_refresh()

    def _on_exit_clicked(self, button: Gtk.Button) -> None:
        """Handle exit button click."""
        logger.info("Exit requested from menu")
        if self._on_exit:
            self._on_exit()

    def _on_camera_toggled(self, switch: Gtk.Switch, gparam) -> None:
        """Handle camera toggle switch."""
        new_state = switch.get_active()
        logger.info("Camera toggled: %s", "enabled" if new_state else "disabled")
        if self._on_camera_toggle:
            self._on_camera_toggle(new_state)

    def update_device_info(
        self,
        device_id: str = "",
        screen_id: str = "",
        connection_mode: str = "",
        status: str = "",
        current_content: str = "",
        camera_enabled: bool = True,
        ip_address: str = "",
        network_status: str = "",
        cms_url: str = ""
    ) -> None:
        """
        Update displayed device information.

        Args:
            device_id: Hardware device ID
            screen_id: CMS screen ID
            connection_mode: Connection mode (hub/direct)
            status: Current status
            current_content: Currently playing content
            camera_enabled: Whether camera is enabled
            ip_address: Device IP address
            network_status: Network connection status (Connected, Disconnected, etc.)
            cms_url: CMS server URL
        """
        if device_id:
            self._device_id_label._value_label.set_text(
                f"{device_id[:20]}..." if len(device_id) > 20 else device_id
            )

        if screen_id:
            self._screen_id_label._value_label.set_text(screen_id)

        if connection_mode:
            self._connection_label._value_label.set_text(connection_mode.title())

        if status:
            self._status_label._value_label.set_text(status.title())

        if current_content:
            # Truncate long filenames
            display_name = current_content
            if len(display_name) > 25:
                display_name = f"...{display_name[-22:]}"
            self._content_label._value_label.set_text(display_name)

        # Update network info
        if ip_address:
            self._ip_address_label._value_label.set_text(ip_address)

        if network_status:
            self._network_status_label._value_label.set_text(network_status)

        if cms_url:
            # Truncate long URLs
            display_url = cms_url
            if len(display_url) > 30:
                display_url = f"{display_url[:27]}..."
            self._cms_url_label._value_label.set_text(display_url)

        # Update camera switch without triggering callback
        self._camera_switch.handler_block_by_func(self._on_camera_toggled)
        self._camera_switch.set_active(camera_enabled)
        self._camera_switch.handler_unblock_by_func(self._on_camera_toggled)

    def set_close_callback(self, callback: Callable[[], None]) -> None:
        """Set the close callback."""
        self._on_close = callback

    def set_re_pair_callback(self, callback: Callable[[], None]) -> None:
        """Set the re-pair callback."""
        self._on_re_pair = callback

    def set_refresh_callback(self, callback: Callable[[], None]) -> None:
        """Set the manual refresh callback."""
        self._on_refresh = callback

    def set_exit_callback(self, callback: Callable[[], None]) -> None:
        """Set the exit callback."""
        self._on_exit = callback

    def set_camera_toggle_callback(self, callback: Callable[[bool], None]) -> None:
        """Set the camera toggle callback."""
        self._on_camera_toggle = callback

    def update_network_info(
        self,
        ip_address: str = "",
        network_status: str = "",
        cms_url: str = ""
    ) -> None:
        """
        Convenience method to update only network info.

        Args:
            ip_address: Device IP address
            network_status: Network connection status
            cms_url: CMS server URL
        """
        if ip_address:
            self._ip_address_label._value_label.set_text(ip_address)
        if network_status:
            self._network_status_label._value_label.set_text(network_status)
        if cms_url:
            display_url = cms_url
            if len(display_url) > 30:
                display_url = f"{display_url[:27]}..."
            self._cms_url_label._value_label.set_text(display_url)
