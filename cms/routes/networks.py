"""
CMS Networks Routes

Blueprint for network management API endpoints:
- POST /: Create a new network
- GET /: List all networks
- GET /<id>: Get a specific network
- PUT /<id>: Update a network
- DELETE /<id>: Delete a network

All endpoints are prefixed with /api/v1/networks when registered with the app.
"""

import re

from flask import Blueprint, request, jsonify

from cms.models import db, Network


# Create networks blueprint
networks_bp = Blueprint('networks', __name__)


def generate_slug(name):
    """
    Generate a URL-friendly slug from a name.

    Args:
        name: The name to convert to a slug

    Returns:
        A lowercase, hyphenated slug string
    """
    # Convert to lowercase and replace spaces with hyphens
    slug = name.lower().strip()
    # Replace any non-alphanumeric characters (except hyphens) with hyphens
    slug = re.sub(r'[^a-z0-9-]', '-', slug)
    # Replace multiple consecutive hyphens with a single hyphen
    slug = re.sub(r'-+', '-', slug)
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    return slug


@networks_bp.route('', methods=['POST'])
def create_network():
    """
    Create a new network.

    Networks are top-level organizational units that contain hubs,
    devices, content, and playlists.

    Request Body:
        {
            "name": "My Network" (required),
            "slug": "my-network" (optional, auto-generated from name if not provided)
        }

    Returns:
        201: New network created
            {
                "id": "uuid",
                "name": "My Network",
                "slug": "my-network",
                "created_at": "2024-01-15T10:00:00Z"
            }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
        409: Network with slug already exists
            {
                "error": "Network with slug 'my-network' already exists"
            }
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate name
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400

    if not isinstance(name, str) or len(name) > 200:
        return jsonify({
            'error': 'name must be a string with max 200 characters'
        }), 400

    # Generate or validate slug
    slug = data.get('slug')
    if slug:
        if not isinstance(slug, str) or len(slug) > 100:
            return jsonify({
                'error': 'slug must be a string with max 100 characters'
            }), 400
        # Validate slug format
        if not re.match(r'^[a-z0-9-]+$', slug):
            return jsonify({
                'error': 'slug must contain only lowercase letters, numbers, and hyphens'
            }), 400
    else:
        # Auto-generate slug from name
        slug = generate_slug(name)

    # Check if network with this slug already exists
    existing_network = Network.query.filter_by(slug=slug).first()
    if existing_network:
        return jsonify({
            'error': f"Network with slug '{slug}' already exists"
        }), 409

    # Create new network
    network = Network(
        name=name,
        slug=slug
    )

    try:
        db.session.add(network)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create network: {str(e)}'
        }), 500

    return jsonify(network.to_dict()), 201


@networks_bp.route('', methods=['GET'])
def list_networks():
    """
    List all networks.

    Returns a list of all networks registered with the CMS.

    Returns:
        200: List of networks
            {
                "networks": [ { network data }, ... ],
                "count": 5
            }
    """
    # Execute query ordered by creation date (newest first)
    networks = Network.query.order_by(Network.created_at.desc()).all()

    return jsonify({
        'networks': [network.to_dict() for network in networks],
        'count': len(networks)
    }), 200


@networks_bp.route('/<network_id>', methods=['GET'])
def get_network(network_id):
    """
    Get a specific network by ID or slug.

    Args:
        network_id: Network UUID or slug

    Returns:
        200: Network data
            { network data }
        404: Network not found
            {
                "error": "Network not found"
            }
    """
    # Try to find network by UUID first, then by slug
    network = db.session.get(Network, network_id)
    if not network:
        network = Network.query.filter_by(slug=network_id).first()

    if not network:
        return jsonify({'error': 'Network not found'}), 404

    return jsonify(network.to_dict()), 200


@networks_bp.route('/<network_id>', methods=['PUT'])
def update_network(network_id):
    """
    Update an existing network.

    Args:
        network_id: Network UUID or slug

    Request Body:
        {
            "name": "Updated Network Name" (optional),
            "slug": "updated-slug" (optional)
        }

    Returns:
        200: Updated network
            { network data }
        400: Invalid data
            {
                "error": "error message"
            }
        404: Network not found
            {
                "error": "Network not found"
            }
        409: Slug already exists
            {
                "error": "Network with slug 'existing-slug' already exists"
            }
    """
    # Find network by UUID or slug
    network = db.session.get(Network, network_id)
    if not network:
        network = Network.query.filter_by(slug=network_id).first()

    if not network:
        return jsonify({'error': 'Network not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Update name if provided
    if 'name' in data:
        name = data['name']
        if not name:
            return jsonify({'error': 'name cannot be empty'}), 400
        if not isinstance(name, str) or len(name) > 200:
            return jsonify({
                'error': 'name must be a string with max 200 characters'
            }), 400
        network.name = name

    # Update slug if provided
    if 'slug' in data:
        slug = data['slug']
        if not slug:
            return jsonify({'error': 'slug cannot be empty'}), 400
        if not isinstance(slug, str) or len(slug) > 100:
            return jsonify({
                'error': 'slug must be a string with max 100 characters'
            }), 400
        # Validate slug format
        if not re.match(r'^[a-z0-9-]+$', slug):
            return jsonify({
                'error': 'slug must contain only lowercase letters, numbers, and hyphens'
            }), 400

        # Check if another network with this slug exists
        if slug != network.slug:
            existing_network = Network.query.filter_by(slug=slug).first()
            if existing_network:
                return jsonify({
                    'error': f"Network with slug '{slug}' already exists"
                }), 409
        network.slug = slug

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update network: {str(e)}'
        }), 500

    return jsonify(network.to_dict()), 200


@networks_bp.route('/<network_id>', methods=['DELETE'])
def delete_network(network_id):
    """
    Delete a network.

    Note: This will fail if the network has associated hubs, devices,
    content, or playlists. Those must be deleted or reassigned first.

    Args:
        network_id: Network UUID or slug

    Returns:
        200: Network deleted successfully
            {
                "message": "Network deleted successfully",
                "id": "uuid"
            }
        404: Network not found
            {
                "error": "Network not found"
            }
        409: Network has dependencies
            {
                "error": "Cannot delete network with associated resources"
            }
    """
    # Find network by UUID or slug
    network = db.session.get(Network, network_id)
    if not network:
        network = Network.query.filter_by(slug=network_id).first()

    if not network:
        return jsonify({'error': 'Network not found'}), 404

    network_id_value = network.id

    try:
        db.session.delete(network)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Check if it's a foreign key constraint error
        error_str = str(e).lower()
        if 'foreign key' in error_str or 'constraint' in error_str:
            return jsonify({
                'error': 'Cannot delete network with associated resources'
            }), 409
        return jsonify({
            'error': f'Failed to delete network: {str(e)}'
        }), 500

    return jsonify({
        'message': 'Network deleted successfully',
        'id': network_id_value
    }), 200
