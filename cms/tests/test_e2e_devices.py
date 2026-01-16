"""
End-to-End tests for CMS Device Registration.

These tests verify the complete device registration flow including
ID generation, database persistence, and response format validation.

Tests:
- Direct mode device registration with SKZ-D-XXXX format
- Sequential ID generation for multiple devices
- Response payload validation
"""

import re
import pytest


# =============================================================================
# E2E Device Registration Tests - Direct Mode
# =============================================================================

class TestE2EDirectModeDeviceRegistration:
    """
    E2E tests for direct mode device registration.

    Verifies the complete flow:
    1. POST request to /api/v1/devices/register
    2. Device created with correct mode
    3. Device ID generated in SKZ-D-XXXX format
    4. Response contains all expected fields
    """

    def test_e2e_register_direct_device_returns_201(self, client, app):
        """
        E2E Test: Register device in direct mode, verify status 201.

        Subtask: subtask-6-3
        Verification: POST /api/v1/devices/register with direct mode returns 201
        """
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'test-hw-001',
            'mode': 'direct'
        })

        assert response.status_code == 201, \
            f"Expected status 201, got {response.status_code}"

    def test_e2e_register_direct_device_id_format_skz_d_xxxx(self, client, app):
        """
        E2E Test: Register device in direct mode, verify ID format SKZ-D-XXXX.

        Subtask: subtask-6-3
        Verification: Device ID matches pattern SKZ-D-[0-9]{4}
        """
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'test-hw-e2e-format-001',
            'mode': 'direct'
        })

        assert response.status_code == 201
        data = response.get_json()

        # Verify device_id is present
        assert 'device_id' in data, "Response missing device_id field"

        # Verify device_id format: SKZ-D-XXXX where XXXX is 4 digits
        device_id = data['device_id']
        pattern = r'^SKZ-D-\d{4}$'
        assert re.match(pattern, device_id), \
            f"Device ID '{device_id}' does not match format SKZ-D-XXXX"

    def test_e2e_register_direct_device_response_payload(self, client, app):
        """
        E2E Test: Register device, verify complete response payload.

        Subtask: subtask-6-3
        Verification: Response contains all required fields with correct values
        """
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'test-hw-e2e-payload-001',
            'mode': 'direct',
            'name': 'E2E Test Device'
        })

        assert response.status_code == 201
        data = response.get_json()

        # Verify required fields
        required_fields = [
            'id', 'device_id', 'hardware_id', 'mode', 'status', 'created_at'
        ]
        for field in required_fields:
            assert field in data, f"Response missing required field: {field}"

        # Verify field values
        assert data['hardware_id'] == 'test-hw-e2e-payload-001'
        assert data['mode'] == 'direct'
        assert data['name'] == 'E2E Test Device'
        assert data['status'] == 'pending'
        assert data['hub_id'] is None  # Direct mode has no hub

        # Verify device_id format
        assert data['device_id'].startswith('SKZ-D-')

    def test_e2e_register_direct_device_sequential_ids(self, client, app):
        """
        E2E Test: Register multiple devices, verify sequential ID generation.

        Subtask: subtask-6-3
        Verification: Each new device gets the next sequential ID
        """
        # Register first device
        response1 = client.post('/api/v1/devices/register', json={
            'hardware_id': 'test-hw-e2e-seq-001',
            'mode': 'direct'
        })
        assert response1.status_code == 201
        device_id_1 = response1.get_json()['device_id']

        # Register second device
        response2 = client.post('/api/v1/devices/register', json={
            'hardware_id': 'test-hw-e2e-seq-002',
            'mode': 'direct'
        })
        assert response2.status_code == 201
        device_id_2 = response2.get_json()['device_id']

        # Register third device
        response3 = client.post('/api/v1/devices/register', json={
            'hardware_id': 'test-hw-e2e-seq-003',
            'mode': 'direct'
        })
        assert response3.status_code == 201
        device_id_3 = response3.get_json()['device_id']

        # Extract numeric parts
        num1 = int(device_id_1.split('-')[-1])
        num2 = int(device_id_2.split('-')[-1])
        num3 = int(device_id_3.split('-')[-1])

        # Verify sequential
        assert num2 == num1 + 1, \
            f"Expected {num1 + 1}, got {num2}"
        assert num3 == num2 + 1, \
            f"Expected {num2 + 1}, got {num3}"

    def test_e2e_register_direct_device_persists_to_database(self, client, app, db_session):
        """
        E2E Test: Register device, verify persistence in database.

        Subtask: subtask-6-3
        Verification: Device is retrievable from database after registration
        """
        from cms.models import Device

        hardware_id = 'test-hw-e2e-persist-001'

        # Register device
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': hardware_id,
            'mode': 'direct'
        })
        assert response.status_code == 201

        # Query database directly
        device = Device.query.filter_by(hardware_id=hardware_id).first()

        assert device is not None, "Device not found in database"
        assert device.mode == 'direct'
        assert device.device_id.startswith('SKZ-D-')
        assert device.status == 'pending'

    def test_e2e_register_direct_device_idempotent(self, client, app):
        """
        E2E Test: Re-registering same hardware_id returns existing device.

        Subtask: subtask-6-3
        Verification: No duplicate devices created for same hardware_id
        """
        hardware_id = 'test-hw-e2e-idempotent-001'

        # First registration
        response1 = client.post('/api/v1/devices/register', json={
            'hardware_id': hardware_id,
            'mode': 'direct'
        })
        assert response1.status_code == 201
        device_data_1 = response1.get_json()

        # Second registration with same hardware_id
        response2 = client.post('/api/v1/devices/register', json={
            'hardware_id': hardware_id,
            'mode': 'direct'
        })

        # Should return 200 (existing) not 201 (new)
        assert response2.status_code == 200
        device_data_2 = response2.get_json()

        # Verify same device returned
        assert device_data_1['id'] == device_data_2['id']
        assert device_data_1['device_id'] == device_data_2['device_id']


# =============================================================================
# E2E Device Registration - Validation Tests
# =============================================================================

class TestE2EDirectModeDeviceRegistrationValidation:
    """E2E tests for direct mode device registration validation."""

    def test_e2e_register_device_missing_hardware_id_returns_400(self, client, app):
        """E2E Test: Missing hardware_id returns 400."""
        response = client.post('/api/v1/devices/register', json={
            'mode': 'direct'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data
        assert 'hardware_id' in data['error']

    def test_e2e_register_device_missing_mode_returns_400(self, client, app):
        """E2E Test: Missing mode returns 400."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'test-hw-no-mode'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data
        assert 'mode' in data['error']

    def test_e2e_register_device_invalid_mode_returns_400(self, client, app):
        """E2E Test: Invalid mode returns 400."""
        response = client.post('/api/v1/devices/register', json={
            'hardware_id': 'test-hw-invalid-mode',
            'mode': 'invalid_mode'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data
        assert "mode must be 'direct' or 'hub'" in data['error']

    def test_e2e_register_device_empty_body_returns_400(self, client, app):
        """E2E Test: Empty request body returns 400."""
        response = client.post(
            '/api/v1/devices/register',
            data='',
            content_type='application/json'
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data
