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

    ip_address = data.get('ip_address') or request.remote_addr
    # Reject loopback - device on Hub itself should not register as a screen
    if ip_address and ip_address.startswith('127.'):
        ip_address = None

    # Register or get existing device
    device, created = Device.register(hardware_id, name, mode, ip_address)

    # Forward registration to CMS so device appears there for approval
    if created and not device.cms_device_id:
        _forward_registration_to_cms(device)

    # Get cached locations for the response
    locations = _get_cached_locations()

    # Get hub URL from config
    from flask import current_app
    config = current_app.config.get('HUB_CONFIG')
    hub_url = f"http://{config.hub_ip if config else '10.10.10.1'}:{config.port if config else 5000}"

    response_data = {
        'success': True,
        'created': created,
        'message': 'Device registered' if created else 'Device already registered',
        'device_id': device.device_id or f"pending-{device.id}",
        'pairing_code': device.pairing_code,
        'status': device.status,
        'hub_url': hub_url,
        'locations': locations
    }

    return jsonify(response_data), 201 if created else 200


def _forward_registration_to_cms(device):
    """
    Forward device registration to CMS so it appears there for approval.

    The CMS is the central authority - admins approve devices there,
    not on individual Hubs.
    """
    import logging
    import requests
    from flask import current_app

    logger = logging.getLogger(__name__)

    hub_config = HubConfig.get_instance()
    if not hub_config or not hub_config.is_registered:
        logger.warning("Hub not registered with CMS, skipping device forward")
        return

    config = current_app.config.get('HUB_CONFIG')
    if not config or not config.cms_url:
        logger.warning("No CMS URL configured, skipping device forward")
        return

    cms_url = config.cms_url.rstrip('/')
    endpoint = f"{cms_url}/api/v1/devices/register-from-hub"

    payload = {
        'hardware_id': device.hardware_id,
        'name': device.name,
        'pairing_code': device.pairing_code,
        'ip_address': device.ip_address,
        'hub_id': hub_config.hub_id,
        'hub_code': hub_config.hub_code,
        'mode': 'hub'
    }

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {hub_config.hub_token}' if hub_config.hub_token else ''
    }

    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        if response.ok:
            data = response.json()
            # Store the CMS device ID for future reference
            if data.get('device_id'):
                device.cms_device_id = data['device_id']
                db.session.commit()
            logger.info(f"Device {device.hardware_id} forwarded to CMS: {data.get('device_id')}")
        else:
            logger.warning(f"CMS device forward failed: {response.status_code} - {response.text[:200]}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to forward device to CMS: {e}")


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


@devices_bp.route('/<int:device_id>', methods=['DELETE'])
def delete_device(device_id):
    """
    Delete a device from the hub.

    Use this when swapping out hardware for repairs. The device
    is removed from the local hub database and the deletion is
    forwarded to the CMS.

    Args:
        device_id: Device ID (local database ID)

    Returns:
        200: Device deleted
            {
                "success": true,
                "message": "Device deleted",
                "device_id": "SKZ-H-XXX-0001"
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

    device_id_str = device.device_id
    hardware_id = device.hardware_id
    cms_device_id = device.cms_device_id

    # Forward deletion to CMS if we have a CMS device ID
    if cms_device_id:
        _forward_deletion_to_cms(cms_device_id)

    # Delete from local database
    db.session.delete(device)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Device deleted',
        'device_id': device_id_str,
        'hardware_id': hardware_id
    }), 200


@devices_bp.route('/by-hardware/<hardware_id>', methods=['DELETE'])
def delete_device_by_hardware_id(hardware_id):
    """
    Delete a device by its hardware ID.

    Alternative to delete by database ID - useful when you know
    the Jetson's hardware ID but not the local database ID.

    Args:
        hardware_id: The device's hardware ID

    Returns:
        200: Device deleted
        404: Device not found
    """
    device = Device.get_by_hardware_id(hardware_id)

    if not device:
        return jsonify({
            'success': False,
            'error': 'Device not found'
        }), 404

    device_id_str = device.device_id
    cms_device_id = device.cms_device_id

    # Forward deletion to CMS if we have a CMS device ID
    if cms_device_id:
        _forward_deletion_to_cms(cms_device_id)

    # Delete from local database
    db.session.delete(device)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Device deleted',
        'device_id': device_id_str,
        'hardware_id': hardware_id
    }), 200


def _forward_deletion_to_cms(cms_device_id):
    """
    Forward device deletion to the CMS.

    Args:
        cms_device_id: The device's UUID on the CMS
    """
    import logging
    import requests
    from flask import current_app

    logger = logging.getLogger(__name__)

    hub_config = HubConfig.get_instance()
    if not hub_config or not hub_config.is_registered:
        logger.warning("Hub not registered, skipping CMS deletion forward")
        return

    config = current_app.config.get('HUB_CONFIG')
    if not config or not config.cms_url:
        logger.warning("No CMS URL configured, skipping deletion forward")
        return

    endpoint = f"{config.cms_url.rstrip('/')}/api/v1/devices/{cms_device_id}"
    headers = {
        'Authorization': f'Bearer {hub_config.hub_token}'
    }

    try:
        response = requests.delete(endpoint, headers=headers, timeout=30)
        if response.ok:
            logger.info(f"Device {cms_device_id} deleted from CMS")
        else:
            logger.warning(f"CMS deletion failed: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Failed to forward deletion to CMS: {e}")


def _get_cached_locations():
    """
    Get cached locations for the registration response.

    Returns:
        list: List of location dicts [{"id": "...", "name": "..."}]
    """
    import json
    import os
    from flask import current_app

    storage_path = current_app.config.get('STORAGE_PATH', '/home/skillz/skillz-hub/storage')
    data_path = os.path.join(os.path.dirname(storage_path), 'data')
    cache_path = os.path.join(data_path, 'locations.json')

    if not os.path.exists(cache_path):
        return []

    try:
        with open(cache_path, 'r') as f:
            data = json.load(f)
            return data.get('locations', [])
    except (json.JSONDecodeError, IOError):
        return []


@devices_bp.route('/by-hardware/<hardware_id>/location', methods=['PUT'])
def update_device_location(hardware_id):
    """
    Update a device's screen location.

    Called by the Jetson when the installer selects a location from the
    dropdown on the pairing screen.

    Args:
        hardware_id: The device's hardware ID

    Request Body:
        {
            "location_id": "uuid (optional)",
            "location_name": "Fishing Counter"
        }

    Returns:
        200: Location updated
            {
                "success": true,
                "message": "Location updated",
                "location_name": "Fishing Counter"
            }
        404: Device not found
    """
    device = Device.get_by_hardware_id(hardware_id)

    if not device:
        return jsonify({
            'success': False,
            'error': 'Device not found'
        }), 404

    data = request.get_json() or {}
    location_name = data.get('location_name') or data.get('location')
    location_id = data.get('location_id')

    # If only location_id provided, look up the name
    if not location_name and location_id:
        location_name = _get_location_name_by_id(location_id)

    if not location_name:
        return jsonify({
            'success': False,
            'error': 'location_name or location_id is required'
        }), 400

    # Update device location
    device.location = location_name
    db.session.commit()

    # Forward location update to CMS
    _forward_location_to_cms(device, location_name, location_id)

    return jsonify({
        'success': True,
        'message': 'Location updated',
        'location_name': location_name
    }), 200


def _forward_location_to_cms(device, location_name, location_id=None):
    """
    Forward device location update to the CMS.

    Args:
        device: Device model instance
        location_name: Selected location name
        location_id: Optional location UUID
    """
    import logging
    import requests
    from flask import current_app

    logger = logging.getLogger(__name__)

    if not device.cms_device_id:
        logger.warning(f"Device {device.hardware_id} has no CMS ID, skipping location forward")
        return

    hub_config = HubConfig.get_instance()
    if not hub_config or not hub_config.is_registered:
        logger.warning("Hub not registered, skipping CMS location forward")
        return

    config = current_app.config.get('HUB_CONFIG')
    if not config or not config.cms_url:
        logger.warning("No CMS URL configured, skipping location forward")
        return

    endpoint = f"{config.cms_url.rstrip('/')}/api/v1/devices/{device.cms_device_id}/location"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {hub_config.hub_token}'
    }
    payload = {
        'screen_location': location_name,
        'location_id': location_id
    }

    try:
        response = requests.put(endpoint, json=payload, headers=headers, timeout=30)
        if response.ok:
            logger.info(f"Device {device.hardware_id} location forwarded to CMS: {location_name}")
        else:
            logger.warning(f"CMS location update failed: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Failed to forward location to CMS: {e}")


def _get_location_name_by_id(location_id):
    """Look up location name by ID from cached locations or defaults."""
    import json
    import os
    from flask import current_app

    # Default store zones
    default_zones = [
        {"id": "entrance", "name": "Entrance"},
        {"id": "checkout1", "name": "Checkout 1"},
        {"id": "checkout2", "name": "Checkout 2"},
        {"id": "checkout3", "name": "Checkout 3"},
        {"id": "register1", "name": "Register 1"},
        {"id": "register2", "name": "Register 2"},
        {"id": "register3", "name": "Register 3"},
        {"id": "aisle1", "name": "Aisle 1"},
        {"id": "aisle2", "name": "Aisle 2"},
        {"id": "cooler", "name": "Cooler"},
        {"id": "backwall", "name": "Back Wall"},
    ]

    # Try to load from cached locations
    storage_path = current_app.config.get('STORAGE_PATH', '/home/skillz/skillz-hub/storage')
    data_path = os.path.join(os.path.dirname(storage_path), 'data')
    cache_path = os.path.join(data_path, 'locations.json')

    locations = default_zones
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r') as f:
                data = json.load(f)
                locations = data.get('locations', default_zones)
        except (json.JSONDecodeError, IOError):
            pass

    # Find location by ID
    for loc in locations:
        if loc.get('id') == location_id:
            return loc.get('name')

    # If ID not found, return the ID itself as the name
    return location_id


# ============================================================================
# Sync endpoints
# ============================================================================

@devices_bp.route('/sync/trigger', methods=['POST'])
def trigger_sync():
    """
    Trigger a sync with the CMS.

    Initiates content and device sync from CMS to Hub.

    Returns:
        200: Sync triggered successfully
        500: Sync failed
    """
    import logging
    logger = logging.getLogger(__name__)

    hub_config = HubConfig.get_instance()
    if not hub_config or not hub_config.is_registered:
        return jsonify({
            'success': False,
            'error': 'Hub not registered with CMS'
        }), 503

    try:
        # Try to trigger the sync service
        from flask import current_app
        sync_service = current_app.config.get('SYNC_SERVICE')

        if sync_service and hasattr(sync_service, 'sync_now'):
            sync_service.sync_now()
            return jsonify({
                'success': True,
                'message': 'Sync triggered successfully'
            }), 200

        # Fallback: manual sync
        config = current_app.config.get('HUB_CONFIG')
        if not config or not config.cms_url:
            return jsonify({
                'success': False,
                'error': 'No CMS URL configured'
            }), 500

        # Sync devices from CMS
        _sync_devices_from_cms(config, hub_config)

        return jsonify({
            'success': True,
            'message': 'Manual sync completed'
        }), 200

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def _sync_devices_from_cms(config, hub_config):
    """Sync device data from CMS."""
    import logging
    import requests

    logger = logging.getLogger(__name__)

    cms_url = config.cms_url.rstrip('/')
    endpoint = f"{cms_url}/api/v1/devices"
    headers = {
        'Authorization': f'Bearer {hub_config.hub_token}' if hub_config.hub_token else ''
    }
    params = {'hub_id': hub_config.hub_id}

    try:
        response = requests.get(endpoint, headers=headers, params=params, timeout=30)
        if response.ok:
            data = response.json()
            devices = data.get('devices', [])

            # Update local devices with CMS data
            for cms_device in devices:
                hardware_id = cms_device.get('hardware_id')
                if hardware_id:
                    Device.update_from_cms(hardware_id, cms_device)

            logger.info(f"Synced {len(devices)} devices from CMS")
        else:
            logger.warning(f"Failed to sync devices from CMS: {response.status_code}")
    except Exception as e:
        logger.error(f"Error syncing devices from CMS: {e}")


# ============================================================================
# CMS Push endpoints - Called by CMS to push updates to Hub
# ============================================================================

@devices_bp.route('/update-from-cms', methods=['POST'])
def update_from_cms():
    """
    Receive device update from CMS.

    Called by CMS when admin updates a device's screen_location or name.
    The Hub updates its local record and optionally pushes to the Jetson.

    Request Body:
        {
            "device_id": "uuid-from-cms",
            "hardware_id": "jetson-hardware-id" (alternative lookup),
            "screen_location": "Entrance",
            "name": "Front Door Screen"
        }

    Returns:
        200: Update received
        404: Device not found
    """
    import logging
    logger = logging.getLogger(__name__)

    data = request.get_json() or {}
    device_id = data.get('device_id')
    hardware_id = data.get('hardware_id')
    screen_location = data.get('screen_location')
    name = data.get('name')

    if not device_id and not hardware_id:
        return jsonify({
            'success': False,
            'error': 'device_id or hardware_id is required'
        }), 400

    # Find device by CMS device_id first, then hardware_id
    device = None
    if device_id:
        device = Device.query.filter_by(cms_device_id=device_id).first()
    if not device and hardware_id:
        device = Device.get_by_hardware_id(hardware_id)

    if not device:
        return jsonify({
            'success': False,
            'error': 'Device not found'
        }), 404

    # Update device fields
    if screen_location is not None:
        device.location = screen_location
        logger.info(f"Updated device {device.hardware_id} location to: {screen_location}")

    if name is not None:
        device.name = name
        logger.info(f"Updated device {device.hardware_id} name to: {name}")

    device.synced_at = datetime.utcnow()
    db.session.commit()

    # Push update to Jetson device if it's online
    if device.ip_address and device.status == 'online':
        _push_update_to_device(device, data)

    return jsonify({
        'success': True,
        'message': 'Device updated',
        'device': device.to_dict()
    }), 200


def _push_update_to_device(device, update_data):
    """
    Push update to the Jetson device.

    Args:
        device: Device model instance
        update_data: Dict with fields to push
    """
    import logging
    import requests

    logger = logging.getLogger(__name__)

    if not device.ip_address:
        logger.warning(f"Device {device.hardware_id} has no IP address, skipping push")
        return

    # Jetson player listens on port 8080
    jetson_url = f"http://{device.ip_address}:8080"

    try:
        response = requests.post(
            f"{jetson_url}/api/v1/config/update",
            json={
                'screen_location': update_data.get('screen_location'),
                'name': update_data.get('name'),
            },
            timeout=5
        )

        if response.ok:
            logger.info(f"Pushed update to device {device.hardware_id}")
        else:
            logger.warning(f"Device {device.hardware_id} returned {response.status_code}")
    except requests.Timeout:
        logger.warning(f"Timeout pushing to device {device.hardware_id}")
    except requests.RequestException as e:
        logger.error(f"Failed to push to device {device.hardware_id}: {e}")
