"""
PairingScreen - GTK3 pairing code display screen.
Shows 6-digit pairing code and instructions for CMS pairing.
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')

from gi.repository import Gtk, Gdk, GLib, Pango
from typing import Callable, Optional

from src.common.logger import setup_logger

logger = setup_logger(__name__)


class PairingScreen(Gtk.Box):
    """
    Pairing screen showing 6-digit code for CMS device registration.

    Layout:
    - Company logo (if available)
    - "Device Pairing" title
    - 6-digit code in large digits
    - Instructions text
    - CMS URL
    - Status spinner (optional)
    """

    # Colors
    BG_COLOR = Gdk.RGBA(0.05, 0.05, 0.1, 1)  # Dark blue-black
    TEXT_COLOR = Gdk.RGBA(1, 1, 1, 1)  # White
    CODE_COLOR = Gdk.RGBA(0.2, 0.8, 1, 1)  # Cyan
    SECONDARY_COLOR = Gdk.RGBA(0.7, 0.7, 0.7, 1)  # Light gray

    def __init__(
        self,
        pairing_code: str = "------",
        cms_url: str = "http://localhost:5002",
        device_id: str = ""
    ):
        """
        Initialize the pairing screen.

        Args:
            pairing_code: Initial pairing code to display
            cms_url: CMS URL to show user
            device_id: Device hardware ID
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20)

        self._pairing_code = pairing_code
        self._cms_url = cms_url
        self._device_id = device_id
        self._status_text = "Waiting for approval..."

        # Build UI
        self._build_ui()

        logger.info("PairingScreen initialized")

    def _build_ui(self) -> None:
        """Build the pairing screen UI."""
        # Set background
        self.override_background_color(Gtk.StateFlags.NORMAL, self.BG_COLOR)

        # Center content vertically
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)

        # Add padding
        self.set_margin_start(50)
        self.set_margin_end(50)
        self.set_margin_top(50)
        self.set_margin_bottom(50)

        # Company title
        title_label = Gtk.Label(label="SKILLZ MEDIA")
        title_label.override_color(Gtk.StateFlags.NORMAL, self.TEXT_COLOR)
        title_label.override_font(Pango.FontDescription("Sans Bold 24"))
        self.pack_start(title_label, False, False, 10)

        # Subtitle
        subtitle_label = Gtk.Label(label="Device Pairing")
        subtitle_label.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
        subtitle_label.override_font(Pango.FontDescription("Sans 18"))
        self.pack_start(subtitle_label, False, False, 5)

        # Separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.pack_start(separator, False, False, 20)

        # Instructions
        instructions = Gtk.Label(label="Enter this code in the CMS to pair this device:")
        instructions.override_color(Gtk.StateFlags.NORMAL, self.TEXT_COLOR)
        instructions.override_font(Pango.FontDescription("Sans 16"))
        self.pack_start(instructions, False, False, 10)

        # Pairing code display (large)
        self._code_label = Gtk.Label(label=self._format_code(self._pairing_code))
        self._code_label.override_color(Gtk.StateFlags.NORMAL, self.CODE_COLOR)
        self._code_label.override_font(Pango.FontDescription("Monospace Bold 72"))
        self._code_label.set_selectable(False)
        self.pack_start(self._code_label, False, False, 30)

        # CMS URL box
        url_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        url_box.set_halign(Gtk.Align.CENTER)

        url_prefix = Gtk.Label(label="CMS URL:")
        url_prefix.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
        url_prefix.override_font(Pango.FontDescription("Sans 14"))
        url_box.pack_start(url_prefix, False, False, 0)

        self._url_label = Gtk.Label(label=f"{self._cms_url}/devices")
        self._url_label.override_color(Gtk.StateFlags.NORMAL, self.CODE_COLOR)
        self._url_label.override_font(Pango.FontDescription("Monospace 14"))
        url_box.pack_start(self._url_label, False, False, 0)

        self.pack_start(url_box, False, False, 10)

        # Status area with spinner
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        status_box.set_halign(Gtk.Align.CENTER)

        self._spinner = Gtk.Spinner()
        self._spinner.start()
        status_box.pack_start(self._spinner, False, False, 0)

        self._status_label = Gtk.Label(label=self._status_text)
        self._status_label.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
        self._status_label.override_font(Pango.FontDescription("Sans 14"))
        status_box.pack_start(self._status_label, False, False, 0)

        self.pack_start(status_box, False, False, 20)

        # Device ID (small, at bottom)
        if self._device_id:
            device_label = Gtk.Label(label=f"Device ID: {self._device_id[:16]}...")
            device_label.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
            device_label.override_font(Pango.FontDescription("Monospace 10"))
            self.pack_start(device_label, False, False, 10)

    def _format_code(self, code: str) -> str:
        """
        Format pairing code with spaces for readability.

        Args:
            code: 6-digit code

        Returns:
            Formatted code (e.g., "123 456")
        """
        if len(code) >= 6:
            return f"{code[:3]} {code[3:6]}"
        return code

    def set_pairing_code(self, code: str) -> None:
        """
        Update the displayed pairing code.

        Args:
            code: New 6-digit pairing code
        """
        self._pairing_code = code
        self._code_label.set_text(self._format_code(code))
        logger.info("Pairing code updated")

    def set_status(self, status: str, show_spinner: bool = True) -> None:
        """
        Update the status text.

        Args:
            status: Status message to display
            show_spinner: Whether to show the spinner
        """
        self._status_text = status
        self._status_label.set_text(status)

        if show_spinner:
            self._spinner.start()
            self._spinner.show()
        else:
            self._spinner.stop()
            self._spinner.hide()

    def set_cms_url(self, url: str) -> None:
        """
        Update the CMS URL.

        Args:
            url: CMS base URL
        """
        self._cms_url = url
        self._url_label.set_text(f"{url}/devices")

    def show_success(self) -> None:
        """Show pairing success state."""
        self._code_label.override_color(
            Gtk.StateFlags.NORMAL,
            Gdk.RGBA(0.2, 1, 0.4, 1)  # Green
        )
        self.set_status("Paired successfully!", show_spinner=False)

    def show_error(self, message: str = "Pairing failed") -> None:
        """
        Show pairing error state.

        Args:
            message: Error message to display
        """
        self._code_label.override_color(
            Gtk.StateFlags.NORMAL,
            Gdk.RGBA(1, 0.3, 0.3, 1)  # Red
        )
        self.set_status(message, show_spinner=False)

    def reset(self) -> None:
        """Reset to initial waiting state."""
        self._code_label.override_color(
            Gtk.StateFlags.NORMAL,
            self.CODE_COLOR
        )
        self.set_status("Waiting for approval...", show_spinner=True)
