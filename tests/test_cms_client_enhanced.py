"""
CMS Client Enhanced Tests

Comprehensive tests for the CMS client with mocking of HTTP requests
and device information to ensure proper pairing flow, retry logic,
and error handling.
"""

import pytest
import time
import requests
from unittest.mock import patch, MagicMock, call

from src.common.cms_client import (
    CMSClient,
    retry_with_backoff,
    generate_pairing_code,
    DEFAULT_MAX_RETRIES,
    DEFAULT_BASE_DELAY,
    DEFAULT_MAX_DELAY,
    DEFAULT_TIMEOUT,
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
        'mac_address': '00:11:22:33:44:55'
    }


@pytest.fixture
def cms_client(mock_device_info):
    """Create a CMSClient instance with mocked device info."""
    with patch('src.common.cms_client.get_device_info', return_value=mock_device_info):
        client = CMSClient(cms_url='http://test-cms:5002')
        yield client


@pytest.fixture
def mock_requests():
    """Mock the requests module."""
    with patch('src.common.cms_client.requests') as mock_req:
        yield mock_req


# =============================================================================
# generate_pairing_code Tests
# =============================================================================


class TestGeneratePairingCode:
    """Tests for the pairing code generation function."""

    def test_generates_six_digit_code(self):
        """Pairing code should be exactly 6 digits."""
        code = generate_pairing_code()
        assert len(code) == 6
        assert code.isdigit()

    def test_code_is_string(self):
        """Pairing code should be returned as a string."""
        code = generate_pairing_code()
        assert isinstance(code, str)

    def test_code_in_valid_range(self):
        """Pairing code should be between 100000 and 999999."""
        for _ in range(100):
            code = generate_pairing_code()
            assert 100000 <= int(code) <= 999999

    def test_codes_are_random(self):
        """Generate multiple codes and check they're not all the same."""
        codes = [generate_pairing_code() for _ in range(100)]
        unique_codes = set(codes)
        # Should have at least 50 unique codes out of 100
        assert len(unique_codes) > 50


# =============================================================================
# retry_with_backoff Tests
# =============================================================================


class TestRetryWithBackoff:
    """Tests for the retry with exponential backoff function."""

    def test_success_on_first_attempt(self):
        """Function should return immediately on success."""
        mock_func = MagicMock(return_value='success')
        result = retry_with_backoff(mock_func, max_retries=3)

        assert result == 'success'
        assert mock_func.call_count == 1

    def test_retries_on_connection_error(self):
        """Should retry on ConnectionError."""
        mock_func = MagicMock(
            side_effect=[
                requests.exceptions.ConnectionError("Connection refused"),
                requests.exceptions.ConnectionError("Connection refused"),
                'success'
            ]
        )

        with patch('src.common.cms_client.time.sleep'):
            result = retry_with_backoff(mock_func, max_retries=3, base_delay=0.1)

        assert result == 'success'
        assert mock_func.call_count == 3

    def test_retries_on_timeout(self):
        """Should retry on Timeout error."""
        mock_func = MagicMock(
            side_effect=[
                requests.exceptions.Timeout("Request timed out"),
                'success'
            ]
        )

        with patch('src.common.cms_client.time.sleep'):
            result = retry_with_backoff(mock_func, max_retries=2, base_delay=0.1)

        assert result == 'success'
        assert mock_func.call_count == 2

    def test_retries_on_request_exception(self):
        """Should retry on general RequestException."""
        mock_func = MagicMock(
            side_effect=[
                requests.exceptions.RequestException("Request failed"),
                'success'
            ]
        )

        with patch('src.common.cms_client.time.sleep'):
            result = retry_with_backoff(mock_func, max_retries=2, base_delay=0.1)

        assert result == 'success'

    def test_raises_after_max_retries(self):
        """Should raise the last exception after max retries."""
        error = requests.exceptions.ConnectionError("Persistent failure")
        mock_func = MagicMock(side_effect=error)

        with patch('src.common.cms_client.time.sleep'):
            with pytest.raises(requests.exceptions.ConnectionError):
                retry_with_backoff(mock_func, max_retries=3, base_delay=0.1)

        # Should be called max_retries + 1 times (initial + retries)
        assert mock_func.call_count == 4

    def test_exponential_backoff_delay(self):
        """Delay should increase exponentially between retries."""
        mock_func = MagicMock(
            side_effect=[
                requests.exceptions.ConnectionError(),
                requests.exceptions.ConnectionError(),
                requests.exceptions.ConnectionError(),
                'success'
            ]
        )

        with patch('src.common.cms_client.time.sleep') as mock_sleep:
            retry_with_backoff(mock_func, max_retries=3, base_delay=1.0, max_delay=30.0)

        # Expected delays: 1.0, 2.0, 4.0
        assert mock_sleep.call_count == 3
        delays = [call[0][0] for call in mock_sleep.call_args_list]
        assert delays == [1.0, 2.0, 4.0]

    def test_delay_capped_at_max(self):
        """Delay should not exceed max_delay."""
        mock_func = MagicMock(
            side_effect=[
                requests.exceptions.ConnectionError(),
                requests.exceptions.ConnectionError(),
                requests.exceptions.ConnectionError(),
                requests.exceptions.ConnectionError(),
                requests.exceptions.ConnectionError(),
                'success'
            ]
        )

        with patch('src.common.cms_client.time.sleep') as mock_sleep:
            retry_with_backoff(mock_func, max_retries=5, base_delay=1.0, max_delay=5.0)

        # Delays: 1, 2, 4, 5 (capped), 5 (capped)
        delays = [call[0][0] for call in mock_sleep.call_args_list]
        assert all(d <= 5.0 for d in delays)


# =============================================================================
# CMSClient Initialization Tests
# =============================================================================


class TestCMSClientInit:
    """Tests for CMSClient initialization."""

    def test_default_values(self, mock_device_info):
        """Client should initialize with default values."""
        with patch('src.common.cms_client.get_device_info', return_value=mock_device_info):
            client = CMSClient()

        assert client.cms_url == 'http://localhost:5002'
        assert client.max_retries == DEFAULT_MAX_RETRIES
        assert client.timeout == DEFAULT_TIMEOUT
        assert client.paired is False
        assert client.pairing_code is None

    def test_custom_cms_url(self, mock_device_info):
        """Client should accept custom CMS URL."""
        with patch('src.common.cms_client.get_device_info', return_value=mock_device_info):
            client = CMSClient(cms_url='http://custom-cms:8000')

        assert client.cms_url == 'http://custom-cms:8000'

    def test_custom_retry_settings(self, mock_device_info):
        """Client should accept custom retry settings."""
        with patch('src.common.cms_client.get_device_info', return_value=mock_device_info):
            client = CMSClient(max_retries=5, timeout=10)

        assert client.max_retries == 5
        assert client.timeout == 10

    def test_device_info_loaded(self, cms_client, mock_device_info):
        """Client should load device info on initialization."""
        assert cms_client.device_info == mock_device_info

    def test_hardware_id_from_device_id(self, cms_client):
        """_get_hardware_id should return device_id from device_info."""
        assert cms_client._get_hardware_id() == 'test-device-001'


# =============================================================================
# register_device Tests
# =============================================================================


class TestRegisterDevice:
    """Tests for device registration."""

    def test_register_device_success(self, cms_client):
        """Successful registration should return device data."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            'device_id': 'test-device-001',
            'status': 'registered'
        }

        with patch('src.common.cms_client.requests.post', return_value=mock_response):
            result = cms_client.register_device()

        assert result is not None
        assert result['device_id'] == 'test-device-001'

    def test_register_device_already_exists(self, cms_client):
        """Registration of existing device should return success."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'device_id': 'test-device-001',
            'status': 'already_registered'
        }

        with patch('src.common.cms_client.requests.post', return_value=mock_response):
            result = cms_client.register_device()

        assert result is not None

    def test_register_device_failure(self, cms_client):
        """Failed registration should return None."""
        mock_response = MagicMock()
        mock_response.status_code = 400

        with patch('src.common.cms_client.requests.post', return_value=mock_response):
            result = cms_client.register_device()

        assert result is None

    def test_register_device_network_error(self, cms_client):
        """Network error during registration should return None after retries."""
        with patch('src.common.cms_client.requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError()
            with patch('src.common.cms_client.time.sleep'):
                result = cms_client.register_device()

        assert result is None

    def test_register_device_sends_correct_payload(self, cms_client, mock_device_info):
        """Registration should send correct payload."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {'device_id': 'test-device-001'}

        with patch('src.common.cms_client.requests.post', return_value=mock_response) as mock_post:
            cms_client.register_device(mode='hub')

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]['json']['hardware_id'] == 'test-device-001'
        assert call_kwargs[1]['json']['mode'] == 'hub'
        assert call_kwargs[1]['json']['name'] == 'test-player'


# =============================================================================
# request_pairing Tests
# =============================================================================


class TestRequestPairing:
    """Tests for pairing request functionality."""

    def test_request_pairing_success(self, cms_client):
        """Successful pairing request should return a 6-digit code."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch('src.common.cms_client.requests.post', return_value=mock_response):
            code = cms_client.request_pairing()

        assert code is not None
        assert len(code) == 6
        assert code.isdigit()
        assert cms_client.pairing_code == code

    def test_request_pairing_device_not_registered(self, cms_client):
        """404 response should return None (device not registered)."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch('src.common.cms_client.requests.post', return_value=mock_response):
            code = cms_client.request_pairing()

        assert code is None

    def test_request_pairing_server_error(self, cms_client):
        """Server error should return None."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch('src.common.cms_client.requests.post', return_value=mock_response):
            code = cms_client.request_pairing()

        assert code is None

    def test_request_pairing_network_error(self, cms_client):
        """Network error should return None after retries."""
        with patch('src.common.cms_client.requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError()
            with patch('src.common.cms_client.time.sleep'):
                code = cms_client.request_pairing()

        assert code is None

    def test_request_pairing_sends_correct_endpoint(self, cms_client):
        """Request should be sent to correct endpoint with code."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch('src.common.cms_client.requests.post', return_value=mock_response) as mock_post:
            cms_client.request_pairing()

        call_kwargs = mock_post.call_args
        assert '/api/v1/devices/pairing/request' in call_kwargs[0][0]
        assert 'pairing_code' in call_kwargs[1]['json']


# =============================================================================
# check_pairing_status Tests
# =============================================================================


class TestCheckPairingStatus:
    """Tests for pairing status check."""

    def test_check_pairing_status_paired(self, cms_client):
        """Should return True when device is paired."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'paired': True}

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            result = cms_client.check_pairing_status()

        assert result is True
        assert cms_client.paired is True

    def test_check_pairing_status_not_paired(self, cms_client):
        """Should return False when device is not paired."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'paired': False}

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            result = cms_client.check_pairing_status()

        assert result is False
        assert cms_client.paired is False

    def test_check_pairing_status_server_error(self, cms_client):
        """Server error should return False."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            result = cms_client.check_pairing_status()

        assert result is False

    def test_check_pairing_status_network_error(self, cms_client):
        """Network error should return False after retries."""
        with patch('src.common.cms_client.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError()
            with patch('src.common.cms_client.time.sleep'):
                result = cms_client.check_pairing_status()

        assert result is False

    def test_check_pairing_status_uses_correct_endpoint(self, cms_client):
        """Status check should use correct endpoint with hardware_id."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'paired': False}

        with patch('src.common.cms_client.requests.get', return_value=mock_response) as mock_get:
            cms_client.check_pairing_status()

        call_args = mock_get.call_args
        assert '/api/v1/devices/pairing/status/test-device-001' in call_args[0][0]


# =============================================================================
# wait_for_pairing Tests
# =============================================================================


class TestWaitForPairing:
    """Tests for wait_for_pairing functionality."""

    def test_wait_for_pairing_immediate_success(self, cms_client):
        """Should return True immediately if already paired."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'paired': True}

        cms_client.pairing_code = '123456'

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            with patch('builtins.print'):  # Suppress output
                result = cms_client.wait_for_pairing(timeout=10)

        assert result is True

    def test_wait_for_pairing_timeout(self, cms_client):
        """Should return False after timeout."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'paired': False}

        cms_client.pairing_code = '123456'

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            with patch('src.common.cms_client.time.sleep'):  # Speed up test
                with patch('src.common.cms_client.time.time') as mock_time:
                    # Simulate timeout scenario
                    mock_time.side_effect = [0, 1, 2, 301]  # Start, then past timeout
                    with patch('builtins.print'):
                        result = cms_client.wait_for_pairing(timeout=300)

        assert result is False

    def test_wait_for_pairing_success_after_attempts(self, cms_client):
        """Should return True when paired after polling."""
        paired_response = MagicMock()
        paired_response.status_code = 200
        paired_response.json.return_value = {'paired': True}

        unpaired_response = MagicMock()
        unpaired_response.status_code = 200
        unpaired_response.json.return_value = {'paired': False}

        cms_client.pairing_code = '123456'

        with patch('src.common.cms_client.requests.get') as mock_get:
            # First two checks: not paired, third: paired
            mock_get.side_effect = [unpaired_response, unpaired_response, paired_response]
            with patch('src.common.cms_client.time.sleep'):
                with patch('builtins.print'):
                    result = cms_client.wait_for_pairing(timeout=300)

        assert result is True


# =============================================================================
# get_config Tests
# =============================================================================


class TestGetConfig:
    """Tests for config retrieval."""

    def test_get_config_not_paired(self, cms_client):
        """Should return empty dict if not paired."""
        assert cms_client.paired is False
        result = cms_client.get_config()
        assert result == {}

    def test_get_config_success(self, cms_client):
        """Should return config when paired and successful."""
        cms_client.paired = True

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'playlist_id': 1,
            'screen_name': 'Lobby Display'
        }

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            result = cms_client.get_config()

        assert result == {'playlist_id': 1, 'screen_name': 'Lobby Display'}

    def test_get_config_server_error(self, cms_client):
        """Should return empty dict on server error."""
        cms_client.paired = True

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            result = cms_client.get_config()

        assert result == {}

    def test_get_config_network_error(self, cms_client):
        """Should return empty dict on network error."""
        cms_client.paired = True

        with patch('src.common.cms_client.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError()
            with patch('src.common.cms_client.time.sleep'):
                result = cms_client.get_config()

        assert result == {}

    def test_get_config_uses_correct_endpoint(self, cms_client):
        """Config request should use correct endpoint."""
        cms_client.paired = True

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        with patch('src.common.cms_client.requests.get', return_value=mock_response) as mock_get:
            cms_client.get_config()

        call_args = mock_get.call_args
        assert '/api/v1/devices/test-device-001/config' in call_args[0][0]


# =============================================================================
# get_connection_config Tests
# =============================================================================


class TestGetConnectionConfig:
    """Tests for connection config retrieval."""

    def test_get_connection_config_success(self, cms_client):
        """Should return connection config on success."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'mode': 'direct',
            'cms_url': 'http://cms.example.com:5002'
        }

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            result = cms_client.get_connection_config()

        assert result == {
            'mode': 'direct',
            'cms_url': 'http://cms.example.com:5002'
        }

    def test_get_connection_config_server_error(self, cms_client):
        """Should return empty dict on server error."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            result = cms_client.get_connection_config()

        assert result == {}

    def test_get_connection_config_network_error(self, cms_client):
        """Should return empty dict on network error."""
        with patch('src.common.cms_client.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()
            with patch('src.common.cms_client.time.sleep'):
                result = cms_client.get_connection_config()

        assert result == {}

    def test_get_connection_config_uses_correct_endpoint(self, cms_client):
        """Connection config request should use correct endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        with patch('src.common.cms_client.requests.get', return_value=mock_response) as mock_get:
            cms_client.get_connection_config()

        call_args = mock_get.call_args
        assert '/api/v1/devices/test-device-001/connection-config' in call_args[0][0]


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestCMSClientIntegration:
    """Integration-style tests for complete pairing flow."""

    def test_full_pairing_flow(self, cms_client):
        """Test the complete pairing flow."""
        # Step 1: Register device
        register_response = MagicMock()
        register_response.status_code = 201
        register_response.json.return_value = {'device_id': 'test-device-001'}

        # Step 2: Request pairing
        pairing_response = MagicMock()
        pairing_response.status_code = 200

        # Step 3: Check status (paired)
        status_response = MagicMock()
        status_response.status_code = 200
        status_response.json.return_value = {'paired': True}

        # Step 4: Get config
        config_response = MagicMock()
        config_response.status_code = 200
        config_response.json.return_value = {'playlist_id': 1}

        with patch('src.common.cms_client.requests.post') as mock_post:
            with patch('src.common.cms_client.requests.get') as mock_get:
                mock_post.side_effect = [register_response, pairing_response]
                mock_get.side_effect = [status_response, config_response]

                # Execute flow
                device = cms_client.register_device()
                assert device is not None

                code = cms_client.request_pairing()
                assert code is not None

                is_paired = cms_client.check_pairing_status()
                assert is_paired is True

                config = cms_client.get_config()
                assert config == {'playlist_id': 1}

    def test_timeout_settings_applied(self, mock_device_info):
        """Timeout setting should be applied to requests."""
        with patch('src.common.cms_client.get_device_info', return_value=mock_device_info):
            client = CMSClient(timeout=15)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'paired': False}

        with patch('src.common.cms_client.requests.get', return_value=mock_response) as mock_get:
            client.check_pairing_status()

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]['timeout'] == 15

    def test_retry_settings_applied(self, mock_device_info):
        """Max retry setting should be applied."""
        with patch('src.common.cms_client.get_device_info', return_value=mock_device_info):
            client = CMSClient(max_retries=5)

        with patch('src.common.cms_client.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError()
            with patch('src.common.cms_client.time.sleep'):
                client.check_pairing_status()

        # Should be called 6 times (initial + 5 retries)
        assert mock_get.call_count == 6


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestCMSClientErrorHandling:
    """Tests for error handling scenarios."""

    def test_handles_json_decode_error(self, cms_client):
        """Should handle JSON decode errors gracefully."""
        cms_client.paired = True

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            # Should raise the ValueError (not catch it silently)
            with pytest.raises(ValueError):
                cms_client.get_config()

    def test_handles_empty_response(self, cms_client):
        """Should handle empty response body."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            result = cms_client.check_pairing_status()

        # Should return False when 'paired' key is missing
        assert result is False

    def test_handles_partial_response(self, cms_client):
        """Should handle responses with missing expected fields."""
        cms_client.paired = True

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'unexpected_field': 'value'}

        with patch('src.common.cms_client.requests.get', return_value=mock_response):
            result = cms_client.get_config()

        # Should return whatever the response contains
        assert result == {'unexpected_field': 'value'}
