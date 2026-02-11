"""
Screen Locations API endpoints.

This module provides endpoints for serving cached screen locations to Jetsons.
Locations are synced from the CMS and cached locally on the Hub.
"""

import json
import os
from datetime import datetime
from flask import Blueprint, jsonify, current_app

locations_bp = Blueprint('locations', __name__, url_prefix='/locations')


def get_locations_cache_path():
    """Get the path to the locations cache file."""
    storage_path = current_app.config.get('STORAGE_PATH', '/home/skillz/skillz-hub/storage')
    data_path = os.path.join(os.path.dirname(storage_path), 'data')
    os.makedirs(data_path, exist_ok=True)
    return os.path.join(data_path, 'locations.json')


def load_cached_locations():
    """Load locations from cache file."""
    cache_path = get_locations_cache_path()

    if not os.path.exists(cache_path):
        return None

    try:
        with open(cache_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_locations_cache(network_id, locations):
    """Save locations to cache file."""
    cache_path = get_locations_cache_path()

    data = {
        'network_id': network_id,
        'locations': locations,
        'last_synced': datetime.utcnow().isoformat() + 'Z'
    }

    with open(cache_path, 'w') as f:
        json.dump(data, f, indent=2)

    return data


def sync_locations_from_cms():
    """
    Sync screen locations from CMS.

    Returns:
        dict: Cache data with network_id, locations list, and last_synced timestamp
    """
    import requests
    from models.hub_config import HubConfig

    hub_config = HubConfig.get_instance()
    if not hub_config or not hub_config.is_registered:
        current_app.logger.warning("Hub not registered, cannot sync locations")
        return None

    config = current_app.config.get('HUB_CONFIG')
    if not config or not config.cms_url:
        current_app.logger.warning("No CMS URL configured")
        return None

    # Get network from hub config or fall back to default
    network_id = hub_config.network_id or 'on-the-wave'

    # Handle UUID network IDs by mapping to network name
    # The CMS API expects network name, not UUID
    # For now, try to determine network from hub code or default
    if network_id and len(network_id) > 20:  # Looks like a UUID
        # Default to on-the-wave for West Marine deployments
        network_id = 'on-the-wave'

    endpoint = f"{config.cms_url.rstrip('/')}/api/v1/networks/{network_id}/locations"

    headers = {
        'Authorization': f'Bearer {hub_config.hub_token}'
    }

    try:
        current_app.logger.info(f"Syncing locations from CMS: {endpoint}")
        response = requests.get(endpoint, headers=headers, timeout=30)

        if response.ok:
            locations = response.json()
            cache_data = save_locations_cache(network_id, locations)
            current_app.logger.info(f"Synced {len(locations)} locations from CMS")
            return cache_data
        else:
            current_app.logger.warning(f"Failed to sync locations: {response.status_code}")
            return None
    except Exception as e:
        current_app.logger.error(f"Error syncing locations from CMS: {e}")
        return None


@locations_bp.route('', methods=['GET'])
def get_locations():
    """
    Get cached screen locations.

    Jetsons call this endpoint to get the list of available screen locations
    for the location picker dropdown on the pairing screen.

    Returns:
        200: List of locations
            {
                "locations": [
                    {"id": "uuid", "name": "Register 1"},
                    {"id": "uuid", "name": "Fishing Counter"}
                ],
                "network_id": "on-the-wave",
                "last_synced": "2026-02-10T14:00:00Z"
            }
    """
    cache_data = load_cached_locations()

    if cache_data:
        return jsonify(cache_data)

    # Try to sync from CMS if no cache
    cache_data = sync_locations_from_cms()

    if cache_data:
        return jsonify(cache_data)

    # Return empty list if no cache and sync failed
    return jsonify({
        'locations': [],
        'network_id': None,
        'last_synced': None,
        'error': 'No cached locations available'
    })


@locations_bp.route('/sync', methods=['POST'])
def force_sync_locations():
    """
    Force sync locations from CMS.

    Admin endpoint to manually trigger a location sync.

    Returns:
        200: Sync successful
        502: CMS unreachable
    """
    cache_data = sync_locations_from_cms()

    if cache_data:
        return jsonify({
            'success': True,
            'message': f"Synced {len(cache_data.get('locations', []))} locations",
            **cache_data
        })

    return jsonify({
        'success': False,
        'error': 'Failed to sync locations from CMS'
    }), 502
