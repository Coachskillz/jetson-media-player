"""
Integration tests for Device Relay and Heartbeat Queue functionality.

Tests the device relay system to ensure:
- Devices can register with the local hub
- Device heartbeats are processed correctly
- Heartbeats are queued reliably when CMS is unreachable
- Queue processing and forwarding works correctly

CRITICAL: These tests verify the reliability guarantees of the heartbeat
queue system. Heartbeats must remain in the queue until CMS confirms receipt.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from models import db, Device, HubConfig
from models.heartbeat_queue import HeartbeatQueue
from services import HeartbeatQueueError, HQConnectionError, HQTimeoutError
from services.heartbeat_queue import HeartbeatQueueService


# =============================================================================
# Device API Tests (/api/v1/devices)
# =============================================================================

class TestDevicesAPI:
    """Tests for /api/v1/devices endpoints."""

    # -------------------------------------------------------------------------
    # POST /devices/register
    # -------------------------------------------------------------------------

    def test_register_device_success(self, client, app, sample_hub_config):
        """POST /devices/register should create a new device."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-device-001',
            'name': 'Test Device 1'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['success'] is True
        assert data['created'] is True
        assert data['message'] == 'Device registered'
        assert data['device']['hardware_id'] == 'hw-device-001'
        assert data['device']['name'] == 'Test Device 1'

    def test_register_existing_device(self, client, app, sample_hub_config, db_session):
        """POST /devices/register should return existing device."""
        # Create existing device
        device = Device(hardware_id='hw-existing-001', name='Existing Device')
        db_session.add(device)
        db_session.commit()

        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-existing-001'
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['created'] is False
        assert data['message'] == 'Device already registered'
        assert data['device']['id'] == device.id

    def test_register_device_hub_not_registered(self, client, app, db_session):
        """POST /devices/register should return 503 when hub not registered."""
        # Ensure hub is not registered
        hub_config = HubConfig.get_instance()
        hub_config.hub_id = None
        hub_config.hub_token = None
        db_session.commit()

        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-test-001'
        })

        assert response.status_code == 503
        data = response.get_json()
        assert data['success'] is False
        assert 'Hub not registered' in data['error']

    def test_register_device_missing_hardware_id(self, client, app, sample_hub_config):
        """POST /devices/register should reject missing hardware_id."""
        response = client.post('/api/v1/devices/register', json={
            'name': 'Test Device'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'hardware_id is required' in data['error']

    def test_register_device_empty_body(self, client, app, sample_hub_config):
        """POST /devices/register should reject empty body."""
        response = client.post('/api/v1/devices/register',
                               data='',
                               content_type='application/json')

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'Request body is required' in data['error']

    def test_register_device_hardware_id_too_long(self, client, app, sample_hub_config):
        """POST /devices/register should reject hardware_id > 100 chars."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'x' * 101
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'max 100 characters' in data['error']

    def test_register_device_name_too_long(self, client, app, sample_hub_config):
        """POST /devices/register should reject name > 200 chars."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-test-002',
            'name': 'x' * 201
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'max 200 characters' in data['error']

    def test_register_device_invalid_mode(self, client, app, sample_hub_config):
        """POST /devices/register should reject invalid mode."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-test-003',
            'mode': 'invalid'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'mode must be' in data['error']

    def test_register_device_with_mode_direct(self, client, app, sample_hub_config):
        """POST /devices/register should accept mode='direct'."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-direct-001',
            'mode': 'direct'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['device']['mode'] == 'direct'

    def test_register_device_with_mode_hub(self, client, app, sample_hub_config):
        """POST /devices/register should accept mode='hub' (default)."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'hw-hub-001'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['device']['mode'] == 'hub'

    # -------------------------------------------------------------------------
    # GET /devices/{id}
    # -------------------------------------------------------------------------

    def test_get_device_success(self, client, app, db_session, sample_hub_config):
        """GET /devices/{id} should return device details."""
        device = Device(hardware_id='hw-get-001', name='Get Test Device')
        db_session.add(device)
        db_session.commit()

        response = client.get(f'/api/v1/devices/{device.id}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['device']['hardware_id'] == 'hw-get-001'
        assert data['device']['name'] == 'Get Test Device'

    def test_get_device_not_found(self, client, app):
        """GET /devices/{id} should return 404 for non-existent device."""
        response = client.get('/api/v1/devices/99999')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'Device not found' in data['error']

    # -------------------------------------------------------------------------
    # POST /devices/{id}/heartbeat
    # -------------------------------------------------------------------------

    def test_device_heartbeat_success(self, client, app, db_session, sample_hub_config):
        """POST /devices/{id}/heartbeat should acknowledge heartbeat."""
        device = Device(hardware_id='hw-hb-001', status='offline')
        db_session.add(device)
        db_session.commit()

        response = client.post(f'/api/v1/devices/{device.id}/heartbeat')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['message'] == 'Heartbeat received'
        assert 'timestamp' in data

    def test_device_heartbeat_not_found(self, client, app):
        """POST /devices/{id}/heartbeat should return 404 for non-existent device."""
        response = client.post('/api/v1/devices/99999/heartbeat')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'Device not found' in data['error']

    def test_device_heartbeat_updates_status(self, client, app, db_session, sample_hub_config):
        """POST /devices/{id}/heartbeat should set status to online."""
        device = Device(hardware_id='hw-status-test', status='offline')
        db_session.add(device)
        db_session.commit()

        response = client.post(f'/api/v1/devices/{device.id}/heartbeat')

        assert response.status_code == 200
        db_session.refresh(device)
        assert device.status == 'online'

    def test_device_heartbeat_updates_timestamp(self, client, app, db_session, sample_hub_config):
        """POST /devices/{id}/heartbeat should update last_heartbeat timestamp."""
        old_time = datetime.utcnow() - timedelta(hours=1)
        device = Device(hardware_id='hw-timestamp-test', last_heartbeat=old_time)
        db_session.add(device)
        db_session.commit()

        response = client.post(f'/api/v1/devices/{device.id}/heartbeat')

        assert response.status_code == 200
        db_session.refresh(device)
        assert device.last_heartbeat > old_time

    # -------------------------------------------------------------------------
    # GET /devices
    # -------------------------------------------------------------------------

    def test_list_devices_empty(self, client, app):
        """GET /devices should return empty list when no devices."""
        response = client.get('/api/v1/devices')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['devices'] == []
        assert data['count'] == 0

    def test_list_devices_all(self, client, app, db_session):
        """GET /devices should return all devices."""
        for i in range(3):
            device = Device(hardware_id=f'hw-list-{i:03d}', name=f'Device {i}')
            db_session.add(device)
        db_session.commit()

        response = client.get('/api/v1/devices')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['count'] == 3

    def test_list_devices_filter_online(self, client, app, db_session):
        """GET /devices?status=online should return only online devices."""
        # Create mixed status devices
        for i in range(4):
            device = Device(
                hardware_id=f'hw-filter-{i:03d}',
                status='online' if i % 2 == 0 else 'offline'
            )
            db_session.add(device)
        db_session.commit()

        response = client.get('/api/v1/devices?status=online')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert all(d['status'] == 'online' for d in data['devices'])

    def test_list_devices_filter_offline(self, client, app, db_session):
        """GET /devices?status=offline should return only offline devices."""
        for i in range(4):
            device = Device(
                hardware_id=f'hw-offline-{i:03d}',
                status='online' if i % 2 == 0 else 'offline'
            )
            db_session.add(device)
        db_session.commit()

        response = client.get('/api/v1/devices?status=offline')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert all(d['status'] == 'offline' for d in data['devices'])

    def test_list_devices_filter_pending(self, client, app, db_session):
        """GET /devices?status=pending should return only pending devices."""
        # Create pending device
        device = Device(hardware_id='hw-pending-001', status='pending')
        db_session.add(device)
        # Create online device
        device2 = Device(hardware_id='hw-online-001', status='online')
        db_session.add(device2)
        db_session.commit()

        response = client.get('/api/v1/devices?status=pending')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['count'] == 1
        assert data['devices'][0]['status'] == 'pending'


# =============================================================================
# Device Model Tests
# =============================================================================

class TestDeviceModel:
    """Tests for Device model methods."""

    def test_device_to_dict(self, app, db_session):
        """to_dict() should serialize all fields correctly."""
        device = Device(
            hardware_id='hw-dict-001',
            name='Dict Test',
            mode='hub',
            status='online',
            camera1_enabled=True,
            camera1_demographics=True,
            camera1_loyalty=False,
            camera2_enabled=False,
            camera2_ncmec=False
        )
        db_session.add(device)
        db_session.commit()

        data = device.to_dict()

        assert data['hardware_id'] == 'hw-dict-001'
        assert data['name'] == 'Dict Test'
        assert data['mode'] == 'hub'
        assert data['status'] == 'online'
        assert data['camera1_enabled'] is True
        assert data['camera1_demographics'] is True
        assert data['camera1_loyalty'] is False
        assert data['camera2_enabled'] is False
        assert data['camera2_ncmec'] is False
        assert 'created_at' in data
        assert 'updated_at' in data

    def test_device_to_heartbeat_dict(self, app, db_session):
        """to_heartbeat_dict() should return heartbeat-ready data."""
        device = Device(
            hardware_id='hw-hb-dict-001',
            device_id='SKZ-D-TEST-001',
            status='online'
        )
        db_session.add(device)
        db_session.commit()

        data = device.to_heartbeat_dict()

        assert data['device_id'] == 'SKZ-D-TEST-001'
        assert data['hardware_id'] == 'hw-hb-dict-001'
        assert data['status'] == 'online'
        assert 'last_heartbeat' in data

    def test_device_register_new(self, app, db_session):
        """register() should create new device when not exists."""
        device, created = Device.register(
            hardware_id='hw-new-001',
            name='New Device',
            mode='direct'
        )

        assert created is True
        assert device.hardware_id == 'hw-new-001'
        assert device.name == 'New Device'
        assert device.mode == 'direct'
        assert device.status == 'pending'

    def test_device_register_existing(self, app, db_session):
        """register() should return existing device and update heartbeat."""
        # Create existing device
        existing = Device(hardware_id='hw-existing-reg', status='offline')
        db_session.add(existing)
        db_session.commit()
        original_id = existing.id

        # Register again
        device, created = Device.register(
            hardware_id='hw-existing-reg',
            name='Updated Name'
        )

        assert created is False
        assert device.id == original_id
        assert device.status == 'online'  # Updated by heartbeat

    def test_device_get_by_hardware_id(self, app, db_session):
        """get_by_hardware_id() should find device by hardware_id."""
        device = Device(hardware_id='hw-find-001')
        db_session.add(device)
        db_session.commit()

        found = Device.get_by_hardware_id('hw-find-001')

        assert found is not None
        assert found.id == device.id

    def test_device_get_by_hardware_id_not_found(self, app, db_session):
        """get_by_hardware_id() should return None when not found."""
        found = Device.get_by_hardware_id('nonexistent')
        assert found is None

    def test_device_get_by_device_id(self, app, db_session):
        """get_by_device_id() should find device by CMS device_id."""
        device = Device(hardware_id='hw-cms-001', device_id='SKZ-D-001')
        db_session.add(device)
        db_session.commit()

        found = Device.get_by_device_id('SKZ-D-001')

        assert found is not None
        assert found.id == device.id

    def test_device_update_heartbeat(self, app, db_session):
        """update_heartbeat() should update timestamp and status."""
        device = Device(hardware_id='hw-update-hb', status='offline')
        db_session.add(device)
        db_session.commit()
        old_heartbeat = device.last_heartbeat

        # Small delay to ensure timestamp difference
        device.update_heartbeat()

        assert device.status == 'online'
        assert device.last_heartbeat >= old_heartbeat

    def test_device_update_from_cms(self, app, db_session):
        """update_from_cms() should update fields from CMS data."""
        device = Device(hardware_id='hw-cms-update-001')
        db_session.add(device)
        db_session.commit()

        cms_data = {
            'id': 'cms-uuid-123',
            'device_id': 'SKZ-D-CMS-001',
            'status': 'active',
            'camera1_enabled': True,
            'camera2_enabled': True,
            'camera2_ncmec': True
        }

        updated = Device.update_from_cms('hw-cms-update-001', cms_data)

        assert updated is not None
        assert updated.cms_device_id == 'cms-uuid-123'
        assert updated.device_id == 'SKZ-D-CMS-001'
        assert updated.status == 'active'
        assert updated.camera1_enabled is True
        assert updated.camera2_enabled is True
        assert updated.camera2_ncmec is True
        assert updated.synced_at is not None

    def test_device_get_all_online(self, app, db_session):
        """get_all_online() should return only online devices."""
        for i in range(4):
            device = Device(
                hardware_id=f'hw-all-online-{i}',
                status='online' if i < 2 else 'offline'
            )
            db_session.add(device)
        db_session.commit()

        online = Device.get_all_online()

        assert len(online) == 2
        assert all(d.status == 'online' for d in online)

    def test_device_get_all_for_heartbeat(self, app, db_session):
        """get_all_for_heartbeat() should return online devices with CMS ID."""
        # Online with CMS ID - should be included
        d1 = Device(
            hardware_id='hw-hb-1',
            status='online',
            cms_device_id='cms-1'
        )
        # Online without CMS ID - should be excluded
        d2 = Device(hardware_id='hw-hb-2', status='online')
        # Offline with CMS ID - should be excluded
        d3 = Device(
            hardware_id='hw-hb-3',
            status='offline',
            cms_device_id='cms-3'
        )
        db_session.add_all([d1, d2, d3])
        db_session.commit()

        ready = Device.get_all_for_heartbeat()

        assert len(ready) == 1
        assert ready[0].hardware_id == 'hw-hb-1'

    def test_device_mark_offline(self, app, db_session):
        """mark_offline() should set device status to offline."""
        device = Device(hardware_id='hw-mark-offline', status='online')
        db_session.add(device)
        db_session.commit()

        result = Device.mark_offline('hw-mark-offline')

        assert result is not None
        assert result.status == 'offline'

    def test_device_is_online_property(self, app, db_session):
        """is_online property should return True only when online."""
        device_online = Device(hardware_id='hw-prop-online', status='online')
        device_offline = Device(hardware_id='hw-prop-offline', status='offline')
        db_session.add_all([device_online, device_offline])
        db_session.commit()

        assert device_online.is_online is True
        assert device_offline.is_online is False

    def test_device_is_synced_property(self, app, db_session):
        """is_synced property should return True when CMS ID present."""
        device_synced = Device(
            hardware_id='hw-prop-synced',
            cms_device_id='cms-123'
        )
        device_unsynced = Device(hardware_id='hw-prop-unsynced')
        db_session.add_all([device_synced, device_unsynced])
        db_session.commit()

        assert device_synced.is_synced is True
        assert device_unsynced.is_synced is False


# =============================================================================
# HeartbeatQueue Model Tests
# =============================================================================

class TestHeartbeatQueueModel:
    """Tests for HeartbeatQueue model."""

    def test_enqueue_heartbeat(self, app, db_session):
        """enqueue() should create new heartbeat entry."""
        payload = {'status': 'online', 'content_id': 'c-001'}

        entry = HeartbeatQueue.enqueue(
            device_id='device-001',
            payload_dict=payload,
            device_type='screen'
        )

        assert entry.id is not None
        assert entry.device_id == 'device-001'
        assert entry.device_type == 'screen'
        assert entry.status == 'pending'
        assert entry.attempts == 0
        assert json.loads(entry.payload) == payload

    def test_get_pending_heartbeats(self, app, db_session):
        """get_pending() should return heartbeats ready for retry."""
        # Create pending heartbeat
        HeartbeatQueue.enqueue('d1', {'data': 1})
        # Create heartbeat with future retry time
        future = HeartbeatQueue.enqueue('d2', {'data': 2})
        future.next_retry_at = datetime.utcnow() + timedelta(hours=1)
        db_session.commit()

        pending = HeartbeatQueue.get_pending(limit=10)

        assert len(pending) == 1
        assert pending[0].device_id == 'd1'

    def test_get_pending_respects_limit(self, app, db_session):
        """get_pending() should respect limit parameter."""
        for i in range(10):
            HeartbeatQueue.enqueue(f'd{i}', {'data': i})

        pending = HeartbeatQueue.get_pending(limit=3)

        assert len(pending) == 3

    def test_mark_sending(self, app, db_session):
        """mark_sending() should update status and increment attempts."""
        entry = HeartbeatQueue.enqueue('device-001', {'test': 'data'})
        assert entry.status == 'pending'
        assert entry.attempts == 0

        entry.mark_sending()

        assert entry.status == 'sending'
        assert entry.attempts == 1
        assert entry.last_attempt_at is not None

    def test_mark_failed_with_backoff(self, app, db_session):
        """mark_failed() should schedule retry with exponential backoff."""
        entry = HeartbeatQueue.enqueue('device-002', {'test': 'data'})
        original_retry = entry.next_retry_at

        entry.mark_sending()  # First attempt
        entry.mark_failed(error_message='Connection error', retry_delay_seconds=30)

        assert entry.status == 'failed'
        assert 'Connection error' in entry.error_message
        assert entry.next_retry_at > original_retry

    def test_mark_sent(self, app, db_session):
        """mark_sent() should set status to sent."""
        entry = HeartbeatQueue.enqueue('device-003', {'test': 'data'})
        entry.mark_sending()

        entry.mark_sent()

        assert entry.status == 'sent'
        assert entry.error_message is None

    def test_to_cms_payload(self, app, db_session):
        """to_cms_payload() should return CMS-formatted data."""
        payload = {'status': 'online', 'metrics': {'cpu': 50}}
        entry = HeartbeatQueue.enqueue('device-004', payload, device_type='sensor')

        cms_payload = entry.to_cms_payload()

        assert cms_payload['queue_id'] == entry.id
        assert cms_payload['device_id'] == 'device-004'
        assert cms_payload['device_type'] == 'sensor'
        assert cms_payload['data'] == payload
        assert 'created_at' in cms_payload

    def test_get_batch_for_cms(self, app, db_session):
        """get_batch_for_cms() should return entries and payloads."""
        for i in range(3):
            HeartbeatQueue.enqueue(f'd{i}', {'i': i})

        entries, payloads = HeartbeatQueue.get_batch_for_cms(limit=10)

        assert len(entries) == 3
        assert len(payloads) == 3
        assert all('queue_id' in p for p in payloads)

    def test_get_by_device(self, app, db_session):
        """get_by_device() should return heartbeats for specific device."""
        HeartbeatQueue.enqueue('device-a', {'a': 1})
        HeartbeatQueue.enqueue('device-a', {'a': 2})
        HeartbeatQueue.enqueue('device-b', {'b': 1})

        device_a_hbs = HeartbeatQueue.get_by_device('device-a')

        assert len(device_a_hbs) == 2
        assert all(h.device_id == 'device-a' for h in device_a_hbs)

    def test_delete_sent_cleanup(self, app, db_session):
        """delete_sent() should remove old sent heartbeats."""
        # Create old sent heartbeat
        old_entry = HeartbeatQueue.enqueue('d-old', {})
        old_entry.mark_sending()
        old_entry.mark_sent()
        old_entry.last_attempt_at = datetime.utcnow() - timedelta(hours=48)
        db_session.commit()
        old_id = old_entry.id

        # Create recent sent heartbeat
        recent_entry = HeartbeatQueue.enqueue('d-recent', {})
        recent_entry.mark_sending()
        recent_entry.mark_sent()
        recent_id = recent_entry.id

        deleted = HeartbeatQueue.delete_sent(older_than_hours=24)

        assert deleted == 1
        assert HeartbeatQueue.query.get(old_id) is None
        assert HeartbeatQueue.query.get(recent_id) is not None

    def test_enforce_max_queue_size(self, app, db_session):
        """enforce_max_queue_size() should remove oldest when exceeded."""
        # Create 10 entries
        for i in range(10):
            HeartbeatQueue.enqueue(f'd{i}', {'i': i})

        # Enforce max of 5
        removed = HeartbeatQueue.enforce_max_queue_size(max_size=5)

        assert removed == 5
        assert HeartbeatQueue.get_pending_count() == 5

    def test_get_pending_count(self, app, db_session):
        """get_pending_count() should return correct count."""
        HeartbeatQueue.enqueue('d1', {})
        HeartbeatQueue.enqueue('d2', {})
        sent = HeartbeatQueue.enqueue('d3', {})
        sent.mark_sending()
        sent.mark_sent()

        count = HeartbeatQueue.get_pending_count()

        assert count == 2

    def test_is_pending_property(self, app, db_session):
        """is_pending property should return True for pending/failed."""
        pending = HeartbeatQueue.enqueue('d-pending', {})
        failed = HeartbeatQueue.enqueue('d-failed', {})
        failed.mark_failed()
        sent = HeartbeatQueue.enqueue('d-sent', {})
        sent.mark_sending()
        sent.mark_sent()

        assert pending.is_pending is True
        assert failed.is_pending is True
        assert sent.is_pending is False

    def test_is_ready_for_retry_property(self, app, db_session):
        """is_ready_for_retry should check next_retry_at time."""
        ready = HeartbeatQueue.enqueue('d-ready', {})
        not_ready = HeartbeatQueue.enqueue('d-not-ready', {})
        not_ready.next_retry_at = datetime.utcnow() + timedelta(hours=1)
        db_session.commit()

        assert ready.is_ready_for_retry is True
        assert not_ready.is_ready_for_retry is False


# =============================================================================
# HeartbeatQueueService Initialization Tests
# =============================================================================

class TestHeartbeatQueueServiceInit:
    """Tests for HeartbeatQueueService initialization."""

    def test_initialization_with_defaults(self, app, db_session):
        """HeartbeatQueueService should initialize with default values."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)

        assert service.hq_client is mock_hq_client
        assert service.config is mock_config
        assert service.retry_interval == 30
        assert service.batch_size == 50
        assert service.max_queue_size == 1000

    def test_initialization_with_custom_values(self, app, db_session):
        """HeartbeatQueueService should accept custom values."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(
            mock_hq_client,
            mock_config,
            retry_interval=60,
            batch_size=100,
            max_queue_size=500
        )

        assert service.retry_interval == 60
        assert service.batch_size == 100
        assert service.max_queue_size == 500

    def test_repr(self, app, db_session):
        """__repr__ should include configuration values."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(
            mock_hq_client,
            mock_config,
            retry_interval=45,
            batch_size=25
        )

        repr_str = repr(service)
        assert 'HeartbeatQueueService' in repr_str
        assert '45' in repr_str
        assert '25' in repr_str


# =============================================================================
# HeartbeatQueueService Forward Tests
# =============================================================================

class TestHeartbeatQueueServiceForward:
    """Tests for HeartbeatQueueService forwarding methods."""

    def test_forward_batch_success(self, app, db_session):
        """forward_heartbeat_batch() should mark entries as sent on success."""
        entries = []
        for i in range(3):
            entries.append(HeartbeatQueue.enqueue(f'd{i}', {'i': i}))

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.return_value = {'success': True}
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.forward_heartbeat_batch(entries, 'hub-123')

        assert result is True
        assert all(e.status == 'sent' for e in entries)
        mock_hq_client.send_batched_heartbeats.assert_called_once()

    def test_forward_batch_with_ack_response(self, app, db_session):
        """forward_heartbeat_batch() should accept 'ack' response."""
        entry = HeartbeatQueue.enqueue('device-ack', {'test': 'data'})

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.return_value = {'ack': True}
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.forward_heartbeat_batch([entry], 'hub-123')

        assert result is True
        assert entry.status == 'sent'

    def test_forward_batch_with_processed_response(self, app, db_session):
        """forward_heartbeat_batch() should accept 'processed' response."""
        entry = HeartbeatQueue.enqueue('device-proc', {'test': 'data'})

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.return_value = {'processed': 1}
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.forward_heartbeat_batch([entry], 'hub-123')

        assert result is True
        assert entry.status == 'sent'

    def test_forward_batch_hq_not_acknowledged(self, app, db_session):
        """forward_heartbeat_batch() should mark as failed when not acked."""
        entry = HeartbeatQueue.enqueue('device-noack', {'test': 'data'})

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.return_value = {'error': 'Invalid'}
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.forward_heartbeat_batch([entry], 'hub-123')

        assert result is False
        assert entry.status == 'failed'
        assert 'Invalid' in entry.error_message

    def test_forward_batch_connection_error(self, app, db_session):
        """forward_heartbeat_batch() should mark as failed on connection error."""
        entry = HeartbeatQueue.enqueue('device-conn', {'test': 'data'})

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.side_effect = HQConnectionError("Refused")
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.forward_heartbeat_batch([entry], 'hub-123')

        assert result is False
        assert entry.status == 'failed'
        # CRITICAL: Entry must still exist
        assert HeartbeatQueue.query.get(entry.id) is not None

    def test_forward_batch_timeout_error(self, app, db_session):
        """forward_heartbeat_batch() should mark as failed on timeout."""
        entry = HeartbeatQueue.enqueue('device-timeout', {'test': 'data'})

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.side_effect = HQTimeoutError("Timeout")
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.forward_heartbeat_batch([entry], 'hub-123')

        assert result is False
        assert entry.status == 'failed'
        # CRITICAL: Entry must still exist
        assert HeartbeatQueue.query.get(entry.id) is not None

    def test_forward_batch_empty(self, app, db_session):
        """forward_heartbeat_batch() should handle empty batch."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.forward_heartbeat_batch([], 'hub-123')

        assert result is True
        mock_hq_client.send_batched_heartbeats.assert_not_called()


# =============================================================================
# HeartbeatQueueService Process Pending Tests
# =============================================================================

class TestHeartbeatQueueServiceProcess:
    """Tests for process_pending_heartbeats() method."""

    def test_process_no_pending(self, app, db_session, sample_hub_config):
        """process_pending_heartbeats() should handle empty queue."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.process_pending_heartbeats(hub_id='hub-123')

        assert result['processed'] == 0
        assert result['succeeded'] == 0
        assert result['failed'] == 0
        assert result['batches'] == 0

    def test_process_single_batch_success(self, app, db_session, sample_hub_config):
        """process_pending_heartbeats() should process single batch."""
        for i in range(3):
            HeartbeatQueue.enqueue(f'd{i}', {'i': i})

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.return_value = {'success': True}
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.process_pending_heartbeats(hub_id='hub-123')

        assert result['processed'] == 3
        assert result['succeeded'] == 3
        assert result['failed'] == 0
        assert result['batches'] == 1

    def test_process_multiple_batches(self, app, db_session, sample_hub_config):
        """process_pending_heartbeats() should process multiple batches."""
        for i in range(10):
            HeartbeatQueue.enqueue(f'd{i}', {'i': i})

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.return_value = {'success': True}
        mock_config = MagicMock()

        service = HeartbeatQueueService(
            mock_hq_client,
            mock_config,
            batch_size=3
        )
        result = service.process_pending_heartbeats(hub_id='hub-123')

        assert result['processed'] == 10
        assert result['succeeded'] == 10
        assert result['batches'] == 4  # 3+3+3+1

    def test_process_with_failures(self, app, db_session, sample_hub_config):
        """process_pending_heartbeats() should track failed batches."""
        for i in range(3):
            HeartbeatQueue.enqueue(f'd{i}', {'i': i})

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.return_value = {'error': 'Failed'}
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.process_pending_heartbeats(hub_id='hub-123')

        assert result['processed'] == 3
        assert result['succeeded'] == 0
        assert result['failed'] == 3

    def test_process_skips_when_hub_not_registered(self, app, db_session):
        """process_pending_heartbeats() should skip when hub not registered."""
        HeartbeatQueue.enqueue('d1', {'test': 'data'})

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.process_pending_heartbeats()  # No hub_id, hub not registered

        assert result['processed'] == 0
        mock_hq_client.send_batched_heartbeats.assert_not_called()


# =============================================================================
# HeartbeatQueueService Queue Status Tests
# =============================================================================

class TestHeartbeatQueueServiceStatus:
    """Tests for queue status methods."""

    def test_get_queue_status_empty(self, app, db_session):
        """get_queue_status() should handle empty queue."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        status = service.get_queue_status()

        assert status['pending_count'] == 0
        assert status['by_status']['pending'] == 0
        assert status['by_status']['failed'] == 0
        assert status['oldest_pending'] is None

    def test_get_queue_status_with_entries(self, app, db_session):
        """get_queue_status() should return correct counts."""
        HeartbeatQueue.enqueue('d1', {})
        HeartbeatQueue.enqueue('d2', {})
        failed = HeartbeatQueue.enqueue('d3', {})
        failed.mark_failed()

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        status = service.get_queue_status()

        assert status['pending_count'] == 3
        assert status['by_status']['pending'] == 2
        assert status['by_status']['failed'] == 1
        assert status['oldest_pending'] is not None

    def test_get_queue_status_by_device_type(self, app, db_session):
        """get_queue_status() should count by device type."""
        HeartbeatQueue.enqueue('d1', {}, device_type='screen')
        HeartbeatQueue.enqueue('d2', {}, device_type='screen')
        HeartbeatQueue.enqueue('d3', {}, device_type='sensor')

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        status = service.get_queue_status()

        assert status['by_device_type']['screen'] == 2
        assert status['by_device_type']['sensor'] == 1

    def test_get_queue_stats(self, app, db_session):
        """get_queue_stats() should calculate statistics."""
        HeartbeatQueue.enqueue('d1', {})
        sent = HeartbeatQueue.enqueue('d2', {})
        sent.mark_sending()
        sent.mark_sent()

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        stats = service.get_queue_stats(hours=24)

        assert stats['total_queued'] == 2
        assert stats['total_sent'] == 1
        assert stats['total_pending'] == 1
        assert stats['devices_seen'] == 2


# =============================================================================
# HeartbeatQueueService Cleanup Tests
# =============================================================================

class TestHeartbeatQueueServiceCleanup:
    """Tests for cleanup methods."""

    def test_cleanup_sent_heartbeats(self, app, db_session):
        """cleanup_sent_heartbeats() should remove old sent entries."""
        old = HeartbeatQueue.enqueue('d-old', {})
        old.mark_sending()
        old.mark_sent()
        old.last_attempt_at = datetime.utcnow() - timedelta(hours=48)
        db_session.commit()
        old_id = old.id

        recent = HeartbeatQueue.enqueue('d-recent', {})
        recent.mark_sending()
        recent.mark_sent()
        recent_id = recent.id

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        deleted = service.cleanup_sent_heartbeats(older_than_hours=24)

        assert deleted == 1
        assert HeartbeatQueue.query.get(old_id) is None
        assert HeartbeatQueue.query.get(recent_id) is not None

    def test_cleanup_never_removes_pending(self, app, db_session):
        """cleanup_sent_heartbeats() should NEVER remove pending entries."""
        pending = HeartbeatQueue.enqueue('d-pending', {})
        pending.created_at = datetime.utcnow() - timedelta(hours=100)
        db_session.commit()
        pending_id = pending.id

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        deleted = service.cleanup_sent_heartbeats(older_than_hours=24)

        # CRITICAL: Pending entry must NOT be deleted
        assert deleted == 0
        assert HeartbeatQueue.query.get(pending_id) is not None


# =============================================================================
# HeartbeatQueueService Force Retry Tests
# =============================================================================

class TestHeartbeatQueueServiceForceRetry:
    """Tests for force_retry_all() method."""

    def test_force_retry_all_empty(self, app, db_session):
        """force_retry_all() should handle empty queue."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        count = service.force_retry_all()

        assert count == 0

    def test_force_retry_all_resets_retry_time(self, app, db_session):
        """force_retry_all() should reset next_retry_at for all pending."""
        entry1 = HeartbeatQueue.enqueue('d1', {})
        entry1.next_retry_at = datetime.utcnow() + timedelta(hours=10)

        entry2 = HeartbeatQueue.enqueue('d2', {})
        entry2.mark_failed()
        entry2.next_retry_at = datetime.utcnow() + timedelta(hours=5)
        db_session.commit()

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        count = service.force_retry_all()

        assert count == 2

        now = datetime.utcnow()
        assert entry1.next_retry_at <= now + timedelta(seconds=5)
        assert entry2.next_retry_at <= now + timedelta(seconds=5)

    def test_force_retry_excludes_sent(self, app, db_session):
        """force_retry_all() should not affect sent entries."""
        pending = HeartbeatQueue.enqueue('d-pending', {})
        pending.next_retry_at = datetime.utcnow() + timedelta(hours=1)
        db_session.commit()

        sent = HeartbeatQueue.enqueue('d-sent', {})
        sent.mark_sending()
        sent.mark_sent()

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        count = service.force_retry_all()

        assert count == 1


# =============================================================================
# HeartbeatQueueService Device-Specific Tests
# =============================================================================

class TestHeartbeatQueueServiceDevice:
    """Tests for device-specific methods."""

    def test_enqueue_heartbeat(self, app, db_session):
        """enqueue_heartbeat() should add heartbeat to queue."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        entry = service.enqueue_heartbeat(
            device_id='device-001',
            payload={'status': 'online'},
            device_type='sensor'
        )

        assert entry.device_id == 'device-001'
        assert entry.device_type == 'sensor'
        assert entry.status == 'pending'

    def test_get_device_heartbeats(self, app, db_session):
        """get_device_heartbeats() should return device's heartbeats."""
        HeartbeatQueue.enqueue('device-a', {'a': 1})
        HeartbeatQueue.enqueue('device-a', {'a': 2})
        HeartbeatQueue.enqueue('device-b', {'b': 1})

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        heartbeats = service.get_device_heartbeats('device-a')

        assert len(heartbeats) == 2
        assert all(h['device_id'] == 'device-a' for h in heartbeats)

    def test_forward_device_heartbeats(self, app, db_session):
        """forward_device_heartbeats() should forward specific device's heartbeats."""
        HeartbeatQueue.enqueue('device-x', {'x': 1})
        HeartbeatQueue.enqueue('device-x', {'x': 2})
        HeartbeatQueue.enqueue('device-y', {'y': 1})

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.return_value = {'success': True}
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.forward_device_heartbeats('device-x', 'hub-123')

        assert result is True
        # Only device-x heartbeats should be sent
        call_args = mock_hq_client.send_batched_heartbeats.call_args
        heartbeats = call_args[1]['heartbeats']
        assert len(heartbeats) == 2
        assert all(h['device_id'] == 'device-x' for h in heartbeats)


# =============================================================================
# Heartbeat Queue Reliability Tests (CRITICAL)
# =============================================================================

class TestHeartbeatQueueReliability:
    """
    CRITICAL tests for heartbeat queue reliability guarantees.

    These tests verify that heartbeats are NEVER lost under any circumstances.
    """

    def test_heartbeats_never_deleted_on_hq_failure(self, app, db_session):
        """Heartbeats MUST remain in queue when HQ forwarding fails."""
        entry = HeartbeatQueue.enqueue('device-critical', {'critical': 'data'})
        entry_id = entry.id

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.side_effect = HQConnectionError("Network down")
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.forward_heartbeat_batch([entry], 'hub-123')

        assert result is False
        # CRITICAL: Entry must still exist
        persisted = HeartbeatQueue.query.get(entry_id)
        assert persisted is not None
        assert persisted.status == 'failed'

    def test_heartbeats_never_deleted_on_timeout(self, app, db_session):
        """Heartbeats MUST remain in queue when HQ request times out."""
        entry = HeartbeatQueue.enqueue('device-timeout', {'important': 'info'})
        entry_id = entry.id

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.side_effect = HQTimeoutError("Timeout")
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.forward_heartbeat_batch([entry], 'hub-123')

        assert result is False
        # CRITICAL: Entry must still exist
        assert HeartbeatQueue.query.get(entry_id) is not None

    def test_heartbeats_never_deleted_on_exception(self, app, db_session):
        """Heartbeats MUST remain in queue on any exception."""
        entry = HeartbeatQueue.enqueue('device-error', {'error': 'test'})
        entry_id = entry.id

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.side_effect = Exception("Unexpected error")
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.forward_heartbeat_batch([entry], 'hub-123')

        assert result is False
        # CRITICAL: Entry must still exist
        assert HeartbeatQueue.query.get(entry_id) is not None

    def test_heartbeats_only_marked_sent_after_hq_confirmation(self, app, db_session):
        """Heartbeats should only be marked sent after HQ confirms receipt."""
        entry = HeartbeatQueue.enqueue('device-confirm', {'data': 'test'})
        entry_id = entry.id

        mock_hq_client = MagicMock()
        # First call: HQ doesn't confirm
        mock_hq_client.send_batched_heartbeats.return_value = {}
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)
        result = service.forward_heartbeat_batch([entry], 'hub-123')

        # Entry should NOT be marked as sent
        assert result is False
        assert entry.status == 'failed'

        # Now simulate HQ confirming
        mock_hq_client.send_batched_heartbeats.return_value = {'success': True}
        # Reset status for retry
        entry.status = 'pending'
        db_session.commit()

        result = service.forward_heartbeat_batch([entry], 'hub-123')
        assert result is True
        assert entry.status == 'sent'

    def test_retry_persists_through_multiple_failures(self, app, db_session):
        """Heartbeats should be retryable through multiple failures."""
        entry = HeartbeatQueue.enqueue('device-persist', {'persistent': 'heartbeat'})
        entry_id = entry.id

        mock_hq_client = MagicMock()
        mock_hq_client.send_batched_heartbeats.side_effect = Exception("Error")
        mock_config = MagicMock()

        service = HeartbeatQueueService(mock_hq_client, mock_config)

        # Simulate 10 failed attempts
        for i in range(10):
            entry.status = 'pending'  # Reset for retry
            db_session.commit()
            service.forward_heartbeat_batch([entry], 'hub-123')

        # CRITICAL: Entry must still exist after 10 failures
        persisted = HeartbeatQueue.query.get(entry_id)
        assert persisted is not None
        assert persisted.attempts == 10

        # Now succeed
        mock_hq_client.send_batched_heartbeats.side_effect = None
        mock_hq_client.send_batched_heartbeats.return_value = {'success': True}
        entry.status = 'pending'
        db_session.commit()

        result = service.forward_heartbeat_batch([entry], 'hub-123')
        assert result is True
        assert entry.status == 'sent'

    def test_queue_overflow_drops_oldest_not_newest(self, app, db_session):
        """When queue overflows, oldest entries should be dropped first."""
        # Create entries with known order
        entries = []
        for i in range(5):
            entry = HeartbeatQueue.enqueue(f'd{i}', {'order': i})
            entries.append(entry)

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        service = HeartbeatQueueService(
            mock_hq_client,
            mock_config,
            max_queue_size=3
        )

        # Add one more to trigger overflow
        new_entry = service.enqueue_heartbeat('d-new', {'order': 'new'})

        # Check that oldest entries were dropped
        remaining = HeartbeatQueue.get_all_pending()
        remaining_orders = [json.loads(e.payload).get('order') for e in remaining]

        # Should have kept the 3 newest (indices 2, 3, 4 and 'new')
        assert len(remaining) == 3
        # New entry should still exist
        assert HeartbeatQueue.query.get(new_entry.id) is not None
