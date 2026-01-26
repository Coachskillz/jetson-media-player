"""
Camera feed routes for Local Hub.

Provides endpoints for viewing camera feeds from Jetson devices.
- GET /api/v1/cameras - List all cameras
- GET /api/v1/cameras/{device_id}/snapshot - Get JPEG snapshot
- GET /api/v1/cameras/{device_id}/stream - Proxy MJPEG stream
"""

from flask import Blueprint, jsonify, Response, request, current_app
import requests
from models.device import Device

cameras_bp = Blueprint('cameras', __name__)


def get_device_stream_url(device):
    """Get the stream URL for a device."""
    # Default stream port and path - can be configured per device
    stream_port = device.stream_port or 8080
    stream_path = device.stream_path or '/stream'
    return f"http://{device.ip_address}:{stream_port}{stream_path}"


def get_device_snapshot_url(device):
    """Get the snapshot URL for a device."""
    stream_port = device.stream_port or 8080
    snapshot_path = device.snapshot_path or '/snapshot'
    return f"http://{device.ip_address}:{stream_port}{snapshot_path}"


@cameras_bp.route('/', methods=['GET'])
@cameras_bp.route('', methods=['GET'])
def list_cameras():
    """List all devices with cameras enabled."""
    try:
        devices = Device.query.filter_by(camera_enabled=True).all()
        cameras = []
        for device in devices:
            cameras.append({
                'device_id': device.device_id,
                'name': device.name,
                'location': device.location,
                'ip_address': device.ip_address,
                'status': device.status,
                'stream_url': f"/api/v1/cameras/{device.device_id}/stream",
                'snapshot_url': f"/api/v1/cameras/{device.device_id}/snapshot",
                'camera_enabled': device.camera_enabled
            })
        return jsonify({'cameras': cameras, 'count': len(cameras)})
    except Exception as e:
        current_app.logger.error(f"Error listing cameras: {e}")
        return jsonify({'error': str(e)}), 500


@cameras_bp.route('/<device_id>/snapshot', methods=['GET'])
def get_snapshot(device_id):
    """Get a JPEG snapshot from a device camera."""
    try:
        device = Device.query.filter_by(device_id=device_id).first()
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        
        if not device.camera_enabled:
            return jsonify({'error': 'Camera not enabled for this device'}), 400
        
        if not device.ip_address:
            return jsonify({'error': 'Device IP address not configured'}), 400
        
        # Fetch snapshot from Jetson
        snapshot_url = get_device_snapshot_url(device)
        response = requests.get(snapshot_url, timeout=5)
        
        if response.status_code == 200:
            return Response(
                response.content,
                mimetype='image/jpeg',
                headers={'Cache-Control': 'no-cache, no-store, must-revalidate'}
            )
        else:
            return jsonify({'error': 'Failed to fetch snapshot'}), 502
            
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Timeout fetching snapshot'}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Cannot connect to device'}), 502
    except Exception as e:
        current_app.logger.error(f"Error getting snapshot: {e}")
        return jsonify({'error': str(e)}), 500


@cameras_bp.route('/<device_id>/stream', methods=['GET'])
def get_stream(device_id):
    """Proxy MJPEG stream from a device camera."""
    try:
        device = Device.query.filter_by(device_id=device_id).first()
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        
        if not device.camera_enabled:
            return jsonify({'error': 'Camera not enabled for this device'}), 400
        
        if not device.ip_address:
            return jsonify({'error': 'Device IP address not configured'}), 400
        
        stream_url = get_device_stream_url(device)
        
        def generate():
            """Generator to proxy MJPEG stream."""
            try:
                with requests.get(stream_url, stream=True, timeout=30) as r:
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:
                            yield chunk
            except Exception as e:
                current_app.logger.error(f"Stream error: {e}")
        
        return Response(
            generate(),
            mimetype='multipart/x-mixed-replace; boundary=frame',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Connection': 'keep-alive'
            }
        )
        
    except Exception as e:
        current_app.logger.error(f"Error starting stream: {e}")
        return jsonify({'error': str(e)}), 500


@cameras_bp.route('/test', methods=['GET'])
def test_cameras():
    """Test endpoint to verify cameras route is working."""
    return jsonify({
        'status': 'ok',
        'message': 'Cameras API is working',
        'endpoints': [
            'GET /api/v1/cameras - List all cameras',
            'GET /api/v1/cameras/{device_id}/snapshot - Get JPEG snapshot',
            'GET /api/v1/cameras/{device_id}/stream - Proxy MJPEG stream'
        ]
    })
