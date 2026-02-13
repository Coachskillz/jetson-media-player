"""
Screen Locations API endpoints.

Manages screen locations locally on the Hub.
Locations are created by technicians as tags, populate the pairing dropdown,
and sync to the CMS.
"""

import json
import os
import uuid
from datetime import datetime
from flask import Blueprint, jsonify, request, current_app

locations_bp = Blueprint('locations', __name__, url_prefix='/locations')


def get_locations_cache_path():
    storage_path = current_app.config.get('STORAGE_PATH', '/home/skillz/skillz-hub/storage')
    data_path = os.path.join(os.path.dirname(storage_path), 'data')
    os.makedirs(data_path, exist_ok=True)
    return os.path.join(data_path, 'locations.json')


def load_cached_locations():
    cache_path = get_locations_cache_path()
    if not os.path.exists(cache_path):
        return {'locations': [], 'last_synced': None}
    try:
        with open(cache_path, 'r') as f:
            data = json.load(f)
            if 'locations' not in data:
                data['locations'] = []
            return data
    except (json.JSONDecodeError, IOError):
        return {'locations': [], 'last_synced': None}


def save_locations(data):
    cache_path = get_locations_cache_path()
    data['last_modified'] = datetime.utcnow().isoformat() + 'Z'
    with open(cache_path, 'w') as f:
        json.dump(data, f, indent=2)
    return data


@locations_bp.route('', methods=['GET'])
def get_locations():
    data = load_cached_locations()
    return jsonify(data)


@locations_bp.route('', methods=['POST'])
def create_location():
    body = request.get_json() or {}
    name = (body.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Location name is required'}), 400
    data = load_cached_locations()
    for loc in data['locations']:
        if loc['name'].lower() == name.lower():
            return jsonify({'error': 'Location already exists'}), 409
    new_location = {
        'id': str(uuid.uuid4()),
        'name': name,
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'synced': False
    }
    data['locations'].append(new_location)
    save_locations(data)
    current_app.logger.info(f'Created location: {name}')
    return jsonify({'success': True, 'location': new_location, 'count': len(data['locations'])}), 201


@locations_bp.route('/<location_id>', methods=['DELETE'])
def delete_location(location_id):
    data = load_cached_locations()
    original_count = len(data['locations'])
    data['locations'] = [loc for loc in data['locations'] if loc['id'] != location_id]
    if len(data['locations']) == original_count:
        return jsonify({'error': 'Location not found'}), 404
    save_locations(data)
    current_app.logger.info(f'Deleted location: {location_id}')
    return jsonify({'success': True, 'count': len(data['locations'])})


@locations_bp.route('/sync', methods=['POST'])
def sync_locations_to_cms():
    import requests
    data = load_cached_locations()
    unsynced = [loc for loc in data['locations'] if not loc.get('synced')]
    if not unsynced:
        return jsonify({'success': True, 'message': 'All synced', 'synced_count': 0})
    try:
        config_dir = os.path.join(os.path.dirname(get_locations_cache_path()), '..', 'config')
        config_path = os.path.join(config_dir, 'device.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                device_config = json.load(f)
        else:
            return jsonify({'success': False, 'error': 'No device config'}), 400
        hub_id = device_config.get('hub_id')
        cms_url = device_config.get('hub_url', '')
        if not cms_url or not hub_id:
            return jsonify({'success': False, 'error': 'Hub not configured'}), 400
        synced_count = 0
        for loc in unsynced:
            try:
                resp = requests.post(
                    f"{cms_url.rstrip('/')}/api/locations",
                    json={'hub_id': hub_id, 'name': loc['name']},
                    headers={'Content-Type': 'application/json'},
                    timeout=10
                )
                if resp.ok:
                    result = resp.json()
                    loc['synced'] = True
                    loc['cms_id'] = result.get('location', {}).get('id')
                    synced_count += 1
            except Exception as e:
                current_app.logger.warning(f'Failed to sync location {loc["name"]}: {e}')
        save_locations(data)
        return jsonify({'success': True, 'synced_count': synced_count, 'total': len(data['locations'])})
    except Exception as e:
        current_app.logger.error(f'Sync error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
