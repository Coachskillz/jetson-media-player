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
import requests
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify

from cms.models import db, Hub, PendingHub, Network, Content, Playlist, Device
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

    return jsonify(hub.to_dict(include_token=True)), 201


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


@hubs_bp.route('/<hub_id>', methods=['DELETE'])
@login_required
def delete_hub(hub_id):
    """
    Delete a hub.

    Args:
        hub_id: Hub UUID or code

    Returns:
        200: Hub deleted successfully
        404: Hub not found
    """
    hub = db.session.get(Hub, hub_id)
    if not hub:
        hub = Hub.query.filter_by(code=hub_id).first()

    if not hub:
        return jsonify({'error': 'Hub not found'}), 404

    hub_name = hub.name
    hub_code = hub.code

    try:
        db.session.delete(hub)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete hub: {str(e)}'}), 500

    log_action(
        action='hub.delete',
        action_category='hubs',
        resource_type='hub',
        resource_id=hub_id,
        resource_name=hub_code,
        details={'name': hub_name}
    )

    return jsonify({'message': f'Hub {hub_name} deleted successfully'}), 200


@hubs_bp.route('/<hub_id>', methods=['PATCH'])
@login_required
def update_hub(hub_id):
    """
    Update a hub's status or other fields.

    Args:
        hub_id: Hub UUID or code

    Request Body:
        {
            "status": "online" | "offline" | "maintenance",
            "name": "New Name" (optional),
            "location": "New Address" (optional),
            "store_address": "123 Main St" (optional),
            "store_city": "Tampa" (optional),
            "store_state": "FL" (optional),
            "store_zipcode": "33601" (optional),
            "manager_name": "John Doe" (optional),
            "store_phone": "813-555-1234" (optional)
        }

    Returns:
        200: Updated hub data
        404: Hub not found
    """
    hub = db.session.get(Hub, hub_id)
    if not hub:
        hub = Hub.query.filter_by(code=hub_id).first()

    if not hub:
        return jsonify({'error': 'Hub not found'}), 404

    data = request.get_json(silent=True) or {}

    # Basic fields
    if 'status' in data:
        hub.status = data['status']
    if 'name' in data:
        hub.name = data['name']
    if 'location' in data:
        hub.location = data['location']

    # Store info fields
    store_info_changed = False
    store_fields = ['store_address', 'store_city', 'store_state', 'store_zipcode',
                    'manager_name', 'store_phone']
    for field in store_fields:
        if field in data:
            setattr(hub, field, data[field])
            store_info_changed = True

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update hub: {str(e)}'}), 500

    # Push store info update to Hub if it has an IP and store info changed
    if store_info_changed and hub.ip_address:
        _push_store_info_to_hub(hub, data)

    return jsonify(hub.to_dict()), 200


def _push_store_info_to_hub(hub, data):
    """
    Push store info update to the Hub.

    Args:
        hub: Hub model instance
        data: Dict with store fields
    """
    import logging
    logger = logging.getLogger(__name__)

    hub_url = f"http://{hub.ip_address}:5000"

    payload = {
        'store_name': hub.name,
        'store_address': hub.store_address,
        'store_city': hub.store_city,
        'store_state': hub.store_state,
        'store_zipcode': hub.store_zipcode,
        'manager_name': hub.manager_name,
        'store_phone': hub.store_phone,
    }

    try:
        response = requests.post(
            f"{hub_url}/api/v1/hub/update-store-info",
            json=payload,
            timeout=10
        )
        if response.ok:
            logger.info(f"Pushed store info update to hub {hub.code}")
        else:
            logger.warning(f"Hub {hub.code} returned {response.status_code} for store info update")
    except requests.Timeout:
        logger.warning(f"Timeout pushing store info to hub {hub.code}")
    except requests.RequestException as e:
        logger.error(f"Failed to push store info to hub {hub.code}: {e}")


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


# ============================================================================
# HUB PAIRING ENDPOINTS
# ============================================================================

@hubs_bp.route('/migrate-store-fields', methods=['POST'])
def migrate_store_fields():
    """
    Add store info columns to hubs table if they don't exist.

    This is a one-time migration endpoint to add new columns.
    Safe to call multiple times - checks if columns exist first.
    """
    from sqlalchemy import text

    columns_to_add = [
        ('store_address', 'VARCHAR(300)'),
        ('store_city', 'VARCHAR(100)'),
        ('store_state', 'VARCHAR(50)'),
        ('store_zipcode', 'VARCHAR(20)'),
        ('manager_name', 'VARCHAR(200)'),
        ('store_phone', 'VARCHAR(30)'),
    ]

    added = []
    skipped = []

    for col_name, col_type in columns_to_add:
        try:
            # Try to add the column
            db.session.execute(text(f'ALTER TABLE hubs ADD COLUMN {col_name} {col_type}'))
            db.session.commit()
            added.append(col_name)
        except Exception as e:
            db.session.rollback()
            if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                skipped.append(col_name)
            else:
                return jsonify({
                    'error': f'Failed to add {col_name}: {str(e)}'
                }), 500

    return jsonify({
        'success': True,
        'added': added,
        'skipped': skipped,
        'message': f'Added {len(added)} columns, skipped {len(skipped)} existing'
    })


@hubs_bp.route('/announce', methods=['POST'])
def announce_hub():
    """
    Hub calls this to announce itself and register pairing code.

    This is called by the hub software when it starts up and displays
    a pairing code on its screen. The hub remains in pending state
    until an admin enters the pairing code in the CMS UI.

    Request Body:
        {
            "hardware_id": "HUB-5A3F2B1C",
            "pairing_code": "A7X-9K2",
            "wan_ip": "76.23.45.189",
            "lan_ip": "10.10.10.1",
            "tunnel_url": "hub-001.skillzmedia.com",
            "version": "1.0.0"
        }

    Returns:
        200: Status response
            {"status": "pending", "message": "Waiting for admin to pair"}
            or
            {"status": "already_paired", "hub_id": "...", "store_name": "..."}
    """
    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    hardware_id = data.get('hardware_id')
    if not hardware_id:
        return jsonify({'error': 'hardware_id is required'}), 400

    pairing_code = data.get('pairing_code')
    if not pairing_code:
        return jsonify({'error': 'pairing_code is required'}), 400

    # Check if already paired
    existing = Hub.query.filter_by(hardware_id=hardware_id).first()
    if existing:
        # Update last heartbeat
        existing.last_heartbeat = datetime.now(timezone.utc)
        existing.status = 'online'
        if data.get('wan_ip'):
            existing.wan_ip = data.get('wan_ip')
        if data.get('tunnel_url'):
            existing.tunnel_url = data.get('tunnel_url')
        db.session.commit()

        return jsonify({
            'status': 'already_paired',
            'hub_id': existing.id,
            'hub_code': existing.code,
            'store_name': existing.name,
            'api_token': existing.api_token
        })

    # Create or update pending hub
    pending = PendingHub.query.filter_by(hardware_id=hardware_id).first()
    if pending:
        pending.pairing_code = pairing_code.upper().strip()
        pending.wan_ip = data.get('wan_ip')
        pending.lan_ip = data.get('lan_ip', '10.10.10.1')
        pending.tunnel_url = data.get('tunnel_url')
        pending.version = data.get('version')
        pending.expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    else:
        pending = PendingHub(
            hardware_id=hardware_id,
            pairing_code=pairing_code.upper().strip(),
            wan_ip=data.get('wan_ip'),
            lan_ip=data.get('lan_ip', '10.10.10.1'),
            tunnel_url=data.get('tunnel_url'),
            version=data.get('version'),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15)
        )
        db.session.add(pending)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to register hub: {str(e)}'}), 500

    return jsonify({
        'status': 'pending',
        'message': 'Waiting for admin to pair',
        'expires_in_minutes': 15
    })


@hubs_bp.route('/pairing-status', methods=['GET'])
def pairing_status():
    """
    Hub polls this to check if admin completed pairing.

    The hub software calls this periodically to check if an admin
    has entered the pairing code and completed the pairing process.

    Query Parameters:
        hardware_id: The hub's hardware identifier

    Returns:
        200: Pairing status
            If paired:
            {
                "status": "paired",
                "hub_id": "uuid",
                "hub_code": "WM",
                "api_token": "hub_xxxxx",
                "store_name": "West Marine Tampa",
                "network_id": "uuid"
            }
            If pending:
            {"status": "pending"}
            If unknown:
            {"status": "unknown"}
    """
    hardware_id = request.args.get('hardware_id')
    if not hardware_id:
        return jsonify({'error': 'hardware_id query parameter is required'}), 400

    # Check if paired
    hub = Hub.query.filter_by(hardware_id=hardware_id).first()
    if hub:
        hub.last_heartbeat = datetime.now(timezone.utc)
        hub.status = 'online'
        db.session.commit()

        return jsonify({
            'status': 'paired',
            'hub_id': hub.id,
            'hub_code': hub.code,
            'api_token': hub.api_token,
            'store_name': hub.name,
            'network_id': hub.network_id,
            # Store info for Hub to cache
            'store_address': hub.store_address,
            'store_city': hub.store_city,
            'store_state': hub.store_state,
            'store_zipcode': hub.store_zipcode,
            'manager_name': hub.manager_name,
            'store_phone': hub.store_phone,
        })

    # Check if pending
    pending = PendingHub.query.filter_by(hardware_id=hardware_id).first()
    if pending:
        # Check if expired
        if pending.expires_at:
            expires_at = pending.expires_at.replace(tzinfo=timezone.utc) if pending.expires_at.tzinfo is None else pending.expires_at
            if expires_at < datetime.now(timezone.utc):
                # Expired - generate new code
                return jsonify({
                    'status': 'expired',
                    'message': 'Pairing code expired. Restart hub to get new code.'
                })
        return jsonify({'status': 'pending'})

    return jsonify({'status': 'unknown'})


@hubs_bp.route('/pair', methods=['POST'])
@login_required
def pair_hub():
    """
    Admin enters pairing code to complete hub pairing.

    This is called from the CMS admin UI when an admin enters
    a pairing code displayed on a hub screen.

    Request Body:
        {
            "pairing_code": "A7X-9K2",
            "store_name": "West Marine Tampa",
            "network_id": "uuid-of-network",
            "existing_hub_id": "uuid-of-existing-hub" (optional - pair with existing store),
            "location": "123 Harbor Blvd, Tampa FL" (optional)
        }

    Returns:
        200: Hub paired successfully
            {
                "status": "paired",
                "hub_id": "uuid",
                "hub_code": "WM-TAMPA",
                "store_name": "West Marine Tampa",
                "message": "Hub paired successfully as West Marine Tampa"
            }
        400: Invalid or expired pairing code
            {"error": "Invalid or expired pairing code"}
        404: Network not found
            {"error": "Network not found"}
    """
    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    pairing_code = data.get('pairing_code', '').upper().strip()
    if not pairing_code:
        return jsonify({'error': 'pairing_code is required'}), 400

    network_id = data.get('network_id')
    if not network_id:
        return jsonify({'error': 'network_id is required'}), 400

    # Check for existing hub to pair with
    existing_hub_id = data.get('existing_hub_id')
    store_name = data.get('store_name')

    if not existing_hub_id and not store_name:
        return jsonify({'error': 'Either existing_hub_id or store_name is required'}), 400

    # Verify network exists
    network = db.session.get(Network, network_id)
    if not network:
        return jsonify({'error': 'Network not found'}), 404

    # Find pending hub with this code (not expired)
    pending = PendingHub.query.filter_by(pairing_code=pairing_code).first()

    if not pending:
        return jsonify({'error': 'Invalid pairing code'}), 400

    # Check expiration
    if pending.expires_at:
        expires_at = pending.expires_at.replace(tzinfo=timezone.utc) if pending.expires_at.tzinfo is None else pending.expires_at
        if expires_at < datetime.now(timezone.utc):
            return jsonify({'error': 'Pairing code has expired'}), 400

    # If pairing with existing hub, update it
    if existing_hub_id:
        hub = db.session.get(Hub, existing_hub_id)
        if not hub:
            return jsonify({'error': 'Existing hub not found'}), 404

        if hub.hardware_id:
            return jsonify({'error': 'This store is already paired with a device'}), 400

        # Update existing hub with hardware info
        hub.hardware_id = pending.hardware_id
        hub.ip_address = pending.lan_ip
        hub.wan_ip = pending.wan_ip
        hub.tunnel_url = pending.tunnel_url
        hub.version = pending.version
        hub.api_token = hub.api_token or f"hub_{secrets.token_urlsafe(32)}"
        hub.status = 'online'
        hub.last_heartbeat = datetime.now(timezone.utc)
        hub.paired_at = datetime.now(timezone.utc)
        # Update store info if provided
        if data.get('store_address'):
            hub.store_address = data.get('store_address')
        if data.get('store_city'):
            hub.store_city = data.get('store_city')
        if data.get('store_state'):
            hub.store_state = data.get('store_state')
        if data.get('store_zipcode'):
            hub.store_zipcode = data.get('store_zipcode')
        if data.get('manager_name'):
            hub.manager_name = data.get('manager_name')
        if data.get('store_phone'):
            hub.store_phone = data.get('store_phone')
    else:
        # Create new hub
        # Generate hub code based on network and store name
        network_code = network.slug.upper()[:4] if network.slug else 'XX'
        store_slug = re.sub(r'[^A-Z0-9]', '', store_name.upper())[:12]
        hub_code = f"{network_code}-{store_slug}"

        # Ensure unique code
        existing_code = Hub.query.filter_by(code=hub_code).first()
        if existing_code:
            # Append hardware ID suffix
            hub_code = f"{hub_code}-{pending.hardware_id[-4:]}"

        # Generate API token
        api_token = f"hub_{secrets.token_urlsafe(32)}"

        # Create paired hub
        hub = Hub(
            code=hub_code,
            name=store_name,
            network_id=network_id,
            hardware_id=pending.hardware_id,
            ip_address=pending.lan_ip,
            wan_ip=pending.wan_ip,
            tunnel_url=pending.tunnel_url,
            version=pending.version,
            api_token=api_token,
            status='online',
            last_heartbeat=datetime.now(timezone.utc),
            paired_at=datetime.now(timezone.utc),
            location=data.get('location'),
            # Store info from pairing request
            store_address=data.get('store_address'),
            store_city=data.get('store_city'),
            store_state=data.get('store_state'),
            store_zipcode=data.get('store_zipcode'),
            manager_name=data.get('manager_name'),
            store_phone=data.get('store_phone'),
        )
        db.session.add(hub)

    try:
        # Remove from pending
        db.session.delete(pending)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to pair hub: {str(e)}'}), 500

    # Log hub pairing
    log_action(
        action='hub.pair',
        action_category='hubs',
        resource_type='hub',
        resource_id=hub.id,
        resource_name=hub.code,
        details={
            'store_name': hub.name,
            'network_id': network_id,
            'network_name': network.name,
            'hardware_id': hub.hardware_id,
            'existing_hub': existing_hub_id is not None
        }
    )

    return jsonify({
        'status': 'paired',
        'hub_id': hub.id,
        'hub_code': hub.code,
        'store_name': hub.name,
        'api_token': hub.api_token,
        'network_id': hub.network_id,
        'store_address': hub.store_address,
        'store_city': hub.store_city,
        'store_state': hub.store_state,
        'store_zipcode': hub.store_zipcode,
        'manager_name': hub.manager_name,
        'store_phone': hub.store_phone,
        'message': f'Hub paired successfully as {hub.name}'
    })


@hubs_bp.route('/heartbeat', methods=['POST'])
def global_heartbeat():
    """
    Receive heartbeat from a hub (global endpoint).

    This endpoint allows hubs to send heartbeats without including hub_id in the URL.
    The hub identifies itself via the hub_id in the request body or via Bearer token.

    Request Body:
        {
            "hub_id": "uuid-of-hub",
            "hub_status": "online",
            "screens": [...],
            "uptime_seconds": 3600,
            "pending_alerts_count": 0
        }

    Returns:
        200: Heartbeat received
        400: Missing hub_id
        404: Hub not found
    """
    data = request.get_json(silent=True) or {}

    # Get hub_id from request body
    hub_id = data.get('hub_id')

    # If not in body, try to get from Authorization header (Bearer token lookup)
    if not hub_id:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            hub = Hub.query.filter_by(api_token=token).first()
            if hub:
                hub_id = hub.id

    if not hub_id:
        return jsonify({'error': 'hub_id is required'}), 400

    # Find hub
    hub = db.session.get(Hub, hub_id)
    if not hub:
        hub = Hub.query.filter_by(code=hub_id).first()

    if not hub:
        return jsonify({'error': 'Hub not found', 'hub_id': hub_id}), 404

    # Update hub status
    hub.last_heartbeat = datetime.now(timezone.utc)
    hub.status = data.get('hub_status', 'online')

    if data.get('screens_connected') is not None:
        hub.screens_connected = data.get('screens_connected')

    # Process device heartbeats if included
    screens = data.get('screens', [])
    processed = 0
    errors = []

    for screen in screens:
        device_id = screen.get('screen_id') or screen.get('device_id')
        if not device_id:
            continue

        device = Device.query.filter_by(device_id=str(device_id)).first()
        if device:
            device.last_seen = datetime.now(timezone.utc)
            if screen.get('status'):
                device.status = screen.get('status')
            processed += 1
        else:
            errors.append(f'Device {device_id} not found')

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to process heartbeat: {str(e)}'}), 500

    return jsonify({
        'ack': True,
        'hub_id': hub.id,
        'hub_status': hub.status,
        'processed_screens': processed,
        'errors': errors if errors else None
    }), 200


@hubs_bp.route('/pending', methods=['GET'])
@login_required
def list_pending_hubs():
    """
    List all pending hubs awaiting pairing.

    Returns all hubs that have announced themselves but have not
    yet been paired by an admin.

    Returns:
        200: List of pending hubs
            {
                "pending_hubs": [...],
                "count": 2
            }
    """
    # Get non-expired pending hubs
    now = datetime.now(timezone.utc)
    pending_hubs = PendingHub.query.filter(
        (PendingHub.expires_at > now) | (PendingHub.expires_at.is_(None))
    ).order_by(PendingHub.created_at.desc()).all()

    return jsonify({
        'pending_hubs': [hub.to_dict() for hub in pending_hubs],
        'count': len(pending_hubs)
    })


@hubs_bp.route('/<hub_id>/push-device-update', methods=['POST'])
@login_required
def push_device_update(hub_id):
    """
    Push device update (screen_location, name, etc.) to Hub.

    Called when admin updates a device in CMS. The Hub needs to know
    about device changes to display on its dashboard.

    Args:
        hub_id: Hub UUID

    Request Body:
        {
            "device_id": "uuid-of-device",
            "screen_location": "Entrance",
            "name": "Front Door Screen"
        }

    Returns:
        200: Update pushed successfully
        404: Hub not found
        400: Hub IP not available
    """
    hub = db.session.get(Hub, hub_id)
    if not hub:
        return jsonify({'error': 'Hub not found'}), 404

    data = request.get_json(silent=True) or {}
    device_id = data.get('device_id')

    if not device_id:
        return jsonify({'error': 'device_id is required'}), 400

    # Get Hub's URL from IP address
    if not hub.ip_address:
        return jsonify({'error': 'Hub IP not available'}), 400

    hub_url = f"http://{hub.ip_address}:5000"

    # Push update to Hub
    try:
        response = requests.post(
            f"{hub_url}/api/v1/devices/update-from-cms",
            json={
                'device_id': device_id,
                'screen_location': data.get('screen_location'),
                'name': data.get('name'),
            },
            timeout=10
        )

        if response.ok:
            return jsonify({'success': True, 'message': 'Update pushed to hub'})
        else:
            return jsonify({
                'success': False,
                'error': f'Hub returned {response.status_code}'
            }), response.status_code

    except requests.Timeout:
        return jsonify({'error': 'Hub request timed out'}), 504
    except requests.RequestException as e:
        return jsonify({'error': f'Failed to reach hub: {str(e)}'}), 502


@hubs_bp.route('/<hub_id>/push-layout', methods=['POST'])
@login_required
def push_layout(hub_id):
    """
    Push a layout with playlist/content to a Hub for a specific device.

    This endpoint builds the full layout payload including:
    - Layout canvas settings
    - Layers with their positions and configurations
    - Playlist items with content download URLs
    - Content metadata (filename, duration, file_size, etc.)

    The Hub receives this and caches the content, then pushes to the device.

    Args:
        hub_id: Hub UUID

    Request Body:
        {
            "device_id": "uuid-of-device",
            "layout_id": "uuid-of-layout"
        }

    Returns:
        200: Layout pushed successfully
        404: Hub, device, or layout not found
        400: Missing required fields or Hub IP not available
    """
    from cms.models.layout import ScreenLayout, ScreenLayer

    hub = db.session.get(Hub, hub_id)
    if not hub:
        return jsonify({'error': 'Hub not found'}), 404

    data = request.get_json(silent=True) or {}
    device_id = data.get('device_id')
    layout_id = data.get('layout_id')

    if not device_id:
        return jsonify({'error': 'device_id is required'}), 400

    if not layout_id:
        return jsonify({'error': 'layout_id is required'}), 400

    # Get device
    device = Device.query.filter_by(id=device_id).first()
    if not device:
        return jsonify({'error': 'Device not found'}), 404

    # Get layout with layers
    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Get Hub's URL
    if not hub.ip_address:
        return jsonify({'error': 'Hub IP not available'}), 400

    hub_url = f"http://{hub.ip_address}:5000"

    # Build layout payload
    layers_data = []
    content_items = []

    for layer in layout.layers.order_by(ScreenLayer.z_index).all():
        layer_data = layer.to_dict()

        # If layer has a playlist, include playlist items with content
        if layer.playlist_id and layer.playlist:
            playlist = layer.playlist
            playlist_items = []

            for item in playlist.items:
                item_data = {
                    'id': item.id,
                    'order': item.order,
                    'duration': item.duration,
                }

                # Get content details
                if item.content:
                    content = item.content
                    content_data = {
                        'id': content.id,
                        'filename': content.filename,
                        'file_type': content.file_type,
                        'duration': content.duration,
                        'file_size': content.file_size,
                        'download_url': f'/api/v1/content/{content.id}/download',
                    }
                    item_data['content'] = content_data

                    # Track content for manifest
                    if content.id not in [c['id'] for c in content_items]:
                        content_items.append(content_data)

                playlist_items.append(item_data)

            layer_data['playlist'] = {
                'id': playlist.id,
                'name': playlist.name,
                'items': playlist_items
            }

        layers_data.append(layer_data)

    # Build full layout payload
    layout_payload = {
        'device_id': device_id,
        'device_hardware_id': device.hardware_id,
        'layout': {
            'id': layout.id,
            'name': layout.name,
            'canvas_width': layout.canvas_width,
            'canvas_height': layout.canvas_height,
            'orientation': layout.orientation,
            'background_type': layout.background_type,
            'background_color': layout.background_color,
            'layers': layers_data
        },
        'content_manifest': content_items
    }

    # Push to Hub
    try:
        response = requests.post(
            f"{hub_url}/api/v1/layouts/receive",
            json=layout_payload,
            timeout=30  # Longer timeout for layout push
        )

        if response.ok:
            return jsonify({
                'success': True,
                'message': 'Layout pushed to hub',
                'content_count': len(content_items)
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Hub returned {response.status_code}',
                'details': response.text
            }), response.status_code

    except requests.Timeout:
        return jsonify({'error': 'Hub request timed out'}), 504
    except requests.RequestException as e:
        return jsonify({'error': f'Failed to reach hub: {str(e)}'}), 502