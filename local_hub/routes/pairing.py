"""
Device pairing API endpoints.

This module provides REST API endpoints for device pairing:
- POST /pairing/request - Request pairing with CMS
- GET /pairing/status/{hardware_id} - Check pairing status

Pairing flow:
1. Device calls POST /pairing/request with hardware_id and pairing_code
2. Hub registers device locally and forwards request to CMS
3. Admin enters pairing_code in CMS to approve
4. Device polls GET /pairing/status to check approval
5. Once approved, device receives device_id and can start operation
"""

from datetime import datetime
import requests

from flask import jsonify, request, current_app, Blueprint

from models import db, Device, HubConfig
from config import get_config

pairing_bp = Blueprint('pairing', __name__)


@pairing_bp.route('/request', methods=['POST'])
def request_pairing():
    """
    Request pairing with CMS via this hub.

    The hub forwards the pairing request to the CMS. The CMS will
    show the pairing code to admins who can then approve the device.

    Request Body:
        {
            "hardware_id": "unique-hardware-id",
            "pairing_code": "123456",
            "name": "optional device name",
            "ip_address": "10.10.10.100"
        }

    Returns:
        200: Pairing request accepted
            {
                "success": true,
                "message": "Pairing request sent to CMS",
                "pairing_code": "123456"
            }
        400: Missing required field
        503: Hub not registered or CMS unreachable
    """
    data = request.get_json()

    if not data:
        return jsonify({
            'success': False,
            'error': 'Request body is required'
        }), 400

    hardware_id = data.get('hardware_id')
    pairing_code = data.get('pairing_code')

    if not hardware_id:
        return jsonify({
            'success': False,
            'error': 'hardware_id is required'
        }), 400

    if not pairing_code:
        return jsonify({
            'success': False,
            'error': 'pairing_code is required'
        }), 400

    # Get hub config
    hub_config = HubConfig.get_instance()
    config = get_config()

    # Check if hub is registered
    if not hub_config.is_registered:
        return jsonify({
            'success': False,
            'error': 'Hub not registered with CMS. Please register hub first.'
        }), 503

    # Register device locally first
    name = data.get('name', f'Device-{hardware_id[-6:]}')
    ip_address = data.get('ip_address')
    location = data.get('location')

    device, created = Device.register(
        hardware_id=hardware_id,
        name=name,
        mode='hub',
        ip_address=ip_address,
        location=location
    )

    # Forward pairing request to CMS
    cms_url = config.cms_url
    try:
        response = requests.post(
            f"{cms_url}/api/v1/pairing/request",
            json={
                "hardware_id": hardware_id,
                "pairing_code": pairing_code,
                "name": name,
                "hub_id": hub_config.hub_id,
                "ip_address": ip_address
            },
            timeout=10
        )

        if response.status_code == 200:
            current_app.logger.info(f"Pairing request forwarded to CMS for {hardware_id}")
            return jsonify({
                'success': True,
                'message': 'Pairing request sent to CMS',
                'pairing_code': pairing_code,
                'device_id': device.id
            }), 200
        else:
            current_app.logger.error(f"CMS pairing request failed: {response.status_code}")
            # Still return success - device is registered locally
            # CMS sync will happen later
            return jsonify({
                'success': True,
                'message': 'Device registered locally. CMS sync pending.',
                'pairing_code': pairing_code,
                'device_id': device.id,
                'cms_sync': False
            }), 200

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Failed to reach CMS: {e}")
        # Device is registered locally, CMS sync will happen later
        return jsonify({
            'success': True,
            'message': 'Device registered locally. CMS sync pending.',
            'pairing_code': pairing_code,
            'device_id': device.id,
            'cms_sync': False
        }), 200


@pairing_bp.route('/status/<hardware_id>', methods=['GET'])
def get_pairing_status(hardware_id):
    """
    Check pairing status for a device.

    Devices poll this endpoint to check if pairing has been approved
    by an admin in the CMS.

    Args:
        hardware_id: Device hardware ID

    Returns:
        200: Pairing status
            {
                "success": true,
                "paired": true/false,
                "device_id": "DEV-001" (if paired),
                "status": "pending|approved|online"
            }
        404: Device not found
    """
    device = Device.get_by_hardware_id(hardware_id)

    if not device:
        return jsonify({
            'success': False,
            'error': 'Device not found'
        }), 404

    # Check if device is paired (has device_id from CMS or local approval)
    paired = device.device_id is not None

    # If not paired locally and not synced with CMS, check with CMS
    if not paired and not device.is_synced:
        hub_config = HubConfig.get_instance()
        config = get_config()

        if hub_config.is_registered:
            try:
                response = requests.get(
                    f"{config.cms_url}/api/v1/devices/by-hardware/{hardware_id}",
                    timeout=5
                )

                if response.status_code == 200:
                    cms_data = response.json()
                    if cms_data.get('success') and cms_data.get('device'):
                        # Update local device with CMS data
                        Device.update_from_cms(hardware_id, cms_data['device'])
                        device = Device.get_by_hardware_id(hardware_id)
                        paired = device.device_id is not None

            except requests.exceptions.RequestException:
                pass  # CMS unreachable, use local status

    return jsonify({
        'success': True,
        'paired': paired,
        'device_id': device.device_id,
        'status': device.status,
        'cms_device_id': device.cms_device_id
    }), 200


@pairing_bp.route('/approve/<hardware_id>', methods=['POST'])
def approve_pairing(hardware_id):
    """
    Locally approve a device pairing (for testing or offline mode).

    In production, pairing is approved via the CMS. This endpoint
    allows local approval for testing purposes.

    Args:
        hardware_id: Device hardware ID

    Request Body:
        {
            "device_id": "DEV-001" (optional, auto-generated if not provided)
        }

    Returns:
        200: Pairing approved
        404: Device not found
    """
    device = Device.get_by_hardware_id(hardware_id)

    if not device:
        return jsonify({
            'success': False,
            'error': 'Device not found'
        }), 404

    data = request.get_json() or {}
    device_id = data.get('device_id')

    if not device_id:
        # Generate device ID
        device_id = f"DEV-{device.id:04d}"

    device.device_id = device_id
    device.status = 'online'
    device.synced_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Device pairing approved',
        'device_id': device_id
    }), 200
