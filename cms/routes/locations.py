"""
Store Locations API Routes.

Manages screen locations within a store/hub.
Used by both Hub mode (tech picks from dropdown) and Direct mode (admin assigns in CMS).
"""

from flask import Blueprint, request, jsonify
from cms.models import db
from cms.models.store_location import StoreLocation
from cms.models.hub import Hub
from cms.auth import login_required
import uuid

locations_bp = Blueprint('locations', __name__)


@locations_bp.route('', methods=['GET'])
def list_locations():
    """List store locations, optionally filtered by hub_id."""
    hub_id = request.args.get('hub_id')

    if hub_id:
        locations = StoreLocation.query.filter_by(hub_id=hub_id).order_by(StoreLocation.name).all()
    else:
        locations = StoreLocation.query.order_by(StoreLocation.name).all()

    return jsonify({
        'count': len(locations),
        'locations': [loc.to_dict() for loc in locations]
    }), 200


@locations_bp.route('', methods=['POST'])
@login_required
def create_location():
    """Create a new store location for a hub."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    hub_id = data.get('hub_id')
    name = data.get('name')

    if not hub_id:
        return jsonify({'error': 'hub_id is required'}), 400
    if not name:
        return jsonify({'error': 'name is required'}), 400

    hub = db.session.get(Hub, hub_id)
    if not hub:
        return jsonify({'error': 'Hub not found'}), 404

    existing = StoreLocation.query.filter_by(hub_id=hub_id, name=name).first()
    if existing:
        return jsonify({'error': f'Location "{name}" already exists for this hub'}), 409

    location = StoreLocation(
        hub_id=hub_id,
        name=name,
        description=data.get('description')
    )

    try:
        db.session.add(location)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    return jsonify(location.to_dict()), 201


@locations_bp.route('/<location_id>', methods=['GET'])
def get_location(location_id):
    """Get a single store location."""
    location = db.session.get(StoreLocation, location_id)
    if not location:
        return jsonify({'error': 'Location not found'}), 404

    return jsonify(location.to_dict()), 200


@locations_bp.route('/<location_id>', methods=['PUT'])
@login_required
def update_location(location_id):
    """Update a store location."""
    location = db.session.get(StoreLocation, location_id)
    if not location:
        return jsonify({'error': 'Location not found'}), 404

    data = request.get_json(silent=True) or {}

    if 'name' in data:
        location.name = data['name']
    if 'description' in data:
        location.description = data['description']

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    return jsonify(location.to_dict()), 200


@locations_bp.route('/<location_id>', methods=['DELETE'])
@login_required
def delete_location(location_id):
    """Delete a store location."""
    location = db.session.get(StoreLocation, location_id)
    if not location:
        return jsonify({'error': 'Location not found'}), 404

    from cms.models.device import Device
    Device.query.filter_by(location_id=location_id).update({
        'location_id': None,
        'screen_location': None
    })

    name = location.name
    try:
        db.session.delete(location)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    return jsonify({'message': f'Location "{name}" deleted'}), 200
