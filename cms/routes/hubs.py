"""
CMS Hubs Routes

Blueprint for hub management API endpoints:
- POST /register: Register a new hub
- GET /: List all hubs
- GET /<hub_id>: Get a specific hub
- GET /<hub_id>/content-manifest: Get hub content manifest
- GET /<hub_id>/playlists: Get hub playlist manifest
- PUT /<hub_id>/approve: Approve a pending hub
- POST /<hub_id>/heartbeats: Receive batched device heartbeats

All endpoints are prefixed with /api/v1/hubs when registered with the app.
"""

import re
import secrets
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify

from cms.models import db, Hub, Network, Content, Playlist, Device
from cms.utils.auth import login_required
from cms.utils.audit import log_action


# Create hubs blueprint
hubs_bp = Blueprint('hubs', __name__)


@hubs_bp.route('/register', methods=['POST'])
def register_hub():
    """
    Register a new hub.

    Hubs are physical locations that contain multiple devices/screens.
    Each hub has a unique code (2-4 uppercase letters) that is used in
    device IDs for devices connected through that hub.

    Upon registration, the hub receives an API token for authenticating
    future requests to the CMS (content sync, heartbeats, etc.).

    Request Body:
        {
            "code": "WM" (required, 2-4 uppercase letters),
            "name": "West Marine Hub" (required),
            "network_id": "uuid-of-network" (required),
            "location": "123 Main St" (optional),
            "ip_address": "192.168.1.100" (optional, IPv4 or IPv6),
            "mac_address": "AA:BB:CC:DD:EE:FF" (optional),
            "hostname": "hub-westmarine" (optional)
        }

    Returns:
        201: New hub created
            {
                "id": "uuid",
                "code": "WM",
                "name": "West Marine Hub",
                "status": "pending",
                "api_token": "hub_...",
                "created_at": "2024-01-15T10:00:00Z"
            }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
        409: Hub with code already exists
            {
                "error": "Hub with code 'WM' already exists"
            }
    """
    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate code
    code = data.get('code')
    if not code:
        return jsonify({'error': 'code is required'}), 400

    # Validate code format: 2-4 uppercase letters
    if not isinstance(code, str) or not re.match(r'^[A-Z]{2,4}$', code):
        return jsonify({
            'error': 'code must be 2-4 uppercase letters (e.g., WM, HON)'
        }), 400

    # Check if hub with this code already exists
    existing_hub = Hub.query.filter_by(code=code).first()
    if existing_hub:
        return jsonify({
            'error': f"Hub with code '{code}' already exists"
        }), 409

    # Validate name
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400

    if not isinstance(name, str) or len(name) > 200:
        return jsonify({
            'error': 'name must be a string with max 200 characters'
        }), 400

    # Validate network_id
    network_id = data.get('network_id')
    if not network_id:
        return jsonify({'error': 'network_id is required'}), 400

    network = db.session.get(Network, network_id)
    if not network:
        return jsonify({
            'error': f'Network with id {network_id} not found'
        }), 404

    # Validate optional location
    location = data.get('location')
    if location and (not isinstance(location, str) or len(location) > 500):
        return jsonify({
            'error': 'location must be a string with max 500 characters'
        }), 400

    # Validate optional ip_address
    ip_address = data.get('ip_address')
    if ip_address:
        if not isinstance(ip_address, str) or len(ip_address) > 45:
            return jsonify({
                'error': 'ip_address must be a string with max 45 characters'
            }), 400

    # Validate optional mac_address
    mac_address = data.get('mac_address')
    if mac_address:
        if not isinstance(mac_address, str) or len(mac_address) > 17:
            return jsonify({
                'error': 'mac_address must be a string with max 17 characters'
            }), 400
        # Validate MAC address format (XX:XX:XX:XX:XX:XX)
        mac_pattern = r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$'
        if not re.match(mac_pattern, mac_address):
            return jsonify({
                'error': 'mac_address must be in format XX:XX:XX:XX:XX:XX'
            }), 400

    # Validate optional hostname
    hostname = data.get('hostname')
    if hostname:
        if not isinstance(hostname, str) or len(hostname) > 255:
            return jsonify({
                'error': 'hostname must be a string with max 255 characters'
            }), 400

    # Generate API token for hub authentication
    # Format: hub_{random_token} for easy identification
    api_token = f"hub_{secrets.token_urlsafe(32)}"

    # Create new hub with all fields
    hub = Hub(
        code=code,
        name=name,
        network_id=network_id,
        status='pending',
        ip_address=ip_address,
        mac_address=mac_address.upper() if mac_address else None,
        hostname=hostname,
        api_token=api_token
    )

    try:
        db.session.add(hub)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create hub: {str(e)}'
        }), 500

    # Log hub registration (hub-initiated action)
    # Note: api_token is intentionally NOT logged for security
    log_action(
        action='hub.register',
        action_category='hubs',
        resource_type='hub',
        resource_id=hub.id,
        resource_name=hub.code,
        user_email='hub',
        details={
            'code': code,
            'name': name,
            'network_id': network_id,
            'network_name': network.name,
            'ip_address': ip_address,
            'hostname': hostname,
        }
    )

    return jsonify(hub.to_dict()), 201


@hubs_bp.route('', methods=['GET'])
@login_required
def list_hubs():
    """
    List all registered hubs.

    Returns a list of all hubs registered with the CMS,
    with optional filtering by status or network.

    Query Parameters:
        status: Filter by status (pending, active, inactive)
        network_id: Filter by network UUID

    Returns:
        200: List of hubs
            {
                "hubs": [ { hub data }, ... ],
                "count": 5
            }
    """
    # Build query with optional filters
    query = Hub.query

    # Filter by status
    status_filter = request.args.get('status')
    if status_filter:
        query = query.filter_by(status=status_filter)

    # Filter by network
    network_id = request.args.get('network_id')
    if network_id:
        query = query.filter_by(network_id=network_id)

    # Execute query
    hubs = query.order_by(Hub.created_at.desc()).all()

    return jsonify({
        'hubs': [hub.to_dict() for hub in hubs],
        'count': len(hubs)
    }), 200


@hubs_bp.route('/<hub_id>', methods=['GET'])
@login_required
def get_hub(hub_id):
    """
    Get a specific hub by ID.

    Args:
        hub_id: Hub UUID or code

    Returns:
        200: Hub data
            { hub data }
        404: Hub not found
            {
                "error": "Hub not found"
            }
    """
    # Try to find hub by UUID first, then by code
    hub = db.session.get(Hub, hub_id)
    if not hub:
        hub = Hub.query.filter_by(code=hub_id).first()

    if not hub:
        return jsonify({'error': 'Hub not found'}), 404

    return jsonify(hub.to_dict()), 200


@hubs_bp.route('/<hub_id>/content-manifest', methods=['GET'])
def get_content_manifest(hub_id):
    """
    Get content manifest for a hub.

    Returns a list of all content available for devices connected
    to this hub. The manifest includes URLs for content download
    and metadata needed for caching and playback.

    Args:
        hub_id: Hub UUID or code

    Returns:
        200: Content manifest
            {
                "hub_id": "uuid",
                "manifest_version": 1,
                "content": [
                    {
                        "id": "uuid",
                        "filename": "promo1.mp4",
                        "url": "/api/v1/content/uuid/download",
                        "mime_type": "video/mp4",
                        "file_size": 52428800
                    }
                ]
            }
        404: Hub not found
            {
                "error": "Hub not found"
            }
    """
    # Try to find hub by UUID first, then by code
    hub = db.session.get(Hub, hub_id)
    if not hub:
        hub = Hub.query.filter_by(code=hub_id).first()

    if not hub:
        return jsonify({'error': 'Hub not found'}), 404

    # Get all content for the hub's network
    content_items = []
    if hub.network_id:
        content_list = Content.query.filter_by(network_id=hub.network_id).all()
        for content in content_list:
            manifest_item = content.to_manifest_item()
            # Add download URL
            manifest_item['url'] = f'/api/v1/content/{content.id}/download'
            content_items.append(manifest_item)

    return jsonify({
        'hub_id': hub.id,
        'hub_code': hub.code,
        'network_id': hub.network_id,
        'manifest_version': 1,
        'content': content_items,
        'count': len(content_items)
    }), 200


@hubs_bp.route('/<hub_id>/playlists', methods=['GET'])
def get_hub_playlists(hub_id):
    """
    Get playlist manifest for a hub.

    Returns a list of all playlists available for devices connected
    to this hub. The manifest includes playlist metadata and items
    needed for local caching and playback scheduling.

    Args:
        hub_id: Hub UUID or code

    Returns:
        200: Playlist manifest
            {
                "hub_id": "uuid",
                "hub_code": "WM",
                "network_id": "uuid",
                "manifest_version": 1,
                "playlists": [
                    {
                        "id": "uuid",
                        "name": "Morning Playlist",
                        "trigger_type": "time",
                        "trigger_config": "...",
                        "is_active": true,
                        "items": [ ... ]
                    }
                ],
                "count": 5
            }
        404: Hub not found
            {
                "error": "Hub not found"
            }
    """
    # Try to find hub by UUID first, then by code
    hub = db.session.get(Hub, hub_id)
    if not hub:
        hub = Hub.query.filter_by(code=hub_id).first()

    if not hub:
        return jsonify({'error': 'Hub not found'}), 404

    # Get all playlists for the hub's network
    playlists = []
    if hub.network_id:
        playlist_list = Playlist.get_active_by_network(hub.network_id)
        playlists = [playlist.to_dict_with_items() for playlist in playlist_list]

    return jsonify({
        'hub_id': hub.id,
        'hub_code': hub.code,
        'network_id': hub.network_id,
        'manifest_version': 1,
        'playlists': playlists,
        'count': len(playlists)
    }), 200


@hubs_bp.route('/<hub_id>/approve', methods=['PUT'])
@login_required
def approve_hub(hub_id):
    """
    Approve a pending hub.

    CMS admins use this endpoint to approve hubs that have registered
    with the system. Only approved hubs can receive content and playlists.

    Args:
        hub_id: Hub UUID or code

    Returns:
        200: Hub approved successfully
            { hub data with status: "active" }
        400: Hub not in pending state
            {
                "error": "Hub is not in pending state"
            }
        404: Hub not found
            {
                "error": "Hub not found"
            }
    """
    # Try to find hub by UUID first, then by code
    hub = db.session.get(Hub, hub_id)
    if not hub:
        hub = Hub.query.filter_by(code=hub_id).first()

    if not hub:
        return jsonify({'error': 'Hub not found'}), 404

    if hub.status != 'pending':
        return jsonify({'error': 'Hub is not in pending state'}), 400

    hub.status = 'active'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to approve hub: {str(e)}'
        }), 500

    # Log hub approval
    log_action(
        action='hub.approve',
        action_category='hubs',
        resource_type='hub',
        resource_id=hub.id,
        resource_name=hub.code,
    )

    return jsonify(hub.to_dict()), 200


@hubs_bp.route('/<hub_id>/heartbeats', methods=['POST'])
def receive_heartbeats(hub_id):
    """
    Receive batched device heartbeats from a hub.

    Hubs collect device heartbeats and send them in batches to reduce
    network traffic. This endpoint receives the batch, updates device
    last_seen timestamps, and updates the hub's last_heartbeat.

    Args:
        hub_id: Hub UUID or code

    Request Body:
        {
            "heartbeats": [
                {
                    "device_id": "SKZ-H-WM-0001" (required),
                    "status": "active" (optional),
                    "timestamp": "2024-01-15T10:00:00Z" (optional, defaults to now)
                },
                ...
            ]
        }

    Returns:
        200: Heartbeats processed successfully
            {
                "processed": 5,
                "errors": [],
                "hub_last_heartbeat": "2024-01-15T10:00:00Z"
            }
        400: Invalid request body
            {
                "error": "error message"
            }
        404: Hub not found
            {
                "error": "Hub not found"
            }
    """
    # Try to find hub by UUID first, then by code
    hub = db.session.get(Hub, hub_id)
    if not hub:
        hub = Hub.query.filter_by(code=hub_id).first()

    if not hub:
        return jsonify({'error': 'Hub not found'}), 404

    # Validate request body
    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    heartbeats = data.get('heartbeats')
    if heartbeats is None:
        return jsonify({'error': 'heartbeats field is required'}), 400

    if not isinstance(heartbeats, list):
        return jsonify({'error': 'heartbeats must be an array'}), 400

    # Process each heartbeat
    processed = 0
    errors = []

    for i, heartbeat in enumerate(heartbeats):
        if not isinstance(heartbeat, dict):
            errors.append(f'Heartbeat at index {i} must be an object')
            continue

        device_id = heartbeat.get('device_id')
        if not device_id:
            errors.append(f'Heartbeat at index {i} is missing device_id')
            continue

        # Find the device
        device = Device.query.filter_by(device_id=device_id).first()
        if not device:
            errors.append(f'Device {device_id} not found')
            continue

        # Parse timestamp if provided, otherwise use current time
        timestamp_str = heartbeat.get('timestamp')
        if timestamp_str:
            try:
                # Parse ISO format timestamp
                heartbeat_time = datetime.fromisoformat(
                    timestamp_str.replace('Z', '+00:00')
                )
            except (ValueError, AttributeError):
                errors.append(f'Invalid timestamp for device {device_id}')
                continue
        else:
            heartbeat_time = datetime.now(timezone.utc)

        # Update device last_seen
        device.last_seen = heartbeat_time

        # Update device status if provided
        status = heartbeat.get('status')
        if status and isinstance(status, str) and status in ['active', 'offline', 'error']:
            device.status = status

        processed += 1

    # Update hub's last_heartbeat timestamp
    hub.last_heartbeat = datetime.now(timezone.utc)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to process heartbeats: {str(e)}'
        }), 500

    return jsonify({
        'processed': processed,
        'errors': errors,
        'hub_last_heartbeat': hub.last_heartbeat.isoformat()
    }), 200
