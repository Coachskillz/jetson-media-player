import random
"""
CMS Devices Routes

Blueprint for device management API endpoints:
- POST /register: Register a new device (direct or hub mode)
- POST /pair: Pair device with a network
- GET /<id>/config: Get device configuration
- GET /<id>/connection-config: Get connection mode settings for device polling
- PUT /<id>/connection-config: Update connection mode settings from UI
- GET /: List all devices
- POST /pairing/request: Store device pairing code for pairing workflow
- GET /pairing/status/<hardware_id>: Check device pairing status
- GET /<hardware_id>/playlist: Get playlist items for a device (no auth)

All endpoints are prefixed with /api/v1/devices when registered with the app.
"""

from datetime import datetime, timezone
from flask import Blueprint, request, jsonify

from cms.models import db, Device, Hub, Network, DeviceAssignment, Playlist
from cms.models.playlist import PlaylistItem
from cms.models.layout import ScreenLayout, ScreenLayer, LayerContent, LayerPlaylistAssignment, DeviceLayout
from cms.utils.auth import login_required
from cms.utils.audit import log_action
from cms.models.device_assignment import TRIGGER_TYPES
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
        # Update IP address and last_seen on each registration
        new_ip = data.get('ip_address')
        if new_ip and new_ip != existing_device.ip_address:
            existing_device.ip_address = new_ip
        existing_device.last_seen = datetime.now(timezone.utc)
        try:
            db.session.commit()
        except:
            db.session.rollback()
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
        status='pending',
        pairing_code=data.get('pairing_code'),
        ip_address=data.get('ip_address')
    )

    try:
        db.session.add(device)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create device: {str(e)}'
        }), 500

    # Log device registration (device-initiated action)
    log_action(
        action='device.register',
        action_category='devices',
        resource_type='device',
        resource_id=device.id,
        resource_name=device.device_id,
        user_email='device',
        details={
            'hardware_id': hardware_id,
            'mode': mode,
            'hub_id': hub_id,
        }
    )

    return jsonify(device.to_dict()), 201


# Store active pairing codes: {pairing_code: hardware_id}
_active_pairing_codes = {}


@devices_bp.route('/pairing/request', methods=['POST'])
def request_pairing_code():
    """
    Request a pairing code for a device.

    The device calls this endpoint to get a 6-digit pairing code that
    the user can enter in the CMS web interface to pair the device.

    Request Body:
        {
            "hardware_id": "unique-hardware-id" (required)
        }

    Returns:
        200: Pairing code generated
            {
                "pairing_code": "123456",
                "hardware_id": "unique-hardware-id",
                "expires_in": 300
            }
        400: Missing required field
            {
                "error": "error message"
            }
    """
    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    hardware_id = data.get('hardware_id')
    if not hardware_id:
        return jsonify({'error': 'hardware_id is required'}), 400

    # Generate 6-digit pairing code
    pairing_code = str(random.randint(100000, 999999))

    # Store the pairing code mapping
    _active_pairing_codes[pairing_code] = {
        'hardware_id': hardware_id,
        'created_at': datetime.now(timezone.utc)
    }

    # Also register the device if not already registered
    existing_device = Device.query.filter_by(hardware_id=hardware_id).first()
    if not existing_device:
        # Create a new device in pending status
        device_id = DeviceIDGenerator.generate_direct_id(db.session)
        ip_address = data.get('ip_address')

        device = Device(
            hardware_id=hardware_id,
            device_id=device_id,
            mode='direct',
            status='pending',
            ip_address=ip_address
        )
        db.session.add(device)
        db.session.commit()
    else:
        # Update IP address if provided
        ip_address = data.get('ip_address')
        if ip_address:
            existing_device.ip_address = ip_address
            db.session.commit()

    return jsonify({
        'pairing_code': pairing_code,
        'hardware_id': hardware_id,
        'expires_in': 300
    }), 200


@devices_bp.route('/pairing/status/<hardware_id>', methods=['GET'])
def check_pairing_status(hardware_id):
    """
    Check if a device has been paired.

    The device polls this endpoint to check if the pairing code has been
    entered in the CMS web interface and the device has been paired.

    Args:
        hardware_id: The device's unique hardware ID

    Returns:
        200: Device status
            {
                "paired": true/false,
                "device_id": "SKZ-D-0001" (if paired),
                "network_id": "uuid" (if paired),
                "status": "pending" | "active"
            }
        404: Device not found
            {
                "error": "Device not found"
            }
    """
    device = Device.query.filter_by(hardware_id=hardware_id).first()

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    return jsonify({
        'paired': device.network_id is not None,
        'device_id': device.device_id,
        'network_id': device.network_id,
        'status': device.status
    }), 200


@devices_bp.route('/pairing/verify', methods=['POST'])
def verify_pairing_code():
    """
    Verify a pairing code and pair the device to a network.

    Called from the CMS web interface when a user enters a pairing code.

    Request Body:
        {
            "pairing_code": "123456" (required),
            "network_id": "uuid" (required)
        }

    Returns:
        200: Device paired successfully
            {
                "message": "Device paired successfully",
                "device": { device data },
                "network": { network data }
            }
        400: Invalid pairing code or missing fields
            {
                "error": "error message"
            }
        404: Network not found
            {
                "error": "error message"
            }
    """
    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    pairing_code = data.get('pairing_code')
    network_id = data.get('network_id')

    if not pairing_code:
        return jsonify({'error': 'pairing_code is required'}), 400
    if not network_id:
        return jsonify({'error': 'network_id is required'}), 400

    # Look up the pairing code
    pairing_info = _active_pairing_codes.get(pairing_code)
    if not pairing_info:
        return jsonify({'error': 'Invalid or expired pairing code'}), 400

    hardware_id = pairing_info['hardware_id']

    # Find the device
    device = Device.query.filter_by(hardware_id=hardware_id).first()
    if not device:
        return jsonify({'error': 'Device not found'}), 404

    # Find the network
    network = db.session.get(Network, network_id)
    if not network:
        return jsonify({'error': f'Network with id {network_id} not found'}), 404

    # Pair the device
    device.network_id = network_id
    device.status = 'active'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to pair device: {str(e)}'}), 500

    # Remove the used pairing code
    del _active_pairing_codes[pairing_code]

    # Log the pairing action
    log_action(
        action='device.pair',
        action_category='devices',
        resource_type='device',
        resource_id=device.id,
        resource_name=device.device_id,
        details={
            'network_id': network_id,
            'network_name': network.name,
            'pairing_code': pairing_code,
        }
    )

    return jsonify({
        'message': 'Device paired successfully',
        'device': device.to_dict(),
        'network': network.to_dict()
    }), 200


@devices_bp.route('/pair', methods=['POST'])
@login_required
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

    # Store previous network for logging
    previous_network_id = device.network_id

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

    # Log the pairing action
    log_action(
        action='device.pair',
        action_category='devices',
        resource_type='device',
        resource_id=device.id,
        resource_name=device.device_id,
        details={
            'network_id': network_id,
            'network_name': network.name,
            'previous_network_id': previous_network_id,
        }
    )

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
@login_required
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


@devices_bp.route('/<device_id>', methods=['GET'])
@login_required
def get_device(device_id):
    """
    Get a single device by ID.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Returns:
        200: Device details with assignments
        404: Device not found
    """
    # Try to find device by device_id (SKZ format) first, then by UUID
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    # Get device data with relationships
    device_data = device.to_dict()

    # Add hub info
    if device.hub:
        device_data['hub'] = {
            'id': device.hub.id,
            'code': device.hub.code,
            'name': device.hub.name
        }

    # Add network info
    if device.network:
        device_data['network'] = {
            'id': device.network.id,
            'name': device.network.name
        }

    # Add playlist assignments with trigger info
    assignments = DeviceAssignment.query.filter_by(device_id=device.id).all()
    device_data['playlists'] = []
    for assignment in assignments:
        if assignment.playlist:
            device_data['playlists'].append({
                'assignment_id': assignment.id,
                'playlist_id': assignment.playlist.id,
                'playlist_name': assignment.playlist.name,
                'trigger_type': assignment.trigger_type,
                'priority': assignment.priority,
                'start_date': assignment.start_date.isoformat() if assignment.start_date else None,
                'end_date': assignment.end_date.isoformat() if assignment.end_date else None
            })

    return jsonify(device_data), 200


@devices_bp.route('/<device_id>/settings', methods=['PATCH'])
@login_required
def update_device_settings(device_id):
    """
    Update device settings (camera configuration).

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Request Body:
        {
            "name": "optional new name",
            "camera1_enabled": true,
            "camera1_demographics": true,
            "camera1_age": true,
            "camera1_gender": true,
            "camera1_loyalty": false,
            "camera2_enabled": true,
            "camera2_ncmec": true
        }

    Returns:
        200: Updated device
        404: Device not found
        400: Invalid data
    """
    # Try to find device by device_id (SKZ format) first, then by UUID
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Update allowed fields
    allowed_fields = [
        'name',
        'camera1_enabled',
        'camera1_demographics',
        'camera1_age',
        'camera1_gender',
        'camera1_loyalty',
        'camera2_enabled',
        'camera2_ncmec',
        'layout_id'
    ]

    # Track changes for logging
    changes = {}

    for field in allowed_fields:
        if field in data:
            old_value = getattr(device, field, None)
            new_value = data[field]
            if old_value != new_value:
                changes[field] = {
                    'old_value': old_value,
                    'new_value': new_value
                }
                setattr(device, field, new_value)

    if not changes:
        return jsonify({'error': 'No valid fields to update'}), 400

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update device settings: {str(e)}'
        }), 500

    # Log the changes
    log_action(
        action='device.settings_update',
        action_category='devices',
        resource_type='device',
        resource_id=device.id,
        resource_name=device.device_id,
        details={
            'changes': changes
        }
    )

    return jsonify(device.to_dict()), 200


@devices_bp.route('/<device_id>/push-layout', methods=['POST'])
@login_required
def push_layout_to_device(device_id):
    """
    Push a layout to a device.

    This marks the device as needing a layout update. The device will
    fetch the new layout on its next sync.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Request Body:
        {
            "layout_id": "uuid of the layout"
        }

    Returns:
        200: Layout push initiated
        404: Device not found
        400: Invalid data
    """
    # Try to find device by device_id (SKZ format) first, then by UUID
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    data = request.get_json(silent=True)
    if not data or 'layout_id' not in data:
        return jsonify({'error': 'layout_id is required'}), 400

    layout_id = data['layout_id']

    # Verify layout exists
    from cms.models.layout import ScreenLayout
    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Update device layout
    device.layout_id = layout_id

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to push layout: {str(e)}'}), 500

    # Log the action
    log_action(
        action='device.layout_push',
        action_category='devices',
        resource_type='device',
        resource_id=device.id,
        resource_name=device.device_id,
        details={
            'layout_id': layout_id,
            'layout_name': layout.name
        }
    )

    return jsonify({
        'message': 'Layout pushed successfully',
        'device_id': device.device_id,
        'layout_id': layout_id,
        'layout_name': layout.name
    }), 200


@devices_bp.route('/<device_id>/playlists', methods=['POST'])
@login_required
def assign_playlist_to_device(device_id):
    """
    Assign a playlist to a device with a specific trigger type.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Request Body:
        {
            "playlist_id": "uuid of the playlist",
            "trigger_type": "default|face_detected|age_*|gender_*|loyalty_recognized|ncmec_alert"
        }

    Returns:
        201: Assignment created
        404: Device or playlist not found
        400: Invalid data or duplicate assignment
    """
    from cms.models import DeviceAssignment, Playlist

    # Try to find device by device_id (SKZ format) first, then by UUID
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    playlist_id = data.get('playlist_id')
    trigger_type = data.get('trigger_type', 'default')

    if not playlist_id:
        return jsonify({'error': 'playlist_id is required'}), 400

    # Verify playlist exists
    playlist = db.session.get(Playlist, playlist_id)
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    # Check for duplicate assignment (same device + trigger type)
    existing = DeviceAssignment.query.filter_by(
        device_id=device.id,
        trigger_type=trigger_type
    ).first()

    if existing:
        return jsonify({'error': f'A playlist is already assigned to trigger "{trigger_type}"'}), 400

    # Create assignment
    # Default trigger is always enabled, others default to disabled
    is_enabled = (trigger_type == 'default')

    assignment = DeviceAssignment(
        device_id=device.id,
        playlist_id=playlist_id,
        trigger_type=trigger_type,
        is_enabled=is_enabled
    )

    db.session.add(assignment)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to create assignment: {str(e)}'}), 500

    return jsonify({
        'message': 'Playlist assigned successfully',
        'assignment': assignment.to_dict()
    }), 201


@devices_bp.route('/<device_id>/playlists/<assignment_id>', methods=['DELETE'])
@login_required
def remove_playlist_from_device(device_id, assignment_id):
    """
    Remove a playlist assignment from a device.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)
        assignment_id: The assignment ID to delete

    Returns:
        200: Assignment deleted
        404: Device or assignment not found
    """
    from cms.models import DeviceAssignment

    # Try to find device by device_id (SKZ format) first, then by UUID
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    assignment = db.session.get(DeviceAssignment, assignment_id)
    if not assignment or assignment.device_id != device.id:
        return jsonify({'error': 'Assignment not found'}), 404

    db.session.delete(assignment)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete assignment: {str(e)}'}), 500

    return jsonify({'message': 'Playlist assignment removed'}), 200


@devices_bp.route('/<device_id>/playlists/<assignment_id>/toggle', methods=['PATCH'])
@login_required
def toggle_playlist_assignment(device_id, assignment_id):
    """
    Toggle a playlist assignment on/off for a device.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)
        assignment_id: The assignment ID to toggle

    Request Body (optional):
        {
            "is_enabled": true|false  // If not provided, toggles current state
        }

    Returns:
        200: Assignment toggled
        404: Device or assignment not found
    """
    from cms.models import DeviceAssignment

    # Try to find device by device_id (SKZ format) first, then by UUID
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    assignment = db.session.get(DeviceAssignment, assignment_id)
    if not assignment or assignment.device_id != device.id:
        return jsonify({'error': 'Assignment not found'}), 404

    data = request.get_json(silent=True)

    if data and 'is_enabled' in data:
        assignment.is_enabled = bool(data['is_enabled'])
    else:
        # Toggle current state
        assignment.is_enabled = not assignment.is_enabled

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to toggle assignment: {str(e)}'}), 500

    return jsonify({
        'message': f'Playlist {"enabled" if assignment.is_enabled else "disabled"}',
        'assignment_id': assignment.id,
        'is_enabled': assignment.is_enabled,
        'trigger_type': assignment.trigger_type
    }), 200


@devices_bp.route('/by-hardware/<hardware_id>', methods=['GET'])
def get_device_by_hardware(hardware_id):
    """
    Get device by hardware ID (no auth - called by Jetson player).

    Used by Jetson devices to check their pairing status.

    Args:
        hardware_id: The hardware ID of the device

    Returns:
        200: Device details
        404: Device not found
    """
    device = Device.query.filter_by(hardware_id=hardware_id).first()
    if not device:
        return jsonify({'error': 'Device not found'}), 404

    return jsonify(device.to_dict()), 200


@devices_bp.route('/<hardware_id>/playlist', methods=['GET'])
def get_device_playlist(hardware_id):
    """Get playlist for a device (no auth - called by Jetson player)."""
    device = Device.query.filter_by(hardware_id=hardware_id).first()
    if not device:
        device = Device.query.filter_by(device_id=hardware_id).first()
    if not device:
        return jsonify({'error': 'Device not found'}), 404
    if device.status != 'active':
        return jsonify({'device_id': getattr(device, 'device_id', ''), 'status': device.status, 'items': []}), 200
    items = []
    for assignment in device.assignments:
        # Only include enabled assignments
        if assignment.is_enabled and assignment.playlist:
            for item in assignment.playlist.items:
                if item.content:
                    items.append({'url': f"/api/v1/content/{item.content.id}/download", 'filename': item.content.filename, 'duration': item.duration_override or 10})
    return jsonify({'device_id': device.device_id, 'status': device.status, 'items': items}), 200


@devices_bp.route('/<device_id>/remote/command', methods=['POST'])
@login_required
def send_remote_command(device_id):
    """
    Send a remote command to a device.

    Forwards commands to the device's health server for execution.
    Commands include: minimize, maximize, restart, reboot, show_pairing

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Request Body:
        {
            "command": "minimize|maximize|restart|reboot|show_pairing"
        }

    Returns:
        200: Command sent successfully
        404: Device not found
        400: Invalid command
        502: Device unreachable
    """
    import requests as http_requests

    # Find device
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)
    if not device:
        return jsonify({'error': 'Device not found'}), 404

    data = request.get_json(silent=True)
    if not data or 'command' not in data:
        return jsonify({'error': 'command is required'}), 400

    command = data['command']
    valid_commands = ['minimize', 'maximize', 'restart', 'reboot', 'show_pairing', 'reset_pairing']
    if command not in valid_commands:
        return jsonify({'error': f'Invalid command. Valid: {valid_commands}'}), 400

    # Get device IP address
    device_ip = device.ip_address
    if not device_ip:
        return jsonify({'error': 'Device IP not available. Device may need to re-register.'}), 400

    # Send command to device health server
    try:
        response = http_requests.post(
            f'http://{device_ip}:8080/api/command/{command}',
            timeout=10
        )
        result = response.json()

        # Log the action
        log_action(
            action='device.remote_command',
            action_category='devices',
            resource_type='device',
            resource_id=device.id,
            resource_name=device.device_id,
            details={'command': command, 'result': result}
        )

        return jsonify({
            'message': f'Command {command} sent',
            'device_response': result
        }), 200

    except http_requests.exceptions.RequestException as e:
        return jsonify({'error': f'Device unreachable: {str(e)}'}), 502


@devices_bp.route('/<device_id>/remote/health', methods=['GET'])
@login_required
def get_device_health(device_id):
    """
    Get health status from a device.

    Fetches system stats from the device's health server.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Returns:
        200: Health data
        404: Device not found
        502: Device unreachable
    """
    import requests as http_requests

    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)
    if not device:
        return jsonify({'error': 'Device not found'}), 404

    # Get device IP address
    device_ip = device.ip_address
    if not device_ip:
        return jsonify({'error': 'Device IP not available'}), 400

    try:
        response = http_requests.get(
            f'http://{device_ip}:8080/api/system',
            timeout=10
        )
        return jsonify(response.json()), 200

    except http_requests.exceptions.RequestException as e:
        return jsonify({'error': f'Device unreachable: {str(e)}'}), 502


@devices_bp.route('/<device_id>/remote/logs', methods=['GET'])
@login_required
def get_device_logs(device_id):
    """
    Get logs from a device.

    Fetches recent log entries from the device.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Returns:
        200: Log entries
        404: Device not found
        502: Device unreachable
    """
    import requests as http_requests

    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)
    if not device:
        return jsonify({'error': 'Device not found'}), 404

    # Get device IP address
    device_ip = device.ip_address
    if not device_ip:
        return jsonify({'error': 'Device IP not available'}), 400

    try:
        response = http_requests.get(
            f'http://{device_ip}:8080/api/logs',
            timeout=10
        )
        return jsonify(response.json()), 200

    except http_requests.exceptions.RequestException as e:
        return jsonify({'error': f'Device unreachable: {str(e)}'}), 502


@devices_bp.route('/<hardware_id>/layout', methods=['GET'])
def get_device_layout(hardware_id):
    """
    Get layout configuration for a device (no auth - called by Jetson player).

    Returns the device's active layout with all layers, content sources,
    and playlist assignments for rendering on the device.

    Args:
        hardware_id: Device hardware ID or device_id

    Returns:
        200: Layout data with layers and content
            {
                "device_id": "SKZ-D-0001",
                "status": "active",
                "layout": {
                    "id": "uuid",
                    "name": "Main Layout",
                    "canvas_width": 1920,
                    "canvas_height": 1080,
                    "orientation": "landscape",
                    "background_type": "solid",
                    "background_color": "#000000",
                    "layers": [
                        {
                            "id": "uuid",
                            "name": "Video Zone",
                            "layer_type": "content",
                            "x": 0, "y": 0, "width": 1920, "height": 1080,
                            "z_index": 0,
                            "content_source": "playlist",
                            "playlist": {...},
                            "items": [...]
                        }
                    ]
                }
            }
        404: Device not found
    """
    import json

    # Find device by hardware_id or device_id
    device = Device.query.filter_by(hardware_id=hardware_id).first()
    if not device:
        device = Device.query.filter_by(device_id=hardware_id).first()
    if not device:
        return jsonify({'error': 'Device not found'}), 404

    # If device not active, return minimal response
    if device.status != 'active':
        return jsonify({
            'device_id': device.device_id,
            'status': device.status,
            'layout': None
        }), 200

    # Get the active layout for this device
    layout = None
    layout_data = None

    # First check device.layout_id (direct assignment)
    if device.layout_id:
        layout = db.session.get(ScreenLayout, device.layout_id)

    # If no direct assignment, check DeviceLayout assignments
    if not layout:
        device_layout = DeviceLayout.get_current_layout_for_device(device.id)
        if device_layout:
            layout = device_layout

    if not layout:
        return jsonify({
            'device_id': device.device_id,
            'status': device.status,
            'layout': None,
            'message': 'No layout assigned'
        }), 200

    # Build complete layout response
    layers_data = []
    for layer in layout.layers.order_by(ScreenLayer.z_index).all():
        if not layer.is_visible:
            continue

        layer_data = {
            'id': layer.id,
            'name': layer.name,
            'layer_type': layer.layer_type,
            'x': layer.x,
            'y': layer.y,
            'width': layer.width,
            'height': layer.height,
            'z_index': layer.z_index,
            'opacity': layer.opacity,
            'background_type': layer.background_type,
            'background_color': layer.background_color,
            'content_source': layer.content_source,
            'is_primary': layer.is_primary,
            'content_config': None,
            'playlist': None,
            'items': []
        }

        # Parse content_config if present
        if layer.content_config:
            try:
                layer_data['content_config'] = json.loads(layer.content_config)
            except (json.JSONDecodeError, TypeError):
                layer_data['content_config'] = layer.content_config

        # Get content based on source type
        if layer.content_source == 'playlist' and layer.playlist_id:
            # Get playlist and items
            playlist = layer.playlist
            if playlist:
                layer_data['playlist'] = {
                    'id': playlist.id,
                    'name': playlist.name
                }
                # Get playlist items with content
                for item in playlist.items:
                    if item.content:
                        layer_data['items'].append({
                            'id': item.id,
                            'content_id': item.content_id,
                            'url': f"/api/v1/content/{item.content.id}/download",
                            'filename': item.content.filename,
                            'content_type': item.content.mime_type,
                            'duration': item.duration_override or item.content.duration or 10,
                            'order': item.position
                        })

        elif layer.content_source == 'static' and layer.content_id:
            # Get static content assignment for this device
            content_assignment = LayerContent.get_for_device_layer(device.id, layer.id)
            if content_assignment:
                layer_data['content_mode'] = content_assignment.content_mode
                if content_assignment.content_mode == 'static':
                    layer_data['static_file_url'] = content_assignment.static_file_url
                    layer_data['static_file_id'] = content_assignment.static_file_id
                elif content_assignment.content_mode == 'ticker':
                    layer_data['ticker_items'] = content_assignment.ticker_items
                    layer_data['ticker_speed'] = content_assignment.ticker_speed
                    layer_data['ticker_direction'] = content_assignment.ticker_direction

        # Check for trigger-based playlist assignments
        playlist_assignments = LayerPlaylistAssignment.get_for_device_layer(device.id, layer.id)
        if playlist_assignments:
            layer_data['trigger_playlists'] = []
            for assignment in playlist_assignments:
                if assignment.playlist:
                    trigger_playlist = {
                        'id': assignment.id,
                        'playlist_id': assignment.playlist_id,
                        'playlist_name': assignment.playlist.name,
                        'trigger_type': assignment.trigger_type,
                        'priority': assignment.priority,
                        'items': []
                    }
                    for item in assignment.playlist.items:
                        if item.content:
                            trigger_playlist['items'].append({
                                'content_id': item.content_id,
                                'url': f"/api/v1/content/{item.content.id}/download",
                                'filename': item.content.filename,
                                'content_type': item.content.mime_type,
                                'duration': item.duration_override or item.content.duration or 10
                            })
                    layer_data['trigger_playlists'].append(trigger_playlist)

        layers_data.append(layer_data)

    layout_data = {
        'id': layout.id,
        'name': layout.name,
        'canvas_width': layout.canvas_width,
        'canvas_height': layout.canvas_height,
        'orientation': layout.orientation,
        'background_type': layout.background_type,
        'background_color': layout.background_color,
        'background_opacity': layout.background_opacity,
        'background_content': layout.background_content,
        'layers': layers_data
    }

    return jsonify({
        'device_id': device.device_id,
        'status': device.status,
        'layout': layout_data
    }), 200
