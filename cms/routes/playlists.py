"""
CMS Playlists Routes

Blueprint for playlist management API endpoints:
- POST /: Create playlist
- GET /: List all playlists
- GET /<playlist_id>: Get playlist details
- PUT /<playlist_id>: Update playlist
- DELETE /<playlist_id>: Delete playlist
- POST /<playlist_id>/items: Add item to playlist
- DELETE /<playlist_id>/items/<item_id>: Remove item from playlist
- PUT /<playlist_id>/items/reorder: Reorder playlist items
- POST /<playlist_id>/assign: Assign playlist to device
- DELETE /<playlist_id>/assign/<assignment_id>: Remove device assignment

All endpoints are prefixed with /api/v1/playlists when registered with the app.
"""

from datetime import datetime, timezone

from flask import Blueprint, request, jsonify

from cms.models import db, Playlist, PlaylistItem, Content, Device, DeviceAssignment, Network
from cms.utils.auth import login_required
from cms.utils.audit import log_action
from cms.models.playlist import TriggerType, LoopMode, Priority


# Create playlists blueprint
playlists_bp = Blueprint('playlists', __name__)


def _parse_datetime(datetime_str):
    """Parse datetime string to datetime object.

    Supports ISO format with optional timezone.

    Args:
        datetime_str: Datetime string to parse

    Returns:
        datetime object or None if invalid
    """
    if not datetime_str:
        return None

    try:
        # Handle ISO format with Z suffix
        return datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
    except ValueError:
        return None


@playlists_bp.route('', methods=['POST'])
@login_required
def create_playlist():
    """
    Create a new playlist.

    Request Body:
        {
            "name": "My Playlist" (required),
            "description": "Optional description",
            "network_id": "uuid-of-network" (optional),
            "trigger_type": "manual" | "time" | "event" (optional, default: "manual"),
            "trigger_config": "{...}" (optional, JSON string for trigger configuration),
            "loop_mode": "continuous" | "play_once" | "scheduled" (optional, default: "continuous"),
            "priority": "normal" | "high" | "interrupt" (optional, default: "normal"),
            "start_date": "2024-01-15T10:00:00Z" (optional, ISO datetime for scheduled playback),
            "end_date": "2024-12-31T23:59:59Z" (optional, ISO datetime for scheduled playback),
            "is_active": true (optional, default: true)
        }

    Returns:
        201: Playlist created successfully
            { playlist data }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate name
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400

    if not isinstance(name, str) or len(name) > 200:
        return jsonify({
            'error': 'name must be a string with max 200 characters'
        }), 400

    # Validate network_id if provided
    network_id = data.get('network_id')
    if network_id:
        network = db.session.get(Network, network_id)
        if not network:
            return jsonify({
                'error': f'Network with id {network_id} not found'
            }), 400

    # Validate trigger_type if provided
    trigger_type = data.get('trigger_type', TriggerType.MANUAL.value)
    valid_trigger_types = [t.value for t in TriggerType]
    if trigger_type not in valid_trigger_types:
        return jsonify({
            'error': f"Invalid trigger_type: {trigger_type}. Valid values: {', '.join(valid_trigger_types)}"
        }), 400

    # Validate loop_mode if provided
    loop_mode = data.get('loop_mode', LoopMode.CONTINUOUS.value)
    valid_loop_modes = [m.value for m in LoopMode]
    if loop_mode not in valid_loop_modes:
        return jsonify({
            'error': f"Invalid loop_mode: {loop_mode}. Valid values: {', '.join(valid_loop_modes)}"
        }), 400

    # Validate priority if provided
    priority = data.get('priority', Priority.NORMAL.value)
    valid_priorities = [p.value for p in Priority]
    if priority not in valid_priorities:
        return jsonify({
            'error': f"Invalid priority: {priority}. Valid values: {', '.join(valid_priorities)}"
        }), 400

    # Parse dates
    start_date = _parse_datetime(data.get('start_date'))
    end_date = _parse_datetime(data.get('end_date'))

    # Validate date range
    if start_date and end_date and start_date > end_date:
        return jsonify({
            'error': 'start_date must be before end_date'
        }), 400

    # Create playlist
    playlist = Playlist(
        name=name,
        description=data.get('description'),
        network_id=network_id,
        trigger_type=trigger_type,
        trigger_config=data.get('trigger_config'),
        loop_mode=loop_mode,
        priority=priority,
        start_date=start_date,
        end_date=end_date,
        is_active=data.get('is_active', True)
    )

    try:
        db.session.add(playlist)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create playlist: {str(e)}'
        }), 500

    # Log playlist creation
    log_action(
        action='playlist.create',
        action_category='playlists',
        resource_type='playlist',
        resource_id=playlist.id,
        resource_name=playlist.name,
        details={
            'name': name,
            'network_id': network_id,
            'trigger_type': trigger_type,
            'loop_mode': loop_mode,
            'priority': priority,
            'start_date': start_date.isoformat() if start_date else None,
            'end_date': end_date.isoformat() if end_date else None,
            'is_active': playlist.is_active,
        }
    )

    return jsonify(playlist.to_dict()), 201


@playlists_bp.route('', methods=['GET'])
@login_required
def list_playlists():
    """
    List all playlists.

    Returns a list of all playlists in the CMS,
    with optional filtering by network or active status.

    Query Parameters:
        network_id: Filter by network UUID
        is_active: Filter by active status (true/false)
        trigger_type: Filter by trigger type

    Returns:
        200: List of playlists
            {
                "playlists": [ { playlist data }, ... ],
                "count": 5
            }
    """
    # Build query with optional filters
    query = Playlist.query

    # Filter by network
    network_id = request.args.get('network_id')
    if network_id:
        query = query.filter_by(network_id=network_id)

    # Filter by active status
    is_active = request.args.get('is_active')
    if is_active is not None:
        is_active_bool = is_active.lower() == 'true'
        query = query.filter_by(is_active=is_active_bool)

    # Filter by trigger type
    trigger_type = request.args.get('trigger_type')
    if trigger_type:
        valid_trigger_types = [t.value for t in TriggerType]
        if trigger_type not in valid_trigger_types:
            return jsonify({
                'error': f"Invalid trigger_type: {trigger_type}. Valid values: {', '.join(valid_trigger_types)}"
            }), 400
        query = query.filter_by(trigger_type=trigger_type)

    # Execute query
    playlists = query.order_by(Playlist.created_at.desc()).all()

    return jsonify({
        'playlists': [p.to_dict() for p in playlists],
        'count': len(playlists)
    }), 200


@playlists_bp.route('/<playlist_id>', methods=['GET'])
@login_required
def get_playlist(playlist_id):
    """
    Get details for a specific playlist including all items.

    Args:
        playlist_id: Playlist UUID

    Query Parameters:
        include_items: Include playlist items in response (default: true)

    Returns:
        200: Playlist data with items
            { playlist data with items }
        400: Invalid playlist_id format
            {
                "error": "Invalid playlist_id format"
            }
        404: Playlist not found
            {
                "error": "Playlist not found"
            }
    """
    # Validate playlist_id format
    if not isinstance(playlist_id, str) or len(playlist_id) > 64:
        return jsonify({
            'error': 'Invalid playlist_id format'
        }), 400

    playlist = db.session.get(Playlist, playlist_id)

    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    # Check if items should be included
    include_items = request.args.get('include_items', 'true').lower() == 'true'

    if include_items:
        return jsonify(playlist.to_dict_with_items()), 200
    else:
        return jsonify(playlist.to_dict()), 200


@playlists_bp.route('/<playlist_id>', methods=['PUT'])
@login_required
def update_playlist(playlist_id):
    """
    Update a playlist.

    Args:
        playlist_id: Playlist UUID

    Request Body:
        {
            "name": "Updated Name" (optional),
            "description": "Updated description" (optional),
            "network_id": "uuid-of-network" (optional),
            "trigger_type": "manual" | "time" | "event" (optional),
            "trigger_config": "{...}" (optional),
            "is_active": true/false (optional)
        }

    Returns:
        200: Playlist updated successfully
            { updated playlist data }
        400: Invalid data
            {
                "error": "error message"
            }
        404: Playlist not found
            {
                "error": "Playlist not found"
            }
    """
    # Validate playlist_id format
    if not isinstance(playlist_id, str) or len(playlist_id) > 64:
        return jsonify({
            'error': 'Invalid playlist_id format'
        }), 400

    playlist = db.session.get(Playlist, playlist_id)

    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Track changes for audit log
    changes = {}

    # Update name if provided
    if 'name' in data:
        name = data['name']
        if not isinstance(name, str) or len(name) > 200:
            return jsonify({
                'error': 'name must be a string with max 200 characters'
            }), 400
        if playlist.name != name:
            changes['name'] = {'before': playlist.name, 'after': name}
        playlist.name = name

    # Update description if provided
    if 'description' in data:
        if playlist.description != data['description']:
            changes['description'] = {'before': playlist.description, 'after': data['description']}
        playlist.description = data['description']

    # Update network_id if provided
    if 'network_id' in data:
        network_id = data['network_id']
        if network_id:
            network = db.session.get(Network, network_id)
            if not network:
                return jsonify({
                    'error': f'Network with id {network_id} not found'
                }), 400
        if playlist.network_id != network_id:
            changes['network_id'] = {'before': playlist.network_id, 'after': network_id}
        playlist.network_id = network_id

    # Update trigger_type if provided
    if 'trigger_type' in data:
        trigger_type = data['trigger_type']
        valid_trigger_types = [t.value for t in TriggerType]
        if trigger_type not in valid_trigger_types:
            return jsonify({
                'error': f"Invalid trigger_type: {trigger_type}. Valid values: {', '.join(valid_trigger_types)}"
            }), 400
        if playlist.trigger_type != trigger_type:
            changes['trigger_type'] = {'before': playlist.trigger_type, 'after': trigger_type}
        playlist.trigger_type = trigger_type

    # Update trigger_config if provided
    if 'trigger_config' in data:
        if playlist.trigger_config != data['trigger_config']:
            changes['trigger_config'] = {'before': playlist.trigger_config, 'after': data['trigger_config']}
        playlist.trigger_config = data['trigger_config']

    # Update is_active if provided
    if 'is_active' in data:
        new_is_active = bool(data['is_active'])
        if playlist.is_active != new_is_active:
            changes['is_active'] = {'before': playlist.is_active, 'after': new_is_active}
        playlist.is_active = new_is_active

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update playlist: {str(e)}'
        }), 500

    # Log playlist update
    if changes:
        log_action(
            action='playlist.update',
            action_category='playlists',
            resource_type='playlist',
            resource_id=playlist.id,
            resource_name=playlist.name,
            details={'changes': changes}
        )

    return jsonify(playlist.to_dict()), 200


@playlists_bp.route('/<playlist_id>', methods=['DELETE'])
@login_required
def delete_playlist(playlist_id):
    """
    Delete a playlist and all its items.

    Args:
        playlist_id: Playlist UUID

    Returns:
        200: Playlist deleted successfully
            {
                "message": "Playlist deleted successfully",
                "id": "uuid"
            }
        400: Invalid playlist_id format
            {
                "error": "Invalid playlist_id format"
            }
        404: Playlist not found
            {
                "error": "Playlist not found"
            }
    """
    # Validate playlist_id format
    if not isinstance(playlist_id, str) or len(playlist_id) > 64:
        return jsonify({
            'error': 'Invalid playlist_id format'
        }), 400

    playlist = db.session.get(Playlist, playlist_id)

    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    # Store info for audit log and response before deleting
    playlist_id_response = playlist.id
    playlist_name = playlist.name
    network_id = playlist.network_id
    item_count = len(playlist.items) if playlist.items else 0

    try:
        db.session.delete(playlist)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to delete playlist: {str(e)}'
        }), 500

    # Log playlist deletion
    log_action(
        action='playlist.delete',
        action_category='playlists',
        resource_type='playlist',
        resource_id=playlist_id_response,
        resource_name=playlist_name,
        details={
            'name': playlist_name,
            'network_id': network_id,
            'item_count': item_count,
        }
    )

    return jsonify({
        'message': 'Playlist deleted successfully',
        'id': playlist_id_response
    }), 200


@playlists_bp.route('/<playlist_id>/items', methods=['POST'])
@login_required
def add_playlist_item(playlist_id):
    """
    Add an item to a playlist.

    Args:
        playlist_id: Playlist UUID

    Request Body:
        {
            "content_id": "uuid-of-content" (required),
            "position": 0 (optional, default: append to end),
            "duration_override": 10 (optional, seconds for images)
        }

    Returns:
        201: Item added successfully
            { playlist item data }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
        404: Playlist or content not found
            {
                "error": "error message"
            }
    """
    # Validate playlist_id format
    if not isinstance(playlist_id, str) or len(playlist_id) > 64:
        return jsonify({
            'error': 'Invalid playlist_id format'
        }), 400

    playlist = db.session.get(Playlist, playlist_id)

    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate content_id
    content_id = data.get('content_id')
    if not content_id:
        return jsonify({'error': 'content_id is required'}), 400

    content = db.session.get(Content, content_id)
    if not content:
        return jsonify({
            'error': f'Content with id {content_id} not found'
        }), 404

    # Determine position
    position = data.get('position')
    if position is None:
        # Append to end - get max position
        max_position = db.session.query(db.func.max(PlaylistItem.position)).filter(
            PlaylistItem.playlist_id == playlist_id
        ).scalar()
        position = (max_position or -1) + 1
    else:
        try:
            position = int(position)
        except (TypeError, ValueError):
            return jsonify({
                'error': 'position must be an integer'
            }), 400

        # Shift existing items at or after this position
        items_to_shift = PlaylistItem.query.filter(
            PlaylistItem.playlist_id == playlist_id,
            PlaylistItem.position >= position
        ).all()

        for item in items_to_shift:
            item.position += 1

    # Parse duration_override
    duration_override = data.get('duration_override')
    if duration_override is not None:
        try:
            duration_override = int(duration_override)
        except (TypeError, ValueError):
            return jsonify({
                'error': 'duration_override must be an integer'
            }), 400

    # Create playlist item
    playlist_item = PlaylistItem(
        playlist_id=playlist_id,
        content_id=content_id,
        position=position,
        duration_override=duration_override
    )

    try:
        db.session.add(playlist_item)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to add item to playlist: {str(e)}'
        }), 500

    # Log playlist item addition
    log_action(
        action='playlist.add_item',
        action_category='playlists',
        resource_type='playlist',
        resource_id=playlist.id,
        resource_name=playlist.name,
        details={
            'item_id': playlist_item.id,
            'content_id': content_id,
            'content_name': content.original_name,
            'position': position,
        }
    )

    return jsonify(playlist_item.to_dict()), 201


@playlists_bp.route('/<playlist_id>/items/<item_id>', methods=['DELETE'])
@login_required
def remove_playlist_item(playlist_id, item_id):
    """
    Remove an item from a playlist.

    Args:
        playlist_id: Playlist UUID
        item_id: PlaylistItem UUID

    Returns:
        200: Item removed successfully
            {
                "message": "Item removed from playlist",
                "id": "uuid"
            }
        400: Invalid ID format
            {
                "error": "Invalid ID format"
            }
        404: Playlist or item not found
            {
                "error": "error message"
            }
    """
    # Validate playlist_id format
    if not isinstance(playlist_id, str) or len(playlist_id) > 64:
        return jsonify({
            'error': 'Invalid playlist_id format'
        }), 400

    # Validate item_id format
    if not isinstance(item_id, str) or len(item_id) > 64:
        return jsonify({
            'error': 'Invalid item_id format'
        }), 400

    playlist = db.session.get(Playlist, playlist_id)

    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    # Find the item
    playlist_item = PlaylistItem.query.filter_by(
        id=item_id,
        playlist_id=playlist_id
    ).first()

    if not playlist_item:
        return jsonify({'error': 'Playlist item not found'}), 404

    # Store info for audit log and response before deleting
    item_id_response = playlist_item.id
    removed_position = playlist_item.position
    content_id = playlist_item.content_id
    content_name = playlist_item.content.original_name if playlist_item.content else None

    try:
        db.session.delete(playlist_item)

        # Shift remaining items to fill the gap
        items_to_shift = PlaylistItem.query.filter(
            PlaylistItem.playlist_id == playlist_id,
            PlaylistItem.position > removed_position
        ).all()

        for item in items_to_shift:
            item.position -= 1

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to remove item from playlist: {str(e)}'
        }), 500

    # Log playlist item removal
    log_action(
        action='playlist.remove_item',
        action_category='playlists',
        resource_type='playlist',
        resource_id=playlist.id,
        resource_name=playlist.name,
        details={
            'item_id': item_id_response,
            'content_id': content_id,
            'content_name': content_name,
            'removed_position': removed_position,
        }
    )

    return jsonify({
        'message': 'Item removed from playlist',
        'id': item_id_response
    }), 200


@playlists_bp.route('/<playlist_id>/items/reorder', methods=['PUT'])
@login_required
def reorder_playlist_items(playlist_id):
    """
    Reorder items in a playlist.

    Args:
        playlist_id: Playlist UUID

    Request Body:
        {
            "item_ids": ["item-uuid-1", "item-uuid-2", ...] (required, new order)
        }

    Returns:
        200: Items reordered successfully
            {
                "message": "Playlist items reordered",
                "items": [ { item data }, ... ]
            }
        400: Invalid data
            {
                "error": "error message"
            }
        404: Playlist or item not found
            {
                "error": "error message"
            }
    """
    # Validate playlist_id format
    if not isinstance(playlist_id, str) or len(playlist_id) > 64:
        return jsonify({
            'error': 'Invalid playlist_id format'
        }), 400

    playlist = db.session.get(Playlist, playlist_id)

    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate item_ids
    item_ids = data.get('item_ids')
    if not item_ids or not isinstance(item_ids, list):
        return jsonify({'error': 'item_ids array is required'}), 400

    # Verify all items exist and belong to this playlist
    existing_items = PlaylistItem.query.filter_by(playlist_id=playlist_id).all()
    existing_ids = {item.id for item in existing_items}

    for item_id in item_ids:
        if item_id not in existing_ids:
            return jsonify({
                'error': f'Item {item_id} not found in playlist'
            }), 404

    # Update positions
    try:
        for position, item_id in enumerate(item_ids):
            item = db.session.get(PlaylistItem, item_id)
            if item:
                item.position = position

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to reorder items: {str(e)}'
        }), 500

    # Get updated items
    updated_items = PlaylistItem.query.filter_by(
        playlist_id=playlist_id
    ).order_by(PlaylistItem.position).all()

    # Log the reorder action
    log_action(
        action='playlist.reorder_items',
        action_category='playlists',
        resource_type='playlist',
        resource_id=playlist.id,
        resource_name=playlist.name,
        details={
            'new_order': item_ids,
            'item_count': len(item_ids),
        }
    )

    return jsonify({
        'message': 'Playlist items reordered',
        'items': [item.to_dict() for item in updated_items]
    }), 200


@playlists_bp.route('/<playlist_id>/assign', methods=['POST'])
@login_required
def assign_playlist_to_device(playlist_id):
    """
    Assign a playlist to a device.

    Args:
        playlist_id: Playlist UUID

    Request Body:
        {
            "device_id": "uuid-of-device" (required),
            "priority": 0 (optional, default: 0),
            "start_date": "2024-01-15T10:00:00Z" (optional),
            "end_date": "2024-12-31T23:59:59Z" (optional)
        }

    Returns:
        201: Assignment created successfully
            { assignment data }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
        404: Playlist or device not found
            {
                "error": "error message"
            }
    """
    # Validate playlist_id format
    if not isinstance(playlist_id, str) or len(playlist_id) > 64:
        return jsonify({
            'error': 'Invalid playlist_id format'
        }), 400

    playlist = db.session.get(Playlist, playlist_id)

    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate device_id
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({'error': 'device_id is required'}), 400

    device = db.session.get(Device, device_id)
    if not device:
        return jsonify({
            'error': f'Device with id {device_id} not found'
        }), 404

    # Check for existing assignment
    existing = DeviceAssignment.query.filter_by(
        device_id=device_id,
        playlist_id=playlist_id
    ).first()

    if existing:
        return jsonify({
            'error': 'Playlist is already assigned to this device',
            'assignment': existing.to_dict()
        }), 400

    # Parse priority
    priority = data.get('priority', 0)
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        return jsonify({
            'error': 'priority must be an integer'
        }), 400

    # Parse dates
    start_date = _parse_datetime(data.get('start_date'))
    end_date = _parse_datetime(data.get('end_date'))

    # Validate date range
    if start_date and end_date and start_date > end_date:
        return jsonify({
            'error': 'start_date must be before end_date'
        }), 400

    # Create assignment
    assignment = DeviceAssignment(
        device_id=device_id,
        playlist_id=playlist_id,
        priority=priority,
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

    # Log playlist assignment to device
    log_action(
        action='playlist.assign_device',
        action_category='playlists',
        resource_type='playlist',
        resource_id=playlist.id,
        resource_name=playlist.name,
        details={
            'assignment_id': assignment.id,
            'device_id': device_id,
            'device_name': device.name or device.device_id,
            'priority': priority,
        }
    )

    return jsonify(assignment.to_dict_with_relations()), 201


@playlists_bp.route('/<playlist_id>/assign/<assignment_id>', methods=['DELETE'])
@login_required
def remove_device_assignment(playlist_id, assignment_id):
    """
    Remove a device assignment from a playlist.

    Args:
        playlist_id: Playlist UUID
        assignment_id: DeviceAssignment UUID

    Returns:
        200: Assignment removed successfully
            {
                "message": "Assignment removed",
                "id": "uuid"
            }
        400: Invalid ID format
            {
                "error": "Invalid ID format"
            }
        404: Playlist or assignment not found
            {
                "error": "error message"
            }
    """
    # Validate playlist_id format
    if not isinstance(playlist_id, str) or len(playlist_id) > 64:
        return jsonify({
            'error': 'Invalid playlist_id format'
        }), 400

    # Validate assignment_id format
    if not isinstance(assignment_id, str) or len(assignment_id) > 64:
        return jsonify({
            'error': 'Invalid assignment_id format'
        }), 400

    playlist = db.session.get(Playlist, playlist_id)

    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    # Find the assignment
    assignment = DeviceAssignment.query.filter_by(
        id=assignment_id,
        playlist_id=playlist_id
    ).first()

    if not assignment:
        return jsonify({'error': 'Assignment not found'}), 404

    # Store info for audit log and response before deleting
    assignment_id_response = assignment.id
    device_id = assignment.device_id
    device_name = assignment.device.name if assignment.device else None
    device_device_id = assignment.device.device_id if assignment.device else None

    try:
        db.session.delete(assignment)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to remove assignment: {str(e)}'
        }), 500

    # Log assignment removal
    log_action(
        action='playlist.unassign_device',
        action_category='playlists',
        resource_type='playlist',
        resource_id=playlist.id,
        resource_name=playlist.name,
        details={
            'assignment_id': assignment_id_response,
            'device_id': device_id,
            'device_name': device_name or device_device_id,
        }
    )

    return jsonify({
        'message': 'Assignment removed',
        'id': assignment_id_response
    }), 200


@playlists_bp.route('/<playlist_id>/assignments', methods=['GET'])
@login_required
def list_playlist_assignments(playlist_id):
    """
    List all device assignments for a playlist.

    Args:
        playlist_id: Playlist UUID

    Returns:
        200: List of assignments
            {
                "assignments": [ { assignment data }, ... ],
                "count": 5
            }
        400: Invalid playlist_id format
            {
                "error": "Invalid playlist_id format"
            }
        404: Playlist not found
            {
                "error": "Playlist not found"
            }
    """
    # Validate playlist_id format
    if not isinstance(playlist_id, str) or len(playlist_id) > 64:
        return jsonify({
            'error': 'Invalid playlist_id format'
        }), 400

    playlist = db.session.get(Playlist, playlist_id)

    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    assignments = DeviceAssignment.query.filter_by(
        playlist_id=playlist_id
    ).all()

    return jsonify({
        'assignments': [a.to_dict_with_relations() for a in assignments],
        'count': len(assignments)
    }), 200
