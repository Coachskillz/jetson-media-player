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

from flask import Blueprint, request, jsonify

from cms.models import db, Device, Hub, Network, DeviceAssignment, Playlist
from cms.models.playlist import PlaylistItem
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
        pairing_code=data.get('pairing_code')
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
        'camera1_loyalty',
        'camera2_enabled',
        'camera2_ncmec'
    ]

    # Track changes for audit log
    changes = {}

    for field in allowed_fields:
        if field in data:
            value = data[field]
            # Validate boolean fields
            if field.startswith('camera') and not isinstance(value, bool):
                return jsonify({
                    'error': f'{field} must be a boolean'
                }), 400
            # Validate name
            if field == 'name' and value is not None:
                if not isinstance(value, str) or len(value) > 200:
                    return jsonify({
                        'error': 'name must be a string with max 200 characters'
                    }), 400
            # Record the change
            old_value = getattr(device, field, None)
            if old_value != value:
                changes[field] = {'before': old_value, 'after': value}
            setattr(device, field, value)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update device: {str(e)}'
        }), 500

    # Log the settings update
    if changes:
        log_action(
            action='device.update_settings',
            action_category='devices',
            resource_type='device',
            resource_id=device.id,
            resource_name=device.device_id,
            details={'changes': changes}
        )

    return jsonify({
        'message': 'Device settings updated successfully',
        'device': device.to_dict()
    }), 200


@devices_bp.route('/<device_id>/playlists', methods=['POST'])
@login_required
def add_device_playlist(device_id):
    """
    Add a playlist assignment to a device with trigger type.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Request Body:
        {
            "playlist_id": "uuid-of-playlist" (required),
            "trigger_type": "default" (required, one of TRIGGER_TYPES),
            "priority": 0 (optional, default 0),
            "start_date": "2024-01-15T10:00:00Z" (optional),
            "end_date": "2024-01-20T18:00:00Z" (optional)
        }

    Returns:
        201: Assignment created
        400: Invalid data
        404: Device or playlist not found
        409: Assignment already exists for this trigger
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

    # Validate playlist_id
    playlist_id = data.get('playlist_id')
    if not playlist_id:
        return jsonify({'error': 'playlist_id is required'}), 400

    playlist = db.session.get(Playlist, playlist_id)
    if not playlist:
        return jsonify({'error': f'Playlist with id {playlist_id} not found'}), 404

    # Validate trigger_type
    trigger_type = data.get('trigger_type', 'default')
    if trigger_type not in TRIGGER_TYPES:
        return jsonify({
            'error': f'Invalid trigger_type. Must be one of: {", ".join(TRIGGER_TYPES)}'
        }), 400

    # Check if assignment already exists for this device and trigger
    existing = DeviceAssignment.query.filter_by(
        device_id=device.id,
        trigger_type=trigger_type
    ).first()

    if existing:
        return jsonify({
            'error': f'Assignment for trigger "{trigger_type}" already exists. Delete it first to assign a new playlist.'
        }), 409

    # Parse optional dates
    start_date = None
    end_date = None
    if data.get('start_date'):
        try:
            from datetime import datetime
            start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'error': 'Invalid start_date format. Use ISO 8601.'}), 400

    if data.get('end_date'):
        try:
            from datetime import datetime
            end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'error': 'Invalid end_date format. Use ISO 8601.'}), 400

    # Create assignment
    assignment = DeviceAssignment(
        device_id=device.id,
        playlist_id=playlist_id,
        trigger_type=trigger_type,
        priority=data.get('priority', 0),
        start_date=start_date,
        end_date=end_date
    )

    try:
        db.session.add(assignment)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create assignment: {str(e)}'
        }), 500

    # Log the playlist assignment
    log_action(
        action='device.assign_playlist',
        action_category='devices',
        resource_type='device',
        resource_id=device.id,
        resource_name=device.device_id,
        details={
            'assignment_id': assignment.id,
            'playlist_id': playlist_id,
            'playlist_name': playlist.name,
            'trigger_type': trigger_type,
            'priority': data.get('priority', 0),
        }
    )

    return jsonify({
        'message': 'Playlist assigned successfully',
        'assignment': assignment.to_dict()
    }), 201




@devices_bp.route('/<device_id>/layout', methods=['PATCH'])
@login_required
def update_device_layout(device_id):
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)
    if not device:
        return jsonify({'error': 'Device not found'}), 404
    data = request.get_json() or {}
    layout_id = data.get('layout_id')
    device.layout_id = layout_id
    try:
        db.session.commit()
        return jsonify({'success': True, 'layout_id': device.layout_id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@devices_bp.route('/<device_id>/playlists/<assignment_id>/toggle', methods=['PATCH'])
@login_required
def toggle_device_playlist(device_id, assignment_id):
    """Toggle a playlist assignment on/off."""
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)
    if not device:
        return jsonify({'error': 'Device not found'}), 404

    assignment = DeviceAssignment.query.filter_by(
        id=assignment_id,
        device_id=device.id
    ).first()
    if not assignment:
        return jsonify({'error': 'Assignment not found'}), 404

    data = request.get_json() or {}
    is_enabled = data.get('is_enabled', True)
    assignment.is_enabled = is_enabled

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Playlist {"enabled" if is_enabled else "disabled"}',
            'assignment_id': assignment.id,
            'is_enabled': is_enabled
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@devices_bp.route('/<device_id>/playlists/<assignment_id>', methods=['DELETE'])
@login_required
def remove_device_playlist(device_id, assignment_id):
    """
    Remove a playlist assignment from a device.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)
        assignment_id: Assignment ID (UUID)

    Returns:
        200: Assignment deleted
        404: Device or assignment not found
    """
    # Try to find device by device_id (SKZ format) first, then by UUID
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    # Find assignment
    assignment = DeviceAssignment.query.filter_by(
        id=assignment_id,
        device_id=device.id
    ).first()

    if not assignment:
        return jsonify({'error': 'Assignment not found'}), 404

    # Store info for audit log before deleting
    playlist_id = assignment.playlist_id
    playlist_name = assignment.playlist.name if assignment.playlist else None
    trigger_type = assignment.trigger_type

    try:
        db.session.delete(assignment)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to delete assignment: {str(e)}'
        }), 500

    # Log the removal
    log_action(
        action='device.unassign_playlist',
        action_category='devices',
        resource_type='device',
        resource_id=device.id,
        resource_name=device.device_id,
        details={
            'assignment_id': assignment_id,
            'playlist_id': playlist_id,
            'playlist_name': playlist_name,
            'trigger_type': trigger_type,
        }
    )

    return jsonify({
        'message': 'Playlist assignment removed successfully'
    }), 200


@devices_bp.route('/<device_id>/connection-config', methods=['GET'])
def get_connection_config(device_id):
    """
    Get connection configuration for a specific device.

    Devices call this endpoint to retrieve their connection settings
    including connection mode and URLs for hub/CMS connections.
    This endpoint is polled by devices to detect configuration changes.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Returns:
        200: Connection configuration
            {
                "connection_mode": "direct" or "hub",
                "hub_url": "http://localhost:5000",
                "cms_url": "http://localhost:5002",
                "hub": { id, code, name } or null
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

    # Get hub info if available
    hub_data = None
    if device.hub:
        hub_data = {
            'id': device.hub.id,
            'code': device.hub.code,
            'name': device.hub.name
        }

    return jsonify({
        'connection_mode': device.connection_mode,
        'hub_url': device.hub_url or 'http://localhost:5000',
        'cms_url': device.cms_url or 'http://localhost:5002',
        'hub': hub_data
    }), 200


@devices_bp.route('/<device_id>/connection-config', methods=['PUT'])
@login_required
def update_connection_config(device_id):
    """
    Update connection configuration for a specific device.

    Allows the CMS UI to update the connection mode and URLs for a device.
    Changes take effect on the device's next sync/heartbeat cycle.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Request Body:
        {
            "connection_mode": "direct" or "hub" (optional),
            "hub_url": "http://192.168.1.100:5000" (optional),
            "cms_url": "http://cms.example.com:5002" (optional)
        }

    Returns:
        200: Connection configuration updated
            {
                "message": "Connection configuration updated successfully",
                "device": { device data }
            }
        400: Invalid data
            {
                "error": "error message"
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

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Track changes for audit log
    changes = {}

    # Validate and update connection_mode
    if 'connection_mode' in data:
        connection_mode = data['connection_mode']
        if connection_mode not in ('direct', 'hub'):
            return jsonify({
                'error': "connection_mode must be 'direct' or 'hub'"
            }), 400
        if device.connection_mode != connection_mode:
            changes['connection_mode'] = {
                'before': device.connection_mode,
                'after': connection_mode
            }
            device.connection_mode = connection_mode

    # Validate and update hub_url
    if 'hub_url' in data:
        hub_url = data['hub_url']
        if hub_url is not None:
            if not isinstance(hub_url, str) or len(hub_url) > 500:
                return jsonify({
                    'error': 'hub_url must be a string with max 500 characters'
                }), 400
            # Basic URL validation
            if hub_url and not (hub_url.startswith('http://') or hub_url.startswith('https://')):
                return jsonify({
                    'error': 'hub_url must start with http:// or https://'
                }), 400
        if device.hub_url != hub_url:
            changes['hub_url'] = {
                'before': device.hub_url,
                'after': hub_url
            }
            device.hub_url = hub_url

    # Validate and update cms_url
    if 'cms_url' in data:
        cms_url = data['cms_url']
        if cms_url is not None:
            if not isinstance(cms_url, str) or len(cms_url) > 500:
                return jsonify({
                    'error': 'cms_url must be a string with max 500 characters'
                }), 400
            # Basic URL validation
            if cms_url and not (cms_url.startswith('http://') or cms_url.startswith('https://')):
                return jsonify({
                    'error': 'cms_url must start with http:// or https://'
                }), 400
        if device.cms_url != cms_url:
            changes['cms_url'] = {
                'before': device.cms_url,
                'after': cms_url
            }
            device.cms_url = cms_url

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update connection configuration: {str(e)}'
        }), 500

    # Log the connection config update if there were changes
    if changes:
        log_action(
            action='device.update_connection_config',
            action_category='devices',
            resource_type='device',
            resource_id=device.id,
            resource_name=device.device_id,
            details={'changes': changes}
        )

    return jsonify({
        'message': 'Connection configuration updated successfully',
        'device': device.to_dict()
    }), 200


@devices_bp.route('/trigger-types', methods=['GET'])
@login_required
def get_trigger_types():
    """
    Get list of available trigger types for playlist assignments.

    Returns:
        200: List of trigger types with descriptions
    """
    trigger_info = [
        {'value': 'default', 'label': 'Default', 'description': 'Always plays (fallback content)'},
        {'value': 'face_detected', 'label': 'Face Detected', 'description': 'Plays when any face is detected'},
        {'value': 'age_child', 'label': 'Age: Child', 'description': 'Plays when child is detected (0-12)'},
        {'value': 'age_teen', 'label': 'Age: Teen', 'description': 'Plays when teen is detected (13-19)'},
        {'value': 'age_adult', 'label': 'Age: Adult', 'description': 'Plays when adult is detected (20-64)'},
        {'value': 'age_senior', 'label': 'Age: Senior', 'description': 'Plays when senior is detected (65+)'},
        {'value': 'gender_male', 'label': 'Gender: Male', 'description': 'Plays when male is detected'},
        {'value': 'gender_female', 'label': 'Gender: Female', 'description': 'Plays when female is detected'},
        {'value': 'loyalty_recognized', 'label': 'Loyalty Member', 'description': 'Plays when loyalty member is recognized'},
        {'value': 'ncmec_alert', 'label': 'NCMEC Alert', 'description': 'Plays during NCMEC alert (amber alert content)'},
    ]
    return jsonify({'trigger_types': trigger_info}), 200


@devices_bp.route('/pairing/request', methods=['POST'])
def request_pairing():
    """
    Request pairing for a device by storing its pairing code.

    Devices call this endpoint to initiate the pairing workflow. The device
    generates a 6-digit pairing code locally and sends it to the CMS. Users
    can then enter this code in the CMS UI to pair the device.

    Request Body:
        {
            "hardware_id": "unique-hardware-id" (required),
            "pairing_code": "123456" (required, 6-digit code)
        }

    Returns:
        200: Pairing request accepted
            {
                "message": "Pairing request received",
                "device": { device data },
                "pairing_code": "123456"
            }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
        404: Device not found
            {
                "error": "Device with hardware_id xxx not found"
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

    # Validate pairing_code
    pairing_code = data.get('pairing_code')
    if not pairing_code:
        return jsonify({'error': 'pairing_code is required'}), 400

    if not isinstance(pairing_code, str) or len(pairing_code) > 10:
        return jsonify({
            'error': 'pairing_code must be a string with max 10 characters'
        }), 400

    # Find device by hardware_id
    device = Device.query.filter_by(hardware_id=hardware_id).first()
    if not device:
        return jsonify({
            'error': f'Device with hardware_id {hardware_id} not found'
        }), 404

    # Store the pairing code
    device.pairing_code = pairing_code

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to store pairing code: {str(e)}'
        }), 500

    # Log the pairing request (device-initiated action)
    log_action(
        action='device.pairing_request',
        action_category='devices',
        resource_type='device',
        resource_id=device.id,
        resource_name=device.device_id,
        user_email='device',
        details={
            'hardware_id': hardware_id,
            'pairing_code': pairing_code,
        }
    )

    return jsonify({
        'message': 'Pairing request received',
        'device': device.to_dict(),
        'pairing_code': pairing_code
    }), 200


@devices_bp.route('/pairing/status/<hardware_id>', methods=['GET'])
def get_pairing_status(hardware_id):
    """
    Get pairing status for a device.

    Devices poll this endpoint to check if they have been paired. Returns
    the current pairing status based on the device's status field.

    Args:
        hardware_id: The unique hardware identifier of the device

    Returns:
        200: Pairing status
            {
                "paired": true/false,
                "status": "pending" or "active" or "offline",
                "device": { device data }
            }
        404: Device not found
            {
                "error": "Device with hardware_id xxx not found"
            }
    """
    # Validate hardware_id
    if not hardware_id or len(hardware_id) > 100:
        return jsonify({
            'error': 'hardware_id must be a string with max 100 characters'
        }), 400

    # Find device by hardware_id
    device = Device.query.filter_by(hardware_id=hardware_id).first()
    if not device:
        return jsonify({
            'error': f'Device with hardware_id {hardware_id} not found'
        }), 404

    # Determine if device is paired based on status
    # Device is considered paired if status is 'active' and has a network_id
    paired = device.status == 'active' and device.network_id is not None

    return jsonify({
        'paired': paired,
        'status': device.status,
        'device': device.to_dict()
    }), 200


@devices_bp.route('/<hardware_id>/playlist', methods=['GET'])
def get_device_playlist(hardware_id):
    """
    Get playlist items for a specific device by hardware ID.

    Devices call this endpoint to retrieve their assigned playlist content.
    No authentication required - devices call this directly.

    Args:
        hardware_id: The unique hardware identifier of the device

    Returns:
        200: Playlist data with items
            {
                "device_id": "SKZ-D-0001",
                "hardware_id": "abc123",
                "playlists": [
                    {
                        "id": "uuid",
                        "name": "Default Playlist",
                        "trigger_type": "default",
                        "priority": 0,
                        "items": [
                            {
                                "id": "uuid",
                                "position": 0,
                                "content": { content data }
                            }
                        ]
                    }
                ]
            }
        400: Invalid hardware_id
            {
                "error": "error message"
            }
        404: Device not found
            {
                "error": "Device with hardware_id xxx not found"
            }
    """
    # Validate hardware_id
    if not hardware_id or len(hardware_id) > 100:
        return jsonify({
            'error': 'hardware_id must be a string with max 100 characters'
        }), 400

    # Find device by hardware_id
    device = Device.query.filter_by(hardware_id=hardware_id).first()
    if not device:
        return jsonify({
            'error': f'Device with hardware_id {hardware_id} not found'
        }), 404

    # Get all active assignments for this device
    assignments = DeviceAssignment.get_active_for_device(device.id)

    # Build playlist response with items
    playlists = []
    for assignment in assignments:
        if assignment.playlist:
            playlist_data = {
                'id': assignment.playlist.id,
                'name': assignment.playlist.name,
                'trigger_type': assignment.trigger_type,
                'priority': assignment.priority,
                'loop_mode': assignment.playlist.loop_mode,
                'items': []
            }

            # Get playlist items ordered by position
            items = PlaylistItem.query.filter_by(
                playlist_id=assignment.playlist.id
            ).order_by(PlaylistItem.position).all()

            for item in items:
                playlist_data['items'].append(item.to_dict())

            playlists.append(playlist_data)

    return jsonify({
        'device_id': device.device_id,
        'hardware_id': device.hardware_id,
        'playlists': playlists
    }), 200


@devices_bp.route('/<device_id>/assign-playlist', methods=['POST'])
def assign_playlist_to_device(device_id):
    """
    Assign a playlist to a device.

    This replaces any existing default playlist assignment for the device.

    Args:
        device_id: Device ID (e.g., 'SKZ-D-0002') or hardware_id

    Request Body:
        {
            "playlist_id": "uuid-of-playlist"
        }

    Returns:
        200: Playlist assigned successfully
        400: Missing playlist_id
        404: Device or playlist not found
    """
    data = request.get_json()
    if not data or 'playlist_id' not in data:
        return jsonify({'error': 'playlist_id is required'}), 400

    playlist_id = data['playlist_id']

    # Find device by device_id or hardware_id
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = Device.query.filter_by(hardware_id=device_id).first()

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    # Find playlist
    playlist = Playlist.query.get(playlist_id)
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    # Get trigger_type from request, default to 'default'
    trigger_type = data.get('trigger_type', 'default')

    # Remove existing assignment for this device + trigger_type combo
    existing = DeviceAssignment.query.filter_by(
        device_id=device.id,
        trigger_type=trigger_type
    ).all()
    for assignment in existing:
        db.session.delete(assignment)

    # Create new assignment
    new_assignment = DeviceAssignment(
        device_id=device.id,
        playlist_id=playlist.id,
        trigger_type=trigger_type,
        priority=0
    )
    db.session.add(new_assignment)
    db.session.commit()

    # Notify hubs about the playlist change
    try:
        from cms.services.hub_notifier import notify_playlist_updated
        notify_playlist_updated(
            device_id=device.hardware_id,
            playlist_id=playlist_id,
            action='assigned'
        )
    except ImportError:
        pass  # Hub notifier not available

    return jsonify({
        'status': 'ok',
        'id': new_assignment.id,
        'assignment_id': new_assignment.id,
        'device_id': device.device_id,
        'hardware_id': device.hardware_id,
        'playlist_id': playlist.id,
        'playlist_name': playlist.name
    }), 200


@devices_bp.route('/<device_id>/location', methods=['PUT'])
def update_device_location(device_id):
    """
    Update device location (screen_location field).

    Called by Hub when a device selects its location during installation.

    Args:
        device_id: Device UUID or SKZ-X-XXXX format

    Request Body:
        {
            "screen_location": "Fishing Counter",
            "location_id": "uuid (optional)"
        }

    Returns:
        200: Location updated
        404: Device not found
    """
    # Find device by UUID first, then by device_id format
    device = db.session.get(Device, device_id)
    if not device:
        device = Device.query.filter_by(device_id=device_id).first()

    if not device:
        return jsonify({
            'success': False,
            'error': 'Device not found'
        }), 404

    data = request.get_json(silent=True) or {}
    screen_location = data.get('screen_location') or data.get('location_name')

    if not screen_location:
        return jsonify({
            'success': False,
            'error': 'screen_location is required'
        }), 400

    # Update device location
    device.screen_location = screen_location

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Failed to update location: {str(e)}'
        }), 500

    # Log the location update
    log_action(
        action='device.update_location',
        action_category='devices',
        resource_type='device',
        resource_id=device.id,
        resource_name=device.device_id,
        user_email='hub',
        details={
            'screen_location': screen_location,
        }
    )

    return jsonify({
        'success': True,
        'message': 'Location updated',
        'screen_location': screen_location
    }), 200


@devices_bp.route('/register-from-hub', methods=['POST'])
def register_from_hub():
    """
    Register a device forwarded from a Hub.

    Hubs call this endpoint when a device registers with them. This creates
    the device in the CMS database so admins can approve it. The device
    remains in 'pending' status until approved.

    Request Body:
        {
            "hardware_id": "unique-hardware-id" (required),
            "name": "device name" (optional),
            "pairing_code": "123456" (required),
            "ip_address": "10.10.10.100" (optional),
            "hub_id": "uuid-of-hub" (required),
            "hub_code": "ABC" (optional, for device ID generation),
            "mode": "hub" (required)
        }

    Returns:
        201: New device created
            {
                "success": true,
                "device_id": "uuid",
                "device_code": "SKZ-H-ABC-0001",
                "message": "Device registered"
            }
        200: Existing device returned
            {
                "success": true,
                "device_id": "uuid",
                "device_code": "SKZ-H-ABC-0001",
                "message": "Device already exists"
            }
        400: Missing required field
        404: Hub not found
    """
    data = request.get_json(silent=True)

    if not data:
        return jsonify({'success': False, 'error': 'Request body is required'}), 400

    # Validate required fields
    hardware_id = data.get('hardware_id')
    if not hardware_id:
        return jsonify({'success': False, 'error': 'hardware_id is required'}), 400

    pairing_code = data.get('pairing_code')
    if not pairing_code:
        return jsonify({'success': False, 'error': 'pairing_code is required'}), 400

    hub_id = data.get('hub_id')
    if not hub_id:
        return jsonify({'success': False, 'error': 'hub_id is required'}), 400

    # Check if device already exists
    existing_device = Device.query.filter_by(hardware_id=hardware_id).first()
    if existing_device:
        # Update device info from Hub
        existing_device.hub_id = hub_id
        existing_device.mode = 'hub'
        existing_device.connection_mode = 'hub'
        hub = db.session.get(Hub, hub_id)
        if hub:
            existing_device.network_id = hub.network_id
        if data.get('name'):
            existing_device.name = data.get('name')
        if data.get('pairing_code'):
            existing_device.pairing_code = data.get('pairing_code')
        if data.get('ip_address'):
            existing_device.ip_address = data.get('ip_address')

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        return jsonify({
            'success': True,
            'device_id': existing_device.id,
            'device_code': existing_device.device_id,
            'message': 'Device updated'
        }), 200

    # Validate hub exists
    hub = db.session.get(Hub, hub_id)
    if not hub:
        return jsonify({
            'success': False,
            'error': f'Hub with id {hub_id} not found'
        }), 404

    # Get hub code for device ID generation
    hub_code = data.get('hub_code') or hub.code

    # Generate device ID
    try:
        device_id = DeviceIDGenerator.generate_hub_id_by_hub_id(
            hub_id, hub_code, db.session
        )
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to generate device ID: {str(e)}'
        }), 500

    # Create device - auto-populate store info from Hub
    device = Device(
        hardware_id=hardware_id,
        device_id=device_id,
        mode='hub',
        connection_mode='hub',
        hub_id=hub_id,
        network_id=hub.network_id,
        name=data.get('name'),
        pairing_code=pairing_code,
        status='active',  # Hub devices are pre-verified, no approval needed
        # Auto-populate from Hub's store info
        store_name=hub.name,
        store_address=hub.store_address,
        store_city=hub.store_city,
        store_state=hub.store_state,
        store_zipcode=hub.store_zipcode,
        manager_name=hub.manager_name,
        store_phone=hub.store_phone,
        # screen_location left blank - admin sets in CMS
    )

    try:
        db.session.add(device)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Failed to create device: {str(e)}'
        }), 500

    # Log device registration
    log_action(
        action='device.register_from_hub',
        action_category='devices',
        resource_type='device',
        resource_id=device.id,
        resource_name=device.device_id,
        user_email='hub',
        details={
            'hardware_id': hardware_id,
            'hub_id': hub_id,
            'pairing_code': pairing_code,
        }
    )

    return jsonify({
        'success': True,
        'device_id': device.id,
        'device_code': device.device_id,
        'message': 'Device registered'
    }), 201


@devices_bp.route('/<device_id>', methods=['DELETE'])
@login_required
def delete_device(device_id):
    """
    Delete a device from the CMS.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Returns:
        200: Device deleted
        404: Device not found
    """
    # Try to find device by device_id (SKZ format) first, then by UUID
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    device_name = device.name
    hardware_id = device.hardware_id

    try:
        # Delete associated assignments first
        DeviceAssignment.query.filter_by(device_id=device.id).delete()

        # Delete device layouts
        from cms.models import DeviceLayout
        DeviceLayout.query.filter_by(device_id=device.id).delete()

        # Delete the device
        db.session.delete(device)
        db.session.commit()

        # Audit log
        log_action(
            action='device.deleted',
            action_category='devices',
            resource_type='device',
            resource_id=device_id,
            resource_name=device_name,
            details={
                'hardware_id': hardware_id,
            }
        )

        return jsonify({
            'message': f'Device "{device_name}" deleted successfully'
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@devices_bp.route('/<device_id>/status', methods=['PUT'])
def update_device_status(device_id):
    """
    Update device status. Called by Hub to activate device after pairing.
    No auth required - Hub calls this directly.

    Args:
        device_id: Device UUID or device_id (SKZ format)

    Request Body:
        {
            "status": "active",
            "location": "Entrance" (optional)
        }
    """
    data = request.get_json() or {}
    new_status = data.get('status')

    if not new_status:
        return jsonify({'error': 'status is required'}), 400

    if new_status not in ('active', 'offline', 'pending'):
        return jsonify({'error': 'Invalid status'}), 400

    # Try UUID first, then device_id format
    device = db.session.get(Device, device_id)
    if not device:
        device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = Device.query.filter_by(hardware_id=device_id).first()

    if not device:
        return jsonify({'error': f'Device not found: {device_id}'}), 404

    device.status = new_status

    location = data.get('location')
    if location:
        device.screen_location = location

    db.session.commit()

    return jsonify({
        'success': True,
        'device_id': device.device_id,
        'status': device.status
    }), 200


@devices_bp.route('/<device_id>/status', methods=['PUT'])
def update_device_status(device_id):
    """
    Update device status. Called by Hub to activate device after pairing.
    No auth required - Hub calls this directly.

    Args:
        device_id: Device UUID or device_id (SKZ format)

    Request Body:
        {
            "status": "active",
            "location": "Entrance" (optional)
        }
    """
    data = request.get_json() or {}
    new_status = data.get('status')

    if not new_status:
        return jsonify({'error': 'status is required'}), 400

    if new_status not in ('active', 'offline', 'pending'):
        return jsonify({'error': 'Invalid status'}), 400

    # Try UUID first, then device_id format
    device = db.session.get(Device, device_id)
    if not device:
        device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = Device.query.filter_by(hardware_id=device_id).first()

    if not device:
        return jsonify({'error': f'Device not found: {device_id}'}), 404

    device.status = new_status

    location = data.get('location')
    if location:
        device.screen_location = location

    db.session.commit()

    return jsonify({
        'success': True,
        'device_id': device.device_id,
        'status': device.status
    }), 200
