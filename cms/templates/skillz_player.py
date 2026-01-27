#!/usr/bin/env python3
"""
Skillz Media Player - Main Application

Integrates:
- Device pairing workflow
- Layout-based media playback with multiple zones
- Seamless video looping and playlist transitions
- Remote control and health monitoring
- Keyboard controls
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')

from gi.repository import Gtk, Gdk, GLib, Gst, GstVideo
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

# Initialize GStreamer
Gst.init(None)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/home/nvidia/skillz-player/logs/player.log')
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class DeviceConfig:
    """Device configuration."""
    hardware_id: str
    device_id: Optional[str] = None
    pairing_code: Optional[str] = None
    status: str = 'pending'
    cms_url: str = 'http://192.168.1.90:5002'
    paired: bool = False


class CMSClient:
    """Client for communicating with the CMS."""

    def __init__(self, cms_url: str):
        self.cms_url = cms_url.rstrip('/')
        self._session = None

    def _get_session(self):
        """Get or create requests session."""
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers.update({
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            })
        return self._session

    def register_device(self, hardware_id: str, ip_address: str = None) -> Optional[Dict]:
        """Register device with CMS."""
        try:
            session = self._get_session()
            data = {
                'hardware_id': hardware_id,
                'mode': 'direct'
            }
            if ip_address:
                data['ip_address'] = ip_address

            response = session.post(
                f'{self.cms_url}/api/v1/devices/register',
                json=data,
                timeout=10
            )

            if response.status_code in (200, 201):
                return response.json()
            else:
                logger.error(f"Register failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Register error: {e}")
            return None

    def request_pairing(self, hardware_id: str) -> Optional[str]:
        """Request a pairing code."""
        try:
            session = self._get_session()
            response = session.post(
                f'{self.cms_url}/api/v1/devices/pairing/request',
                json={'hardware_id': hardware_id},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return data.get('pairing_code')
            else:
                logger.error(f"Pairing request failed: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Pairing request error: {e}")
            return None

    def check_pairing_status(self, hardware_id: str) -> Optional[Dict]:
        """Check if device has been paired."""
        try:
            session = self._get_session()
            response = session.get(
                f'{self.cms_url}/api/v1/devices/pairing/status/{hardware_id}',
                timeout=10
            )

            if response.status_code == 200:
                return response.json()
            return None

        except Exception as e:
            logger.error(f"Pairing status error: {e}")
            return None

    def get_device_layout(self, hardware_id: str) -> Optional[Dict]:
        """Get device layout configuration."""
        try:
            session = self._get_session()
            response = session.get(
                f'{self.cms_url}/api/v1/devices/{hardware_id}/layout',
                timeout=10
            )

            if response.status_code == 200:
                return response.json()
            return None

        except Exception as e:
            logger.error(f"Get layout error: {e}")
            return None


class PairingScreen:
    """Full-screen pairing code display."""

    def __init__(self, on_paired: callable):
        self._on_paired = on_paired
        self._pairing_code = '------'
        self._status_text = 'Connecting...'
        self._window: Optional[Gtk.Window] = None
        self._code_label: Optional[Gtk.Label] = None
        self._status_label: Optional[Gtk.Label] = None

    def create_window(self) -> Gtk.Window:
        """Create the pairing screen window."""
        self._window = Gtk.Window(title="Device Pairing")
        self._window.fullscreen()
        self._window.set_decorated(False)

        # Apply dark theme
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            window {
                background-color: #0f172a;
            }
            .title-label {
                color: #667eea;
                font-size: 48px;
                font-weight: bold;
            }
            .code-label {
                color: #ffffff;
                font-size: 180px;
                font-weight: bold;
                letter-spacing: 20px;
            }
            .status-label {
                color: #94a3b8;
                font-size: 32px;
            }
            .instruction-label {
                color: #64748b;
                font-size: 24px;
            }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Main container
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=40)
        vbox.set_halign(Gtk.Align.CENTER)
        vbox.set_valign(Gtk.Align.CENTER)

        # Title
        title_label = Gtk.Label(label="Skillz Media Player")
        title_label.get_style_context().add_class('title-label')
        vbox.pack_start(title_label, False, False, 0)

        # Pairing code
        self._code_label = Gtk.Label(label=self._pairing_code)
        self._code_label.get_style_context().add_class('code-label')
        vbox.pack_start(self._code_label, False, False, 40)

        # Status
        self._status_label = Gtk.Label(label=self._status_text)
        self._status_label.get_style_context().add_class('status-label')
        vbox.pack_start(self._status_label, False, False, 0)

        # Instructions
        instruction_label = Gtk.Label(label="Enter this code at 192.168.1.90 to pair this device")
        instruction_label.get_style_context().add_class('instruction-label')
        vbox.pack_start(instruction_label, False, False, 40)

        self._window.add(vbox)
        self._window.connect('key-press-event', self._on_key_press)

        return self._window

    def set_pairing_code(self, code: str) -> None:
        """Update the pairing code display."""
        self._pairing_code = code
        if self._code_label:
            self._code_label.set_text(code)

    def set_status(self, status: str) -> None:
        """Update the status text."""
        self._status_text = status
        if self._status_label:
            self._status_label.set_text(status)

    def show_success(self) -> None:
        """Show pairing success."""
        self.set_status("Pairing Successful!")
        if self._code_label:
            self._code_label.set_text("\u2713")  # Checkmark

    def _on_key_press(self, widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        """Handle key press."""
        if event.keyval == Gdk.KEY_Escape:
            return True
        elif event.keyval == Gdk.KEY_q and (event.state & Gdk.ModifierType.CONTROL_MASK):
            Gtk.main_quit()
            return True
        return False

    def show(self) -> None:
        """Show the pairing screen."""
        if self._window:
            self._window.show_all()

    def hide(self) -> None:
        """Hide the pairing screen."""
        if self._window:
            self._window.hide()

    def destroy(self) -> None:
        """Destroy the pairing screen."""
        if self._window:
            self._window.destroy()
            self._window = None


class LayoutPlayer:
    """
    Layout-based media player with multi-zone support.
    """

    def __init__(self, cms_url: str, media_dir: str, hardware_id: str):
        self.cms_url = cms_url.rstrip('/')
        self.media_dir = Path(media_dir)
        self.hardware_id = hardware_id

        self._window: Optional[Gtk.Window] = None
        self._fixed: Optional[Gtk.Fixed] = None
        self._video_players: Dict[str, Any] = {}
        self._layout_data: Optional[Dict] = None
        self._running = False

    def fetch_layout(self) -> bool:
        """Fetch layout from CMS."""
        try:
            import requests
            response = requests.get(
                f'{self.cms_url}/api/v1/devices/{self.hardware_id}/layout',
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                self._layout_data = data.get('layout')
                return self._layout_data is not None

            return False
        except Exception as e:
            logger.error(f"Failed to fetch layout: {e}")
            return False

    def sync_content(self) -> bool:
        """Download all content files from CMS to local media directory."""
        if not self._layout_data:
            return False

        import requests
        self.media_dir.mkdir(parents=True, exist_ok=True)
        success = True

        for layer in self._layout_data.get('layers', []):
            for item in layer.get('items', []):
                filename = item.get('filename')
                url = item.get('url')
                if not filename or not url:
                    continue

                local_path = self.media_dir / filename
                if local_path.exists():
                    logger.info(f"Content exists: {filename}")
                    continue

                # Download from CMS
                try:
                    full_url = f"{self.cms_url}{url}" if url.startswith('/') else url
                    logger.info(f"Downloading: {filename}")
                    response = requests.get(full_url, stream=True, timeout=60)
                    if response.status_code == 200:
                        with open(local_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        logger.info(f"Downloaded: {filename}")
                    else:
                        logger.error(f"Failed to download {filename}: HTTP {response.status_code}")
                        success = False
                except Exception as e:
                    logger.error(f"Failed to download {filename}: {e}")
                    success = False

        return success

    def create_window(self) -> Gtk.Window:
        """Create fullscreen window for video playback."""
        self._window = Gtk.Window(title="Skillz Media Player")
        self._window.fullscreen()
        self._window.set_decorated(False)

        # Black background via CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"window { background-color: black; }")
        self._window.get_style_context().add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Fixed container for video zones
        self._fixed = Gtk.Fixed()
        self._window.add(self._fixed)

        self._window.connect('key-press-event', self._on_key_press)
        self._window.connect('destroy', self._on_destroy)

        return self._window

    def _create_video_zone(self, layer: Dict) -> Gtk.DrawingArea:
        """Create a video zone widget."""
        widget = Gtk.DrawingArea()
        widget.set_size_request(layer['width'], layer['height'])

        # Black background
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"drawingarea { background-color: black; }")
        widget.get_style_context().add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Create GStreamer pipeline
        layer_id = layer['id']
        self._video_players[layer_id] = {
            'widget': widget,
            'items': layer.get('items', []),
            'current_index': 0,
            'player': None,
            'layer': layer
        }

        widget.connect('realize', lambda w: self._init_video_player(layer_id))

        return widget

    def _init_video_player(self, layer_id: str) -> None:
        """Initialize GStreamer player for a video zone."""
        zone = self._video_players.get(layer_id)
        if not zone:
            return

        widget = zone['widget']
        layer = zone['layer']

        # Get window XID for embedding
        window = widget.get_window()
        if not window:
            return

        xid = window.get_xid()

        # Create playbin3
        player = Gst.ElementFactory.make('playbin3', f'player_{layer_id}')
        if not player:
            logger.error("Failed to create playbin3")
            return

        # Use xvimagesink for GTK-embedded fullscreen playback
        video_sink = Gst.ElementFactory.make('xvimagesink', 'videosink')
        if video_sink:
            video_sink.set_property('sync', True)
            player.set_property('video-sink', video_sink)
            # Store sink and XID for overlay setup
            zone['video_sink'] = video_sink
            zone['xid'] = xid
            # Set window handle using GstVideo.VideoOverlay
            GstVideo.VideoOverlay.set_window_handle(video_sink, xid)
            logger.info(f"Using xvimagesink with XID {xid}")
        else:
            # Fallback to autovideosink
            video_sink = Gst.ElementFactory.make('autovideosink', 'videosink')
            if video_sink:
                player.set_property('video-sink', video_sink)
                logger.info("Using autovideosink fallback")

        # Connect signals for gapless playback
        player.connect('about-to-finish', lambda p: self._on_about_to_finish(layer_id))

        # Setup bus
        bus = player.get_bus()
        bus.add_signal_watch()
        bus.connect('message::eos', lambda b, m: self._on_eos(layer_id))
        bus.connect('message::error', lambda b, m: self._on_error(layer_id, m))

        zone['player'] = player
        zone['bus'] = bus

    def _get_content_uri(self, item: Dict) -> str:
        """Get content URI for an item."""
        filename = item.get('filename', '')
        local_path = self.media_dir / filename

        if local_path.exists():
            return f"file://{local_path}"

        url = item.get('url', '')
        if url.startswith('/'):
            return f"{self.cms_url}{url}"
        return url

    def _on_about_to_finish(self, layer_id: str) -> None:
        """Handle about-to-finish for gapless playback."""
        zone = self._video_players.get(layer_id)
        if not zone or not zone['items']:
            return

        items = zone['items']
        current = zone['current_index']
        next_idx = (current + 1) % len(items)

        # Queue next video for seamless transition
        if next_idx != current or len(items) > 1:
            next_item = items[next_idx]
            uri = self._get_content_uri(next_item)
            zone['player'].set_property('uri', uri)
            zone['current_index'] = next_idx
            zone['next_queued'] = True
            logger.info(f"Queued next: {next_item.get('filename')}")

    def _on_eos(self, layer_id: str) -> None:
        """Handle end of stream for looping."""
        zone = self._video_players.get(layer_id)
        if not zone:
            return

        # If next wasn't queued (single video loop), restart
        if not zone.get('next_queued', False):
            self._play_video_zone(layer_id)
        else:
            zone['next_queued'] = False

    def _on_error(self, layer_id: str, message: Gst.Message) -> None:
        """Handle playback error."""
        error, debug = message.parse_error()
        logger.error(f"Playback error in {layer_id}: {error.message}")

        # Try next video
        zone = self._video_players.get(layer_id)
        if zone and len(zone['items']) > 1:
            zone['current_index'] = (zone['current_index'] + 1) % len(zone['items'])
            GLib.idle_add(lambda: self._play_video_zone(layer_id))

    def _play_video_zone(self, layer_id: str) -> bool:
        """Start playing a video zone."""
        zone = self._video_players.get(layer_id)
        if not zone or not zone['items'] or not zone['player']:
            return False

        item = zone['items'][zone['current_index']]
        uri = self._get_content_uri(item)

        logger.info(f"Playing: {item.get('filename')}")
        zone['player'].set_state(Gst.State.NULL)
        zone['player'].set_property('uri', uri)
        zone['next_queued'] = False

        ret = zone['player'].set_state(Gst.State.PLAYING)
        return ret != Gst.StateChangeReturn.FAILURE

    def _build_layout(self) -> None:
        """Build the layout UI from fetched data."""
        if not self._layout_data:
            return

        layers = self._layout_data.get('layers', [])
        layers.sort(key=lambda l: l.get('z_index', 0))

        for layer in layers:
            content_type = 'video'  # Default
            items = layer.get('items', [])
            if items:
                content_type = items[0].get('content_type', 'video')

            if 'video' in content_type:
                widget = self._create_video_zone(layer)
            else:
                # For now, treat other types as video
                widget = self._create_video_zone(layer)

            widget.set_opacity(layer.get('opacity', 1.0))
            self._fixed.put(widget, layer.get('x', 0), layer.get('y', 0))

    def _on_key_press(self, widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        """Handle key press."""
        if event.keyval == Gdk.KEY_Escape:
            self._window.iconify()
            return True
        elif event.keyval == Gdk.KEY_F11:
            if self._window.get_window().get_state() & Gdk.WindowState.FULLSCREEN:
                self._window.unfullscreen()
            else:
                self._window.fullscreen()
            return True
        elif event.keyval == Gdk.KEY_q and (event.state & Gdk.ModifierType.CONTROL_MASK):
            self.stop()
            Gtk.main_quit()
            return True
        return False

    def _on_destroy(self, widget: Gtk.Widget) -> None:
        """Handle window destroy."""
        self.stop()

    def start(self) -> bool:
        """Start the layout player."""
        if self._running:
            return True

        # Fetch layout
        if not self.fetch_layout():
            logger.warning("No layout available, using fallback")
            # Create a default full-screen video zone
            self._layout_data = {
                'name': 'Default',
                'canvas_width': 1920,
                'canvas_height': 1080,
                'background_color': '#000000',
                'layers': [{
                    'id': 'default',
                    'name': 'Main Video',
                    'layer_type': 'content',
                    'x': 0, 'y': 0,
                    'width': 1920, 'height': 1080,
                    'z_index': 0,
                    'opacity': 1.0,
                    'content_source': 'playlist',
                    'items': []  # Will be populated from playlist
                }]
            }

        # Download content files before playback
        logger.info("Syncing content files...")
        self.sync_content()

        # Create window
        self.create_window()

        # Build layout
        self._build_layout()

        self._running = True
        self._window.show_all()

        # Start video playback
        for layer_id in self._video_players:
            GLib.timeout_add(500, lambda lid=layer_id: self._play_video_zone(lid))

        return True

    def stop(self) -> None:
        """Stop the player."""
        if not self._running:
            return

        self._running = False

        for zone in self._video_players.values():
            if zone.get('player'):
                zone['player'].set_state(Gst.State.NULL)
            if zone.get('bus'):
                zone['bus'].remove_signal_watch()

        self._video_players.clear()

    def show(self) -> None:
        """Show the player window."""
        if self._window:
            self._window.show_all()

    def hide(self) -> None:
        """Hide the player window."""
        if self._window:
            self._window.hide()


class SkillzMediaPlayer:
    """
    Main application orchestrating pairing and playback.
    """

    PAIRING_CHECK_INTERVAL_MS = 5000
    CONFIG_FILE = '/home/nvidia/skillz-player/config/device.json'
    MEDIA_DIR = '/home/nvidia/skillz-player/media'
    LOGS_DIR = '/home/nvidia/skillz-player/logs'

    def __init__(self, cms_url: str = 'http://192.168.1.90:5002'):
        self.cms_url = cms_url

        # Ensure directories exist
        Path(self.MEDIA_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.LOGS_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.CONFIG_FILE).parent.mkdir(parents=True, exist_ok=True)

        # Load or create config
        self.config = self._load_config()

        # Components
        self.cms_client = CMSClient(cms_url)
        self.pairing_screen: Optional[PairingScreen] = None
        self.layout_player: Optional[LayoutPlayer] = None

        self._running = False
        self._pairing_check_id: Optional[int] = None

    def _load_config(self) -> DeviceConfig:
        """Load device configuration from disk."""
        if Path(self.CONFIG_FILE).exists():
            try:
                with open(self.CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                return DeviceConfig(**data)
            except Exception as e:
                logger.error(f"Failed to load config: {e}")

        # Create new config with hardware ID
        hardware_id = self._get_hardware_id()
        config = DeviceConfig(
            hardware_id=hardware_id,
            cms_url=self.cms_url
        )
        self._save_config(config)
        return config

    def _save_config(self, config: DeviceConfig) -> None:
        """Save device configuration to disk."""
        try:
            data = {
                'hardware_id': config.hardware_id,
                'device_id': config.device_id,
                'pairing_code': config.pairing_code,
                'status': config.status,
                'cms_url': config.cms_url,
                'paired': config.paired
            }
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def _get_hardware_id(self) -> str:
        """Get or generate hardware ID."""
        id_file = Path('/home/nvidia/skillz-player/.hardware_id')
        if id_file.exists():
            return id_file.read_text().strip()

        # Generate from system info
        try:
            result = subprocess.run(
                ['cat', '/sys/class/dmi/id/product_uuid'],
                capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                hw_id = result.stdout.strip()
            else:
                hw_id = str(uuid.uuid4())
        except Exception:
            hw_id = str(uuid.uuid4())

        id_file.write_text(hw_id)
        return hw_id

    def _get_ip_address(self) -> Optional[str]:
        """Get device IP address."""
        try:
            result = subprocess.run(
                ['hostname', '-I'],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                ips = result.stdout.strip().split()
                return ips[0] if ips else None
        except Exception:
            pass
        return None

    def _start_pairing_flow(self) -> None:
        """Start the device pairing flow."""
        logger.info("Starting pairing flow")

        # Create pairing screen
        self.pairing_screen = PairingScreen(on_paired=self._on_paired)
        self.pairing_screen.create_window()
        self.pairing_screen.show()

        # Register device
        ip_address = self._get_ip_address()
        device_data = self.cms_client.register_device(
            self.config.hardware_id,
            ip_address
        )

        if device_data:
            self.config.device_id = device_data.get('device_id')
            self._save_config(self.config)
            logger.info(f"Device registered: {self.config.device_id}")

        # Request pairing code
        code = self.cms_client.request_pairing(self.config.hardware_id)

        if code:
            self.config.pairing_code = code
            self._save_config(self.config)
            self.pairing_screen.set_pairing_code(code)
            self.pairing_screen.set_status("Waiting for approval...")

            # Start polling for approval
            self._pairing_check_id = GLib.timeout_add(
                self.PAIRING_CHECK_INTERVAL_MS,
                self._check_pairing_status
            )
        else:
            self.pairing_screen.set_status("Connection error - retrying...")
            GLib.timeout_add(5000, self._retry_pairing)

    def _retry_pairing(self) -> bool:
        """Retry pairing code request."""
        code = self.cms_client.request_pairing(self.config.hardware_id)
        if code:
            self.config.pairing_code = code
            self._save_config(self.config)
            self.pairing_screen.set_pairing_code(code)
            self.pairing_screen.set_status("Waiting for approval...")

            self._pairing_check_id = GLib.timeout_add(
                self.PAIRING_CHECK_INTERVAL_MS,
                self._check_pairing_status
            )
            return False
        return True  # Keep retrying

    def _check_pairing_status(self) -> bool:
        """Check if device has been paired."""
        if not self._running:
            return False

        result = self.cms_client.check_pairing_status(self.config.hardware_id)

        if result and result.get('status') == 'active':
            logger.info("Device paired!")
            self.config.paired = True
            self.config.status = 'active'
            self._save_config(self.config)

            self.pairing_screen.show_success()
            GLib.timeout_add(1500, self._transition_to_playback)
            return False  # Stop checking

        return True  # Continue checking

    def _on_paired(self) -> None:
        """Handle pairing completion."""
        self._transition_to_playback()

    def _transition_to_playback(self) -> bool:
        """Transition from pairing to playback."""
        logger.info("Transitioning to playback")

        # Hide pairing screen
        if self.pairing_screen:
            self.pairing_screen.destroy()
            self.pairing_screen = None

        # Start layout player
        self._start_playback()

        return False  # Don't repeat

    def _start_playback(self) -> None:
        """Start layout-based playback."""
        self.layout_player = LayoutPlayer(
            cms_url=self.cms_url,
            media_dir=self.MEDIA_DIR,
            hardware_id=self.config.hardware_id
        )

        if not self.layout_player.start():
            logger.error("Failed to start layout player")
            # Fall back to showing status
            self._show_status_screen()
            return

        logger.info("Layout player started")

    def _show_status_screen(self) -> None:
        """Show a status screen when no content is available."""
        window = Gtk.Window(title="Skillz Media Player")
        window.fullscreen()

        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            window { background-color: #0f172a; }
            label { color: #ffffff; font-size: 32px; }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        label = Gtk.Label(label="Waiting for content...")
        label.set_halign(Gtk.Align.CENTER)
        label.set_valign(Gtk.Align.CENTER)
        window.add(label)

        window.connect('key-press-event', lambda w, e: (
            Gtk.main_quit() if e.keyval == Gdk.KEY_q and
            (e.state & Gdk.ModifierType.CONTROL_MASK) else False
        ))

        window.show_all()

    def start(self) -> bool:
        """Start the application."""
        if self._running:
            return True

        logger.info("=" * 60)
        logger.info("Starting Skillz Media Player")
        logger.info(f"Hardware ID: {self.config.hardware_id}")
        logger.info(f"CMS URL: {self.cms_url}")
        logger.info("=" * 60)

        self._running = True

        if self.config.paired and self.config.status == 'active':
            logger.info("Device is paired - starting playback")
            self._start_playback()
        else:
            logger.info("Device not paired - starting pairing flow")
            self._start_pairing_flow()

        return True

    def stop(self) -> None:
        """Stop the application."""
        if not self._running:
            return

        self._running = False

        if self._pairing_check_id:
            GLib.source_remove(self._pairing_check_id)
            self._pairing_check_id = None

        if self.layout_player:
            self.layout_player.stop()

        if self.pairing_screen:
            self.pairing_screen.destroy()

        logger.info("Skillz Media Player stopped")

    def run(self) -> None:
        """Run the application (blocking)."""
        signal.signal(signal.SIGINT, lambda s, f: GLib.idle_add(Gtk.main_quit))
        signal.signal(signal.SIGTERM, lambda s, f: GLib.idle_add(Gtk.main_quit))

        if not self.start():
            logger.error("Failed to start")
            sys.exit(1)

        try:
            Gtk.main()
        except KeyboardInterrupt:
            pass

        self.stop()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Skillz Media Player")
    parser.add_argument('--cms-url', default='http://192.168.1.90:5002',
                        help='CMS URL')
    parser.add_argument('--reset-pairing', action='store_true',
                        help='Reset pairing and show pairing screen')

    args = parser.parse_args()

    # Handle reset-pairing flag
    if args.reset_pairing:
        config_file = Path('/home/nvidia/skillz-player/config/device.json')
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                config['paired'] = False
                config['status'] = 'pending'
                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=2)
                logger.info("Pairing reset - will show pairing screen")
            except Exception as e:
                logger.error(f"Failed to reset pairing: {e}")

    player = SkillzMediaPlayer(cms_url=args.cms_url)
    player.run()


if __name__ == '__main__':
    main()
