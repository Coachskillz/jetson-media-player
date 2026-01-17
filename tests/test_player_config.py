"""Unit tests for the Config module.

Tests configuration loading, getting/setting values, environment overrides,
and the global config instance.
"""

import os
import pytest
import tempfile
from pathlib import Path
from unittest import mock

import yaml

from src.common.config import Config, get_config, _global_config


# Sample test configuration
SAMPLE_CONFIG = {
    'device': {
        'id': 'test-device-001',
        'name': 'Test Player',
        'location': 'Test Location'
    },
    'cms': {
        'base_url': 'https://test.example.com/api/v1',
        'api_key': 'test-api-key',
        'sync_interval': 300
    },
    'playback': {
        'content_dir': '/test/media',
        'default_playlist': 'default',
        'transition_time': 0.1
    },
    'ml': {
        'face_recognition': {
            'enabled': True,
            'confidence_threshold': 0.7
        }
    },
    'logging': {
        'level': 'DEBUG'
    }
}


@pytest.fixture
def temp_config_file():
    """Create a temporary config file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(SAMPLE_CONFIG, f)
        temp_path = f.name
    yield temp_path
    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def config(temp_config_file):
    """Create a Config instance with test configuration."""
    return Config(temp_config_file)


@pytest.fixture
def reset_global_config():
    """Reset the global config instance before and after tests."""
    import src.common.config as config_module
    original = config_module._global_config
    config_module._global_config = None
    yield
    config_module._global_config = original


class TestConfigLoading:
    """Tests for configuration file loading."""

    def test_load_valid_config(self, temp_config_file):
        """Test loading a valid configuration file."""
        config = Config(temp_config_file)
        assert config._config is not None
        assert config._config['device']['id'] == 'test-device-001'

    def test_load_missing_config_raises_error(self):
        """Test that loading a missing config file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            Config('/nonexistent/path/config.yaml')
        assert 'Config file not found' in str(exc_info.value)

    def test_config_path_stored(self, temp_config_file):
        """Test that config path is stored correctly."""
        config = Config(temp_config_file)
        assert config.config_path == Path(temp_config_file)

    def test_repr(self, config, temp_config_file):
        """Test string representation of Config."""
        repr_str = repr(config)
        assert 'Config' in repr_str
        assert 'path=' in repr_str


class TestConfigGet:
    """Tests for getting configuration values."""

    def test_get_simple_key(self, config):
        """Test getting a simple (non-nested) key."""
        # Device section exists at top level
        device_config = config.get('device')
        assert device_config is not None
        assert device_config['id'] == 'test-device-001'

    def test_get_nested_key(self, config):
        """Test getting a nested key using dot notation."""
        assert config.get('device.id') == 'test-device-001'
        assert config.get('device.name') == 'Test Player'
        assert config.get('cms.base_url') == 'https://test.example.com/api/v1'

    def test_get_deeply_nested_key(self, config):
        """Test getting a deeply nested key."""
        assert config.get('ml.face_recognition.enabled') is True
        assert config.get('ml.face_recognition.confidence_threshold') == 0.7

    def test_get_missing_key_returns_none(self, config):
        """Test that missing key returns None by default."""
        assert config.get('nonexistent.key') is None

    def test_get_missing_key_returns_default(self, config):
        """Test that missing key returns specified default."""
        assert config.get('nonexistent.key', 'default_value') == 'default_value'
        assert config.get('nonexistent.key', 42) == 42

    def test_get_partial_path_returns_none(self, config):
        """Test that partial paths to non-dict values return None."""
        # device.id.something doesn't exist because device.id is a string
        assert config.get('device.id.nonexistent') is None


class TestConfigSet:
    """Tests for setting configuration values."""

    def test_set_existing_key(self, config):
        """Test setting an existing key."""
        config.set('device.id', 'new-device-id')
        assert config.get('device.id') == 'new-device-id'

    def test_set_new_key_in_existing_section(self, config):
        """Test setting a new key in an existing section."""
        config.set('device.new_field', 'new_value')
        assert config.get('device.new_field') == 'new_value'

    def test_set_creates_nested_structure(self, config):
        """Test that set creates nested structure for new paths."""
        config.set('new_section.nested.deep.value', 'test')
        assert config.get('new_section.nested.deep.value') == 'test'

    def test_set_overwrites_value(self, config):
        """Test that set overwrites existing values."""
        original = config.get('cms.api_key')
        config.set('cms.api_key', 'new-api-key')
        assert config.get('cms.api_key') == 'new-api-key'
        assert config.get('cms.api_key') != original


class TestConfigSave:
    """Tests for saving configuration to file."""

    def test_save_to_same_path(self, config, temp_config_file):
        """Test saving config back to the same file."""
        config.set('device.id', 'modified-device')
        config.save()

        # Reload and verify
        reloaded = Config(temp_config_file)
        assert reloaded.get('device.id') == 'modified-device'

    def test_save_to_new_path(self, config):
        """Test saving config to a new file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            new_path = f.name

        try:
            config.set('device.id', 'saved-device')
            config.save(new_path)

            # Load from new path and verify
            new_config = Config(new_path)
            assert new_config.get('device.id') == 'saved-device'
        finally:
            if os.path.exists(new_path):
                os.unlink(new_path)


class TestConfigProperties:
    """Tests for configuration property accessors."""

    def test_device_id_property(self, config):
        """Test device_id property."""
        assert config.device_id == 'test-device-001'

    def test_device_id_default(self, temp_config_file):
        """Test device_id returns 'unknown' when not set."""
        # Create config without device.id
        with open(temp_config_file, 'w') as f:
            yaml.dump({'cms': {'base_url': 'test'}}, f)

        config = Config(temp_config_file)
        assert config.device_id == 'unknown'

    def test_cms_base_url_property(self, config):
        """Test cms_base_url property."""
        assert config.cms_base_url == 'https://test.example.com/api/v1'

    def test_cms_base_url_default(self, temp_config_file):
        """Test cms_base_url returns empty string when not set."""
        with open(temp_config_file, 'w') as f:
            yaml.dump({'device': {'id': 'test'}}, f)

        config = Config(temp_config_file)
        assert config.cms_base_url == ''

    def test_content_dir_property(self, config):
        """Test content_dir property."""
        assert config.content_dir == '/test/media'

    def test_content_dir_default(self, temp_config_file):
        """Test content_dir returns default when not set."""
        with open(temp_config_file, 'w') as f:
            yaml.dump({'device': {'id': 'test'}}, f)

        config = Config(temp_config_file)
        assert config.content_dir == '/media/ssd'


class TestEnvironmentOverrides:
    """Tests for environment variable overrides."""

    def test_api_key_override(self, temp_config_file):
        """Test that JMP_CMS_API_KEY environment variable overrides config."""
        with mock.patch.dict(os.environ, {'JMP_CMS_API_KEY': 'env-api-key'}):
            config = Config(temp_config_file)
            assert config.get('cms.api_key') == 'env-api-key'

    def test_device_id_override(self, temp_config_file):
        """Test that JMP_DEVICE_ID environment variable overrides config."""
        with mock.patch.dict(os.environ, {'JMP_DEVICE_ID': 'env-device-id'}):
            config = Config(temp_config_file)
            assert config.device_id == 'env-device-id'

    def test_env_override_takes_precedence(self, temp_config_file):
        """Test that environment variables take precedence over file values."""
        with mock.patch.dict(os.environ, {
            'JMP_CMS_API_KEY': 'override-key',
            'JMP_DEVICE_ID': 'override-device'
        }):
            config = Config(temp_config_file)
            # Should use env values, not file values
            assert config.get('cms.api_key') == 'override-key'
            assert config.device_id == 'override-device'

    def test_no_override_without_env_vars(self, config):
        """Test that config values are unchanged without env vars."""
        # Ensure env vars are not set
        with mock.patch.dict(os.environ, {}, clear=True):
            # Re-load to apply (no) overrides
            config.load()
            assert config.get('cms.api_key') == 'test-api-key'
            assert config.device_id == 'test-device-001'


class TestGlobalConfig:
    """Tests for global configuration instance."""

    def test_get_config_creates_instance(self, temp_config_file, reset_global_config):
        """Test that get_config creates a new instance on first call."""
        import src.common.config as config_module

        config = get_config(temp_config_file)
        assert config is not None
        assert isinstance(config, Config)

    def test_get_config_returns_same_instance(self, temp_config_file, reset_global_config):
        """Test that get_config returns the same instance on subsequent calls."""
        config1 = get_config(temp_config_file)
        config2 = get_config()
        config3 = get_config('/different/path')  # Path ignored after first call

        assert config1 is config2
        assert config2 is config3

    def test_get_config_singleton_pattern(self, temp_config_file, reset_global_config):
        """Test that global config follows singleton pattern."""
        config1 = get_config(temp_config_file)
        config1.set('test.value', 'modified')

        config2 = get_config()
        assert config2.get('test.value') == 'modified'


class TestConfigReload:
    """Tests for configuration reloading."""

    def test_reload_picks_up_changes(self, config, temp_config_file):
        """Test that reload picks up external file changes."""
        # Modify the file externally
        with open(temp_config_file, 'r') as f:
            data = yaml.safe_load(f)

        data['device']['id'] = 'externally-modified'

        with open(temp_config_file, 'w') as f:
            yaml.dump(data, f)

        # Reload and verify
        config.load()
        assert config.device_id == 'externally-modified'


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_config_file(self):
        """Test handling of empty config file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write('')  # Empty file
            temp_path = f.name

        try:
            config = Config(temp_path)
            # Empty YAML becomes None, get should handle gracefully
            assert config.get('any.key') is None
        finally:
            os.unlink(temp_path)

    def test_get_with_empty_key(self, config):
        """Test get with empty string key."""
        # Empty key should return the entire config
        result = config.get('')
        # With empty key, the loop doesn't iterate, returns the config dict
        assert result == config._config

    def test_set_with_single_key(self, config):
        """Test set with non-nested key."""
        config.set('simple_key', 'simple_value')
        assert config.get('simple_key') == 'simple_value'

    def test_config_with_list_values(self):
        """Test config with list values."""
        config_data = {
            'items': ['item1', 'item2', 'item3'],
            'nested': {
                'list': [1, 2, 3]
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = f.name

        try:
            config = Config(temp_path)
            assert config.get('items') == ['item1', 'item2', 'item3']
            assert config.get('nested.list') == [1, 2, 3]
        finally:
            os.unlink(temp_path)

    def test_config_with_boolean_values(self, config):
        """Test handling of boolean values."""
        assert config.get('ml.face_recognition.enabled') is True

        config.set('ml.face_recognition.enabled', False)
        assert config.get('ml.face_recognition.enabled') is False

    def test_config_with_numeric_values(self, config):
        """Test handling of numeric values."""
        assert config.get('ml.face_recognition.confidence_threshold') == 0.7
        assert config.get('cms.sync_interval') == 300

        config.set('cms.sync_interval', 600)
        assert config.get('cms.sync_interval') == 600


# =============================================================================
# PlayerConfig Tests (src.player.config.PlayerConfig)
# =============================================================================

from src.player.config import PlayerConfig


@pytest.fixture
def temp_player_config_dir():
    """Create a temporary config directory for PlayerConfig testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def player_config(temp_player_config_dir):
    """Create a PlayerConfig instance with test configuration."""
    return PlayerConfig(temp_player_config_dir)


class TestPlayerConfigConnectionMode:
    """Tests for PlayerConfig connection mode properties."""

    def test_connection_mode_default(self, player_config):
        """connection_mode should default to 'direct'."""
        assert player_config.connection_mode == 'direct'

    def test_connection_mode_setter_valid_hub(self, player_config):
        """connection_mode setter should accept 'hub'."""
        player_config.connection_mode = 'hub'
        assert player_config.connection_mode == 'hub'

    def test_connection_mode_setter_valid_direct(self, player_config):
        """connection_mode setter should accept 'direct'."""
        player_config.connection_mode = 'hub'  # First set to hub
        player_config.connection_mode = 'direct'  # Then back to direct
        assert player_config.connection_mode == 'direct'

    def test_connection_mode_setter_invalid(self, player_config):
        """connection_mode setter should reject invalid values."""
        with pytest.raises(ValueError) as exc_info:
            player_config.connection_mode = 'invalid'
        assert "must be 'hub' or 'direct'" in str(exc_info.value)

    def test_connection_mode_setter_invalid_empty(self, player_config):
        """connection_mode setter should reject empty string."""
        with pytest.raises(ValueError) as exc_info:
            player_config.connection_mode = ''
        assert "must be 'hub' or 'direct'" in str(exc_info.value)


class TestPlayerConfigCmsUrl:
    """Tests for PlayerConfig cms_url property."""

    def test_cms_url_default(self, player_config):
        """cms_url should default to 'http://localhost:5002'."""
        assert player_config.cms_url == 'http://localhost:5002'

    def test_cms_url_setter(self, player_config):
        """cms_url setter should store the value."""
        player_config.cms_url = 'http://cms.example.com:5002'
        assert player_config.cms_url == 'http://cms.example.com:5002'


class TestPlayerConfigHubUrl:
    """Tests for PlayerConfig hub_url property."""

    def test_hub_url_default(self, player_config):
        """hub_url should return default value when not set."""
        # Default is 'http://192.168.1.100:5000' from the config
        assert 'http://' in player_config.hub_url

    def test_hub_url_setter(self, player_config):
        """hub_url setter should store the value."""
        player_config.hub_url = 'http://myhub.local:5000'
        assert player_config.hub_url == 'http://myhub.local:5000'


class TestPlayerConfigEnvironmentOverrides:
    """Tests for PlayerConfig environment variable overrides."""

    def test_env_override_connection_mode_hub(self, temp_player_config_dir):
        """JMP_CONNECTION_MODE env var should override config to 'hub'."""
        with mock.patch.dict(os.environ, {'JMP_CONNECTION_MODE': 'hub'}):
            config = PlayerConfig(temp_player_config_dir)
            assert config.connection_mode == 'hub'

    def test_env_override_connection_mode_direct(self, temp_player_config_dir):
        """JMP_CONNECTION_MODE env var should override config to 'direct'."""
        with mock.patch.dict(os.environ, {'JMP_CONNECTION_MODE': 'direct'}):
            config = PlayerConfig(temp_player_config_dir)
            assert config.connection_mode == 'direct'

    def test_env_override_connection_mode_invalid_ignored(self, temp_player_config_dir):
        """JMP_CONNECTION_MODE with invalid value should be ignored."""
        with mock.patch.dict(os.environ, {'JMP_CONNECTION_MODE': 'invalid'}):
            config = PlayerConfig(temp_player_config_dir)
            # Should fall back to default since invalid value is ignored
            assert config.connection_mode == 'direct'

    def test_env_override_cms_url(self, temp_player_config_dir):
        """JMP_CMS_URL env var should override config."""
        with mock.patch.dict(os.environ, {'JMP_CMS_URL': 'http://env-cms.example.com:5002'}):
            config = PlayerConfig(temp_player_config_dir)
            assert config.cms_url == 'http://env-cms.example.com:5002'

    def test_env_override_hub_url(self, temp_player_config_dir):
        """JMP_HUB_URL env var should override config."""
        with mock.patch.dict(os.environ, {'JMP_HUB_URL': 'http://env-hub.example.com:5000'}):
            config = PlayerConfig(temp_player_config_dir)
            assert config.hub_url == 'http://env-hub.example.com:5000'


class TestPlayerConfigSaveLoad:
    """Tests for PlayerConfig save and load functionality."""

    def test_save_and_load_connection_mode(self, player_config):
        """connection_mode should persist after save and load."""
        player_config.connection_mode = 'hub'
        player_config.save_device()

        # Create new instance and load
        new_config = PlayerConfig(player_config.config_dir)
        assert new_config.connection_mode == 'hub'

    def test_save_and_load_cms_url(self, player_config):
        """cms_url should persist after save and load."""
        player_config.cms_url = 'http://saved-cms.example.com:5002'
        player_config.save_device()

        # Create new instance and load
        new_config = PlayerConfig(player_config.config_dir)
        assert new_config.cms_url == 'http://saved-cms.example.com:5002'

    def test_save_and_load_hub_url(self, player_config):
        """hub_url should persist after save and load."""
        player_config.hub_url = 'http://saved-hub.example.com:5000'
        player_config.save_device()

        # Create new instance and load
        new_config = PlayerConfig(player_config.config_dir)
        assert new_config.hub_url == 'http://saved-hub.example.com:5000'
