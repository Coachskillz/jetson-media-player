"""
CMS Devices Routes

Blueprint for device management API endpoints:
- POST /register: Register a new device (direct or hub mode)
- POST /pair: Pair device with a network
- GET /<id>/config: Get device configuration
- GET /: List all devices

All endpoints are prefixed with /api/v1/devices when registered with the app.
"""

from flask import Blueprint, request, jsonify

from cms.models import db, Device, Hub, Network, DeviceAssignment
from cms.services.device_id import DeviceIDGenerator


# Create devices blueprint
devices_bp = Blueprint('devices', __name__)


@devices_bp.route('/register', methods=['POST'])
def register_device():
    """
    Register a new device or return existing device.

    Devices call this endpoint to register with the CMS. Supports two modes:
    - Direct mode: Device connects directly to CMS (ID format: SKZ-D-XXXX)
    - Hub mode: Device connects through a hub (ID format: SKZ-H-{CODE}-XXXX)

    If a device with the given hardware_id already exists, returns the
    existing device without creating a duplicate.

    Request Body:
        {
            "hardware_id": "unique-hardware-id" (required),
            "mode": "direct" or "hub" (required),
            "hub_id": "uuid-of-hub" (required for hub mode),
            "name": "optional device name"
        }

    Returns:
        201: New device created
            {
                "id": "uuid",
                "device_id": "SKZ-D-0001",
                "hardware_id": "unique-hardware-id",
                "mode": "direct",
                "status": "pending",
                "created_at": "2024-01-15T10:00:00Z"
            }
        200: Existing device returned
            {
                "id": "uuid",
                "device_id": "SKZ-D-0001",
                ...
            }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
    """
    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate hardware_id
    hardware_id = data.get('hardware_id')
    if not hardware_id:
        return jsonify({'error': 'hardware_id is required'}), 400

    if not isinstance(hardware_id, str) or len(hardware_id) > 100:
        return jsonify({
            'error': 'hardware_id must be a string with max 100 characters'
        }), 400

    # Check if device already exists
    existing_device = Device.query.filter_by(hardware_id=hardware_id).first()
    if existing_device:
        return jsonify(existing_device.to_dict()), 200

    # Validate mode
    mode = data.get('mode')
    if not mode:
        return jsonify({'error': 'mode is required'}), 400

    if mode not in ('direct', 'hub'):
        return jsonify({
            'error': "mode must be 'direct' or 'hub'"
        }), 400

    # Validate name if provided
    name = data.get('name')
    if name and (not isinstance(name, str) or len(name) > 200):
        return jsonify({
            'error': 'name must be a string with max 200 characters'
        }), 400

    # Hub mode validation
    hub = None
    hub_id = None
    if mode == 'hub':
        hub_id = data.get('hub_id')
        if not hub_id:
            return jsonify({
                'error': 'hub_id is required for hub mode'
            }), 400

        hub = db.session.get(Hub, hub_id)
        if not hub:
            return jsonify({
                'error': f'Hub with id {hub_id} not found'
            }), 400

    # Generate device ID based on mode
    try:
        if mode == 'direct':
            device_id = DeviceIDGenerator.generate_direct_id(db.session)
        else:
            # Hub mode - use hub's code for the device ID
            device_id = DeviceIDGenerator.generate_hub_id_by_hub_id(
                hub_id, hub.code, db.session
            )
    except Exception as e:
        return jsonify({
            'error': f'Failed to generate device ID: {str(e)}'
        }), 500

    # Create new device
    device = Device(
        hardware_id=hardware_id,
        device_id=device_id,
        mode=mode,
        hub_id=hub_id,
        network_id=hub.network_id if hub else None,
        name=name,
        status='pending'
    )

    try:
        db.session.add(device)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create device: {str(e)}'
        }), 500

    return jsonify(device.to_dict()), 201


@devices_bp.route('/pair', methods=['POST'])
def pair_device():
    """
    Pair a device to a network.

    Links a registered device to a specific network, allowing it to receive
    content and playlists from that network.

    Request Body:
        {
            "device_id": "SKZ-D-0001" (required),
            "network_id": "uuid-of-network" (required)
        }

    Returns:
        200: Device paired successfully
            {
                "message": "Device paired successfully",
                "device": { device data },
                "network": { network data }
            }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
        404: Device or network not found
            {
                "error": "error message"
            }
    """
    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate device_id
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({'error': 'device_id is required'}), 400

    # Validate network_id
    network_id = data.get('network_id')
    if not network_id:
        return jsonify({'error': 'network_id is required'}), 400

    # Find device by device_id (the SKZ-X-XXXX format)
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        return jsonify({'error': f'Device with id {device_id} not found'}), 404

    # Find network
    network = db.session.get(Network, network_id)
    if not network:
        return jsonify({'error': f'Network with id {network_id} not found'}), 404

    # Pair device to network
    device.network_id = network_id
    device.status = 'active'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to pair device: {str(e)}'
        }), 500

    return jsonify({
        'message': 'Device paired successfully',
        'device': device.to_dict(),
        'network': network.to_dict()
    }), 200


@devices_bp.route('/<device_id>/config', methods=['GET'])
def get_device_config(device_id):
    """
    Get configuration for a specific device.

    Devices call this endpoint to retrieve their configuration including
    network info, hub info, and assigned playlists.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Returns:
        200: Device configuration
            {
                "device_id": "SKZ-D-0001",
                "network": { id, name } or null,
                "hub": { id, code, name } or null,
                "playlists": [ ... ],
                "config_version": 1
            }
        404: Device not found
            {
                "error": "Device not found"
            }
    """
    # Try to find device by device_id (SKZ format) first, then by UUID
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    # Get associated network
    network_data = None
    if device.network_id:
        network = db.session.get(Network, device.network_id)
        if network:
            network_data = {
                'id': network.id,
                'name': network.name
            }

    # Get associated hub
    hub_data = None
    if device.hub_id:
        hub = db.session.get(Hub, device.hub_id)
        if hub:
            hub_data = {
                'id': hub.id,
                'code': hub.code,
                'name': hub.name
            }

    # Get assigned playlists
    playlists = []
    assignments = DeviceAssignment.query.filter_by(device_id=device.id).all()
    for assignment in assignments:
        if assignment.playlist:
            playlists.append({
                'id': assignment.playlist.id,
                'name': assignment.playlist.name,
                'priority': assignment.priority,
                'start_date': assignment.start_date.isoformat() if assignment.start_date else None,
                'end_date': assignment.end_date.isoformat() if assignment.end_date else None
            })

    return jsonify({
        'device_id': device.device_id,
        'network': network_data,
        'hub': hub_data,
        'playlists': playlists,
        'config_version': 1
    }), 200


@devices_bp.route('', methods=['GET'])
def list_devices():
    """
    List all registered devices.

    Returns a list of all devices registered with the CMS,
    with optional filtering by status, mode, or network.

    Query Parameters:
        status: Filter by status (pending, active, offline)
        mode: Filter by mode (direct, hub)
        network_id: Filter by network UUID
        hub_id: Filter by hub UUID

    Returns:
        200: List of devices
            {
                "devices": [ { device data }, ... ],
                "count": 5
            }
    """
    # Build query with optional filters
    query = Device.query

    # Filter by status
    status_filter = request.args.get('status')
    if status_filter:
        query = query.filter_by(status=status_filter)

    # Filter by mode
    mode_filter = request.args.get('mode')
    if mode_filter:
        if mode_filter not in ('direct', 'hub'):
            return jsonify({
                'error': "mode must be 'direct' or 'hub'"
            }), 400
        query = query.filter_by(mode=mode_filter)

    # Filter by network
    network_id = request.args.get('network_id')
    if network_id:
        query = query.filter_by(network_id=network_id)

    # Filter by hub
    hub_id = request.args.get('hub_id')
    if hub_id:
        query = query.filter_by(hub_id=hub_id)

    # Execute query
    devices = query.order_by(Device.created_at.desc()).all()

    return jsonify({
        'devices': [device.to_dict() for device in devices],
        'count': len(devices)
    }), 200
