"""
JSON configuration management for Jetson Media Player.
Handles device.json, playlist.json, and settings.json files.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class PlayerConfig:
    """Manages JSON configuration files for the media player."""

    # Default config directory on Jetson devices
    DEFAULT_CONFIG_DIR = "/home/skillz/config"

    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize configuration manager.

        Args:
            config_dir: Path to config directory. If None, uses DEFAULT_CONFIG_DIR
        """
        if config_dir is None:
            config_dir = self.DEFAULT_CONFIG_DIR

        self.config_dir = Path(config_dir)

        # Individual config data
        self._device: Dict[str, Any] = {}
        self._playlist: Dict[str, Any] = {}
        self._settings: Dict[str, Any] = {}

        # Load configs if directory exists
        if self.config_dir.exists():
            self.load_all()

    def _load_json(self, filename: str) -> Dict[str, Any]:
        """
        Load a JSON config file.

        Args:
            filename: Name of the JSON file to load

        Returns:
            Parsed JSON data as dictionary
        """
        file_path = self.config_dir / filename
        if not file_path.exists():
            return {}

        with open(file_path, 'r') as f:
            return json.load(f)

    def _save_json(self, filename: str, data: Dict[str, Any]) -> None:
        """
        Save data to a JSON config file.

        Args:
            filename: Name of the JSON file to save
            data: Dictionary to save as JSON
        """
        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

        file_path = self.config_dir / filename
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)

    def load_all(self) -> None:
        """Load all configuration files."""
        self._device = self._load_json("device.json")
        self._playlist = self._load_json("playlist.json")
        self._settings = self._load_json("settings.json")

        # Apply environment variable overrides
        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """Override config values from environment variables."""
        if 'JMP_SCREEN_ID' in os.environ:
            self._device['screen_id'] = os.environ['JMP_SCREEN_ID']

        if 'JMP_HUB_URL' in os.environ:
            self._device['hub_url'] = os.environ['JMP_HUB_URL']

    def save_all(self) -> None:
        """Save all configuration files."""
        self._save_json("device.json", self._device)
        self._save_json("playlist.json", self._playlist)
        self._save_json("settings.json", self._settings)

    # Device config accessors

    @property
    def screen_id(self) -> str:
        """Get screen ID."""
        return self._device.get('screen_id', '')

    @screen_id.setter
    def screen_id(self, value: str) -> None:
        """Set screen ID."""
        self._device['screen_id'] = value

    @property
    def hardware_id(self) -> str:
        """Get hardware ID (MAC address or UUID)."""
        return self._device.get('hardware_id', '')

    @hardware_id.setter
    def hardware_id(self, value: str) -> None:
        """Set hardware ID."""
        self._device['hardware_id'] = value

    @property
    def hub_url(self) -> str:
        """Get local hub URL."""
        return self._device.get('hub_url', 'http://192.168.1.100:5000')

    @hub_url.setter
    def hub_url(self, value: str) -> None:
        """Set local hub URL."""
        self._device['hub_url'] = value

    @property
    def device_name(self) -> str:
        """Get device display name."""
        return self._device.get('name', 'Unnamed Screen')

    @device_name.setter
    def device_name(self, value: str) -> None:
        """Set device display name."""
        self._device['name'] = value

    @property
    def location_in_store(self) -> str:
        """Get device location description."""
        return self._device.get('location_in_store', '')

    @location_in_store.setter
    def location_in_store(self, value: str) -> None:
        """Set device location description."""
        self._device['location_in_store'] = value

    @property
    def connection_mode(self) -> str:
        """Get connection mode (hub or direct)."""
        return self._device.get('connection_mode', 'direct')

    @connection_mode.setter
    def connection_mode(self, value: str) -> None:
        """Set connection mode."""
        if value not in ('hub', 'direct'):
            raise ValueError("connection_mode must be 'hub' or 'direct'")
        self._device['connection_mode'] = value

    # Playlist config accessors

    @property
    def default_playlist(self) -> Dict[str, Any]:
        """Get default playlist configuration."""
        return self._playlist.get('default_playlist', {'id': '', 'items': []})

    @default_playlist.setter
    def default_playlist(self, value: Dict[str, Any]) -> None:
        """Set default playlist configuration."""
        self._playlist['default_playlist'] = value

    @property
    def triggered_playlists(self) -> List[Dict[str, Any]]:
        """Get list of triggered playlists."""
        return self._playlist.get('triggered_playlists', [])

    @triggered_playlists.setter
    def triggered_playlists(self, value: List[Dict[str, Any]]) -> None:
        """Set triggered playlists."""
        self._playlist['triggered_playlists'] = value

    @property
    def playlist_version(self) -> int:
        """Get current playlist version number."""
        return self._playlist.get('version', 0)

    @playlist_version.setter
    def playlist_version(self, value: int) -> None:
        """Set playlist version number."""
        self._playlist['version'] = value

    @property
    def playlist_updated_at(self) -> str:
        """Get playlist last updated timestamp."""
        return self._playlist.get('updated_at', '')

    @playlist_updated_at.setter
    def playlist_updated_at(self, value: str) -> None:
        """Set playlist updated timestamp."""
        self._playlist['updated_at'] = value

    # Settings config accessors

    @property
    def camera_enabled(self) -> bool:
        """Check if camera is enabled."""
        return self._settings.get('camera_enabled', True)

    @camera_enabled.setter
    def camera_enabled(self, value: bool) -> None:
        """Set camera enabled state."""
        self._settings['camera_enabled'] = value

    @property
    def ncmec_enabled(self) -> bool:
        """Check if NCMEC alerts are enabled."""
        return self._settings.get('ncmec_enabled', True)

    @ncmec_enabled.setter
    def ncmec_enabled(self, value: bool) -> None:
        """Set NCMEC enabled state."""
        self._settings['ncmec_enabled'] = value

    @property
    def loyalty_enabled(self) -> bool:
        """Check if loyalty program integration is enabled."""
        return self._settings.get('loyalty_enabled', False)

    @loyalty_enabled.setter
    def loyalty_enabled(self, value: bool) -> None:
        """Set loyalty enabled state."""
        self._settings['loyalty_enabled'] = value

    @property
    def demographics_enabled(self) -> bool:
        """Check if demographic targeting is enabled."""
        return self._settings.get('demographics_enabled', True)

    @demographics_enabled.setter
    def demographics_enabled(self, value: bool) -> None:
        """Set demographics enabled state."""
        self._settings['demographics_enabled'] = value

    @property
    def ncmec_db_version(self) -> int:
        """Get NCMEC database version."""
        return self._settings.get('ncmec_db_version', 0)

    @ncmec_db_version.setter
    def ncmec_db_version(self, value: int) -> None:
        """Set NCMEC database version."""
        self._settings['ncmec_db_version'] = value

    @property
    def loyalty_db_version(self) -> int:
        """Get loyalty database version."""
        return self._settings.get('loyalty_db_version', 0)

    @loyalty_db_version.setter
    def loyalty_db_version(self, value: int) -> None:
        """Set loyalty database version."""
        self._settings['loyalty_db_version'] = value

    # Direct config access methods

    def get_device_config(self) -> Dict[str, Any]:
        """Get raw device configuration dictionary."""
        return self._device.copy()

    def get_playlist_config(self) -> Dict[str, Any]:
        """Get raw playlist configuration dictionary."""
        return self._playlist.copy()

    def get_settings_config(self) -> Dict[str, Any]:
        """Get raw settings configuration dictionary."""
        return self._settings.copy()

    def set_device_config(self, config: Dict[str, Any]) -> None:
        """Set device configuration from dictionary."""
        self._device = config.copy()

    def set_playlist_config(self, config: Dict[str, Any]) -> None:
        """Set playlist configuration from dictionary."""
        self._playlist = config.copy()

    def set_settings_config(self, config: Dict[str, Any]) -> None:
        """Set settings configuration from dictionary."""
        self._settings = config.copy()

    def save_device(self) -> None:
        """Save device configuration to file."""
        self._save_json("device.json", self._device)

    def save_playlist(self) -> None:
        """Save playlist configuration to file."""
        self._save_json("playlist.json", self._playlist)

    def save_settings(self) -> None:
        """Save settings configuration to file."""
        self._save_json("settings.json", self._settings)

    def load_device(self) -> None:
        """Load device configuration from file."""
        self._device = self._load_json("device.json")

    def load_playlist(self) -> None:
        """Load playlist configuration from file."""
        self._playlist = self._load_json("playlist.json")

    def load_settings(self) -> None:
        """Load settings configuration from file."""
        self._settings = self._load_json("settings.json")

    def __repr__(self) -> str:
        """String representation."""
        return f"PlayerConfig(config_dir={self.config_dir})"


# Global config instance
_global_player_config: Optional[PlayerConfig] = None


def get_player_config(config_dir: Optional[str] = None) -> PlayerConfig:
    """
    Get the global player configuration instance.

    Args:
        config_dir: Path to config directory (only used on first call)

    Returns:
        PlayerConfig instance
    """
    global _global_player_config

    if _global_player_config is None:
        _global_player_config = PlayerConfig(config_dir)

    return _global_player_config
