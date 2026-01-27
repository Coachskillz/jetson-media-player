#!/usr/bin/env python3
"""
Layout Renderer for Skillz Media Player.

Renders multi-zone layouts from CMS with support for:
- Video zones with seamless looping and gapless playback
- Image zones with rotation
- Ticker text zones with scrolling
- Triggered content based on demographics/loyalty
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')

from gi.repository import Gtk, Gdk, GLib, Gst, GstVideo, Pango, GdkPixbuf
import json
import logging
import os
import threading
import time
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum

# Initialize GStreamer
Gst.init(None)

logger = logging.getLogger(__name__)


class LayerType(Enum):
    """Types of layers supported by the renderer."""
    VIDEO = "content"
    IMAGE = "image"
    TICKER = "ticker"
    TEXT = "text"
    WIDGET = "widget"
    HTML = "html"


@dataclass
class ContentItem:
    """Represents a content item in a playlist."""
    content_id: str
    url: str
    filename: str
    content_type: str
    duration: int
    local_path: Optional[str] = None


@dataclass
class LayerConfig:
    """Configuration for a single layer."""
    id: str
    name: str
    layer_type: str
    x: int
    y: int
    width: int
    height: int
    z_index: int
    opacity: float
    background_type: str
    background_color: Optional[str]
    content_source: str
    is_primary: bool
    items: List[ContentItem]
    content_config: Optional[Dict] = None


class VideoZone:
    """
    Handles video playback in a layer zone.
    Uses GStreamer playbin3 for gapless playback.
    """

    def __init__(
        self,
        layer_config: LayerConfig,
        media_dir: str,
        cms_url: str,
        on_video_end: Optional[Callable] = None
    ):
        self.config = layer_config
        self.media_dir = Path(media_dir)
        self.cms_url = cms_url.rstrip('/')
        self._on_video_end = on_video_end

        # Playlist management
        self._items: List[ContentItem] = layer_config.items
        self._current_index = 0
        self._next_uri_queued = False

        # GStreamer
        self._player: Optional[Gst.Element] = None
        self._bus: Optional[Gst.Bus] = None
        self._video_sink: Optional[Gst.Element] = None

        # Widget
        self.widget: Optional[Gtk.DrawingArea] = None
        self._xid: Optional[int] = None

        logger.info(f"VideoZone created: {layer_config.name} with {len(self._items)} items")

    def create_widget(self) -> Gtk.DrawingArea:
        """Create the GTK widget for video display."""
        self.widget = Gtk.DrawingArea()
        self.widget.set_size_request(self.config.width, self.config.height)

        # Black background
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"drawingarea { background-color: black; }")
        style_context = self.widget.get_style_context()
        style_context.add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Connect realize signal to get window handle
        self.widget.connect('realize', self._on_realize)

        return self.widget

    def _on_realize(self, widget: Gtk.DrawingArea) -> None:
        """Handle widget realization to get window handle."""
        window = widget.get_window()
        if window:
            self._xid = window.get_xid()
            logger.debug(f"VideoZone {self.config.name} XID: {self._xid}")

    def _create_player(self) -> None:
        """Create GStreamer playbin3 element."""
        self._player = Gst.ElementFactory.make('playbin3', f'player_{self.config.id}')
        if not self._player:
            raise RuntimeError("Failed to create playbin3")

        # Create video sink for NVIDIA hardware acceleration
        video_sink = Gst.ElementFactory.make('nveglglessink', 'videosink')
        if not video_sink:
            logger.warning("nveglglessink not available, trying nv3dsink")
            video_sink = Gst.ElementFactory.make('nv3dsink', 'videosink')
        if not video_sink:
            logger.warning("nv3dsink not available, falling back to autovideosink")
            video_sink = Gst.ElementFactory.make('autovideosink', 'videosink')

        if video_sink:
            video_sink.set_property('sync', True)
            # Set window position and size for nveglglessink
            if video_sink.get_factory().get_name() == 'nveglglessink':
                video_sink.set_property('window-x', self.config.x)
                video_sink.set_property('window-y', self.config.y)
                video_sink.set_property('window-width', self.config.width)
                video_sink.set_property('window-height', self.config.height)
            self._video_sink = video_sink
            self._player.set_property('video-sink', video_sink)

        # Connect signals
        self._player.connect('about-to-finish', self._on_about_to_finish)

        # Setup bus for messages
        self._bus = self._player.get_bus()
        if self._bus:
            self._bus.add_signal_watch()
            self._bus.connect('message::error', self._on_error)
            self._bus.connect('message::eos', self._on_eos)
            self._bus.connect('message::element', self._on_element_message)

    def _on_element_message(self, bus: Gst.Bus, message: Gst.Message) -> None:
        """Handle element messages (for window handle setup)."""
        if message.get_structure() and message.get_structure().get_name() == 'prepare-window-handle':
            if self._xid:
                message.src.set_window_handle(self._xid)

    def _get_content_url(self, item: ContentItem) -> str:
        """Get the full URL or local path for a content item."""
        # First check if we have a local cached copy
        local_path = self.media_dir / item.filename
        if local_path.exists():
            return f"file://{local_path}"

        # Otherwise use the CMS URL
        if item.url.startswith('/'):
            return f"{self.cms_url}{item.url}"
        return item.url

    def _on_about_to_finish(self, player: Gst.Element) -> None:
        """Handle about-to-finish signal for gapless playback."""
        if not self._items:
            return

        # Get next item
        next_index = (self._current_index + 1) % len(self._items)
        next_item = self._items[next_index]
        next_uri = self._get_content_url(next_item)

        # For seamless looping of same video, let it go to EOS
        current_item = self._items[self._current_index]
        if len(self._items) == 1 or next_uri == self._get_content_url(current_item):
            logger.debug(f"Same video - will loop after EOS")
            self._next_uri_queued = False
            return

        logger.info(f"Queuing next video: {next_item.filename}")
        player.set_property('uri', next_uri)
        self._current_index = next_index
        self._next_uri_queued = True

    def _on_eos(self, bus: Gst.Bus, message: Gst.Message) -> None:
        """Handle end-of-stream for looping."""
        if not self._next_uri_queued:
            # Loop current or play next
            if self._items:
                self._current_index = (self._current_index + 1) % len(self._items)
                item = self._items[self._current_index]
                uri = self._get_content_url(item)
                logger.info(f"Looping to: {item.filename}")
                # Seek back to start for seamless loop
                self._player.seek_simple(
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    0
                )
                self._player.set_property('uri', uri)
                self._player.set_state(Gst.State.PLAYING)

        if self._on_video_end:
            self._on_video_end(self)

    def _on_error(self, bus: Gst.Bus, message: Gst.Message) -> None:
        """Handle playback errors."""
        error, debug = message.parse_error()
        logger.error(f"Video error in {self.config.name}: {error.message}")
        # Try next item
        if self._items and len(self._items) > 1:
            self._current_index = (self._current_index + 1) % len(self._items)
            self.play()

    def play(self) -> bool:
        """Start video playback."""
        if not self._items:
            logger.warning(f"No items to play in {self.config.name}")
            return False

        if not self._player:
            self._create_player()

        item = self._items[self._current_index]
        uri = self._get_content_url(item)

        logger.info(f"Playing: {item.filename} in {self.config.name}")
        self._player.set_property('uri', uri)
        self._next_uri_queued = False

        ret = self._player.set_state(Gst.State.PLAYING)
        return ret != Gst.StateChangeReturn.FAILURE

    def pause(self) -> None:
        """Pause playback."""
        if self._player:
            self._player.set_state(Gst.State.PAUSED)

    def stop(self) -> None:
        """Stop playback."""
        if self._player:
            self._player.set_state(Gst.State.NULL)

    def cleanup(self) -> None:
        """Clean up resources."""
        self.stop()
        if self._bus:
            self._bus.remove_signal_watch()
        self._player = None


class ImageZone:
    """Handles image display in a layer zone with rotation support."""

    def __init__(
        self,
        layer_config: LayerConfig,
        media_dir: str,
        cms_url: str
    ):
        self.config = layer_config
        self.media_dir = Path(media_dir)
        self.cms_url = cms_url.rstrip('/')

        self._items: List[ContentItem] = layer_config.items
        self._current_index = 0
        self._rotation_id: Optional[int] = None

        self.widget: Optional[Gtk.Image] = None

    def create_widget(self) -> Gtk.Image:
        """Create the GTK widget for image display."""
        self.widget = Gtk.Image()
        self.widget.set_size_request(self.config.width, self.config.height)
        return self.widget

    def _get_local_path(self, item: ContentItem) -> Optional[str]:
        """Get local path for an image."""
        local_path = self.media_dir / item.filename
        if local_path.exists():
            return str(local_path)
        return None

    def _load_image(self) -> None:
        """Load and display current image."""
        if not self._items or not self.widget:
            return

        item = self._items[self._current_index]
        local_path = self._get_local_path(item)

        if local_path:
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    local_path,
                    self.config.width,
                    self.config.height,
                    True  # Preserve aspect ratio
                )
                self.widget.set_from_pixbuf(pixbuf)
                logger.debug(f"Loaded image: {item.filename}")
            except Exception as e:
                logger.error(f"Failed to load image {item.filename}: {e}")

    def _rotate(self) -> bool:
        """Rotate to next image."""
        if not self._items:
            return False

        self._current_index = (self._current_index + 1) % len(self._items)
        self._load_image()
        return True  # Continue rotation

    def play(self) -> None:
        """Start image rotation."""
        self._load_image()

        # Start rotation if multiple images
        if len(self._items) > 1:
            duration = self._items[self._current_index].duration * 1000  # ms
            self._rotation_id = GLib.timeout_add(duration, self._rotate)

    def stop(self) -> None:
        """Stop image rotation."""
        if self._rotation_id:
            GLib.source_remove(self._rotation_id)
            self._rotation_id = None

    def cleanup(self) -> None:
        """Clean up resources."""
        self.stop()


class TickerZone:
    """Handles scrolling ticker text in a layer zone."""

    def __init__(
        self,
        layer_config: LayerConfig,
        ticker_items: List[str],
        ticker_speed: int = 100,
        ticker_direction: str = 'left'
    ):
        self.config = layer_config
        self._items = ticker_items or ['Welcome to Skillz Media']
        self._speed = ticker_speed
        self._direction = ticker_direction

        self._text = '    '.join(self._items) + '    '
        self._offset = 0
        self._animation_id: Optional[int] = None

        self.widget: Optional[Gtk.DrawingArea] = None

    def create_widget(self) -> Gtk.DrawingArea:
        """Create the GTK widget for ticker display."""
        self.widget = Gtk.DrawingArea()
        self.widget.set_size_request(self.config.width, self.config.height)
        self.widget.connect('draw', self._on_draw)

        # Set background color
        css_provider = Gtk.CssProvider()
        bg_color = self.config.background_color or '#000000'
        css_provider.load_from_data(
            f"drawingarea {{ background-color: {bg_color}; }}".encode()
        )
        self.widget.get_style_context().add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        return self.widget

    def _on_draw(self, widget: Gtk.DrawingArea, cr) -> bool:
        """Draw the ticker text."""
        # Set text color (white)
        cr.set_source_rgb(1, 1, 1)

        # Create Pango layout
        layout = widget.create_pango_layout(self._text)
        font_desc = Pango.FontDescription.from_string("Sans Bold 32")
        layout.set_font_description(font_desc)

        # Get text dimensions
        text_width, text_height = layout.get_pixel_size()

        # Calculate position
        y = (self.config.height - text_height) // 2

        if self._direction == 'left':
            x = self.config.width - self._offset
        elif self._direction == 'right':
            x = self._offset - text_width
        else:
            x = 0

        cr.move_to(x, y)
        PangoCairo = __import__('gi.repository.PangoCairo', fromlist=['PangoCairo']).PangoCairo
        PangoCairo.show_layout(cr, layout)

        return True

    def _animate(self) -> bool:
        """Animate the ticker."""
        if not self.widget:
            return False

        layout = self.widget.create_pango_layout(self._text)
        font_desc = Pango.FontDescription.from_string("Sans Bold 32")
        layout.set_font_description(font_desc)
        text_width, _ = layout.get_pixel_size()

        if self._direction == 'left':
            self._offset += self._speed // 30
            if self._offset > text_width + self.config.width:
                self._offset = 0
        elif self._direction == 'right':
            self._offset += self._speed // 30
            if self._offset > text_width + self.config.width:
                self._offset = 0

        self.widget.queue_draw()
        return True

    def play(self) -> None:
        """Start ticker animation."""
        if not self._animation_id:
            self._animation_id = GLib.timeout_add(33, self._animate)  # ~30 FPS

    def stop(self) -> None:
        """Stop ticker animation."""
        if self._animation_id:
            GLib.source_remove(self._animation_id)
            self._animation_id = None

    def cleanup(self) -> None:
        """Clean up resources."""
        self.stop()


class LayoutRenderer:
    """
    Main layout renderer that manages multiple zones/layers.
    """

    def __init__(
        self,
        cms_url: str,
        media_dir: str = '/home/nvidia/skillz-player/media',
        hardware_id: Optional[str] = None
    ):
        self.cms_url = cms_url.rstrip('/')
        self.media_dir = Path(media_dir)
        self.hardware_id = hardware_id

        # Layout data
        self._layout_data: Optional[Dict] = None
        self._layers: List[LayerConfig] = []

        # Zones (layer renderers)
        self._video_zones: Dict[str, VideoZone] = {}
        self._image_zones: Dict[str, ImageZone] = {}
        self._ticker_zones: Dict[str, TickerZone] = {}

        # GTK
        self._window: Optional[Gtk.Window] = None
        self._fixed: Optional[Gtk.Fixed] = None

        # State
        self._running = False
        self._layout_check_id: Optional[int] = None

        logger.info(f"LayoutRenderer initialized: cms={cms_url}, media={media_dir}")

    def fetch_layout(self) -> bool:
        """Fetch layout from CMS."""
        if not self.hardware_id:
            logger.error("No hardware_id set")
            return False

        try:
            import requests
            url = f"{self.cms_url}/api/v1/devices/{self.hardware_id}/layout"
            response = requests.get(url, timeout=10)

            if response.status_code != 200:
                logger.error(f"Failed to fetch layout: {response.status_code}")
                return False

            data = response.json()
            self._layout_data = data.get('layout')

            if not self._layout_data:
                logger.warning("No layout assigned to device")
                return False

            self._parse_layout()
            logger.info(f"Fetched layout: {self._layout_data.get('name')}")
            return True

        except Exception as e:
            logger.error(f"Error fetching layout: {e}")
            return False

    def _parse_layout(self) -> None:
        """Parse layout data into layer configs."""
        self._layers = []

        if not self._layout_data:
            return

        for layer_data in self._layout_data.get('layers', []):
            items = []
            for item_data in layer_data.get('items', []):
                items.append(ContentItem(
                    content_id=item_data.get('content_id', ''),
                    url=item_data.get('url', ''),
                    filename=item_data.get('filename', ''),
                    content_type=item_data.get('content_type', 'video'),
                    duration=item_data.get('duration', 10)
                ))

            config = LayerConfig(
                id=layer_data.get('id', ''),
                name=layer_data.get('name', 'Layer'),
                layer_type=layer_data.get('layer_type', 'content'),
                x=layer_data.get('x', 0),
                y=layer_data.get('y', 0),
                width=layer_data.get('width', 1920),
                height=layer_data.get('height', 1080),
                z_index=layer_data.get('z_index', 0),
                opacity=layer_data.get('opacity', 1.0),
                background_type=layer_data.get('background_type', 'transparent'),
                background_color=layer_data.get('background_color'),
                content_source=layer_data.get('content_source', 'none'),
                is_primary=layer_data.get('is_primary', False),
                items=items,
                content_config=layer_data.get('content_config')
            )
            self._layers.append(config)

        # Sort by z_index
        self._layers.sort(key=lambda l: l.z_index)

    def _build_ui(self) -> None:
        """Build the GTK UI with all layers."""
        # Create fullscreen window
        self._window = Gtk.Window(title="Skillz Media Player")
        self._window.fullscreen()
        self._window.set_decorated(False)

        # Set background color
        bg_color = self._layout_data.get('background_color', '#000000') if self._layout_data else '#000000'
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(f"window {{ background-color: {bg_color}; }}".encode())
        self._window.get_style_context().add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Use Fixed container for absolute positioning
        self._fixed = Gtk.Fixed()
        self._window.add(self._fixed)

        # Create zones for each layer
        for layer in self._layers:
            self._create_zone(layer)

        self._window.connect('destroy', self._on_destroy)
        self._window.connect('key-press-event', self._on_key_press)

    def _create_zone(self, layer: LayerConfig) -> None:
        """Create a zone widget for a layer."""
        widget = None

        # Determine zone type based on content
        if layer.items and layer.items[0].content_type.startswith('video'):
            # Video zone
            zone = VideoZone(layer, str(self.media_dir), self.cms_url)
            widget = zone.create_widget()
            self._video_zones[layer.id] = zone

        elif layer.items and layer.items[0].content_type.startswith('image'):
            # Image zone
            zone = ImageZone(layer, str(self.media_dir), self.cms_url)
            widget = zone.create_widget()
            self._image_zones[layer.id] = zone

        elif layer.layer_type == 'ticker':
            # Ticker zone
            config = layer.content_config or {}
            zone = TickerZone(
                layer,
                ticker_items=config.get('items', ['Welcome to Skillz Media']),
                ticker_speed=config.get('speed', 100),
                ticker_direction=config.get('direction', 'left')
            )
            widget = zone.create_widget()
            self._ticker_zones[layer.id] = zone

        elif layer.content_source == 'playlist' and layer.items:
            # Default to video zone for playlist content
            zone = VideoZone(layer, str(self.media_dir), self.cms_url)
            widget = zone.create_widget()
            self._video_zones[layer.id] = zone

        if widget:
            # Set opacity
            widget.set_opacity(layer.opacity)

            # Position the widget
            self._fixed.put(widget, layer.x, layer.y)
            widget.set_size_request(layer.width, layer.height)

    def _on_key_press(self, widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        """Handle key press events."""
        keyval = event.keyval

        if keyval == Gdk.KEY_Escape:
            # Minimize/show desktop
            self._window.iconify()
            return True

        elif keyval == Gdk.KEY_q and (event.state & Gdk.ModifierType.CONTROL_MASK):
            # Quit
            self.stop()
            Gtk.main_quit()
            return True

        elif keyval == Gdk.KEY_F11:
            # Toggle fullscreen
            if self._window.get_window().get_state() & Gdk.WindowState.FULLSCREEN:
                self._window.unfullscreen()
            else:
                self._window.fullscreen()
            return True

        return False

    def _on_destroy(self, widget: Gtk.Widget) -> None:
        """Handle window destroy."""
        self.stop()

    def start(self) -> bool:
        """Start the layout renderer."""
        if self._running:
            return True

        # Fetch layout
        if not self.fetch_layout():
            logger.error("Failed to fetch layout")
            return False

        # Build UI
        self._build_ui()

        self._running = True

        # Show window
        self._window.show_all()

        # Start all zones
        for zone in self._video_zones.values():
            zone.play()

        for zone in self._image_zones.values():
            zone.play()

        for zone in self._ticker_zones.values():
            zone.play()

        logger.info("Layout renderer started")
        return True

    def stop(self) -> None:
        """Stop the layout renderer."""
        if not self._running:
            return

        self._running = False

        # Stop all zones
        for zone in self._video_zones.values():
            zone.cleanup()

        for zone in self._image_zones.values():
            zone.cleanup()

        for zone in self._ticker_zones.values():
            zone.cleanup()

        self._video_zones.clear()
        self._image_zones.clear()
        self._ticker_zones.clear()

        logger.info("Layout renderer stopped")

    def run(self) -> None:
        """Run the layout renderer (blocking)."""
        if not self.start():
            logger.error("Failed to start renderer")
            return

        try:
            Gtk.main()
        except KeyboardInterrupt:
            pass

        self.stop()


def get_screen_resolution() -> tuple:
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


if __name__ == '__main__':
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description="Skillz Media Layout Renderer")
    parser.add_argument('--cms-url', default='http://localhost:5002',
                        help='CMS URL')
    parser.add_argument('--media-dir', default='/home/nvidia/skillz-player/media',
                        help='Media directory')
    parser.add_argument('--hardware-id', required=True,
                        help='Device hardware ID')

    args = parser.parse_args()

    renderer = LayoutRenderer(
        cms_url=args.cms_url,
        media_dir=args.media_dir,
        hardware_id=args.hardware_id
    )

    renderer.run()
