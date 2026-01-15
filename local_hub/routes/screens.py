"""
Screen management API endpoints.

This module provides REST API endpoints for Jetson screen management:
- POST /screens/register - Register a new screen or return existing
- GET /screens/{id}/config - Get screen configuration
- POST /screens/{id}/heartbeat - Update screen heartbeat

All endpoints are prefixed with /api/v1 when registered with the app.
"""

from datetime import datetime

from flask import jsonify, request

from models import db, Screen
from routes import screens_bp


@screens_bp.route('/register', methods=['POST'])
def register_screen():
    """
    Register a new screen or return existing screen.

    Jetson screens call this endpoint on boot to register with the hub.
    If a screen with the given hardware_id already exists, returns
    the existing screen and updates its heartbeat timestamp.

    Request Body:
        {
            "hardware_id": "unique-hardware-id",
            "name": "optional screen name"
        }

    Returns:
        201: New screen created
            {
                "success": true,
                "message": "Screen registered",
                "screen": { screen data },
                "created": true
            }
        200: Existing screen returned
            {
                "success": true,
                "message": "Screen already registered",
                "screen": { screen data },
                "created": false
            }
        400: Missing required field
            {
                "success": false,
                "error": "hardware_id is required"
            }
    """
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
    if not isinstance(hardware_id, str) or len(hardware_id) > 64:
        return jsonify({
            'success': False,
            'error': 'hardware_id must be a string with max 64 characters'
        }), 400

    name = data.get('name')
    if name and (not isinstance(name, str) or len(name) > 128):
        return jsonify({
            'success': False,
            'error': 'name must be a string with max 128 characters'
        }), 400

    # Register or get existing screen
    screen, created = Screen.register(hardware_id, name)

    if created:
        return jsonify({
            'success': True,
            'message': 'Screen registered',
            'screen': screen.to_dict(),
            'created': True
        }), 201
    else:
        return jsonify({
            'success': True,
            'message': 'Screen already registered',
            'screen': screen.to_dict(),
            'created': False
        }), 200


@screens_bp.route('/<int:screen_id>/config', methods=['GET'])
def get_screen_config(screen_id):
    """
    Get configuration for a specific screen.

    Jetson screens call this endpoint to retrieve their configuration
    including feature flags, playlist assignments, and database versions.

    Args:
        screen_id: Screen ID from registration

    Returns:
        200: Screen configuration
            {
                "success": true,
                "config": {
                    "screen_id": 1,
                    "playlist_id": "playlist-123",
                    "camera_enabled": false,
                    "loyalty_enabled": false,
                    "ncmec_enabled": true,
                    "ncmec_db_version": "v1.0.0",
                    "loyalty_db_version": null
                }
            }
        404: Screen not found
            {
                "success": false,
                "error": "Screen not found"
            }
    """
    screen = db.session.get(Screen, screen_id)

    if not screen:
        return jsonify({
            'success': False,
            'error': 'Screen not found'
        }), 404

    return jsonify({
        'success': True,
        'config': screen.to_config_dict()
    }), 200


@screens_bp.route('/<int:screen_id>/heartbeat', methods=['POST'])
def screen_heartbeat(screen_id):
    """
    Receive heartbeat from a screen.

    Jetson screens send heartbeats periodically to indicate they are
    online and functioning. This updates the screen's last_heartbeat
    timestamp and sets status to 'online'.

    Screens that don't send heartbeats for 2 minutes are marked offline
    by the screen monitor service.

    Args:
        screen_id: Screen ID from registration

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
        404: Screen not found
            {
                "success": false,
                "error": "Screen not found"
            }
    """
    screen = db.session.get(Screen, screen_id)

    if not screen:
        return jsonify({
            'success': False,
            'error': 'Screen not found'
        }), 404

    # Update heartbeat timestamp and status
    screen.update_heartbeat()

    return jsonify({
        'success': True,
        'message': 'Heartbeat received',
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }), 200


@screens_bp.route('', methods=['GET'])
def list_screens():
    """
    List all registered screens.

    Returns a list of all screens registered with this hub,
    including their current status.

    Query Parameters:
        status: Filter by status (online, offline)

    Returns:
        200: List of screens
            {
                "success": true,
                "screens": [ { screen data }, ... ],
                "count": 5
            }
    """
    status_filter = request.args.get('status')

    if status_filter == 'online':
        screens = Screen.get_all_online()
    elif status_filter == 'offline':
        screens = Screen.get_all_offline()
    else:
        screens = Screen.query.all()

    return jsonify({
        'success': True,
        'screens': [screen.to_dict() for screen in screens],
        'count': len(screens)
    }), 200
