"""
Content Catalog Tenants Routes

Blueprint for tenant management API endpoints (admin only):
- GET /: List all tenants
- GET /<tenant_id>: Get a specific tenant by UUID
- POST /: Create a new tenant
- PUT /<tenant_id>: Update a tenant

All endpoints are prefixed with /api/v1/tenants when registered with the app.
These endpoints require admin permissions (Super Admin or Admin roles).
"""

import re

from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from content_catalog.models import db, User
from content_catalog.models.tenant import Tenant
from content_catalog.utils.api_key_auth import api_key_or_jwt_required


# Create tenants blueprint
tenants_bp = Blueprint('tenants', __name__)


def _get_current_user():
    """
    Get the current authenticated user from JWT identity.

    Returns:
        User object or None if not found
    """
    current_user_id = get_jwt_identity()
    if current_user_id is None:
        return None
    return db.session.get(User, current_user_id)


def _is_admin(user):
    """
    Check if the user has admin permissions (Super Admin or Admin roles).

    Args:
        user: The User object to check permissions for

    Returns:
        True if user is admin, False otherwise
    """
    if not user:
        return False
    return user.role in [User.ROLE_SUPER_ADMIN, User.ROLE_ADMIN]


def _validate_slug(slug):
    """
    Validate slug format.

    Slugs must be lowercase alphanumeric with hyphens, 3-100 characters.

    Args:
        slug: The slug string to validate

    Returns:
        True if slug format is valid, False otherwise
    """
    if not slug:
        return False
    pattern = r'^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$'
    return bool(re.match(pattern, slug)) and 3 <= len(slug) <= 100


@tenants_bp.route('/active', methods=['GET'])
@api_key_or_jwt_required
def list_active_tenants():
    """
    List all active tenants (service endpoint).

    This endpoint is accessible via service API key for CMS integration.
    Returns only active tenants with basic info (uuid, name, slug).

    Returns:
        200: List of active tenants
            [
                { "uuid": "...", "name": "...", "slug": "...", "is_active": true },
                ...
            ]
    """
    tenants = Tenant.query.filter_by(is_active=True).order_by(Tenant.name.asc()).all()

    return jsonify([
        {
            'uuid': tenant.uuid,
            'name': tenant.name,
            'slug': tenant.slug,
            'is_active': tenant.is_active,
        }
        for tenant in tenants
    ]), 200


@tenants_bp.route('', methods=['GET'])
@jwt_required()
def list_tenants():
    """
    List all tenants.

    Returns a list of all tenants in the system.
    Requires admin permissions.

    Query Parameters:
        is_active: Filter by active status (optional, 'true' or 'false')

    Returns:
        200: List of tenants
            {
                "tenants": [ { tenant data }, ... ],
                "count": 5
            }
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    if not _is_admin(current_user):
        return jsonify({'error': 'Admin access required'}), 403

    # Build query
    query = Tenant.query

    # Filter by is_active if provided
    is_active = request.args.get('is_active')
    if is_active is not None:
        if is_active.lower() == 'true':
            query = query.filter_by(is_active=True)
        elif is_active.lower() == 'false':
            query = query.filter_by(is_active=False)
        else:
            return jsonify({
                'error': "is_active must be 'true' or 'false'"
            }), 400

    # Execute query ordered by name
    tenants = query.order_by(Tenant.name.asc()).all()

    return jsonify({
        'tenants': [tenant.to_dict() for tenant in tenants],
        'count': len(tenants)
    }), 200


@tenants_bp.route('/<tenant_id>', methods=['GET'])
@jwt_required()
def get_tenant(tenant_id):
    """
    Get a specific tenant by UUID.

    Args:
        tenant_id: Tenant UUID

    Returns:
        200: Tenant data
            { tenant data }
        400: Invalid tenant_id format
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions
        404: Tenant not found
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    if not _is_admin(current_user):
        return jsonify({'error': 'Admin access required'}), 403

    # Validate tenant_id format
    if not isinstance(tenant_id, str) or len(tenant_id) > 64:
        return jsonify({
            'error': 'Invalid tenant_id format'
        }), 400

    # Look up by UUID
    tenant = Tenant.get_by_uuid(tenant_id)

    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404

    return jsonify(tenant.to_dict()), 200


@tenants_bp.route('', methods=['POST'])
@jwt_required()
def create_tenant():
    """
    Create a new tenant.

    Tenants are top-level entities for multi-tenant data isolation.
    Requires admin permissions.

    Request Body:
        {
            "name": "Tenant Name" (required),
            "slug": "tenant-slug" (required, lowercase alphanumeric with hyphens, 3-100 chars),
            "description": "Tenant description" (optional),
            "is_active": true (optional, defaults to true)
        }

    Returns:
        201: New tenant created
            { tenant data }
        400: Missing required field or invalid data
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions
        409: Slug already exists
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    if not _is_admin(current_user):
        return jsonify({'error': 'Admin access required'}), 403

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate name
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400

    if not isinstance(name, str) or len(name) > 255:
        return jsonify({
            'error': 'name must be a string with max 255 characters'
        }), 400

    name = name.strip()
    if not name:
        return jsonify({'error': 'name cannot be empty'}), 400

    # Validate slug
    slug = data.get('slug')
    if not slug:
        return jsonify({'error': 'slug is required'}), 400

    if not isinstance(slug, str):
        return jsonify({
            'error': 'slug must be a string'
        }), 400

    slug = slug.strip().lower()

    if not _validate_slug(slug):
        return jsonify({
            'error': 'slug must be lowercase alphanumeric with hyphens, 3-100 characters'
        }), 400

    # Check if slug already exists
    existing = Tenant.get_by_slug(slug)
    if existing:
        return jsonify({
            'error': 'A tenant with this slug already exists'
        }), 409

    # Validate description if provided
    description = data.get('description')
    if description is not None:
        if not isinstance(description, str):
            return jsonify({
                'error': 'description must be a string'
            }), 400

    # Validate is_active if provided
    is_active = data.get('is_active', True)
    if not isinstance(is_active, bool):
        return jsonify({
            'error': 'is_active must be a boolean'
        }), 400

    # Create new tenant
    tenant = Tenant(
        name=name,
        slug=slug,
        description=description,
        is_active=is_active
    )

    try:
        db.session.add(tenant)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create tenant: {str(e)}'
        }), 500

    return jsonify(tenant.to_dict()), 201


@tenants_bp.route('/<tenant_id>', methods=['PUT'])
@jwt_required()
def update_tenant(tenant_id):
    """
    Update an existing tenant.

    Requires admin permissions.

    Args:
        tenant_id: Tenant UUID

    Request Body:
        {
            "name": "Updated Tenant Name" (optional),
            "slug": "updated-slug" (optional),
            "description": "Updated description" (optional),
            "is_active": false (optional)
        }

    Returns:
        200: Updated tenant
            { tenant data }
        400: Invalid data
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions
        404: Tenant not found
        409: Slug already exists (if changing slug)
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    if not _is_admin(current_user):
        return jsonify({'error': 'Admin access required'}), 403

    # Validate tenant_id format
    if not isinstance(tenant_id, str) or len(tenant_id) > 64:
        return jsonify({
            'error': 'Invalid tenant_id format'
        }), 400

    # Look up by UUID
    tenant = Tenant.get_by_uuid(tenant_id)

    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Update name if provided
    if 'name' in data:
        name = data['name']
        if not name:
            return jsonify({'error': 'name cannot be empty'}), 400
        if not isinstance(name, str) or len(name) > 255:
            return jsonify({
                'error': 'name must be a string with max 255 characters'
            }), 400
        tenant.name = name.strip()

    # Update slug if provided
    if 'slug' in data:
        slug = data['slug']
        if not slug:
            return jsonify({'error': 'slug cannot be empty'}), 400
        if not isinstance(slug, str):
            return jsonify({
                'error': 'slug must be a string'
            }), 400

        slug = slug.strip().lower()

        if not _validate_slug(slug):
            return jsonify({
                'error': 'slug must be lowercase alphanumeric with hyphens, 3-100 characters'
            }), 400

        # Check if slug already exists (for a different tenant)
        existing = Tenant.get_by_slug(slug)
        if existing and existing.id != tenant.id:
            return jsonify({
                'error': 'A tenant with this slug already exists'
            }), 409

        tenant.slug = slug

    # Update description if provided
    if 'description' in data:
        description = data['description']
        if description is not None and not isinstance(description, str):
            return jsonify({
                'error': 'description must be a string'
            }), 400
        tenant.description = description

    # Update is_active if provided
    if 'is_active' in data:
        is_active = data['is_active']
        if not isinstance(is_active, bool):
            return jsonify({
                'error': 'is_active must be a boolean'
            }), 400
        tenant.is_active = is_active

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update tenant: {str(e)}'
        }), 500

    return jsonify(tenant.to_dict()), 200
