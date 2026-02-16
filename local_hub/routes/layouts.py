"""
Layout API endpoints for receiving layouts from CMS.

This module provides REST API endpoints for layout management:
- POST /layouts/receive - Receive layout push from CMS

Layouts are pushed from CMS when admin assigns a layout to a device.
The Hub caches the content and pushes the layout to the Jetson device.
"""

import json
import logging
import os
from datetime import datetime

from flask import Blueprint, jsonify, request, current_app
import requests

from models import db, Device


layouts_bp = Blueprint('layouts', __name__, url_prefix='/layouts')
logger = logging.getLogger(__name__)


@layouts_bp.route('/receive', methods=['POST'])
def receive_layout():
    """
    Receive a layout push from CMS.

    The CMS pushes layout data including:
    - Layout configuration (canvas, layers)
    - Playlist items with content
    - Content manifest with download URLs

    The Hub:
    1. Stores the layout in the device's local record
    2. Downloads any missing content
    3. Pushes the layout to the Jetson device

    Request Body:
        {
            "device_id": "cms-device-uuid",
            "device_hardware_id": "jetson-hardware-id",
            "layout": {
                "id": "layout-uuid",
                "name": "Main Layout",
                "canvas_width": 1920,
                "canvas_height": 1080,
                "layers": [...]
            },
            "content_manifest": [
                {
                    "id": "content-uuid",
                    "filename": "promo.mp4",
                    "download_url": "/api/v1/content/uuid/download",
                    "file_size": 52428800
                }
            ]
        }

    Returns:
        200: Layout received and processed
        400: Missing required fields
        404: Device not found
    """
    data = request.get_json() or {}

    device_id = data.get('device_id')
    hardware_id = data.get('device_hardware_id')
    layout_data = data.get('layout')
    content_manifest = data.get('content_manifest', [])

    if not device_id and not hardware_id:
        return jsonify({
            'success': False,
            'error': 'device_id or device_hardware_id is required'
        }), 400

    if not layout_data:
        return jsonify({
            'success': False,
            'error': 'layout is required'
        }), 400

    # Find device
    device = None
    if device_id:
        device = Device.query.filter_by(cms_device_id=device_id).first()
    if not device and hardware_id:
        device = Device.get_by_hardware_id(hardware_id)

    if not device:
        return jsonify({
            'success': False,
            'error': 'Device not found'
        }), 404

    # Store layout in device record (as JSON)
    # Merge content manifest items into the layout layers so the Jetson
    # config endpoint can find them when it calls _get_playlist_for_screen
    enriched_layout = dict(layout_data)
    if content_manifest:
        for layer in enriched_layout.get('layers', []):
            if layer.get('content_source') == 'playlist' and layer.get('playlist_id'):
                # Attach content items to this layer
                layer['items'] = []
                for idx, content in enumerate(content_manifest):
                    layer['items'].append({
                        'content_id': content.get('id'),
                        'filename': content.get('filename'),
                        'duration': content.get('duration', 10),
                        'order': idx,
                        'content_type': content.get('type', 'video'),
                        'file_size': content.get('file_size', 0),
                        'url': content.get('download_url', '')
                    })
                layer['playlist'] = {
                    'id': layer.get('playlist_id'),
                    'name': layer.get('playlist_name', 'default')
                }

    device.layout_json = json.dumps(enriched_layout)
    device.layout_updated_at = datetime.utcnow()
    db.session.commit()

    logger.info(f"Received layout '{layout_data.get('name')}' for device {device.hardware_id}")

    # Download missing content
    download_results = _download_content_for_device(device, content_manifest)

    # Push layout to Jetson device
    push_result = _push_layout_to_device(device, layout_data, content_manifest)

    return jsonify({
        'success': True,
        'message': 'Layout received',
        'layout_name': layout_data.get('name'),
        'content_downloaded': download_results.get('downloaded', 0),
        'content_cached': download_results.get('cached', 0),
        'pushed_to_device': push_result
    }), 200


def _download_content_for_device(device, content_manifest):
    """
    Download missing content from CMS to local cache.

    Args:
        device: Device model instance
        content_manifest: List of content items with download_url

    Returns:
        dict with download stats
    """
    from models import HubConfig

    if not content_manifest:
        return {'downloaded': 0, 'cached': 0, 'errors': []}

    hub_config = HubConfig.get_instance()
    config = current_app.config.get('HUB_CONFIG')

    if not config or not config.cms_url:
        logger.warning("No CMS URL configured, cannot download content")
        return {'downloaded': 0, 'cached': 0, 'errors': ['No CMS URL']}

    cms_url = config.cms_url.rstrip('/')
    storage_path = current_app.config.get('STORAGE_PATH', '/home/skillz/skillz-hub/storage')
    content_dir = os.path.join(storage_path, 'content')
    os.makedirs(content_dir, exist_ok=True)

    downloaded = 0
    cached = 0
    errors = []

    for item in content_manifest:
        content_id = item.get('id')
        filename = item.get('filename')
        download_url = item.get('download_url')

        if not content_id or not download_url:
            continue

        # Check if content already cached
        local_path = os.path.join(content_dir, f"{content_id}_{filename}")
        if os.path.exists(local_path):
            cached += 1
            continue

        # Download from CMS
        full_url = f"{cms_url}{download_url}"
        headers = {}
        if hub_config and hub_config.hub_token:
            headers['Authorization'] = f'Bearer {hub_config.hub_token}'

        try:
            response = requests.get(full_url, headers=headers, timeout=300, stream=True)
            if response.ok:
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                downloaded += 1
                logger.info(f"Downloaded content {filename} ({content_id})")
            else:
                errors.append(f"{filename}: HTTP {response.status_code}")
                logger.warning(f"Failed to download {filename}: {response.status_code}")
        except Exception as e:
            errors.append(f"{filename}: {str(e)}")
            logger.error(f"Error downloading {filename}: {e}")

    return {
        'downloaded': downloaded,
        'cached': cached,
        'errors': errors
    }


def _push_layout_to_device(device, layout_data, content_manifest):
    """
    Push the layout to the Jetson device.

    Args:
        device: Device model instance
        layout_data: Layout configuration dict
        content_manifest: List of content items

    Returns:
        bool: True if push succeeded
    """
    if not device.ip_address:
        logger.warning(f"Device {device.hardware_id} has no IP, cannot push layout")
        return False

    # Jetson player listens on port 8080
    jetson_url = f"http://{device.ip_address}:8080"

    try:
        # Trigger the Jetson to sync - it pulls content from the Hub
        response = requests.post(
            f"{jetson_url}/api/command/sync",
            timeout=10
        )

        if response.ok:
            logger.info(f"Triggered sync on device {device.hardware_id}")
            return True
        else:
            logger.warning(f"Device {device.hardware_id} returned {response.status_code}")
            return False
    except requests.Timeout:
        logger.warning(f"Timeout pushing layout to device {device.hardware_id}")
        return False
    except requests.RequestException as e:
        logger.error(f"Failed to push layout to device {device.hardware_id}: {e}")
        return False


def _extract_playlist_from_layout(layout_data):
    """
    Extract playlist items from layout layers.

    Finds content layers with playlists and extracts the items.

    Args:
        layout_data: Layout configuration dict

    Returns:
        list: Playlist items for the Jetson
    """
    items = []

    layers = layout_data.get('layers', [])
    for layer in layers:
        playlist = layer.get('playlist')
        if playlist and playlist.get('items'):
            for item in playlist['items']:
                content = item.get('content')
                if content:
                    items.append({
                        'content_id': content.get('id'),
                        'filename': content.get('filename'),
                        'duration': item.get('duration') or content.get('duration', 10),
                        'file_type': content.get('file_type'),
                    })

    return items
