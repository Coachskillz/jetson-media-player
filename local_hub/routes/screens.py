"""
Screen management API endpoints.

This module provides REST API endpoints for Jetson screen management:
- POST /screens/register - Register a new screen or return existing
- GET /screens/{id}/config - Get screen configuration
- GET /screens/by-device/{id}/config - Get full config with playlist for Jetson
- POST /screens/{id}/heartbeat - Update screen heartbeat

All endpoints are prefixed with /api/v1 when registered with the app.
"""

import json
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
        200: Existing screen returned
        400: Missing required field
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


@screens_bp.route('/by-device/<screen_id>/config', methods=['GET'])
def get_screen_config_by_device(screen_id):
    """
    Get configuration for a Jetson screen including playlist.

    Returns playlist as a named package - device doesn't see individual files.

    Args:
        screen_id: Screen identifier (hardware_id or integer id)

    Returns:
        200: Screen configuration with playlist
            {
                "device_id": "1",
                "hardware_id": "jetson-xxx",
                "playlist": {
                    "name": "Morning Ads",
                    "version": "abc123",
                    "duration": 90,
                    "loop": true
                },
                "content_path": "/playlists/morning-ads"
            }
        404: Screen not found
    """
    # Try to find screen by hardware_id first, then by integer id
    screen = Screen.query.filter_by(hardware_id=screen_id).first()

    if not screen:
        try:
            screen_int_id = int(screen_id)
            screen = db.session.get(Screen, screen_int_id)
        except (ValueError, TypeError):
            pass

    if not screen:
        return jsonify({
            'success': False,
            'error': 'Screen not found'
        }), 404

    # Get cached playlist for this screen (with staging items for content download)
    playlist_data = _get_playlist_for_screen(screen, include_staging=True)

    # Build response - includes staging info for Jetson to download content
    response = {
        'device_id': str(screen.id),
        'hardware_id': screen.hardware_id,
        'name': screen.name,
        'status': screen.status,
        'camera_enabled': screen.camera_enabled,
        'ncmec_enabled': screen.ncmec_enabled,
        'loyalty_enabled': screen.loyalty_enabled,
    }

    if playlist_data.get('name'):
        response['playlist'] = {
            'name': playlist_data.get('name'),
            'version': playlist_data.get('version', '1'),
            'duration': playlist_data.get('duration', 0),
            'loop': True
        }
        response['content_path'] = f"/playlists/{playlist_data.get('playlist_id', 'default')}"

        # Include staging items for Jetson to download content
        # The playlist is treated as a unit - these items are internal staging info
        staging_items = playlist_data.get('staging_items', [])
        if staging_items:
            response['_staging'] = {
                'items': staging_items
            }
    else:
        response['playlist'] = None
        response['content_path'] = None

    return jsonify(response), 200


def _get_playlist_for_screen(screen, include_staging=False):
    """
    Get the playlist data for a screen.

    Returns playlist as a named package. When include_staging is True,
    also includes the content items needed for staging/downloading.

    Args:
        screen: Screen model instance
        include_staging: Whether to include staging items for download

    Returns:
        Dictionary with playlist name, version, duration, and optionally staging items
    """
    import json

    try:
        from models.playlist import Playlist

        # Get cached playlist for this screen
        playlist = Playlist.query.filter_by(screen_id=screen.id).first()

        if playlist:
            result = {
                'playlist_id': playlist.playlist_id,
                'name': playlist.name,
                'version': playlist.version or '1',
                'duration': playlist.total_duration or 0
            }

            # Include staging items if requested
            if include_staging and playlist.items_json:
                try:
                    items = json.loads(playlist.items_json)
                    result['staging_items'] = items
                except (json.JSONDecodeError, TypeError):
                    result['staging_items'] = []
            elif include_staging:
                result['staging_items'] = []

            return result
    except Exception:
        pass

    # No cached playlist
    result = {
        'playlist_id': None,
        'name': None,
        'version': None,
        'duration': 0
    }
    if include_staging:
        result['staging_items'] = []
    return result


@screens_bp.route('/<int:screen_id>/config', methods=['GET'])
def get_screen_config(screen_id):
    """
    Get configuration for a specific screen.

    Args:
        screen_id: Screen ID from registration

    Returns:
        200: Screen configuration
        404: Screen not found
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


@screens_bp.route('/<screen_id>/heartbeat', methods=['POST'])
def screen_heartbeat(screen_id):
    """
    Receive heartbeat from a screen.

    Accepts both integer screen_id and hardware_id string.

    Args:
        screen_id: Screen ID (integer) or hardware_id (string)

    Returns:
        200: Heartbeat acknowledged
        404: Screen not found
    """
    # Try to find screen by hardware_id first, then by integer id
    screen = Screen.query.filter_by(hardware_id=screen_id).first()

    if not screen:
        try:
            screen_int_id = int(screen_id)
            screen = db.session.get(Screen, screen_int_id)
        except (ValueError, TypeError):
            pass

    if not screen:
        return jsonify({
            'success': False,
            'error': 'Screen not found'
        }), 404

    # Capture IP address from request
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip and ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()
    if client_ip and client_ip != screen.ip_address:
        screen.ip_address = client_ip

    screen.update_heartbeat()

    return jsonify({
        'success': True,
        'message': 'Heartbeat received',
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }), 200


@screens_bp.route('/<int:screen_id>/playlist', methods=['GET'])
def get_screen_playlist(screen_id):
    """
    Get the full playlist for a specific screen.

    Args:
        screen_id: Screen ID from registration

    Returns:
        200: Complete playlist data
        404: Screen not found
    """
    screen = db.session.get(Screen, screen_id)
    if not screen:
        return jsonify({
            'success': False,
            'error': 'Screen not found'
        }), 404

    playlist_data = _get_playlist_for_screen(screen)

    return jsonify({
        'success': True,
        'playlist': playlist_data
    }), 200


@screens_bp.route('/<int:screen_id>/playlist/sync', methods=['POST'])
def sync_screen_playlist(screen_id):
    """
    Manually trigger playlist sync for a specific screen from CMS.

    Args:
        screen_id: Screen ID from registration

    Returns:
        200: Playlist synced successfully
        404: Screen not found
        500: Sync failed
    """
    screen = db.session.get(Screen, screen_id)
    if not screen:
        return jsonify({
            'success': False,
            'error': 'Screen not found'
        }), 404

    try:
        from services.sync_service import SyncService
        from services.hq_client import HQClient
        from config import load_config

        config = load_config()
        hq_client = HQClient(config.cms_url)
        sync_service = SyncService(hq_client, config)

        result = sync_service.sync_playlist_for_screen(
            screen_id=screen.id,
            hardware_id=screen.hardware_id
        )

        return jsonify({
            'success': True,
            'message': 'Playlist synced successfully',
            'result': result
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Sync failed: {str(e)}'
        }), 500


@screens_bp.route('', methods=['GET'])
def list_screens():
    """
    List all registered screens.

    Query Parameters:
        status: Filter by status (online, offline)

    Returns:
        200: List of screens
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


@screens_bp.route('/webhook/playlist-updated', methods=['POST'])
def webhook_playlist_updated():
    """
    Webhook endpoint for CMS to notify Hub of playlist updates.

    CMS calls this endpoint immediately when a playlist is changed,
    triggering the Hub to notify Jetsons to sync right away.

    Request Body:
        {
            "device_id": "jetson-xxx" (optional - notify specific device),
            "playlist_id": 1 (optional - which playlist changed),
            "action": "updated" | "deleted" (optional)
        }

    If no device_id is provided, notifies all registered screens.

    Returns:
        200: Notifications sent successfully
        207: Partial success (some notifications failed)
    """
    import requests as http_requests

    data = request.get_json() or {}
    device_id = data.get('device_id')

    push_results = []
    errors = []

    try:
        if device_id:
            # Notify specific device
            screen = Screen.query.filter_by(hardware_id=device_id).first()
            if screen:
                if screen.ip_address:
                    try:
                        push_url = f"http://{screen.ip_address}:8080/api/command/sync"
                        resp = http_requests.post(push_url, timeout=5)
                        push_results.append({
                            'hardware_id': screen.hardware_id,
                            'ip': screen.ip_address,
                            'notified': resp.status_code == 200
                        })
                    except Exception as push_err:
                        push_results.append({
                            'hardware_id': screen.hardware_id,
                            'ip': screen.ip_address,
                            'notified': False,
                            'error': str(push_err)
                        })
                else:
                    errors.append({
                        'hardware_id': screen.hardware_id,
                        'error': 'No IP address recorded for device'
                    })
            else:
                errors.append({
                    'device_id': device_id,
                    'error': 'Device not registered on this hub'
                })
        else:
            # Notify all registered screens with known IP addresses
            screens = Screen.query.filter(Screen.ip_address.isnot(None)).all()
            for screen in screens:
                try:
                    push_url = f"http://{screen.ip_address}:8080/api/command/sync"
                    resp = http_requests.post(push_url, timeout=5)
                    push_results.append({
                        'hardware_id': screen.hardware_id,
                        'ip': screen.ip_address,
                        'notified': resp.status_code == 200
                    })
                except Exception as push_err:
                    push_results.append({
                        'hardware_id': screen.hardware_id,
                        'ip': screen.ip_address,
                        'notified': False,
                        'error': str(push_err)
                    })

        all_notified = all(r.get('notified', False) for r in push_results)
        return jsonify({
            'success': len(errors) == 0 and all_notified,
            'message': f'Notified {len(push_results)} devices',
            'pushed': push_results,
            'errors': errors
        }), 200 if (len(errors) == 0 and all_notified) else 207

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Webhook processing failed: {str(e)}'
        }), 500
