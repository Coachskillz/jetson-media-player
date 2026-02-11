"""
CMS Devices Routes

Blueprint for device management API endpoints:
- GET /<id>/playlist: Get playlist package for a device
- GET /: List all devices

All endpoints are prefixed with /api/v1/devices when registered with the app.
"""

import hashlib
from flask import Blueprint, request, jsonify
from cms.models import db


# Create devices blueprint
devices_bp = Blueprint('devices', __name__)


def _generate_package_hash(playlist_id, items):
    """Generate a hash for the playlist package content."""
    content = f"{playlist_id}:" + ",".join(
        f"{item['content_id']}:{item.get('file_hash', '')}" for item in items
    )
    return hashlib.sha256(content.encode()).hexdigest()[:16]


@devices_bp.route('/<device_id>/playlist', methods=['GET'])
def get_device_playlist(device_id):
    """
    Get the playlist for a specific device.

    Returns the playlist as a single named package.
    The playlist content is treated as one unit.

    Args:
        device_id: Device ID (e.g., 'jetson-8cf96efbb864')

    Returns:
        200: Playlist
            {
                "playlist": {
                    "name": "Morning Ads",
                    "version": 1,
                    "duration": 90,
                    "loop": true
                },
                "content_url": "/playlists/morning-ads/content"
            }
        404: Device not found
    """
    # 1. Check if device exists
    device_row = db.session.execute(
        db.text("SELECT id, name FROM devices WHERE id = :device_id"),
        {"device_id": device_id}
    ).fetchone()

    if not device_row:
        return jsonify({'error': 'Device not found'}), 404

    # 2. Get playlist assignment for this device
    playlist_assignment = db.session.execute(
        db.text("""
            SELECT dp.playlist_id, p.name, p.description, p.trigger_type
            FROM device_playlists dp
            JOIN playlists p ON dp.playlist_id = p.id
            WHERE dp.device_id = :device_id
            LIMIT 1
        """),
        {"device_id": device_id}
    ).fetchone()

    if not playlist_assignment:
        return jsonify({'playlist': None}), 200

    playlist_id = playlist_assignment[0]
    playlist_name = playlist_assignment[1]

    # 3. Calculate total duration
    duration_row = db.session.execute(
        db.text("""
            SELECT COALESCE(SUM(c.duration), 0)
            FROM playlist_items pi
            JOIN content c ON pi.content_id = c.id
            WHERE pi.playlist_id = :playlist_id
        """),
        {"playlist_id": playlist_id}
    ).fetchone()

    total_duration = int(duration_row[0]) if duration_row and duration_row[0] else 0

    # 4. Generate version hash
    items_rows = db.session.execute(
        db.text("""
            SELECT c.id FROM playlist_items pi
            JOIN content c ON pi.content_id = c.id
            WHERE pi.playlist_id = :playlist_id
            ORDER BY pi.position ASC
        """),
        {"playlist_id": playlist_id}
    ).fetchall()

    version_hash = _generate_package_hash(playlist_id, [{'content_id': r[0]} for r in items_rows])

    # Return clean playlist reference
    return jsonify({
        'playlist': {
            'name': playlist_name,
            'version': version_hash,
            'duration': total_duration,
            'loop': True
        },
        'content_url': f'/playlists/{playlist_id}/content'
    }), 200


@devices_bp.route('', methods=['GET'])
def list_devices():
    """
    List all registered devices.

    Returns:
        200: List of devices
            {
                "devices": [...],
                "count": 5
            }
    """
    devices_rows = db.session.execute(
        db.text("""
            SELECT id, name, location_id, paired, mac_address, last_seen, created_at
            FROM devices
            ORDER BY created_at DESC
        """)
    ).fetchall()

    devices = []
    for row in devices_rows:
        devices.append({
            'id': row[0],
            'name': row[1],
            'location_id': row[2],
            'paired': bool(row[3]),
            'mac_address': row[4],
            'last_seen': row[5],
            'created_at': row[6]
        })

    return jsonify({
        'devices': devices,
        'count': len(devices)
    }), 200


@devices_bp.route('/<device_id>', methods=['GET'])
def get_device(device_id):
    """
    Get a specific device by ID.

    Args:
        device_id: Device ID (e.g., 'jetson-8cf96efbb864')

    Returns:
        200: Device data
        404: Device not found
    """
    device_row = db.session.execute(
        db.text("""
            SELECT id, name, location_id, paired, mac_address, last_seen, created_at
            FROM devices
            WHERE id = :device_id
        """),
        {"device_id": device_id}
    ).fetchone()

    if not device_row:
        return jsonify({'error': 'Device not found'}), 404

    # Get assigned playlists
    playlists_rows = db.session.execute(
        db.text("""
            SELECT p.id, p.name, p.trigger_type
            FROM device_playlists dp
            JOIN playlists p ON dp.playlist_id = p.id
            WHERE dp.device_id = :device_id
        """),
        {"device_id": device_id}
    ).fetchall()

    playlists = [{'id': r[0], 'name': r[1], 'trigger_type': r[2]} for r in playlists_rows]

    return jsonify({
        'id': device_row[0],
        'name': device_row[1],
        'location_id': device_row[2],
        'paired': bool(device_row[3]),
        'mac_address': device_row[4],
        'last_seen': device_row[5],
        'created_at': device_row[6],
        'playlists': playlists
    }), 200


@devices_bp.route('/<device_id>/assign-playlist', methods=['POST'])
def assign_playlist_to_device(device_id):
    """
    Assign a playlist to a device.

    This replaces any existing playlist assignment for the device.

    Args:
        device_id: Device ID (e.g., 'jetson-8cf96efbb864')

    Request Body:
        {
            "playlist_id": 1
        }

    Returns:
        200: Playlist assigned successfully
        400: Missing playlist_id
        404: Device or playlist not found
    """
    from cms.services.hub_notifier import notify_playlist_updated

    data = request.get_json()
    if not data or 'playlist_id' not in data:
        return jsonify({'error': 'playlist_id is required'}), 400

    playlist_id = data['playlist_id']

    # Verify device exists
    device_row = db.session.execute(
        db.text("SELECT id FROM devices WHERE id = :device_id"),
        {"device_id": device_id}
    ).fetchone()

    if not device_row:
        return jsonify({'error': 'Device not found'}), 404

    # Verify playlist exists
    playlist_row = db.session.execute(
        db.text("SELECT id, name FROM playlists WHERE id = :playlist_id"),
        {"playlist_id": playlist_id}
    ).fetchone()

    if not playlist_row:
        return jsonify({'error': 'Playlist not found'}), 404

    # Remove existing assignment(s) for this device
    db.session.execute(
        db.text("DELETE FROM device_playlists WHERE device_id = :device_id"),
        {"device_id": device_id}
    )

    # Create new assignment
    db.session.execute(
        db.text("""
            INSERT INTO device_playlists (device_id, playlist_id)
            VALUES (:device_id, :playlist_id)
        """),
        {"device_id": device_id, "playlist_id": playlist_id}
    )
    db.session.commit()

    # Notify hubs about the playlist change
    notify_playlist_updated(
        device_id=device_id,
        playlist_id=playlist_id,
        action='assigned'
    )

    return jsonify({
        'status': 'ok',
        'device_id': device_id,
        'playlist_id': playlist_id,
        'playlist_name': playlist_row[1]
    }), 200
