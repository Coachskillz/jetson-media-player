127
"""
Configuration management for Jetson Media Player.
Loads and validates settings from YAML files.
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


class Config:
    """Manages application configuration from YAML files."""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration.
        
        Args:
            config_path: Path to config file. If None, uses default_config.yaml
        """
        if config_path is None:
            # Default to config/default_config.yaml in project root
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "config" / "default_config.yaml"
        
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self.load()
    
    def load(self) -> None:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        with open(self.config_path, 'r') as f:
            self._config = yaml.safe_load(f)
        
        # Apply environment variable overrides
        self._apply_env_overrides()
    
    def _apply_env_overrides(self) -> None:
        """Override config values from environment variables."""
        # Example: JMP_CMS_API_KEY environment variable overrides cms.api_key
        if 'JMP_CMS_API_KEY' in os.environ:
            self._config['cms']['api_key'] = os.environ['JMP_CMS_API_KEY']
        
        if 'JMP_DEVICE_ID' in os.environ:
            self._config['device']['id'] = os.environ['JMP_DEVICE_ID']
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.
        
        Args:
            key: Configuration key (e.g., 'cms.base_url')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
            
        Example:
            >>> config = Config()
            >>> config.get('cms.base_url')
            'https://cms.example.com/api/v1'
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
        """        Set configuration value using dot notation.
        
        Args:
            key: Configuration key (e.g., 'cms.api_key')
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
        Save configuration to YAML file.
        
        Args:
            path: Path to save to. If None, uses original config_path
        """
        save_path = Path(path) if path else self.config_path
        
        with open(save_path, 'w') as f:
            yaml.dump(self._config, f, default_flow_style=False, indent=2)
    
    @property
    def device_id(self) -> str:
        """Get device ID."""
        return self.get('device.id', 'unknown')
    
    @property
    def cms_base_url(self) -> str:
        """Get CMS base URL."""
        return self.get('cms.base_url', '')
    
    @property
    def content_dir(self) -> str:
        """Get content directory path."""
        return self.get('playback.content_dir', '/media/ssd')
    
    def __repr__(self) -> str:
        """String representation."""
        return f"Config(path={self.config_path})"

# Global config instance (can be imported by other modules)
_global_config: Optional[Config] = None


def get_config(config_path: Optional[str] = None) -> Config:
    """
    Get the global configuration instance.
    
    Args:
        config_path: Path to config file (only used on first call)
        
    Returns:
        Config instance
    """
    global _global_config
    
    if _global_config is None:
        _global_config = Config(config_path)
    
    return _global_config
