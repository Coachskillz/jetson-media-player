"""
CMS Hubs Routes

Blueprint for hub management API endpoints:
- POST /register: Register a new hub
- GET /: List all hubs
- GET /<hub_id>/content-manifest: Get hub content manifest

All endpoints are prefixed with /api/v1/hubs when registered with the app.
"""

import re

from flask import Blueprint, request, jsonify

from cms.models import db, Hub, Network, Content
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

    Request Body:
        {
            "code": "WM" (required, 2-4 uppercase letters),
            "name": "West Marine Hub" (required),
            "location": "123 Main St" (optional),
            "network_id": "uuid-of-network" (required)
        }

    Returns:
        201: New hub created
            {
                "id": "uuid",
                "code": "WM",
                "name": "West Marine Hub",
                "status": "pending",
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

    # Create new hub
    hub = Hub(
        code=code,
        name=name,
        network_id=network_id,
        status='pending'
    )

    # Note: Hub model doesn't have location column based on current schema
    # If location needs to be stored, the model should be updated

    try:
        db.session.add(hub)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create hub: {str(e)}'
        }), 500

    # Log hub registration (hub-initiated action)
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
