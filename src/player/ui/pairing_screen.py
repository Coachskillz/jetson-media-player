"""
PairingScreen - GTK3 fullscreen pairing screen with connection mode selection.
Step 1: Choose direct CMS or hub connection.
Step 2: Display 6-digit pairing code.
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
    Fullscreen pairing screen with connection mode selection and pairing code display.
    """

    # Colors
    BG_COLOR = Gdk.RGBA(0.06, 0.06, 0.08, 1)
    TEXT_COLOR = Gdk.RGBA(1, 1, 1, 1)
    CODE_COLOR = Gdk.RGBA(0.2, 0.78, 1, 1)
    SECONDARY_COLOR = Gdk.RGBA(0.55, 0.55, 0.6, 1)
    ACCENT_COLOR = Gdk.RGBA(0.2, 0.78, 1, 0.15)
    SUCCESS_COLOR = Gdk.RGBA(0.2, 1, 0.4, 1)
    ERROR_COLOR = Gdk.RGBA(1, 0.3, 0.3, 1)
    DIRECT_COLOR = Gdk.RGBA(0.3, 0.85, 0.4, 1)
    HUB_COLOR = Gdk.RGBA(1, 0.7, 0.2, 1)
    BTN_BG = Gdk.RGBA(0.12, 0.12, 0.15, 1)
    BTN_HOVER = Gdk.RGBA(0.18, 0.18, 0.22, 1)

    def __init__(
        self,
        pairing_code: str = "------",
        cms_url: str = "",
        device_id: str = "",
        connection_mode: str = "direct",
        hub_url: str = "",
        on_mode_selected: Optional[Callable[[str], None]] = None,
        on_back: Optional[Callable[[], None]] = None
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._pairing_code = pairing_code
        self._cms_url = cms_url
        self._device_id = device_id
        self._connection_mode = connection_mode
        self._hub_url = hub_url
        self._on_mode_selected = on_mode_selected
        self._on_back = on_back
        self._status_text = "Waiting for approval..."

        self.override_background_color(Gtk.StateFlags.NORMAL, self.BG_COLOR)
        self.set_hexpand(True)
        self.set_vexpand(True)

        # Internal stack for step 1 (mode select) and step 2 (pairing code)
        self._internal_stack = Gtk.Stack()
        self._internal_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._internal_stack.set_transition_duration(400)

        self._build_mode_select_page()
        self._build_code_page()

        self.pack_start(self._internal_stack, True, True, 0)

        # Show mode select first
        self._internal_stack.set_visible_child_name("mode_select")

        logger.info("PairingScreen initialized")

    # ─── Step 1: Mode Selection ───────────────────────────────────────

    def _build_mode_select_page(self) -> None:
        """Build the connection mode selection page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.override_background_color(Gtk.StateFlags.NORMAL, self.BG_COLOR)

        # Top spacer
        page.pack_start(Gtk.Box(), True, True, 0)

        # Center content
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        center.set_halign(Gtk.Align.CENTER)

        # Title
        title = Gtk.Label(label="SKILLZ MEDIA")
        title.override_color(Gtk.StateFlags.NORMAL, self.TEXT_COLOR)
        title.modify_font(Pango.FontDescription("Sans Bold 36"))
        center.pack_start(title, False, False, 0)

        # Separator
        sep = Gtk.Box()
        sep.set_size_request(120, 2)
        sep.override_background_color(Gtk.StateFlags.NORMAL, self.CODE_COLOR)
        sep.set_halign(Gtk.Align.CENTER)
        center.pack_start(sep, False, False, 20)

        # Subtitle
        subtitle = Gtk.Label(label="Select Connection Mode")
        subtitle.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
        subtitle.modify_font(Pango.FontDescription("Sans 18"))
        center.pack_start(subtitle, False, False, 40)

        # Buttons container
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=40)
        btn_box.set_halign(Gtk.Align.CENTER)

        # Direct button
        direct_btn = self._create_mode_button(
            title="Direct to CMS",
            description="Connect this screen directly\nto the central CMS server",
            icon_text="\u2601",  # Cloud icon
            color=self.DIRECT_COLOR,
            mode="direct"
        )
        btn_box.pack_start(direct_btn, False, False, 0)

        # Hub button
        hub_btn = self._create_mode_button(
            title="Via Local Hub",
            description="Connect through a local hub\nat this store location",
            icon_text="\u2302",  # House icon
            color=self.HUB_COLOR,
            mode="hub"
        )
        btn_box.pack_start(hub_btn, False, False, 0)

        center.pack_start(btn_box, False, False, 0)

        page.pack_start(center, False, False, 0)

        # Bottom spacer
        page.pack_start(Gtk.Box(), True, True, 0)

        # Device ID at bottom
        if self._device_id:
            bottom = Gtk.Box()
            bottom.set_halign(Gtk.Align.CENTER)
            bottom.set_margin_bottom(30)
            dev_label = Gtk.Label(label=self._device_id)
            dev_label.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
            dev_label.modify_font(Pango.FontDescription("Monospace 11"))
            bottom.pack_start(dev_label, False, False, 0)
            page.pack_end(bottom, False, False, 0)

        self._internal_stack.add_named(page, "mode_select")

    def _create_mode_button(self, title: str, description: str,
                            icon_text: str, color: Gdk.RGBA, mode: str) -> Gtk.EventBox:
        """Create a clickable mode selection card."""
        event_box = Gtk.EventBox()
        event_box.set_above_child(True)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.override_background_color(Gtk.StateFlags.NORMAL, self.BTN_BG)
        card.set_size_request(300, 220)
        card.set_margin_top(10)
        card.set_margin_bottom(10)
        card.set_valign(Gtk.Align.CENTER)

        # Icon
        icon = Gtk.Label(label=icon_text)
        icon.override_color(Gtk.StateFlags.NORMAL, color)
        icon.modify_font(Pango.FontDescription("Sans 48"))
        icon.set_margin_top(25)
        card.pack_start(icon, False, False, 0)

        # Title
        lbl = Gtk.Label(label=title)
        lbl.override_color(Gtk.StateFlags.NORMAL, self.TEXT_COLOR)
        lbl.modify_font(Pango.FontDescription("Sans Bold 18"))
        card.pack_start(lbl, False, False, 0)

        # Description
        desc = Gtk.Label(label=description)
        desc.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
        desc.modify_font(Pango.FontDescription("Sans 12"))
        desc.set_justify(Gtk.Justification.CENTER)
        desc.set_line_wrap(True)
        desc.set_margin_bottom(20)
        card.pack_start(desc, False, False, 0)

        event_box.add(card)

        # Hover effect
        def on_enter(widget, event):
            card.override_background_color(Gtk.StateFlags.NORMAL, self.BTN_HOVER)
        def on_leave(widget, event):
            card.override_background_color(Gtk.StateFlags.NORMAL, self.BTN_BG)
        def on_click(widget, event):
            self._select_mode(mode)

        event_box.connect('enter-notify-event', on_enter)
        event_box.connect('leave-notify-event', on_leave)
        event_box.connect('button-press-event', on_click)
        event_box.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK |
                             Gdk.EventMask.LEAVE_NOTIFY_MASK |
                             Gdk.EventMask.BUTTON_PRESS_MASK)

        return event_box

    def _select_mode(self, mode: str) -> None:
        """Handle connection mode selection."""
        logger.info("Connection mode selected: %s", mode)
        self._connection_mode = mode
        self._update_code_page_mode()
        self._internal_stack.set_visible_child_name("code_display")

        if self._on_mode_selected:
            self._on_mode_selected(mode)

    def _go_back_to_mode_select(self, widget, event) -> None:
        """Go back to mode selection — notify parent to stop polling."""
        logger.info("Back to mode selection requested")
        self._internal_stack.set_visible_child_name("mode_select")

        if self._on_back:
            self._on_back()

    # ─── Step 2: Pairing Code Display ─────────────────────────────────

    def _build_code_page(self) -> None:
        """Build the pairing code display page."""
        self._code_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._code_page.override_background_color(Gtk.StateFlags.NORMAL, self.BG_COLOR)

        # Top spacer
        self._code_page.pack_start(Gtk.Box(), True, True, 0)

        # Center content
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        center.set_halign(Gtk.Align.CENTER)

        # Title
        title = Gtk.Label(label="SKILLZ MEDIA")
        title.override_color(Gtk.StateFlags.NORMAL, self.TEXT_COLOR)
        title.modify_font(Pango.FontDescription("Sans Bold 36"))
        center.pack_start(title, False, False, 0)

        # Separator
        sep = Gtk.Box()
        sep.set_size_request(120, 2)
        sep.override_background_color(Gtk.StateFlags.NORMAL, self.CODE_COLOR)
        sep.set_halign(Gtk.Align.CENTER)
        center.pack_start(sep, False, False, 20)

        # Subtitle
        subtitle = Gtk.Label(label="Device Pairing")
        subtitle.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
        subtitle.modify_font(Pango.FontDescription("Sans 18"))
        center.pack_start(subtitle, False, False, 8)

        # Connection mode badge
        self._mode_badge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._mode_badge_box.set_halign(Gtk.Align.CENTER)

        self._mode_dot = Gtk.Label(label="\u25CF")
        self._mode_dot.modify_font(Pango.FontDescription("Sans 12"))
        self._mode_badge_box.pack_start(self._mode_dot, False, False, 0)

        self._mode_label = Gtk.Label()
        self._mode_label.modify_font(Pango.FontDescription("Sans Bold 12"))
        self._mode_badge_box.pack_start(self._mode_label, False, False, 0)

        center.pack_start(self._mode_badge_box, False, False, 20)

        # Back button — prominent, easy to tap
        back_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        back_btn_box.set_halign(Gtk.Align.CENTER)
        back_label = Gtk.Label(label="\u2190  Change Connection Mode")
        back_label.override_color(Gtk.StateFlags.NORMAL, self.CODE_COLOR)
        back_label.modify_font(Pango.FontDescription("Sans Bold 16"))
        back_event = Gtk.EventBox()
        back_event.add(back_label)
        back_event.connect('button-press-event', self._go_back_to_mode_select)
        back_event.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                              Gdk.EventMask.ENTER_NOTIFY_MASK |
                              Gdk.EventMask.LEAVE_NOTIFY_MASK)
        back_event.connect('enter-notify-event',
                           lambda w, e: back_label.override_color(
                               Gtk.StateFlags.NORMAL, self.TEXT_COLOR))
        back_event.connect('leave-notify-event',
                           lambda w, e: back_label.override_color(
                               Gtk.StateFlags.NORMAL, self.CODE_COLOR))
        back_btn_box.pack_start(back_event, False, False, 0)
        center.pack_start(back_btn_box, False, False, 10)

        # Instructions
        instructions = Gtk.Label(label="Enter this code in the CMS to pair this screen")
        instructions.override_color(Gtk.StateFlags.NORMAL, self.TEXT_COLOR)
        instructions.modify_font(Pango.FontDescription("Sans 16"))
        center.pack_start(instructions, False, False, 30)

        # Code frame
        code_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        code_frame.set_halign(Gtk.Align.CENTER)
        code_frame.override_background_color(Gtk.StateFlags.NORMAL, self.ACCENT_COLOR)

        self._code_label = Gtk.Label(label=self._format_code(self._pairing_code))
        self._code_label.override_color(Gtk.StateFlags.NORMAL, self.CODE_COLOR)
        self._code_label.modify_font(Pango.FontDescription("Monospace Bold 80"))
        self._code_label.set_selectable(False)
        self._code_label.set_margin_top(20)
        self._code_label.set_margin_bottom(20)
        self._code_label.set_margin_start(50)
        self._code_label.set_margin_end(50)
        code_frame.pack_start(self._code_label, False, False, 0)

        center.pack_start(code_frame, False, False, 10)

        # Status with spinner
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        status_box.set_halign(Gtk.Align.CENTER)

        self._spinner = Gtk.Spinner()
        self._spinner.start()
        status_box.pack_start(self._spinner, False, False, 0)

        self._status_label = Gtk.Label(label=self._status_text)
        self._status_label.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
        self._status_label.modify_font(Pango.FontDescription("Sans 14"))
        status_box.pack_start(self._status_label, False, False, 0)

        center.pack_start(status_box, False, False, 30)

        # CMS URL
        self._url_label = Gtk.Label(label=self._cms_url)
        self._url_label.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
        self._url_label.modify_font(Pango.FontDescription("Monospace 12"))
        center.pack_start(self._url_label, False, False, 0)

        # Hub URL (shown only in hub mode)
        self._hub_label = Gtk.Label()
        self._hub_label.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
        self._hub_label.modify_font(Pango.FontDescription("Monospace 12"))
        self._hub_label.set_no_show_all(True)
        center.pack_start(self._hub_label, False, False, 4)

        self._code_page.pack_start(center, False, False, 0)

        # Bottom spacer
        self._code_page.pack_start(Gtk.Box(), True, True, 0)

        # Device ID
        if self._device_id:
            bottom = Gtk.Box()
            bottom.set_halign(Gtk.Align.CENTER)
            bottom.set_margin_bottom(30)
            dev_label = Gtk.Label(label=self._device_id)
            dev_label.override_color(Gtk.StateFlags.NORMAL, self.SECONDARY_COLOR)
            dev_label.modify_font(Pango.FontDescription("Monospace 11"))
            bottom.pack_start(dev_label, False, False, 0)
            self._code_page.pack_end(bottom, False, False, 0)

        self._internal_stack.add_named(self._code_page, "code_display")

        # Set initial mode colors
        self._update_code_page_mode()

    def _update_code_page_mode(self) -> None:
        """Update the code page to reflect current connection mode."""
        if self._connection_mode == 'direct':
            color = self.DIRECT_COLOR
            self._mode_label.set_text("DIRECT TO CMS")
            self._hub_label.hide()
        else:
            color = self.HUB_COLOR
            self._mode_label.set_text("VIA LOCAL HUB")
            if self._hub_url:
                self._hub_label.set_text(f"Hub: {self._hub_url}")
                self._hub_label.show()

        self._mode_dot.override_color(Gtk.StateFlags.NORMAL, color)
        self._mode_label.override_color(Gtk.StateFlags.NORMAL, color)

    # ─── Public API ───────────────────────────────────────────────────

    def _format_code(self, code: str) -> str:
        if len(code) >= 6:
            return f"{code[:3]}  {code[3:6]}"
        return code

    def show_code_page(self) -> None:
        """Switch to the code display page."""
        self._internal_stack.set_visible_child_name("code_display")

    def show_mode_select(self) -> None:
        """Switch back to mode selection page."""
        self._internal_stack.set_visible_child_name("mode_select")

    def set_pairing_code(self, code: str) -> None:
        self._pairing_code = code
        self._code_label.set_text(self._format_code(code))
        logger.info("Pairing code updated")

    def set_status(self, status: str, show_spinner: bool = True) -> None:
        self._status_text = status
        self._status_label.set_text(status)
        if show_spinner:
            self._spinner.start()
            self._spinner.show()
        else:
            self._spinner.stop()
            self._spinner.hide()

    def set_cms_url(self, url: str) -> None:
        self._cms_url = url
        self._url_label.set_text(url)

    def set_hub_url(self, url: str) -> None:
        self._hub_url = url

    def show_success(self) -> None:
        self._code_label.override_color(Gtk.StateFlags.NORMAL, self.SUCCESS_COLOR)
        self.set_status("Paired successfully!", show_spinner=False)

    def show_error(self, message: str = "Pairing failed") -> None:
        self._code_label.override_color(Gtk.StateFlags.NORMAL, self.ERROR_COLOR)
        self.set_status(message, show_spinner=False)

    def reset(self) -> None:
        self._code_label.override_color(Gtk.StateFlags.NORMAL, self.CODE_COLOR)
        self.set_status("Waiting for approval...", show_spinner=True)
        self._internal_stack.set_visible_child_name("mode_select")
