"""
Tests for pairing state persistence in PlayerConfig.
"""

import pytest
import tempfile
import json
import os
from datetime import datetime

from src.player.config import PlayerConfig, get_player_config


class TestPairingConfig:
    """Tests for pairing-related configuration."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def config(self, temp_config_dir):
        """Create a PlayerConfig instance with temp directory."""
        return PlayerConfig(config_dir=temp_config_dir)

    def test_paired_default_false(self, config):
        """Test that paired defaults to False."""
        assert config.paired is False

    def test_paired_setter(self, config):
        """Test setting paired property."""
        config.paired = True
        assert config.paired is True

    def test_pairing_code_default_empty(self, config):
        """Test that pairing_code defaults to empty string."""
        assert config.pairing_code == ''

    def test_pairing_code_setter(self, config):
        """Test setting pairing_code property."""
        config.pairing_code = '123456'
        assert config.pairing_code == '123456'

    def test_paired_at_default_empty(self, config):
        """Test that paired_at defaults to empty string."""
        assert config.paired_at == ''

    def test_set_paired_true(self, config, temp_config_dir):
        """Test set_paired with paired=True."""
        config.pairing_code = '123456'
        config.set_paired(True)

        # Check state
        assert config.paired is True
        assert config.pairing_code == ''  # Should be cleared
        assert config.paired_at != ''  # Should have timestamp

        # Check persistence
        device_file = os.path.join(temp_config_dir, 'device.json')
        with open(device_file) as f:
            data = json.load(f)

        assert data['paired'] is True
        assert data['pairing_code'] == ''
        assert 'paired_at' in data

    def test_set_paired_false_with_code(self, config, temp_config_dir):
        """Test set_paired with paired=False and a new code."""
        config.set_paired(True)  # First pair
        config.set_paired(False, '654321')  # Then unpair with new code

        assert config.paired is False
        assert config.pairing_code == '654321'

        # Check persistence
        device_file = os.path.join(temp_config_dir, 'device.json')
        with open(device_file) as f:
            data = json.load(f)

        assert data['paired'] is False
        assert data['pairing_code'] == '654321'

    def test_pairing_status_default(self, config):
        """Test that pairing_status defaults to 'unpaired'."""
        assert config.pairing_status == 'unpaired'

    def test_pairing_status_setter_valid(self, config):
        """Test setting valid pairing_status values."""
        for status in ('unpaired', 'pairing', 'paired', 'error'):
            config.pairing_status = status
            assert config.pairing_status == status

    def test_pairing_status_setter_invalid(self, config):
        """Test that invalid pairing_status raises ValueError."""
        with pytest.raises(ValueError):
            config.pairing_status = 'invalid_status'

    def test_persistence_after_reload(self, config, temp_config_dir):
        """Test that pairing state persists after reload."""
        config.paired = True
        config.pairing_code = '123456'
        config.save_device()

        # Create new config instance
        config2 = PlayerConfig(config_dir=temp_config_dir)

        assert config2.paired is True
        assert config2.pairing_code == '123456'

    def test_paired_at_is_valid_iso_format(self, config):
        """Test that paired_at is valid ISO format timestamp."""
        config.set_paired(True)

        # Should be parseable
        timestamp = datetime.fromisoformat(config.paired_at)
        assert isinstance(timestamp, datetime)


class TestGlobalPlayerConfig:
    """Tests for global player config singleton."""

    def test_get_player_config_creates_instance(self):
        """Test that get_player_config creates an instance."""
        import src.player.config as config_module
        config_module._global_player_config = None

        with tempfile.TemporaryDirectory() as tmpdir:
            config = get_player_config(tmpdir)
            assert config is not None
            assert str(config.config_dir) == tmpdir

    def test_get_player_config_returns_same_instance(self):
        """Test that get_player_config returns same instance."""
        import src.player.config as config_module
        config_module._global_player_config = None

        with tempfile.TemporaryDirectory() as tmpdir:
            config1 = get_player_config(tmpdir)
            config2 = get_player_config('/different/path')

            assert config1 is config2
