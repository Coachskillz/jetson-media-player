"""
Integration tests for CMS Hub Sync API endpoints.

Tests all hub sync API routes:
- PUT /api/v1/hubs/<hub_id>/approve - Approve a pending hub
- GET /api/v1/hubs/<hub_id>/playlists - Get playlist manifest for hub
- POST /api/v1/hubs/<hub_id>/heartbeats - Receive batched device heartbeats

Each test class covers a specific operation with comprehensive
endpoint validation including success cases and error handling.
"""

import pytest
from datetime import datetime, timezone

from cms.models import db, Hub, Network, Device, Playlist, PlaylistItem, Content


# =============================================================================
# Hub Approval API Tests (PUT /api/v1/hubs/<hub_id>/approve)
# =============================================================================

class TestHubApprovalAPI:
    """Tests for PUT /api/v1/hubs/<hub_id>/approve endpoint."""

    # -------------------------------------------------------------------------
    # Success Cases
    # -------------------------------------------------------------------------

    def test_approve_hub_by_uuid(self, client, app, db_session, sample_network):
        """PUT /hubs/<hub_id>/approve should approve a pending hub by UUID."""
        # Create a pending hub
        hub = Hub(
            code='PND',
            name='Pending Hub',
            network_id=sample_network.id,
            status='pending'
        )
        db_session.add(hub)
        db_session.commit()

        response = client.put(f'/api/v1/hubs/{hub.id}/approve')

        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == hub.id
        assert data['code'] == 'PND'
        assert data['status'] == 'active'

    def test_approve_hub_by_code(self, client, app, db_session, sample_network):
        """PUT /hubs/<hub_id>/approve should approve a pending hub by code."""
        # Create a pending hub
        hub = Hub(
            code='PND',
            name='Pending Hub',
            network_id=sample_network.id,
            status='pending'
        )
        db_session.add(hub)
        db_session.commit()

        response = client.put(f'/api/v1/hubs/{hub.code}/approve')

        assert response.status_code == 200
        data = response.get_json()
        assert data['code'] == 'PND'
        assert data['status'] == 'active'

    def test_approve_hub_updates_database(self, client, app, db_session, sample_network):
        """PUT /hubs/<hub_id>/approve should persist status change to database."""
        # Create a pending hub
        hub = Hub(
            code='DBU',
            name='Database Update Hub',
            network_id=sample_network.id,
            status='pending'
        )
        db_session.add(hub)
        db_session.commit()
        hub_id = hub.id

        response = client.put(f'/api/v1/hubs/{hub_id}/approve')
        assert response.status_code == 200

        # Verify database was updated
        updated_hub = db.session.get(Hub, hub_id)
        assert updated_hub.status == 'active'

    # -------------------------------------------------------------------------
    # Error Cases
    # -------------------------------------------------------------------------

    def test_approve_hub_not_found(self, client, app):
        """PUT /hubs/<hub_id>/approve should return 404 for non-existent hub."""
        response = client.put('/api/v1/hubs/non-existent-hub-id/approve')

        assert response.status_code == 404
        data = response.get_json()
        assert 'not found' in data['error'].lower()

    def test_approve_hub_already_active(self, client, app, sample_hub):
        """PUT /hubs/<hub_id>/approve should reject already active hub."""
        # sample_hub is created with status='active' by default
        response = client.put(f'/api/v1/hubs/{sample_hub.id}/approve')

        assert response.status_code == 400
        data = response.get_json()
        assert 'not in pending state' in data['error']

    def test_approve_hub_inactive_status(self, client, app, db_session, sample_network):
        """PUT /hubs/<hub_id>/approve should reject inactive hub."""
        # Create an inactive hub
        hub = Hub(
            code='INA',
            name='Inactive Hub',
            network_id=sample_network.id,
            status='inactive'
        )
        db_session.add(hub)
        db_session.commit()

        response = client.put(f'/api/v1/hubs/{hub.id}/approve')

        assert response.status_code == 400
        data = response.get_json()
        assert 'not in pending state' in data['error']


# =============================================================================
# Hub Playlists API Tests (GET /api/v1/hubs/<hub_id>/playlists)
# =============================================================================

class TestHubPlaylistsAPI:
    """Tests for GET /api/v1/hubs/<hub_id>/playlists endpoint."""

    # -------------------------------------------------------------------------
    # Success Cases
    # -------------------------------------------------------------------------

    def test_get_playlists_empty(self, client, app, sample_hub):
        """GET /hubs/<hub_id>/playlists should return empty list when no playlists."""
        response = client.get(f'/api/v1/hubs/{sample_hub.id}/playlists')

        assert response.status_code == 200
        data = response.get_json()
        assert data['hub_id'] == sample_hub.id
        assert data['hub_code'] == sample_hub.code
        assert data['network_id'] == sample_hub.network_id
        assert data['manifest_version'] == 1
        assert data['playlists'] == []
        assert data['count'] == 0

    def test_get_playlists_by_uuid(self, client, app, sample_hub):
        """GET /hubs/<hub_id>/playlists should work with UUID."""
        response = client.get(f'/api/v1/hubs/{sample_hub.id}/playlists')

        assert response.status_code == 200
        data = response.get_json()
        assert data['hub_id'] == sample_hub.id

    def test_get_playlists_by_code(self, client, app, sample_hub):
        """GET /hubs/<hub_id>/playlists should work with code."""
        response = client.get(f'/api/v1/hubs/{sample_hub.code}/playlists')

        assert response.status_code == 200
        data = response.get_json()
        assert data['hub_code'] == sample_hub.code

    def test_get_playlists_with_playlist(self, client, app, sample_hub, sample_playlist):
        """GET /hubs/<hub_id>/playlists should include network playlists."""
        response = client.get(f'/api/v1/hubs/{sample_hub.id}/playlists')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1
        assert len(data['playlists']) == 1

        playlist = data['playlists'][0]
        assert playlist['id'] == sample_playlist.id
        assert playlist['name'] == sample_playlist.name
        assert 'items' in playlist

    def test_get_playlists_with_items(self, client, app, sample_hub, sample_playlist_with_items):
        """GET /hubs/<hub_id>/playlists should include playlist items."""
        response = client.get(f'/api/v1/hubs/{sample_hub.id}/playlists')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1

        playlist = data['playlists'][0]
        assert playlist['id'] == sample_playlist_with_items.id
        assert len(playlist['items']) == 2

        # Verify items have required fields
        for item in playlist['items']:
            assert 'id' in item
            assert 'content_id' in item
            assert 'position' in item

    def test_get_playlists_excludes_inactive(self, client, app, db_session, sample_hub, sample_network):
        """GET /hubs/<hub_id>/playlists should only include active playlists."""
        # Create active and inactive playlists
        active_playlist = Playlist(
            name='Active Playlist',
            network_id=sample_network.id,
            trigger_type='manual',
            is_active=True
        )
        inactive_playlist = Playlist(
            name='Inactive Playlist',
            network_id=sample_network.id,
            trigger_type='manual',
            is_active=False
        )
        db_session.add_all([active_playlist, inactive_playlist])
        db_session.commit()

        response = client.get(f'/api/v1/hubs/{sample_hub.id}/playlists')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1
        assert data['playlists'][0]['name'] == 'Active Playlist'

    def test_get_playlists_excludes_other_network(self, client, app, db_session, sample_hub, sample_network):
        """GET /hubs/<hub_id>/playlists should only include hub's network playlists."""
        # Create another network with playlist
        other_network = Network(name='Other Network', slug='other-network')
        db_session.add(other_network)
        db_session.commit()

        # Create playlists in both networks
        network_playlist = Playlist(
            name='Network Playlist',
            network_id=sample_network.id,
            trigger_type='manual',
            is_active=True
        )
        other_playlist = Playlist(
            name='Other Network Playlist',
            network_id=other_network.id,
            trigger_type='manual',
            is_active=True
        )
        db_session.add_all([network_playlist, other_playlist])
        db_session.commit()

        response = client.get(f'/api/v1/hubs/{sample_hub.id}/playlists')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1
        assert data['playlists'][0]['name'] == 'Network Playlist'

    def test_get_playlists_multiple(self, client, app, db_session, sample_hub, sample_network):
        """GET /hubs/<hub_id>/playlists should return all active network playlists."""
        # Create multiple playlists
        playlist1 = Playlist(
            name='Morning Playlist',
            network_id=sample_network.id,
            trigger_type='time',
            is_active=True
        )
        playlist2 = Playlist(
            name='Afternoon Playlist',
            network_id=sample_network.id,
            trigger_type='time',
            is_active=True
        )
        playlist3 = Playlist(
            name='Evening Playlist',
            network_id=sample_network.id,
            trigger_type='time',
            is_active=True
        )
        db_session.add_all([playlist1, playlist2, playlist3])
        db_session.commit()

        response = client.get(f'/api/v1/hubs/{sample_hub.id}/playlists')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 3
        assert len(data['playlists']) == 3

    # -------------------------------------------------------------------------
    # Error Cases
    # -------------------------------------------------------------------------

    def test_get_playlists_hub_not_found(self, client, app):
        """GET /hubs/<hub_id>/playlists should return 404 for non-existent hub."""
        response = client.get('/api/v1/hubs/non-existent-hub-id/playlists')

        assert response.status_code == 404
        data = response.get_json()
        assert 'not found' in data['error'].lower()


# =============================================================================
# Hub Heartbeats API Tests (POST /api/v1/hubs/<hub_id>/heartbeats)
# =============================================================================

class TestHubHeartbeatsAPI:
    """Tests for POST /api/v1/hubs/<hub_id>/heartbeats endpoint."""

    # -------------------------------------------------------------------------
    # Success Cases
    # -------------------------------------------------------------------------

    def test_receive_heartbeats_success(self, client, app, sample_hub, sample_device_hub):
        """POST /hubs/<hub_id>/heartbeats should process valid heartbeats."""
        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'heartbeats': [
                {
                    'device_id': sample_device_hub.device_id,
                    'status': 'active',
                    'timestamp': '2024-01-15T10:00:00Z'
                }
            ]
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['processed'] == 1
        assert data['errors'] == []
        assert 'hub_last_heartbeat' in data

    def test_receive_heartbeats_by_code(self, client, app, sample_hub, sample_device_hub):
        """POST /hubs/<hub_id>/heartbeats should work with hub code."""
        response = client.post(f'/api/v1/hubs/{sample_hub.code}/heartbeats', json={
            'heartbeats': [
                {
                    'device_id': sample_device_hub.device_id,
                    'status': 'active'
                }
            ]
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['processed'] == 1

    def test_receive_heartbeats_multiple_devices(self, client, app, db_session, sample_hub, sample_network):
        """POST /hubs/<hub_id>/heartbeats should process multiple device heartbeats."""
        # Create multiple devices
        device1 = Device(
            device_id=f'SKZ-H-{sample_hub.code}-0001',
            hardware_id='test-hw-001',
            mode='hub',
            hub_id=sample_hub.id,
            network_id=sample_network.id,
            status='active'
        )
        device2 = Device(
            device_id=f'SKZ-H-{sample_hub.code}-0002',
            hardware_id='test-hw-002',
            mode='hub',
            hub_id=sample_hub.id,
            network_id=sample_network.id,
            status='active'
        )
        device3 = Device(
            device_id=f'SKZ-H-{sample_hub.code}-0003',
            hardware_id='test-hw-003',
            mode='hub',
            hub_id=sample_hub.id,
            network_id=sample_network.id,
            status='active'
        )
        db_session.add_all([device1, device2, device3])
        db_session.commit()

        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'heartbeats': [
                {'device_id': device1.device_id, 'status': 'active'},
                {'device_id': device2.device_id, 'status': 'active'},
                {'device_id': device3.device_id, 'status': 'offline'}
            ]
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['processed'] == 3
        assert data['errors'] == []

    def test_receive_heartbeats_updates_device_status(self, client, app, db_session, sample_hub, sample_device_hub):
        """POST /hubs/<hub_id>/heartbeats should update device status."""
        # Verify initial status
        assert sample_device_hub.status == 'active'

        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'heartbeats': [
                {
                    'device_id': sample_device_hub.device_id,
                    'status': 'offline'
                }
            ]
        })

        assert response.status_code == 200

        # Verify status was updated
        device = Device.query.filter_by(device_id=sample_device_hub.device_id).first()
        assert device.status == 'offline'

    def test_receive_heartbeats_updates_hub_last_heartbeat(self, client, app, db_session, sample_hub, sample_device_hub):
        """POST /hubs/<hub_id>/heartbeats should update hub's last_heartbeat."""
        # Verify initial state
        assert sample_hub.last_heartbeat is None

        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'heartbeats': [
                {'device_id': sample_device_hub.device_id}
            ]
        })

        assert response.status_code == 200

        # Verify hub last_heartbeat was updated
        hub = db.session.get(Hub, sample_hub.id)
        assert hub.last_heartbeat is not None

    def test_receive_heartbeats_empty_array(self, client, app, sample_hub):
        """POST /hubs/<hub_id>/heartbeats should accept empty heartbeats array."""
        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'heartbeats': []
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['processed'] == 0
        assert data['errors'] == []

    def test_receive_heartbeats_without_timestamp(self, client, app, sample_hub, sample_device_hub):
        """POST /hubs/<hub_id>/heartbeats should use current time when timestamp not provided."""
        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'heartbeats': [
                {'device_id': sample_device_hub.device_id}
            ]
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['processed'] == 1

    def test_receive_heartbeats_partial_success(self, client, app, sample_hub, sample_device_hub):
        """POST /hubs/<hub_id>/heartbeats should process valid heartbeats and report errors."""
        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'heartbeats': [
                {'device_id': sample_device_hub.device_id, 'status': 'active'},
                {'device_id': 'non-existent-device', 'status': 'active'},
                {'device_id': 'another-missing-device', 'status': 'active'}
            ]
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['processed'] == 1
        assert len(data['errors']) == 2
        assert any('non-existent-device' in error for error in data['errors'])

    # -------------------------------------------------------------------------
    # Validation Error Tests
    # -------------------------------------------------------------------------

    def test_receive_heartbeats_empty_body(self, client, app, sample_hub):
        """POST /hubs/<hub_id>/heartbeats should reject empty body."""
        response = client.post(
            f'/api/v1/hubs/{sample_hub.id}/heartbeats',
            data='',
            content_type='application/json'
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Request body is required' in data['error']

    def test_receive_heartbeats_missing_heartbeats_field(self, client, app, sample_hub):
        """POST /hubs/<hub_id>/heartbeats should reject missing heartbeats field."""
        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'other_field': 'value'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'heartbeats field is required' in data['error']

    def test_receive_heartbeats_invalid_heartbeats_type(self, client, app, sample_hub):
        """POST /hubs/<hub_id>/heartbeats should reject non-array heartbeats."""
        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'heartbeats': 'not-an-array'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'heartbeats must be an array' in data['error']

    def test_receive_heartbeats_missing_device_id(self, client, app, sample_hub):
        """POST /hubs/<hub_id>/heartbeats should report error for missing device_id."""
        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'heartbeats': [
                {'status': 'active'}
            ]
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['processed'] == 0
        assert len(data['errors']) == 1
        assert 'missing device_id' in data['errors'][0]

    def test_receive_heartbeats_invalid_heartbeat_type(self, client, app, sample_hub):
        """POST /hubs/<hub_id>/heartbeats should report error for non-object heartbeat."""
        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'heartbeats': [
                'not-an-object'
            ]
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['processed'] == 0
        assert len(data['errors']) == 1
        assert 'must be an object' in data['errors'][0]

    def test_receive_heartbeats_invalid_timestamp(self, client, app, sample_hub, sample_device_hub):
        """POST /hubs/<hub_id>/heartbeats should report error for invalid timestamp."""
        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'heartbeats': [
                {
                    'device_id': sample_device_hub.device_id,
                    'timestamp': 'invalid-timestamp'
                }
            ]
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['processed'] == 0
        assert len(data['errors']) == 1
        assert 'Invalid timestamp' in data['errors'][0]

    def test_receive_heartbeats_device_not_found(self, client, app, sample_hub):
        """POST /hubs/<hub_id>/heartbeats should report error for unknown device."""
        response = client.post(f'/api/v1/hubs/{sample_hub.id}/heartbeats', json={
            'heartbeats': [
                {
                    'device_id': 'SKZ-H-XXX-9999',
                    'status': 'active'
                }
            ]
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['processed'] == 0
        assert len(data['errors']) == 1
        assert 'not found' in data['errors'][0]

    # -------------------------------------------------------------------------
    # Hub Not Found Tests
    # -------------------------------------------------------------------------

    def test_receive_heartbeats_hub_not_found(self, client, app):
        """POST /hubs/<hub_id>/heartbeats should return 404 for non-existent hub."""
        response = client.post('/api/v1/hubs/non-existent-hub-id/heartbeats', json={
            'heartbeats': []
        })

        assert response.status_code == 404
        data = response.get_json()
        assert 'not found' in data['error'].lower()


# =============================================================================
# Hub Registration with New Fields Tests
# =============================================================================

class TestHubRegistrationEnhanced:
    """Tests for enhanced hub registration with additional fields."""

    # -------------------------------------------------------------------------
    # Success Cases
    # -------------------------------------------------------------------------

    def test_register_hub_with_ip_address(self, client, app, sample_network):
        """POST /hubs/register should accept ip_address field."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'IP',
            'name': 'IP Address Hub',
            'network_id': sample_network.id,
            'ip_address': '192.168.1.100'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['code'] == 'IP'
        assert data['ip_address'] == '192.168.1.100'

    def test_register_hub_with_mac_address(self, client, app, sample_network):
        """POST /hubs/register should accept mac_address field."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'MAC',
            'name': 'MAC Address Hub',
            'network_id': sample_network.id,
            'mac_address': 'AA:BB:CC:DD:EE:FF'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['code'] == 'MAC'
        assert data['mac_address'] == 'AA:BB:CC:DD:EE:FF'

    def test_register_hub_with_hostname(self, client, app, sample_network):
        """POST /hubs/register should accept hostname field."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'HOST',
            'name': 'Hostname Hub',
            'network_id': sample_network.id,
            'hostname': 'hub-westmarine'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['code'] == 'HOST'
        assert data['hostname'] == 'hub-westmarine'

    def test_register_hub_with_all_fields(self, client, app, sample_network):
        """POST /hubs/register should accept all optional fields."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'ALL',
            'name': 'All Fields Hub',
            'network_id': sample_network.id,
            'location': '123 Main St',
            'ip_address': '192.168.1.100',
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'hostname': 'hub-all-fields'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['code'] == 'ALL'
        assert data['ip_address'] == '192.168.1.100'
        assert data['mac_address'] == 'AA:BB:CC:DD:EE:FF'
        assert data['hostname'] == 'hub-all-fields'

    def test_register_hub_returns_api_token(self, client, app, sample_network):
        """POST /hubs/register should return an API token."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'TOK',
            'name': 'Token Hub',
            'network_id': sample_network.id
        })

        assert response.status_code == 201
        data = response.get_json()
        assert 'api_token' in data
        assert data['api_token'].startswith('hub_')

    def test_register_hub_mac_address_uppercase(self, client, app, sample_network):
        """POST /hubs/register should store mac_address in uppercase."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'LMC',
            'name': 'Lowercase MAC Hub',
            'network_id': sample_network.id,
            'mac_address': 'aa:bb:cc:dd:ee:ff'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['mac_address'] == 'AA:BB:CC:DD:EE:FF'

    # -------------------------------------------------------------------------
    # Validation Error Tests
    # -------------------------------------------------------------------------

    def test_register_hub_invalid_mac_format(self, client, app, sample_network):
        """POST /hubs/register should reject invalid mac_address format."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'IMC',
            'name': 'Invalid MAC Hub',
            'network_id': sample_network.id,
            'mac_address': 'invalid-mac'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'XX:XX:XX:XX:XX:XX' in data['error']

    def test_register_hub_ip_address_too_long(self, client, app, sample_network):
        """POST /hubs/register should reject ip_address > 45 chars."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'LIP',
            'name': 'Long IP Hub',
            'network_id': sample_network.id,
            'ip_address': 'x' * 46
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'max 45 characters' in data['error']

    def test_register_hub_hostname_too_long(self, client, app, sample_network):
        """POST /hubs/register should reject hostname > 255 chars."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'LHN',
            'name': 'Long Hostname Hub',
            'network_id': sample_network.id,
            'hostname': 'x' * 256
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'max 255 characters' in data['error']

    def test_register_hub_mac_address_too_long(self, client, app, sample_network):
        """POST /hubs/register should reject mac_address > 17 chars."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'LMA',
            'name': 'Long MAC Hub',
            'network_id': sample_network.id,
            'mac_address': 'x' * 18
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'max 17 characters' in data['error']
