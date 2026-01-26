"""
Configuration management for Local Hub Service.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_CONFIG_PATH = "/etc/skillz-hub/config.json"

DEFAULT_CONFIG = {
    "cms_url": "http://localhost:5002",
    "hub_id": "",
    "hub_code": "",
    "hub_name": "",
    "hub_ip": "10.10.10.1",
    "network_id": "",
    "sync_interval_minutes": 5,
    "heartbeat_interval_seconds": 60,
    "alert_retry_interval_seconds": 30,
    "storage_path": "/var/skillz-hub",
    "log_path": "/var/log/skillz-hub",
    "port": 5000
}


class HubConfig:
    """Manages hub configuration from JSON files."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = DEFAULT_CONFIG_PATH
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self._loaded = False
        self.load()

    def load(self) -> None:
        """Load configuration from JSON file."""
        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                file_config = json.load(f)
                self._config.update(file_config)
            self._loaded = True
        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """Override config values from environment variables."""
        env_map = {
            "SKILLZ_HUB_CMS_URL": "cms_url",
            "SKILLZ_HUB_CODE": "hub_code",
            "SKILLZ_HUB_NAME": "hub_name",
            "SKILLZ_HUB_NETWORK_ID": "network_id",
            "SKILLZ_HUB_STORAGE_PATH": "storage_path",
            "SKILLZ_HUB_PORT": "port",
        }
        for env_var, config_key in env_map.items():
            if env_var in os.environ:
                value = os.environ[env_var]
                if config_key == "port":
                    value = int(value)
                self._config[config_key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    @property
    def cms_url(self) -> str:
        return self.get("cms_url", DEFAULT_CONFIG["cms_url"])

    @property
    def hub_id(self) -> str:
        return self.get("hub_id", "")

    @property
    def hub_code(self) -> str:
        return self.get("hub_code", "")

    @property
    def hub_name(self) -> str:
        return self.get("hub_name", "")

    @property
    def hub_ip(self) -> str:
        return self.get("hub_ip", "10.10.10.1")

    @property
    def network_id(self) -> str:
        return self.get("network_id", "")

    @property
    def storage_path(self) -> str:
        return self.get("storage_path", DEFAULT_CONFIG["storage_path"])

    @property
    def log_path(self) -> str:
        return self.get("log_path", DEFAULT_CONFIG["log_path"])

    @property
    def port(self) -> int:
        return self.get("port", DEFAULT_CONFIG["port"])

    @property
    def sync_interval_minutes(self) -> int:
        return self.get("sync_interval_minutes", DEFAULT_CONFIG["sync_interval_minutes"])

    @property
    def heartbeat_interval_seconds(self) -> int:
        return self.get("heartbeat_interval_seconds", DEFAULT_CONFIG["heartbeat_interval_seconds"])

    @property
    def alert_retry_interval_seconds(self) -> int:
        return self.get("alert_retry_interval_seconds", DEFAULT_CONFIG["alert_retry_interval_seconds"])

    @property
    def content_path(self) -> str:
        return self.get("content_path", os.path.join(self.storage_path, "content"))

    @property
    def databases_path(self) -> str:
        return self.get("databases_path", os.path.join(self.storage_path, "databases"))

    @property
    def db_path(self) -> str:
        """Get SQLite database path."""
        return os.path.join(self.storage_path, "hub.db")


_global_config: Optional[HubConfig] = None


def load_config(config_path: Optional[str] = None) -> HubConfig:
    global _global_config
    if _global_config is None:
        if config_path is None:
            config_path = os.environ.get("SKILLZ_HUB_CONFIG")
        _global_config = HubConfig(config_path)
    return _global_config


def get_config(config_path: Optional[str] = None) -> HubConfig:
    return load_config(config_path)


def reset_config() -> None:
    global _global_config
    _global_config = None
