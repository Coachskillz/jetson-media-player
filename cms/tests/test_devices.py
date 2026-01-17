"""
Integration tests for CMS Devices API endpoints.

Tests all device API routes:
- POST /api/v1/devices/register - Device registration (direct and hub modes)
- POST /api/v1/devices/pair - Device pairing with network
- GET /api/v1/devices/<id>/config - Device configuration
- GET /api/v1/devices - List all devices

Each test class covers a specific operation with comprehensive
endpoint validation including success cases and error handling.
"""

import pytest

from cms.models import db, Device, Hub, Network, DeviceAssignment, Playlist


# =============================================================================
# Device Registration API Tests (POST /api/v1/devices/register)
# =============================================================================

class TestDeviceRegistrationAPI:
    """Tests for POST /api/v1/devices/register endpoint."""

    # -------------------------------------------------------------------------
    # Direct Mode Registration Tests
    # -------------------------------------------------------------------------

    def test_register_direct_device_success(self, client, app):
        """POST /devices/register should create a new direct mode device."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-direct-test-001',
            'mode': 'direct',
            'name': 'Test Direct Device'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['hardware_id'] == 'hw-direct-test-001'
        assert data['mode'] == 'direct'
        assert data['name'] == 'Test Direct Device'
        assert data['status'] == 'pending'
        assert data['device_id'].startswith('SKZ-D-')
        assert data['hub_id'] is None
        assert 'id' in data
        assert 'created_at' in data

    def test_register_direct_device_without_name(self, client, app):
        """POST /devices/register should allow direct device without name."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-direct-noname-001',
            'mode': 'direct'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['hardware_id'] == 'hw-direct-noname-001'
        assert data['mode'] == 'direct'
        assert data['name'] is None
        assert data['device_id'].startswith('SKZ-D-')

    def test_register_direct_device_generates_sequential_ids(self, client, app):
        """POST /devices/register should generate sequential device IDs."""
        # Register first device
        response1 = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-seq-001',
            'mode': 'direct'
        })
        assert response1.status_code == 201
        device_id_1 = response1.get_json()['device_id']

        # Register second device
        response2 = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-seq-002',
            'mode': 'direct'
        })
        assert response2.status_code == 201
        device_id_2 = response2.get_json()['device_id']

        # Extract numeric parts and verify sequential
        num1 = int(device_id_1.split('-')[-1])
        num2 = int(device_id_2.split('-')[-1])
        assert num2 == num1 + 1

    # -------------------------------------------------------------------------
    # Hub Mode Registration Tests
    # -------------------------------------------------------------------------

    def test_register_hub_device_success(self, client, app, sample_hub):
        """POST /devices/register should create a new hub mode device."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-hub-test-001',
            'mode': 'hub',
            'hub_id': sample_hub.id,
            'name': 'Test Hub Device'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['hardware_id'] == 'hw-hub-test-001'
        assert data['mode'] == 'hub'
        assert data['name'] == 'Test Hub Device'
        assert data['status'] == 'pending'
        assert data['hub_id'] == sample_hub.id
        assert data['network_id'] == sample_hub.network_id
        assert f'SKZ-H-{sample_hub.code}-' in data['device_id']

    def test_register_hub_device_without_name(self, client, app, sample_hub):
        """POST /devices/register should allow hub device without name."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-hub-noname-001',
            'mode': 'hub',
            'hub_id': sample_hub.id
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['hardware_id'] == 'hw-hub-noname-001'
        assert data['name'] is None
        assert data['hub_id'] == sample_hub.id

    def test_register_hub_device_inherits_network(self, client, app, sample_hub, sample_network):
        """POST /devices/register in hub mode should inherit network from hub."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-hub-network-001',
            'mode': 'hub',
            'hub_id': sample_hub.id
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['network_id'] == sample_network.id

    def test_register_hub_device_generates_hub_prefixed_id(self, client, app, sample_hub):
        """POST /devices/register in hub mode should generate hub-prefixed device ID."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-hub-id-001',
            'mode': 'hub',
            'hub_id': sample_hub.id
        })

        assert response.status_code == 201
        data = response.get_json()
        # ID should be SKZ-H-{HUB_CODE}-XXXX
        assert data['device_id'].startswith(f'SKZ-H-{sample_hub.code}-')

    def test_register_hub_device_missing_hub_id(self, client, app):
        """POST /devices/register in hub mode should reject missing hub_id."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-hub-missing-001',
            'mode': 'hub'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'hub_id is required for hub mode' in data['error']

    def test_register_hub_device_invalid_hub_id(self, client, app):
        """POST /devices/register should reject non-existent hub_id."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-hub-invalid-001',
            'mode': 'hub',
            'hub_id': 'non-existent-hub-id'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'not found' in data['error']

    # -------------------------------------------------------------------------
    # Existing Device Tests
    # -------------------------------------------------------------------------

    def test_register_existing_device_returns_existing(self, client, app, sample_device_direct):
        """POST /devices/register should return existing device without creating duplicate."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': sample_device_direct.hardware_id,
            'mode': 'direct'
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == sample_device_direct.id
        assert data['device_id'] == sample_device_direct.device_id
        assert data['hardware_id'] == sample_device_direct.hardware_id

    def test_register_existing_device_ignores_new_mode(self, client, app, sample_device_direct, sample_hub):
        """POST /devices/register for existing device should ignore new mode parameter."""
        original_mode = sample_device_direct.mode

        response = client.post('/api/v1/devices/register', json={
            'hardware_id': sample_device_direct.hardware_id,
            'mode': 'hub',  # Different mode
            'hub_id': sample_hub.id
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['mode'] == original_mode  # Mode unchanged

    # -------------------------------------------------------------------------
    # Validation Error Tests
    # -------------------------------------------------------------------------

    def test_register_device_empty_body(self, client, app):
        """POST /devices/register should reject empty body."""
        response = client.post('/api/v1/devices/register',
                               data='',
                               content_type='application/json')

        assert response.status_code == 400
        data = response.get_json()
        assert 'Request body is required' in data['error']

    def test_register_device_missing_hardware_id(self, client, app):
        """POST /devices/register should reject missing hardware_id."""
        response = client.post('/api/v1/devices/register', json={
            'mode': 'direct'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'hardware_id is required' in data['error']

    def test_register_device_missing_mode(self, client, app):
        """POST /devices/register should reject missing mode."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-missing-mode-001'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'mode is required' in data['error']

    def test_register_device_invalid_mode(self, client, app):
        """POST /devices/register should reject invalid mode."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-invalid-mode-001',
            'mode': 'invalid'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert "mode must be 'direct' or 'hub'" in data['error']

    def test_register_device_hardware_id_too_long(self, client, app):
        """POST /devices/register should reject hardware_id > 100 chars."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'x' * 101,
            'mode': 'direct'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'max 100 characters' in data['error']

    def test_register_device_name_too_long(self, client, app):
        """POST /devices/register should reject name > 200 chars."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-name-long-001',
            'mode': 'direct',
            'name': 'x' * 201
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'max 200 characters' in data['error']

    def test_register_device_invalid_hardware_id_type(self, client, app):
        """POST /devices/register should reject non-string hardware_id."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 12345,
            'mode': 'direct'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'hardware_id must be a string' in data['error']


# =============================================================================
# Device Pairing API Tests (POST /api/v1/devices/pair)
# =============================================================================

class TestDevicePairingAPI:
    """Tests for POST /api/v1/devices/pair endpoint."""

    def test_pair_device_success(self, client, app, db_session):
        """POST /devices/pair should pair device to network."""
        # Create network and device
        network = Network(name='Pair Test Network', slug='pair-test')
        db_session.add(network)
        db_session.commit()

        device = Device(
            device_id='SKZ-D-9001',
            hardware_id='hw-pair-test-001',
            mode='direct',
            status='pending'
        )
        db_session.add(device)
        db_session.commit()

        response = client.post('/api/v1/devices/pair', json={
            'device_id': 'SKZ-D-9001',
            'network_id': network.id
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Device paired successfully'
        assert data['device']['network_id'] == network.id
        assert data['device']['status'] == 'active'
        assert data['network']['id'] == network.id

    def test_pair_device_updates_status_to_active(self, client, app, db_session):
        """POST /devices/pair should update device status to active."""
        network = Network(name='Status Test Network', slug='status-test')
        db_session.add(network)
        db_session.commit()

        device = Device(
            device_id='SKZ-D-9002',
            hardware_id='hw-status-test-001',
            mode='direct',
            status='pending'
        )
        db_session.add(device)
        db_session.commit()

        response = client.post('/api/v1/devices/pair', json={
            'device_id': 'SKZ-D-9002',
            'network_id': network.id
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['device']['status'] == 'active'

    def test_pair_device_empty_body(self, client, app):
        """POST /devices/pair should reject empty body."""
        response = client.post('/api/v1/devices/pair',
                               data='',
                               content_type='application/json')

        assert response.status_code == 400
        data = response.get_json()
        assert 'Request body is required' in data['error']

    def test_pair_device_missing_device_id(self, client, app, sample_network):
        """POST /devices/pair should reject missing device_id."""
        response = client.post('/api/v1/devices/pair', json={
            'network_id': sample_network.id
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'device_id is required' in data['error']

    def test_pair_device_missing_network_id(self, client, app, sample_device_direct):
        """POST /devices/pair should reject missing network_id."""
        response = client.post('/api/v1/devices/pair', json={
            'device_id': sample_device_direct.device_id
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'network_id is required' in data['error']

    def test_pair_device_not_found(self, client, app, sample_network):
        """POST /devices/pair should return 404 for non-existent device."""
        response = client.post('/api/v1/devices/pair', json={
            'device_id': 'SKZ-D-9999',
            'network_id': sample_network.id
        })

        assert response.status_code == 404
        data = response.get_json()
        assert 'not found' in data['error']

    def test_pair_device_network_not_found(self, client, app, sample_device_direct):
        """POST /devices/pair should return 404 for non-existent network."""
        response = client.post('/api/v1/devices/pair', json={
            'device_id': sample_device_direct.device_id,
            'network_id': 'non-existent-network-id'
        })

        assert response.status_code == 404
        data = response.get_json()
        assert 'not found' in data['error']


# =============================================================================
# Device Config API Tests (GET /api/v1/devices/<id>/config)
# =============================================================================

class TestDeviceConfigAPI:
    """Tests for GET /api/v1/devices/<id>/config endpoint."""

    def test_get_config_by_device_id(self, client, app, sample_device_direct):
        """GET /devices/<id>/config should return config by device_id."""
        response = client.get(f'/api/v1/devices/{sample_device_direct.device_id}/config')

        assert response.status_code == 200
        data = response.get_json()
        assert data['device_id'] == sample_device_direct.device_id
        assert 'network' in data
        assert 'hub' in data
        assert 'playlists' in data
        assert data['config_version'] == 1

    def test_get_config_by_uuid(self, client, app, sample_device_direct):
        """GET /devices/<id>/config should return config by UUID."""
        response = client.get(f'/api/v1/devices/{sample_device_direct.id}/config')

        assert response.status_code == 200
        data = response.get_json()
        assert data['device_id'] == sample_device_direct.device_id

    def test_get_config_with_network(self, client, app, sample_device_direct, sample_network):
        """GET /devices/<id>/config should include network data."""
        response = client.get(f'/api/v1/devices/{sample_device_direct.device_id}/config')

        assert response.status_code == 200
        data = response.get_json()
        assert data['network'] is not None
        assert data['network']['id'] == sample_network.id
        assert data['network']['name'] == sample_network.name

    def test_get_config_with_hub(self, client, app, sample_device_hub, sample_hub):
        """GET /devices/<id>/config should include hub data for hub mode device."""
        response = client.get(f'/api/v1/devices/{sample_device_hub.device_id}/config')

        assert response.status_code == 200
        data = response.get_json()
        assert data['hub'] is not None
        assert data['hub']['id'] == sample_hub.id
        assert data['hub']['code'] == sample_hub.code
        assert data['hub']['name'] == sample_hub.name

    def test_get_config_direct_device_no_hub(self, client, app, sample_device_direct):
        """GET /devices/<id>/config should return null hub for direct device."""
        response = client.get(f'/api/v1/devices/{sample_device_direct.device_id}/config')

        assert response.status_code == 200
        data = response.get_json()
        assert data['hub'] is None

    def test_get_config_with_playlists(self, client, app, sample_device_assignment):
        """GET /devices/<id>/config should include assigned playlists."""
        device = sample_device_assignment.device
        response = client.get(f'/api/v1/devices/{device.device_id}/config')

        assert response.status_code == 200
        data = response.get_json()
        assert len(data['playlists']) == 1
        assert data['playlists'][0]['id'] == sample_device_assignment.playlist_id
        assert data['playlists'][0]['priority'] == sample_device_assignment.priority

    def test_get_config_not_found(self, client, app):
        """GET /devices/<id>/config should return 404 for non-existent device."""
        response = client.get('/api/v1/devices/non-existent-device/config')

        assert response.status_code == 404
        data = response.get_json()
        assert 'Device not found' in data['error']


# =============================================================================
# Device List API Tests (GET /api/v1/devices)
# =============================================================================

class TestDeviceListAPI:
    """Tests for GET /api/v1/devices endpoint."""

    def test_list_devices_empty(self, client, app):
        """GET /devices should return empty list when no devices."""
        response = client.get('/api/v1/devices')

        assert response.status_code == 200
        data = response.get_json()
        assert data['devices'] == []
        assert data['count'] == 0

    def test_list_devices_all(self, client, app, sample_device_direct, sample_device_hub):
        """GET /devices should return all devices."""
        response = client.get('/api/v1/devices')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 2
        device_ids = [d['device_id'] for d in data['devices']]
        assert sample_device_direct.device_id in device_ids
        assert sample_device_hub.device_id in device_ids

    def test_list_devices_filter_by_status(self, client, app, db_session):
        """GET /devices?status=X should filter by status."""
        # Create devices with different statuses
        active_device = Device(
            device_id='SKZ-D-8001',
            hardware_id='hw-status-active-001',
            mode='direct',
            status='active'
        )
        pending_device = Device(
            device_id='SKZ-D-8002',
            hardware_id='hw-status-pending-001',
            mode='direct',
            status='pending'
        )
        db_session.add_all([active_device, pending_device])
        db_session.commit()

        response = client.get('/api/v1/devices?status=active')

        assert response.status_code == 200
        data = response.get_json()
        assert all(d['status'] == 'active' for d in data['devices'])

    def test_list_devices_filter_by_mode_direct(self, client, app, sample_device_direct, sample_device_hub):
        """GET /devices?mode=direct should return only direct mode devices."""
        response = client.get('/api/v1/devices?mode=direct')

        assert response.status_code == 200
        data = response.get_json()
        assert all(d['mode'] == 'direct' for d in data['devices'])

    def test_list_devices_filter_by_mode_hub(self, client, app, sample_device_direct, sample_device_hub):
        """GET /devices?mode=hub should return only hub mode devices."""
        response = client.get('/api/v1/devices?mode=hub')

        assert response.status_code == 200
        data = response.get_json()
        assert all(d['mode'] == 'hub' for d in data['devices'])

    def test_list_devices_filter_by_network(self, client, app, sample_device_direct, sample_network):
        """GET /devices?network_id=X should filter by network."""
        response = client.get(f'/api/v1/devices?network_id={sample_network.id}')

        assert response.status_code == 200
        data = response.get_json()
        assert all(d['network_id'] == sample_network.id for d in data['devices'])

    def test_list_devices_filter_by_hub(self, client, app, sample_device_hub, sample_hub):
        """GET /devices?hub_id=X should filter by hub."""
        response = client.get(f'/api/v1/devices?hub_id={sample_hub.id}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1
        assert data['devices'][0]['hub_id'] == sample_hub.id

    def test_list_devices_invalid_mode_filter(self, client, app):
        """GET /devices?mode=invalid should return 400."""
        response = client.get('/api/v1/devices?mode=invalid')

        assert response.status_code == 400
        data = response.get_json()
        assert "mode must be 'direct' or 'hub'" in data['error']

    def test_list_devices_combined_filters(self, client, app, db_session, sample_network):
        """GET /devices should support multiple filters."""
        # Create devices
        d1 = Device(
            device_id='SKZ-D-7001',
            hardware_id='hw-combo-001',
            mode='direct',
            status='active',
            network_id=sample_network.id
        )
        d2 = Device(
            device_id='SKZ-D-7002',
            hardware_id='hw-combo-002',
            mode='direct',
            status='pending',
            network_id=sample_network.id
        )
        db_session.add_all([d1, d2])
        db_session.commit()

        response = client.get(
            f'/api/v1/devices?mode=direct&status=active&network_id={sample_network.id}'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert all(
            d['mode'] == 'direct' and
            d['status'] == 'active' and
            d['network_id'] == sample_network.id
            for d in data['devices']
        )


# =============================================================================
# Connection Config API Tests (GET/PUT /api/v1/devices/<id>/connection-config)
# =============================================================================

class TestConnectionConfigAPI:
    """Tests for GET/PUT /api/v1/devices/<id>/connection-config endpoints."""

    # -------------------------------------------------------------------------
    # GET Tests
    # -------------------------------------------------------------------------

    def test_get_connection_config_by_device_id(self, client, app, sample_device_direct):
        """GET /devices/<id>/connection-config should return config by device_id."""
        response = client.get(f'/api/v1/devices/{sample_device_direct.device_id}/connection-config')

        assert response.status_code == 200
        data = response.get_json()
        assert 'connection_mode' in data
        assert 'hub_url' in data
        assert 'cms_url' in data
        assert 'hub' in data

    def test_get_connection_config_by_uuid(self, client, app, sample_device_direct):
        """GET /devices/<id>/connection-config should return config by UUID."""
        response = client.get(f'/api/v1/devices/{sample_device_direct.id}/connection-config')

        assert response.status_code == 200
        data = response.get_json()
        assert data['connection_mode'] == 'direct'

    def test_get_connection_config_default_values(self, client, app, sample_device_direct):
        """GET should return sensible defaults for null hub_url and cms_url."""
        response = client.get(f'/api/v1/devices/{sample_device_direct.device_id}/connection-config')

        assert response.status_code == 200
        data = response.get_json()
        assert data['connection_mode'] == 'direct'  # Default
        assert data['hub_url'] == 'http://localhost:5000'  # Default when null
        assert data['cms_url'] == 'http://localhost:5002'  # Default when null

    def test_get_connection_config_with_hub(self, client, app, sample_device_hub, sample_hub):
        """GET should return hub info for hub mode device."""
        response = client.get(f'/api/v1/devices/{sample_device_hub.device_id}/connection-config')

        assert response.status_code == 200
        data = response.get_json()
        assert data['hub'] is not None
        assert data['hub']['id'] == sample_hub.id
        assert data['hub']['code'] == sample_hub.code
        assert data['hub']['name'] == sample_hub.name

    def test_get_connection_config_direct_device_no_hub(self, client, app, sample_device_direct):
        """GET should return null hub for direct mode device."""
        response = client.get(f'/api/v1/devices/{sample_device_direct.device_id}/connection-config')

        assert response.status_code == 200
        data = response.get_json()
        assert data['hub'] is None

    def test_get_connection_config_not_found(self, client, app):
        """GET should return 404 for non-existent device."""
        response = client.get('/api/v1/devices/non-existent-device/connection-config')

        assert response.status_code == 404
        data = response.get_json()
        assert 'Device not found' in data['error']

    # -------------------------------------------------------------------------
    # PUT Tests
    # -------------------------------------------------------------------------

    def test_put_connection_config_update_mode(self, client, app, sample_device_direct):
        """PUT should update connection_mode."""
        response = client.put(
            f'/api/v1/devices/{sample_device_direct.device_id}/connection-config',
            json={'connection_mode': 'hub'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['device']['connection_mode'] == 'hub'

    def test_put_connection_config_invalid_mode(self, client, app, sample_device_direct):
        """PUT should reject invalid connection_mode values."""
        response = client.put(
            f'/api/v1/devices/{sample_device_direct.device_id}/connection-config',
            json={'connection_mode': 'invalid'}
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "must be 'direct' or 'hub'" in data['error']

    def test_put_connection_config_update_urls(self, client, app, sample_device_direct):
        """PUT should update hub_url and cms_url."""
        response = client.put(
            f'/api/v1/devices/{sample_device_direct.device_id}/connection-config',
            json={
                'hub_url': 'http://192.168.1.100:5000',
                'cms_url': 'http://cms.example.com:5002'
            }
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['device']['hub_url'] == 'http://192.168.1.100:5000'
        assert data['device']['cms_url'] == 'http://cms.example.com:5002'

    def test_put_connection_config_invalid_hub_url_format(self, client, app, sample_device_direct):
        """PUT should reject hub_url without http:// or https://."""
        response = client.put(
            f'/api/v1/devices/{sample_device_direct.device_id}/connection-config',
            json={'hub_url': 'ftp://invalid.url'}
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'must start with http://' in data['error']

    def test_put_connection_config_invalid_cms_url_format(self, client, app, sample_device_direct):
        """PUT should reject cms_url without http:// or https://."""
        response = client.put(
            f'/api/v1/devices/{sample_device_direct.device_id}/connection-config',
            json={'cms_url': 'ftp://invalid.url'}
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'must start with http://' in data['error']

    def test_put_connection_config_empty_body(self, client, app, sample_device_direct):
        """PUT should reject empty request body."""
        response = client.put(
            f'/api/v1/devices/{sample_device_direct.device_id}/connection-config',
            data='',
            content_type='application/json'
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Request body is required' in data['error']

    def test_put_connection_config_not_found(self, client, app):
        """PUT should return 404 for non-existent device."""
        response = client.put(
            '/api/v1/devices/non-existent-device/connection-config',
            json={'connection_mode': 'hub'}
        )

        assert response.status_code == 404
        data = response.get_json()
        assert 'Device not found' in data['error']

    def test_put_connection_config_persists_changes(self, client, app, sample_device_direct):
        """PUT should persist changes that are visible on subsequent GET."""
        # Update the mode
        put_response = client.put(
            f'/api/v1/devices/{sample_device_direct.device_id}/connection-config',
            json={'connection_mode': 'hub', 'hub_url': 'http://test.hub:5000'}
        )
        assert put_response.status_code == 200

        # Verify with GET
        get_response = client.get(f'/api/v1/devices/{sample_device_direct.device_id}/connection-config')
        assert get_response.status_code == 200
        data = get_response.get_json()
        assert data['connection_mode'] == 'hub'
        assert data['hub_url'] == 'http://test.hub:5000'

    def test_put_connection_config_partial_update(self, client, app, sample_device_direct):
        """PUT should allow partial updates (only connection_mode)."""
        response = client.put(
            f'/api/v1/devices/{sample_device_direct.device_id}/connection-config',
            json={'connection_mode': 'hub'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['device']['connection_mode'] == 'hub'
        # Other fields should remain unchanged/default
        assert 'message' in data
