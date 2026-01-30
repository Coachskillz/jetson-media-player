"""
CMS Playlists Routes

Blueprint for playlist management API endpoints:
- POST /: Create playlist
- GET /: List all playlists
- GET /approved-content: List approved content for playlist builder
- GET /<playlist_id>: Get playlist details
- PUT /<playlist_id>: Update playlist
- DELETE /<playlist_id>: Delete playlist
- POST /<playlist_id>/items: Add item to playlist
- DELETE /<playlist_id>/items/<item_id>: Remove item from playlist
- PUT /<playlist_id>/items/reorder: Reorder playlist items
- GET /<playlist_id>/preview: Get playlist preview with full content details
- POST /<playlist_id>/assign: Assign playlist to device
- DELETE /<playlist_id>/assign/<assignment_id>: Remove device assignment
- GET /<playlist_id>/assignments: List device assignments for playlist

All endpoints are prefixed with /api/v1/playlists when registered with the app.
"""

from datetime import datetime, timezone

from flask import Blueprint, request, jsonify

from cms.models import db, Playlist, PlaylistItem, Content, Device, DeviceAssignment, Network, ContentStatus, DevicePlaylistSync, DeviceSyncStatus
from cms.models.synced_content import SyncedContent
from cms.utils.auth import login_required
from cms.utils.audit import log_action
from cms.models.playlist import TriggerType, LoopMode, Priority, SyncStatus


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


@playlists_bp.route('/approved-content', methods=['GET'])
@login_required
def list_approved_content():
    """
    List all approved content for the playlist builder.

    Returns a list of content items with status="approved" that can be
    added to playlists. This endpoint is designed for the playlist builder
    UI to populate the content browser panel.

    Query Parameters:
        network_id: Filter by network UUID
        type: Filter by content type (video, image, audio)
        search: Search by original filename (case-insensitive)

    Returns:
        200: List of approved content
            {
                "content": [ { content data }, ... ],
                "count": 5
            }
    """
    # Build query filtering for approved content only
    query = Content.query.filter_by(status=ContentStatus.APPROVED.value)

    # Filter by network
    network_id = request.args.get('network_id')
    if network_id:
        query = query.filter_by(network_id=network_id)

    # Filter by content type
    content_type = request.args.get('type')
    if content_type:
        if content_type == 'video':
            query = query.filter(Content.mime_type.like('video/%'))
        elif content_type == 'image':
            query = query.filter(Content.mime_type.like('image/%'))
        elif content_type == 'audio':
            query = query.filter(Content.mime_type.like('audio/%'))

    # Search by original filename
    search = request.args.get('search')
    if search:
        query = query.filter(Content.original_name.ilike(f'%{search}%'))

    # Filter by folder
    folder_id = request.args.get('folder_id')
    if folder_id:
        query = query.filter_by(folder_id=folder_id)

    # Execute query
    content_list = query.order_by(Content.created_at.desc()).all()

    # Add content_type helper field to each item
    result = []
    for content in content_list:
        content_data = content.to_dict()
        if content.is_video:
            content_data['content_type'] = 'video'
        elif content.is_image:
            content_data['content_type'] = 'image'
        elif content.is_audio:
            content_data['content_type'] = 'audio'
        else:
            content_data['content_type'] = 'unknown'
        result.append(content_data)

    return jsonify({
        'content': result,
        'count': len(result)
    }), 200


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
            "loop_mode": "continuous" | "play_once" | "scheduled" (optional),
            "priority": "normal" | "high" | "interrupt" (optional),
            "start_date": "2024-01-15T10:00:00Z" (optional, ISO datetime),
            "end_date": "2024-12-31T23:59:59Z" (optional, ISO datetime),
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

    # Update loop_mode if provided
    if 'loop_mode' in data:
        loop_mode = data['loop_mode']
        valid_loop_modes = [m.value for m in LoopMode]
        if loop_mode not in valid_loop_modes:
            return jsonify({
                'error': f"Invalid loop_mode: {loop_mode}. Valid values: {', '.join(valid_loop_modes)}"
            }), 400
        if playlist.loop_mode != loop_mode:
            changes['loop_mode'] = {'before': playlist.loop_mode, 'after': loop_mode}
        playlist.loop_mode = loop_mode

    # Update priority if provided
    if 'priority' in data:
        priority = data['priority']
        valid_priorities = [p.value for p in Priority]
        if priority not in valid_priorities:
            return jsonify({
                'error': f"Invalid priority: {priority}. Valid values: {', '.join(valid_priorities)}"
            }), 400
        if playlist.priority != priority:
            changes['priority'] = {'before': playlist.priority, 'after': priority}
        playlist.priority = priority

    # Update start_date if provided
    if 'start_date' in data:
        start_date = _parse_datetime(data['start_date'])
        old_start_date = playlist.start_date.isoformat() if playlist.start_date else None
        new_start_date = start_date.isoformat() if start_date else None
        if old_start_date != new_start_date:
            changes['start_date'] = {'before': old_start_date, 'after': new_start_date}
        playlist.start_date = start_date

    # Update end_date if provided
    if 'end_date' in data:
        end_date = _parse_datetime(data['end_date'])
        old_end_date = playlist.end_date.isoformat() if playlist.end_date else None
        new_end_date = end_date.isoformat() if end_date else None
        if old_end_date != new_end_date:
            changes['end_date'] = {'before': old_end_date, 'after': new_end_date}
        playlist.end_date = end_date

    # Validate date range after both dates are potentially updated
    if playlist.start_date and playlist.end_date and playlist.start_date > playlist.end_date:
        return jsonify({
            'error': 'start_date must be before end_date'
        }), 400

    # Update is_active if provided
    if 'is_active' in data:
        new_is_active = bool(data['is_active'])
        if playlist.is_active != new_is_active:
            changes['is_active'] = {'before': playlist.is_active, 'after': new_is_active}
        playlist.is_active = new_is_active

    try:
        # Mark playlist as needing sync if any changes were made
        if changes:
            playlist.mark_pending_sync()
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

    # Validate content_id - check both Content and SyncedContent tables
    content_id = data.get('content_id')
    if not content_id:
        return jsonify({'error': 'content_id is required'}), 400

    content = db.session.get(Content, content_id)
    synced = db.session.get(SyncedContent, content_id) if not content else None
    if not content and not synced:
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

    # Create playlist item - store in correct FK column
    playlist_item = PlaylistItem(
        playlist_id=playlist_id,
        content_id=content_id if content else None,
        synced_content_id=content_id if synced else None,
        position=position,
        duration_override=duration_override
    )

    try:
        db.session.add(playlist_item)
        # Mark playlist as needing sync since content changed
        playlist.mark_pending_sync()
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
            'content_name': content.original_name if content else (synced.title if synced else 'Unknown'),
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
    content_id = playlist_item.content_id or playlist_item.synced_content_id
    content_name = (playlist_item.content.original_name if playlist_item.content
                    else (playlist_item.synced_content.title if playlist_item.synced_content else None))

    try:
        db.session.delete(playlist_item)

        # Shift remaining items to fill the gap
        items_to_shift = PlaylistItem.query.filter(
            PlaylistItem.playlist_id == playlist_id,
            PlaylistItem.position > removed_position
        ).all()

        for item in items_to_shift:
            item.position -= 1

        # Mark playlist as needing sync since content changed
        playlist.mark_pending_sync()
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

        # Mark playlist as needing sync since order changed
        playlist.mark_pending_sync()
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


@playlists_bp.route('/<playlist_id>/preview', methods=['GET'])
@login_required
def preview_playlist(playlist_id):
    """
    Get a playlist preview with full content details.

    Returns the playlist with all items including complete content metadata,
    calculated durations, and content status. This endpoint is designed for
    the playlist builder UI to display a full preview of the playlist.

    Args:
        playlist_id: Playlist UUID

    Returns:
        200: Playlist preview with full content details
            {
                "id": "uuid",
                "name": "Playlist Name",
                "description": "Description",
                "network_id": "uuid" or null,
                "trigger_type": "manual",
                "trigger_config": null,
                "loop_mode": "continuous",
                "priority": "normal",
                "start_date": "2024-01-15T10:00:00+00:00" or null,
                "end_date": "2024-12-31T23:59:59+00:00" or null,
                "is_active": true,
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
                "item_count": 5,
                "total_duration": 120,
                "items": [
                    {
                        "id": "item-uuid",
                        "playlist_id": "playlist-uuid",
                        "content_id": "content-uuid",
                        "position": 0,
                        "duration_override": null,
                        "effective_duration": 30,
                        "created_at": "2024-01-01T00:00:00+00:00",
                        "content": {
                            "id": "content-uuid",
                            "filename": "video.mp4",
                            "original_name": "My Video.mp4",
                            "mime_type": "video/mp4",
                            "file_size": 1024000,
                            "width": 1920,
                            "height": 1080,
                            "duration": 30,
                            "status": "approved",
                            "network_id": "uuid",
                            "created_at": "2024-01-01T00:00:00+00:00",
                            "content_type": "video"
                        }
                    },
                    ...
                ]
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

    # Build preview response with full content details
    items_preview = []
    total_duration = 0
    default_image_duration = 10  # Default duration for images in seconds

    for item in playlist.items.order_by(PlaylistItem.position).all():
        # Calculate effective duration for this item
        effective_duration = None
        resolved = item.content or item.synced_content
        if item.duration_override:
            effective_duration = item.duration_override
        elif resolved and getattr(resolved, 'duration', None):
            effective_duration = resolved.duration
        elif resolved and getattr(resolved, 'is_image', False):
            effective_duration = default_image_duration
        elif resolved and getattr(resolved, 'content_type', None) == 'image':
            effective_duration = default_image_duration

        # Add to total duration
        if effective_duration:
            total_duration += effective_duration

        # Build item preview with enhanced content details
        item_data = {
            'id': item.id,
            'playlist_id': item.playlist_id,
            'content_id': item.content_id or item.synced_content_id,
            'position': item.position,
            'duration_override': item.duration_override,
            'effective_duration': effective_duration,
            'created_at': item.created_at.isoformat() if item.created_at else None,
        }

        # Add content details if content exists (check both tables)
        if item.content:
            content = item.content
            content_data = content.to_dict()
            if content.is_video:
                content_data['content_type'] = 'video'
            elif content.is_image:
                content_data['content_type'] = 'image'
            elif content.is_audio:
                content_data['content_type'] = 'audio'
            else:
                content_data['content_type'] = 'unknown'
            item_data['content'] = content_data
        elif item.synced_content:
            content_data = item.synced_content.to_dict()
            content_data['content_type'] = item.synced_content.content_type or 'unknown'
            item_data['content'] = content_data
        else:
            # Content was deleted - mark as missing
            item_data['content'] = None
            item_data['content_missing'] = True

        items_preview.append(item_data)

    # Build response
    response = {
        'id': playlist.id,
        'name': playlist.name,
        'description': playlist.description,
        'network_id': playlist.network_id,
        'trigger_type': playlist.trigger_type,
        'trigger_config': playlist.trigger_config,
        'loop_mode': playlist.loop_mode,
        'priority': playlist.priority,
        'start_date': playlist.start_date.isoformat() if playlist.start_date else None,
        'end_date': playlist.end_date.isoformat() if playlist.end_date else None,
        'is_active': playlist.is_active,
        'created_at': playlist.created_at.isoformat() if playlist.created_at else None,
        'updated_at': playlist.updated_at.isoformat() if playlist.updated_at else None,
        'item_count': len(items_preview),
        'total_duration': total_duration if total_duration > 0 else None,
        'items': items_preview,
    }

    return jsonify(response), 200


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


@playlists_bp.route('/<playlist_id>/push', methods=['POST'])
@login_required
def push_playlist_to_devices(playlist_id):
    """
    Push a playlist to all assigned devices.

    This triggers a sync operation to push the playlist and its content
    to all devices that have this playlist assigned. Devices can be:
    - Direct mode: Connected directly to the internet
    - Hub mode: Connected through a local hub

    For hub-connected devices, the content is pushed to the hub first,
    which then distributes it to the devices on the local network.

    Args:
        playlist_id: Playlist UUID

    Returns:
        200: Sync initiated successfully
            {
                "message": "Sync initiated",
                "playlist_id": "uuid",
                "device_count": 5,
                "synced_count": 0,
                "direct_devices": 2,
                "hub_devices": 3
            }
        404: Playlist not found
    """
    # Validate playlist_id format
    if not isinstance(playlist_id, str) or len(playlist_id) > 64:
        return jsonify({
            'error': 'Invalid playlist_id format'
        }), 400

    playlist = db.session.get(Playlist, playlist_id)

    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    # Get all device assignments for this playlist
    assignments = DeviceAssignment.query.filter_by(playlist_id=playlist_id).all()

    if not assignments:
        return jsonify({
            'error': 'No devices assigned to this playlist',
            'device_count': 0
        }), 400

    direct_devices = 0
    hub_devices = 0

    try:
        # Mark playlist as syncing
        playlist.mark_syncing()

        # Create or update DevicePlaylistSync records for each assigned device
        for assignment in assignments:
            device = assignment.device
            if not device:
                continue

            # Count device types
            if device.mode == 'hub' and device.hub_id:
                hub_devices += 1
            else:
                direct_devices += 1

            # Find or create sync record
            sync_record = DevicePlaylistSync.query.filter_by(
                device_id=device.id,
                playlist_id=playlist_id
            ).first()

            if not sync_record:
                sync_record = DevicePlaylistSync(
                    device_id=device.id,
                    playlist_id=playlist_id
                )
                db.session.add(sync_record)

            # Mark as syncing
            sync_record.mark_syncing()

        db.session.commit()

        # In a real implementation, this would queue background jobs to:
        # 1. For direct devices: Push content directly via API
        # 2. For hub devices: Push to the hub, which distributes to devices
        #
        # For now, we simulate successful sync after a short delay
        # by marking devices as synced (this would normally happen
        # asynchronously as each device reports successful sync)

        # Simulate immediate sync for demo purposes
        # In production, this would be handled by background workers
        for assignment in assignments:
            device = assignment.device
            if not device:
                continue

            sync_record = DevicePlaylistSync.query.filter_by(
                device_id=device.id,
                playlist_id=playlist_id
            ).first()

            if sync_record:
                sync_record.mark_synced(playlist.version)

        # Mark playlist as synced
        playlist.mark_synced()

        # Bump pending_sync_version on all assigned devices for fast delivery
        for assignment in assignments:
            device = assignment.device
            if device:
                device.pending_sync_version = (device.pending_sync_version or 0) + 1

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        playlist.mark_sync_error()
        db.session.commit()
        return jsonify({
            'error': f'Failed to initiate sync: {str(e)}'
        }), 500

    # Log the push action
    log_action(
        action='playlist.push',
        action_category='playlists',
        resource_type='playlist',
        resource_id=playlist.id,
        resource_name=playlist.name,
        details={
            'device_count': len(assignments),
            'direct_devices': direct_devices,
            'hub_devices': hub_devices,
            'version': playlist.version,
        }
    )

    return jsonify({
        'message': 'Sync initiated',
        'playlist_id': playlist_id,
        'device_count': len(assignments),
        'synced_count': len(assignments),  # All synced in demo mode
        'direct_devices': direct_devices,
        'hub_devices': hub_devices,
        'sync_status': playlist.sync_status,
        'version': playlist.version,
        'last_synced_at': playlist.last_synced_at.isoformat() if playlist.last_synced_at else None
    }), 200


@playlists_bp.route('/<playlist_id>/sync-status', methods=['GET'])
@login_required
def get_playlist_sync_status(playlist_id):
    """
    Get the sync status for a playlist across all assigned devices.

    Returns detailed sync information including:
    - Overall playlist sync status
    - Number of devices synced vs total
    - Per-device sync details (optional)

    Args:
        playlist_id: Playlist UUID

    Query Parameters:
        include_devices: Include per-device sync details (default: false)

    Returns:
        200: Sync status details
            {
                "playlist_id": "uuid",
                "sync_status": "synced",
                "version": 3,
                "device_count": 5,
                "synced_count": 4,
                "pending_count": 1,
                "failed_count": 0,
                "last_synced_at": "2024-01-15T10:00:00Z",
                "devices": [...]  // Optional, if include_devices=true
            }
        404: Playlist not found
    """
    # Validate playlist_id format
    if not isinstance(playlist_id, str) or len(playlist_id) > 64:
        return jsonify({
            'error': 'Invalid playlist_id format'
        }), 400

    playlist = db.session.get(Playlist, playlist_id)

    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    # Get all device assignments for this playlist
    assignments = DeviceAssignment.query.filter_by(playlist_id=playlist_id).all()
    device_ids = [a.device_id for a in assignments if a.device_id]

    # Get sync records for assigned devices
    sync_records = DevicePlaylistSync.query.filter(
        DevicePlaylistSync.playlist_id == playlist_id,
        DevicePlaylistSync.device_id.in_(device_ids)
    ).all() if device_ids else []

    # Calculate counts
    synced_count = sum(1 for r in sync_records if r.sync_status == DeviceSyncStatus.SYNCED.value and r.is_up_to_date)
    pending_count = sum(1 for r in sync_records if r.sync_status in [DeviceSyncStatus.PENDING.value, DeviceSyncStatus.QUEUED.value, DeviceSyncStatus.SYNCING.value])
    failed_count = sum(1 for r in sync_records if r.sync_status == DeviceSyncStatus.FAILED.value)

    # Devices without sync records are considered pending
    untracked_count = len(device_ids) - len(sync_records)
    pending_count += untracked_count

    response = {
        'playlist_id': playlist_id,
        'sync_status': playlist.sync_status,
        'version': playlist.version,
        'device_count': len(device_ids),
        'synced_count': synced_count,
        'pending_count': pending_count,
        'failed_count': failed_count,
        'last_synced_at': playlist.last_synced_at.isoformat() if playlist.last_synced_at else None
    }

    # Optionally include per-device details
    include_devices = request.args.get('include_devices', 'false').lower() == 'true'
    if include_devices:
        devices_status = []
        for assignment in assignments:
            device = assignment.device
            if not device:
                continue

            sync_record = next((r for r in sync_records if r.device_id == device.id), None)

            device_status = {
                'device_id': device.id,
                'device_name': device.name or device.device_id,
                'mode': device.mode,
                'hub_id': device.hub_id,
                'sync_status': sync_record.sync_status if sync_record else 'pending',
                'synced_version': sync_record.synced_version if sync_record else None,
                'is_up_to_date': sync_record.is_up_to_date if sync_record else False,
                'last_sync_attempt': sync_record.last_sync_attempt.isoformat() if sync_record and sync_record.last_sync_attempt else None,
                'last_successful_sync': sync_record.last_successful_sync.isoformat() if sync_record and sync_record.last_successful_sync else None,
                'error_message': sync_record.error_message if sync_record else None
            }
            devices_status.append(device_status)

        response['devices'] = devices_status

    return jsonify(response), 200
