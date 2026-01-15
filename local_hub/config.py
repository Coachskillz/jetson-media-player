"""
Configuration management for Local Hub Service.
Loads and validates settings from JSON config file.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


# Default configuration path
DEFAULT_CONFIG_PATH = '/etc/skillz-hub/config.json'

# Default configuration values
DEFAULT_CONFIG = {
    'hq_url': 'https://hub.skillzmedia.com',
    'network_slug': '',
    'sync_interval_minutes': 5,
    'heartbeat_interval_seconds': 60,
    'alert_retry_interval_seconds': 30,
    'storage_path': '/var/skillz-hub',
    'log_path': '/var/log/skillz-hub',
    'port': 5000
}


class HubConfig:
    """Manages hub configuration from JSON files."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration.

        Args:
            config_path: Path to config file. If None, uses /etc/skillz-hub/config.json
        """
        if config_path is None:
            config_path = DEFAULT_CONFIG_PATH

        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self._loaded = False
        self.load()

    def load(self) -> None:
        """Load configuration from JSON file."""
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                file_config = json.load(f)
                # Merge file config with defaults
                self._config.update(file_config)
            self._loaded = True

        # Apply environment variable overrides
        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """Override config values from environment variables."""
        # SKILLZ_HUB_HQ_URL overrides hq_url
        if 'SKILLZ_HUB_HQ_URL' in os.environ:
            self._config['hq_url'] = os.environ['SKILLZ_HUB_HQ_URL']

        # SKILLZ_HUB_NETWORK_SLUG overrides network_slug
        if 'SKILLZ_HUB_NETWORK_SLUG' in os.environ:
            self._config['network_slug'] = os.environ['SKILLZ_HUB_NETWORK_SLUG']

        # SKILLZ_HUB_STORAGE_PATH overrides storage_path
        if 'SKILLZ_HUB_STORAGE_PATH' in os.environ:
            self._config['storage_path'] = os.environ['SKILLZ_HUB_STORAGE_PATH']

        # SKILLZ_HUB_PORT overrides port
        if 'SKILLZ_HUB_PORT' in os.environ:
            self._config['port'] = int(os.environ['SKILLZ_HUB_PORT'])

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.

        Args:
            key: Configuration key (e.g., 'hq_url' or 'nested.key')
            default: Default value if key not found

        Returns:
            Configuration value or default

        Example:
            >>> config = HubConfig()
            >>> config.get('hq_url')
            'https://hub.skillzmedia.com'
        """
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value using dot notation.

        Args:
            key: Configuration key (e.g., 'hq_url')
            value: Value to set
        """
        keys = key.split('.')
        config = self._config

        # Navigate to the parent key
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        # Set the final key
        config[keys[-1]] = value

    def save(self, path: Optional[str] = None) -> None:
        """
        Save configuration to JSON file.

        Args:
            path: Path to save to. If None, uses original config_path
        """
        save_path = Path(path) if path else self.config_path

        # Ensure parent directory exists
        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, 'w') as f:
            json.dump(self._config, f, indent=2)

    @property
    def hq_url(self) -> str:
        """Get HQ API base URL."""
        return self.get('hq_url', DEFAULT_CONFIG['hq_url'])

    @property
    def network_slug(self) -> str:
        """Get network slug for registration."""
        return self.get('network_slug', '')

    @property
    def storage_path(self) -> str:
        """Get local storage root path."""
        return self.get('storage_path', DEFAULT_CONFIG['storage_path'])

    @property
    def log_path(self) -> str:
        """Get log directory path."""
        return self.get('log_path', DEFAULT_CONFIG['log_path'])

    @property
    def sync_interval_minutes(self) -> int:
        """Get content sync interval in minutes."""
        return self.get('sync_interval_minutes', DEFAULT_CONFIG['sync_interval_minutes'])

    @property
    def heartbeat_interval_seconds(self) -> int:
        """Get HQ heartbeat interval in seconds."""
        return self.get('heartbeat_interval_seconds', DEFAULT_CONFIG['heartbeat_interval_seconds'])

    @property
    def alert_retry_interval_seconds(self) -> int:
        """Get alert retry interval in seconds."""
        return self.get('alert_retry_interval_seconds', DEFAULT_CONFIG['alert_retry_interval_seconds'])

    @property
    def port(self) -> int:
        """Get server port."""
        return self.get('port', DEFAULT_CONFIG['port'])

    @property
    def content_path(self) -> str:
        """Get content storage path."""
        return os.path.join(self.storage_path, 'storage', 'content')

    @property
    def databases_path(self) -> str:
        """Get databases storage path."""
        return os.path.join(self.storage_path, 'storage', 'databases')

    @property
    def db_path(self) -> str:
        """Get SQLite database path."""
        return os.path.join(self.storage_path, 'hub.db')

    def __repr__(self) -> str:
        """String representation."""
        return f"HubConfig(path={self.config_path}, loaded={self._loaded})"


# Global config instance (can be imported by other modules)
_global_config: Optional[HubConfig] = None


def load_config(config_path: Optional[str] = None) -> HubConfig:
    """
    Load and return the configuration instance.

    This function provides a simple interface for loading configuration.
    On first call, it creates a new HubConfig instance. Subsequent calls
    return the cached instance.

    Args:
        config_path: Path to config file (only used on first call)

    Returns:
        HubConfig instance

    Example:
        >>> from config import load_config
        >>> config = load_config()
        >>> config.get('hq_url')
        'https://hub.skillzmedia.com'
    """
    global _global_config

    if _global_config is None:
        _global_config = HubConfig(config_path)

    return _global_config


def get_config(config_path: Optional[str] = None) -> HubConfig:
    """
    Alias for load_config for consistency with other modules.

    Args:
        config_path: Path to config file (only used on first call)

    Returns:
        HubConfig instance
    """
    return load_config(config_path)


def reset_config() -> None:
    """
    Reset the global config instance.

    Useful for testing when you need to reload configuration.
    """
    global _global_config
    _global_config = None
