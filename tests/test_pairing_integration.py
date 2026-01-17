"""
Pairing Flow Integration Tests.

End-to-end tests for the device pairing flow including:
- CMS client registration and pairing code generation
- Player config state persistence
- State machine mode transitions
- Re-pairing flow
"""

import pytest
import tempfile
import json
import os
from datetime import datetime
from unittest.mock import patch, MagicMock

from src.common.cms_client import CMSClient, generate_pairing_code
from src.player.config import PlayerConfig
from src.player.state_machine import (
    PlayerStateMachine,
    PlayerMode,
    StateTransitionError
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_device_info():
    """Mock device info for testing."""
    return {
        'device_id': 'test-device-001',
        'hostname': 'test-player',
        'mac_address': '00:11:22:33:44:55',
        'ip_address': '192.168.1.100'
    }


@pytest.fixture
def cms_client(mock_device_info):
    """Create a CMSClient instance with mocked device info."""
    with patch('src.common.cms_client.get_device_info', return_value=mock_device_info):
        client = CMSClient(cms_url='http://test-cms:5002')
        yield client


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def player_config(temp_config_dir):
    """Create a PlayerConfig instance with temp directory."""
    return PlayerConfig(config_dir=temp_config_dir)


@pytest.fixture
def reset_global_instances():
    """Reset global singleton instances before and after tests."""
    import src.player.config as config_module
    import src.player.state_machine as sm_module

    # Store originals
    orig_config = config_module._global_player_config
    orig_sm = sm_module._global_state_machine

    # Reset to None
    config_module._global_player_config = None
    sm_module._global_state_machine = None

    yield

    # Restore originals
    config_module._global_player_config = orig_config
    sm_module._global_state_machine = orig_sm


# =============================================================================
# Pairing Code Generation Tests
# =============================================================================


class TestPairingCodeGeneration:
    """Tests for pairing code generation functionality."""

    def test_pairing_code_format(self):
        """Generated code should be a 6-digit string."""
        code = generate_pairing_code()

        assert isinstance(code, str)
        assert len(code) == 6
        assert code.isdigit()

    def test_pairing_code_range(self):
        """Generated codes should be in valid range."""
        for _ in range(50):
            code = generate_pairing_code()
            assert 100000 <= int(code) <= 999999

    def test_pairing_codes_are_unique(self):
        """Multiple generations should produce different codes."""
        codes = {generate_pairing_code() for _ in range(100)}
        # With 100 generations, we expect high uniqueness
        assert len(codes) > 80


# =============================================================================
# CMS Client Registration Integration Tests
# =============================================================================


class TestCMSClientRegistration:
    """Tests for device registration with CMS."""

    def test_registration_flow(self, cms_client, mock_device_info):
        """Test complete registration flow."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            'device_id': 'test-device-001',
            'status': 'registered'
        }

        with patch('src.common.cms_client.requests.post', return_value=mock_response):
            result = cms_client.register_device(mode='direct')

        assert result is not None
        assert result['device_id'] == 'test-device-001'

    def test_registration_sends_correct_data(self, cms_client, mock_device_info):
        """Registration should send hardware_id, mode, and name."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {'device_id': 'test-device-001'}

        with patch('src.common.cms_client.requests.post', return_value=mock_response) as mock_post:
            cms_client.register_device(mode='hub')

        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]['json']

        assert payload['hardware_id'] == 'test-device-001'
        assert payload['mode'] == 'hub'
        assert payload['name'] == 'test-player'


# =============================================================================
# Full Pairing Flow Integration Tests
# =============================================================================


class TestPairingFlowIntegration:
    """Integration tests for complete pairing flow."""

    def test_full_pairing_flow_success(self, cms_client, mock_device_info):
        """Test the complete pairing flow from registration to paired status."""
        # Step 1: Device registration
        register_response = MagicMock()
        register_response.status_code = 201
        register_response.json.return_value = {
            'device_id': 'test-device-001',
            'status': 'registered'
        }

        # Step 2: Pairing code request
        pairing_response = MagicMock()
        pairing_response.status_code = 200

        # Step 3: Status check - paired
        status_response = MagicMock()
        status_response.status_code = 200
        status_response.json.return_value = {'paired': True}

        with patch('src.common.cms_client.requests.post') as mock_post:
            with patch('src.common.cms_client.requests.get', return_value=status_response):
                mock_post.side_effect = [register_response, pairing_response]

                # Execute flow
                device = cms_client.register_device()
                assert device is not None
                assert device['device_id'] == 'test-device-001'

                code = cms_client.request_pairing()
                assert code is not None
                assert len(code) == 6
                assert cms_client.pairing_code == code

                is_paired = cms_client.check_pairing_status()
                assert is_paired is True
                assert cms_client.paired is True

    def test_pairing_flow_with_config_persistence(
        self,
        cms_client,
        player_config,
        temp_config_dir,
        mock_device_info
    ):
        """Test that pairing state is correctly persisted to config."""
        pairing_response = MagicMock()
        pairing_response.status_code = 200

        status_response = MagicMock()
        status_response.status_code = 200
        status_response.json.return_value = {'paired': True}

        with patch('src.common.cms_client.requests.post', return_value=pairing_response):
            # Start pairing
            code = cms_client.request_pairing()
            assert code is not None

            # Persist pairing code to config
            player_config.pairing_code = code
            player_config.pairing_status = 'pairing'
            player_config.save_device()

            # Verify persistence
            device_file = os.path.join(temp_config_dir, 'device.json')
            with open(device_file) as f:
                data = json.load(f)

            assert data['pairing_code'] == code
            assert data['pairing_status'] == 'pairing'

        with patch('src.common.cms_client.requests.get', return_value=status_response):
            # Check pairing status
            is_paired = cms_client.check_pairing_status()
            assert is_paired is True

            # Update config to paired state
            player_config.set_paired(True)

            # Verify final state
            assert player_config.paired is True
            assert player_config.pairing_code == ''  # Code should be cleared
            assert player_config.pairing_status == 'paired'
            assert player_config.paired_at != ''

            # Verify persistence after pairing
            with open(device_file) as f:
                data = json.load(f)

            assert data['paired'] is True
            assert data['pairing_code'] == ''

    def test_pairing_status_transitions(self, player_config):
        """Test valid pairing status transitions."""
        # Initial state
        assert player_config.pairing_status == 'unpaired'
        assert player_config.paired is False

        # Start pairing
        player_config.pairing_status = 'pairing'
        player_config.pairing_code = '123456'
        assert player_config.pairing_status == 'pairing'

        # Complete pairing
        player_config.set_paired(True)
        assert player_config.paired is True
        assert player_config.pairing_status == 'paired'
        assert player_config.pairing_code == ''

    def test_pairing_error_status(self, player_config):
        """Test that error status can be set."""
        player_config.pairing_status = 'pairing'
        player_config.pairing_status = 'error'

        assert player_config.pairing_status == 'error'
        assert player_config.paired is False


# =============================================================================
# State Machine Mode Transition Tests
# =============================================================================


class TestStateMachinePairingTransitions:
    """Tests for state machine mode transitions during pairing."""

    def test_initial_mode_unpaired_device(self):
        """Unpaired device should start in PAIRING mode."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        assert sm.mode == PlayerMode.PAIRING
        assert sm.is_pairing is True
        assert sm.is_playback is False

    def test_initial_mode_paired_device(self):
        """Paired device should start in PLAYBACK mode."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)

        assert sm.mode == PlayerMode.PLAYBACK
        assert sm.is_playback is True
        assert sm.is_pairing is False

    def test_pairing_to_playback_transition(self):
        """After successful pairing, should transition to PLAYBACK."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        # Simulate successful pairing
        result = sm.to_playback()

        assert result is True
        assert sm.mode == PlayerMode.PLAYBACK
        assert sm.previous_mode == PlayerMode.PAIRING

    def test_playback_to_pairing_transition(self):
        """Re-pair should transition from PLAYBACK to PAIRING."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)

        # Simulate re-pair request
        result = sm.to_pairing()

        assert result is True
        assert sm.mode == PlayerMode.PAIRING
        assert sm.previous_mode == PlayerMode.PLAYBACK

    def test_menu_to_pairing_transition(self):
        """Re-pair from menu should transition to PAIRING."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)
        sm.to_menu()

        assert sm.mode == PlayerMode.MENU

        # Re-pair from menu
        result = sm.to_pairing()

        assert result is True
        assert sm.mode == PlayerMode.PAIRING
        assert sm.previous_mode == PlayerMode.MENU

    def test_pairing_to_menu_not_allowed(self):
        """Cannot show menu while in pairing mode."""
        sm = PlayerStateMachine(initial_mode=PlayerMode.PAIRING)

        with pytest.raises(StateTransitionError):
            sm.to_menu()

    def test_mode_callback_on_pairing_complete(self):
        """Callback should be invoked when pairing completes."""
        callback_data = []

        def on_mode_changed(state_machine, old_mode, new_mode):
            callback_data.append({
                'old': old_mode,
                'new': new_mode
            })

        sm = PlayerStateMachine(
            initial_mode=PlayerMode.PAIRING,
            on_mode_changed=on_mode_changed
        )

        sm.to_playback()

        assert len(callback_data) == 1
        assert callback_data[0]['old'] == PlayerMode.PAIRING
        assert callback_data[0]['new'] == PlayerMode.PLAYBACK


# =============================================================================
# Integrated Pairing and State Machine Tests
# =============================================================================


class TestIntegratedPairingStateMachine:
    """Tests for pairing flow with state machine and config together."""

    def test_full_pairing_with_state_and_config(
        self,
        cms_client,
        player_config,
        mock_device_info,
        reset_global_instances
    ):
        """Test complete pairing flow with all components."""
        # Setup state machine based on config
        initial_mode = PlayerMode.PAIRING if not player_config.paired else PlayerMode.PLAYBACK
        assert initial_mode == PlayerMode.PAIRING

        sm = PlayerStateMachine(initial_mode=initial_mode)
        assert sm.is_pairing is True

        # Mock CMS responses
        pairing_response = MagicMock()
        pairing_response.status_code = 200

        status_unpaired = MagicMock()
        status_unpaired.status_code = 200
        status_unpaired.json.return_value = {'paired': False}

        status_paired = MagicMock()
        status_paired.status_code = 200
        status_paired.json.return_value = {'paired': True}

        with patch('src.common.cms_client.requests.post', return_value=pairing_response):
            # Request pairing code
            code = cms_client.request_pairing()
            assert code is not None

            # Update config
            player_config.pairing_code = code
            player_config.pairing_status = 'pairing'

        with patch('src.common.cms_client.requests.get', return_value=status_unpaired):
            # Check status - not yet paired
            is_paired = cms_client.check_pairing_status()
            assert is_paired is False
            assert sm.is_pairing is True

        with patch('src.common.cms_client.requests.get', return_value=status_paired):
            # Check status - now paired
            is_paired = cms_client.check_pairing_status()
            assert is_paired is True

            # Update config and state machine
            player_config.set_paired(True)
            sm.to_playback()

            assert player_config.paired is True
            assert sm.is_playback is True

    def test_re_pairing_flow(
        self,
        cms_client,
        player_config,
        mock_device_info,
        reset_global_instances
    ):
        """Test re-pairing flow for a previously paired device."""
        # Setup as already paired
        player_config.set_paired(True)
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)

        assert player_config.paired is True
        assert sm.is_playback is True

        # Request re-pair
        player_config.set_paired(False)
        sm.to_pairing()

        assert player_config.paired is False
        assert sm.is_pairing is True

        # Complete re-pairing
        pairing_response = MagicMock()
        pairing_response.status_code = 200

        status_response = MagicMock()
        status_response.status_code = 200
        status_response.json.return_value = {'paired': True}

        with patch('src.common.cms_client.requests.post', return_value=pairing_response):
            new_code = cms_client.request_pairing()
            player_config.pairing_code = new_code
            player_config.pairing_status = 'pairing'

        with patch('src.common.cms_client.requests.get', return_value=status_response):
            is_paired = cms_client.check_pairing_status()
            assert is_paired is True

            player_config.set_paired(True)
            sm.to_playback()

            assert player_config.paired is True
            assert sm.is_playback is True

    def test_config_determines_initial_state(
        self,
        player_config,
        reset_global_instances
    ):
        """Test that config pairing status determines initial state machine mode."""
        # Test unpaired config
        player_config.paired = False
        sm_unpaired = PlayerStateMachine(
            initial_mode=PlayerMode.PAIRING if not player_config.paired else PlayerMode.PLAYBACK
        )
        assert sm_unpaired.is_pairing is True

        # Test paired config
        player_config.paired = True
        sm_paired = PlayerStateMachine(
            initial_mode=PlayerMode.PAIRING if not player_config.paired else PlayerMode.PLAYBACK
        )
        assert sm_paired.is_playback is True


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestPairingErrorHandling:
    """Tests for error handling during pairing."""

    def test_pairing_request_network_error(self, cms_client, mock_device_info):
        """Network errors during pairing should be handled gracefully."""
        with patch('src.common.cms_client.requests.post') as mock_post:
            mock_post.side_effect = Exception("Network error")
            with patch('src.common.cms_client.time.sleep'):
                code = cms_client.request_pairing()

        assert code is None

    def test_pairing_status_check_server_error(self, cms_client, mock_device_info):
        """Server errors during status check should return False."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            result = cms_client.check_pairing_status()

        assert result is False
        assert cms_client.paired is False

    def test_pairing_status_check_empty_response(self, cms_client, mock_device_info):
        """Empty response during status check should return False."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            result = cms_client.check_pairing_status()

        assert result is False

    def test_invalid_pairing_status_raises(self, player_config):
        """Setting invalid pairing status should raise ValueError."""
        with pytest.raises(ValueError):
            player_config.pairing_status = 'invalid'


# =============================================================================
# Persistence Recovery Tests
# =============================================================================


class TestPairingPersistenceRecovery:
    """Tests for pairing state persistence and recovery."""

    def test_reload_pairing_state_after_restart(self, temp_config_dir):
        """Pairing state should survive application restart."""
        # Create initial config and set pairing state
        config1 = PlayerConfig(config_dir=temp_config_dir)
        config1.pairing_code = '654321'
        config1.pairing_status = 'pairing'
        config1.save_device()

        # Simulate restart with new config instance
        config2 = PlayerConfig(config_dir=temp_config_dir)

        assert config2.pairing_code == '654321'
        assert config2.pairing_status == 'pairing'
        assert config2.paired is False

    def test_reload_paired_state_after_restart(self, temp_config_dir):
        """Paired state should survive application restart."""
        # Create initial config and complete pairing
        config1 = PlayerConfig(config_dir=temp_config_dir)
        config1.set_paired(True)

        # Verify timestamp was set
        assert config1.paired_at != ''
        paired_at = config1.paired_at

        # Simulate restart
        config2 = PlayerConfig(config_dir=temp_config_dir)

        assert config2.paired is True
        assert config2.pairing_status == 'paired'
        assert config2.paired_at == paired_at

    def test_state_machine_initialized_from_persisted_state(self, temp_config_dir):
        """State machine should initialize correctly from persisted config."""
        # Setup paired config
        config = PlayerConfig(config_dir=temp_config_dir)
        config.set_paired(True)

        # Simulate restart - new instances
        config2 = PlayerConfig(config_dir=temp_config_dir)
        initial_mode = PlayerMode.PAIRING if not config2.paired else PlayerMode.PLAYBACK

        sm = PlayerStateMachine(initial_mode=initial_mode)

        assert sm.is_playback is True
        assert config2.paired is True


# =============================================================================
# Remote Unpair Tests
# =============================================================================


class TestRemoteUnpair:
    """Tests for handling remote unpair from CMS."""

    def test_detect_remote_unpair(
        self,
        cms_client,
        player_config,
        mock_device_info,
        reset_global_instances
    ):
        """Should detect when device is unpaired remotely."""
        # Setup as paired
        player_config.set_paired(True)
        sm = PlayerStateMachine(initial_mode=PlayerMode.PLAYBACK)

        assert cms_client.paired is False  # Client starts unpaired
        cms_client.paired = True  # Simulate paired state

        # Simulate remote unpair
        status_response = MagicMock()
        status_response.status_code = 200
        status_response.json.return_value = {'paired': False}

        with patch('src.common.cms_client.requests.get', return_value=status_response):
            is_still_paired = cms_client.check_pairing_status()

        assert is_still_paired is False
        assert cms_client.paired is False

        # Update local state
        player_config.set_paired(False)
        sm.to_pairing()

        assert player_config.paired is False
        assert sm.is_pairing is True


# =============================================================================
# Run as Script (for manual testing)
# =============================================================================


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
