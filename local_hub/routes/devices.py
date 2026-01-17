"""
Device management API endpoints.

This module provides REST API endpoints for device management on the local hub:
- POST /devices/register - Register a new device or return existing
- GET /devices/{id} - Get device details
- POST /devices/{id}/heartbeat - Update device heartbeat
- GET /devices - List all registered devices

All endpoints are prefixed with /api/v1 when registered with the app.

Devices connect to the local hub for content serving and heartbeat monitoring.
The hub acts as a relay, forwarding device registrations and heartbeats to the CMS.
"""

from datetime import datetime

from flask import jsonify, request

from models import db, Device, HubConfig
from routes import devices_bp


@devices_bp.route('/register', methods=['POST'])
def register_device():
    """
    Register a new device or return existing device.

    Devices call this endpoint on boot to register with the hub.
    If a device with the given hardware_id already exists, returns
    the existing device and updates its heartbeat timestamp.

    The hub must be registered with CMS before devices can register.
    If the hub is not registered, returns 503 Service Unavailable.

    Request Body:
        {
            "hardware_id": "unique-hardware-id",
            "name": "optional device name",
            "mode": "hub" (optional, default: "hub")
        }

    Returns:
        201: New device created
            {
                "success": true,
                "message": "Device registered",
                "device": { device data },
                "created": true
            }
        200: Existing device returned
            {
                "success": true,
                "message": "Device already registered",
                "device": { device data },
                "created": false
            }
        400: Missing required field
            {
                "success": false,
                "error": "hardware_id is required"
            }
        503: Hub not registered
            {
                "success": false,
                "error": "Hub not registered with CMS"
            }
    """
    # Check if hub is registered before accepting device registrations
    hub_config = HubConfig.get_instance()
    if not hub_config.is_registered:
        return jsonify({
            'success': False,
            'error': 'Hub not registered with CMS'
        }), 503

    data = request.get_json()

    if not data:
        return jsonify({
            'success': False,
            'error': 'Request body is required'
        }), 400

    hardware_id = data.get('hardware_id')
    if not hardware_id:
        return jsonify({
            'success': False,
            'error': 'hardware_id is required'
        }), 400

    # Validate hardware_id format (basic sanitization)
    if not isinstance(hardware_id, str) or len(hardware_id) > 100:
        return jsonify({
            'success': False,
            'error': 'hardware_id must be a string with max 100 characters'
        }), 400

    name = data.get('name')
    if name and (not isinstance(name, str) or len(name) > 200):
        return jsonify({
            'success': False,
            'error': 'name must be a string with max 200 characters'
        }), 400

    mode = data.get('mode', 'hub')
    if mode not in ('direct', 'hub'):
        return jsonify({
            'success': False,
            'error': 'mode must be "direct" or "hub"'
        }), 400

    # Register or get existing device
    device, created = Device.register(hardware_id, name, mode)

    if created:
        return jsonify({
            'success': True,
            'message': 'Device registered',
            'device': device.to_dict(),
            'created': True
        }), 201
    else:
        return jsonify({
            'success': True,
            'message': 'Device already registered',
            'device': device.to_dict(),
            'created': False
        }), 200


@devices_bp.route('/<int:device_id>', methods=['GET'])
def get_device(device_id):
    """
    Get details for a specific device.

    Args:
        device_id: Device ID from registration

    Returns:
        200: Device details
            {
                "success": true,
                "device": { device data }
            }
        404: Device not found
            {
                "success": false,
                "error": "Device not found"
            }
    """
    device = db.session.get(Device, device_id)

    if not device:
        return jsonify({
            'success': False,
            'error': 'Device not found'
        }), 404

    return jsonify({
        'success': True,
        'device': device.to_dict()
    }), 200


@devices_bp.route('/<int:device_id>/heartbeat', methods=['POST'])
def device_heartbeat(device_id):
    """
    Receive heartbeat from a device.

    Devices send heartbeats periodically to indicate they are
    online and functioning. This updates the device's last_heartbeat
    timestamp and sets status to 'online'.

    The hub batches these heartbeats and forwards them to the CMS
    periodically. When CMS is unreachable, heartbeats are queued.

    Args:
        device_id: Device ID from registration

    Request Body (optional):
        {
            "status": "playing|idle|error",
            "current_content_id": "content-123",
            "error_message": "optional error details"
        }

    Returns:
        200: Heartbeat acknowledged
            {
                "success": true,
                "message": "Heartbeat received",
                "timestamp": "2024-01-15T12:00:00Z"
            }
        404: Device not found
            {
                "success": false,
                "error": "Device not found"
            }
    """
    device = db.session.get(Device, device_id)

    if not device:
        return jsonify({
            'success': False,
            'error': 'Device not found'
        }), 404

    # Update heartbeat timestamp and status
    device.update_heartbeat()

    return jsonify({
        'success': True,
        'message': 'Heartbeat received',
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }), 200


@devices_bp.route('', methods=['GET'])
def list_devices():
    """
    List all registered devices.

    Returns a list of all devices registered with this hub,
    including their current status.

    Query Parameters:
        status: Filter by status (online, offline, pending)

    Returns:
        200: List of devices
            {
                "success": true,
                "devices": [ { device data }, ... ],
                "count": 5
            }
    """
    status_filter = request.args.get('status')

    if status_filter == 'online':
        devices = Device.get_all_online()
    elif status_filter == 'pending':
        devices = Device.get_all_pending()
    elif status_filter == 'offline':
        devices = Device.query.filter_by(status='offline').all()
    else:
        devices = Device.query.all()

    return jsonify({
        'success': True,
        'devices': [device.to_dict() for device in devices],
        'count': len(devices)
    }), 200
