"""
Content Catalog Organizations Routes

Blueprint for organization management API endpoints:
- POST /: Create a new organization
- GET /: List all organizations
- GET /<id>: Get a specific organization
- PUT /<id>: Update an organization
- POST /<id>/api-key: Generate or regenerate API key for an organization
- GET /<id>/users: Get all users for an organization
- GET /<id>/assets: Get all content assets for an organization

All endpoints are prefixed with /api/v1/organizations when registered with the app.
"""

import re

from flask import Blueprint, request, jsonify

from content_catalog.models import db, Organization, User, ContentAsset


# Create organizations blueprint
organizations_bp = Blueprint('organizations', __name__)


# Valid organization types
VALID_ORG_TYPES = ['internal', 'partner', 'advertiser']

# Valid organization statuses
VALID_ORG_STATUSES = ['active', 'pending', 'suspended', 'deactivated']


def validate_email(email):
    """
    Validate email format.

    Args:
        email: The email string to validate

    Returns:
        True if email format is valid, False otherwise
    """
    if not email:
        return True  # Email is optional
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


@organizations_bp.route('', methods=['POST'])
def create_organization():
    """
    Create a new organization.

    Organizations are top-level entities for multi-tenancy that contain
    users and content assets.

    Request Body:
        {
            "name": "Partner Company" (required),
            "type": "partner" (required, one of: internal, partner, advertiser),
            "contact_email": "contact@example.com" (optional),
            "logo_url": "https://example.com/logo.png" (optional),
            "zoho_account_id": "123456" (optional),
            "status": "active" (optional, defaults to 'active')
        }

    Returns:
        201: New organization created
            {
                "id": 1,
                "name": "Partner Company",
                "type": "partner",
                ...
            }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
    """
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

    # Validate type
    org_type = data.get('type')
    if not org_type:
        return jsonify({'error': 'type is required'}), 400

    if org_type not in VALID_ORG_TYPES:
        return jsonify({
            'error': f"type must be one of: {', '.join(VALID_ORG_TYPES)}"
        }), 400

    # Validate contact_email if provided
    contact_email = data.get('contact_email')
    if contact_email:
        if not isinstance(contact_email, str) or len(contact_email) > 255:
            return jsonify({
                'error': 'contact_email must be a string with max 255 characters'
            }), 400
        if not validate_email(contact_email):
            return jsonify({
                'error': 'contact_email must be a valid email address'
            }), 400

    # Validate logo_url if provided
    logo_url = data.get('logo_url')
    if logo_url:
        if not isinstance(logo_url, str) or len(logo_url) > 500:
            return jsonify({
                'error': 'logo_url must be a string with max 500 characters'
            }), 400

    # Validate zoho_account_id if provided
    zoho_account_id = data.get('zoho_account_id')
    if zoho_account_id:
        if not isinstance(zoho_account_id, str) or len(zoho_account_id) > 100:
            return jsonify({
                'error': 'zoho_account_id must be a string with max 100 characters'
            }), 400

    # Validate status if provided
    status = data.get('status', 'active')
    if status not in VALID_ORG_STATUSES:
        return jsonify({
            'error': f"status must be one of: {', '.join(VALID_ORG_STATUSES)}"
        }), 400

    # Create new organization
    organization = Organization(
        name=name,
        type=org_type,
        contact_email=contact_email,
        logo_url=logo_url,
        zoho_account_id=zoho_account_id,
        status=status
    )

    try:
        db.session.add(organization)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create organization: {str(e)}'
        }), 500

    return jsonify(organization.to_dict()), 201


@organizations_bp.route('', methods=['GET'])
def list_organizations():
    """
    List all organizations.

    Returns a list of all organizations registered with the Content Catalog.

    Query Parameters:
        type: Filter by organization type (optional)
        status: Filter by organization status (optional)

    Returns:
        200: List of organizations
            {
                "organizations": [ { organization data }, ... ],
                "count": 5
            }
    """
    # Build query
    query = Organization.query

    # Filter by type if provided
    org_type = request.args.get('type')
    if org_type:
        if org_type not in VALID_ORG_TYPES:
            return jsonify({
                'error': f"type must be one of: {', '.join(VALID_ORG_TYPES)}"
            }), 400
        query = query.filter_by(type=org_type)

    # Filter by status if provided
    status = request.args.get('status')
    if status:
        if status not in VALID_ORG_STATUSES:
            return jsonify({
                'error': f"status must be one of: {', '.join(VALID_ORG_STATUSES)}"
            }), 400
        query = query.filter_by(status=status)

    # Execute query ordered by creation date (newest first)
    organizations = query.order_by(Organization.created_at.desc()).all()

    return jsonify({
        'organizations': [org.to_dict() for org in organizations],
        'count': len(organizations)
    }), 200


@organizations_bp.route('/<int:organization_id>', methods=['GET'])
def get_organization(organization_id):
    """
    Get a specific organization by ID.

    Args:
        organization_id: Organization integer ID

    Returns:
        200: Organization data
            { organization data }
        404: Organization not found
            {
                "error": "Organization not found"
            }
    """
    organization = db.session.get(Organization, organization_id)

    if not organization:
        return jsonify({'error': 'Organization not found'}), 404

    return jsonify(organization.to_dict()), 200


@organizations_bp.route('/<int:organization_id>', methods=['PUT'])
def update_organization(organization_id):
    """
    Update an existing organization.

    Args:
        organization_id: Organization integer ID

    Request Body:
        {
            "name": "Updated Organization Name" (optional),
            "type": "advertiser" (optional),
            "contact_email": "new@example.com" (optional),
            "logo_url": "https://example.com/new-logo.png" (optional),
            "zoho_account_id": "654321" (optional),
            "status": "suspended" (optional)
        }

    Returns:
        200: Updated organization
            { organization data }
        400: Invalid data
            {
                "error": "error message"
            }
        404: Organization not found
            {
                "error": "Organization not found"
            }
    """
    organization = db.session.get(Organization, organization_id)

    if not organization:
        return jsonify({'error': 'Organization not found'}), 404

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
        organization.name = name

    # Update type if provided
    if 'type' in data:
        org_type = data['type']
        if not org_type:
            return jsonify({'error': 'type cannot be empty'}), 400
        if org_type not in VALID_ORG_TYPES:
            return jsonify({
                'error': f"type must be one of: {', '.join(VALID_ORG_TYPES)}"
            }), 400
        organization.type = org_type

    # Update contact_email if provided
    if 'contact_email' in data:
        contact_email = data['contact_email']
        if contact_email is not None:
            if not isinstance(contact_email, str) or len(contact_email) > 255:
                return jsonify({
                    'error': 'contact_email must be a string with max 255 characters'
                }), 400
            if contact_email and not validate_email(contact_email):
                return jsonify({
                    'error': 'contact_email must be a valid email address'
                }), 400
        organization.contact_email = contact_email

    # Update logo_url if provided
    if 'logo_url' in data:
        logo_url = data['logo_url']
        if logo_url is not None:
            if not isinstance(logo_url, str) or len(logo_url) > 500:
                return jsonify({
                    'error': 'logo_url must be a string with max 500 characters'
                }), 400
        organization.logo_url = logo_url

    # Update zoho_account_id if provided
    if 'zoho_account_id' in data:
        zoho_account_id = data['zoho_account_id']
        if zoho_account_id is not None:
            if not isinstance(zoho_account_id, str) or len(zoho_account_id) > 100:
                return jsonify({
                    'error': 'zoho_account_id must be a string with max 100 characters'
                }), 400
        organization.zoho_account_id = zoho_account_id

    # Update status if provided
    if 'status' in data:
        status = data['status']
        if not status:
            return jsonify({'error': 'status cannot be empty'}), 400
        if status not in VALID_ORG_STATUSES:
            return jsonify({
                'error': f"status must be one of: {', '.join(VALID_ORG_STATUSES)}"
            }), 400
        organization.status = status

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update organization: {str(e)}'
        }), 500

    return jsonify(organization.to_dict()), 200


@organizations_bp.route('/<int:organization_id>/api-key', methods=['POST'])
def generate_api_key(organization_id):
    """
    Generate or regenerate an API key for an organization.

    Creates a new secure random API key using secrets.token_urlsafe(32).
    If an API key already exists, it will be replaced with a new one.

    Args:
        organization_id: Organization integer ID

    Returns:
        200: API key generated successfully
            {
                "id": 1,
                "name": "Partner Company",
                "api_key": "newly_generated_api_key",
                "message": "API key generated successfully"
            }
        404: Organization not found
            {
                "error": "Organization not found"
            }
        500: Failed to save API key
            {
                "error": "Failed to generate API key: ..."
            }
    """
    organization = db.session.get(Organization, organization_id)

    if not organization:
        return jsonify({'error': 'Organization not found'}), 404

    # Generate a new secure random API key
    new_api_key = organization.generate_api_key()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to generate API key: {str(e)}'
        }), 500

    # Return organization data with the new API key visible
    response = organization.to_dict(include_api_key=True)
    response['message'] = 'API key generated successfully'

    return jsonify(response), 200


@organizations_bp.route('/<int:organization_id>/users', methods=['GET'])
def get_organization_users(organization_id):
    """
    Get all users for a specific organization.

    Returns a list of users that belong to the specified organization,
    with optional filtering by role and status.

    Args:
        organization_id: Organization integer ID

    Query Parameters:
        role: Filter by user role (optional)
        status: Filter by user status (optional)

    Returns:
        200: List of users
            {
                "users": [ { user data }, ... ],
                "count": 5,
                "organization_id": 1
            }
        404: Organization not found
            {
                "error": "Organization not found"
            }
    """
    # Verify organization exists
    organization = db.session.get(Organization, organization_id)

    if not organization:
        return jsonify({'error': 'Organization not found'}), 404

    # Build query for users
    query = User.query.filter_by(organization_id=organization_id)

    # Filter by role if provided
    role = request.args.get('role')
    if role:
        if role not in User.VALID_ROLES:
            return jsonify({
                'error': f"role must be one of: {', '.join(User.VALID_ROLES)}"
            }), 400
        query = query.filter_by(role=role)

    # Filter by status if provided
    status = request.args.get('status')
    if status:
        if status not in User.VALID_STATUSES:
            return jsonify({
                'error': f"status must be one of: {', '.join(User.VALID_STATUSES)}"
            }), 400
        query = query.filter_by(status=status)

    # Execute query ordered by creation date (newest first)
    users = query.order_by(User.created_at.desc()).all()

    return jsonify({
        'users': [user.to_dict() for user in users],
        'count': len(users),
        'organization_id': organization_id
    }), 200


@organizations_bp.route('/<int:organization_id>/assets', methods=['GET'])
def get_organization_assets(organization_id):
    """
    Get all content assets for a specific organization.

    Returns a list of content assets that belong to the specified organization,
    with optional filtering by status and category.

    Args:
        organization_id: Organization integer ID

    Query Parameters:
        status: Filter by asset status (optional)
        category: Filter by asset category (optional)

    Returns:
        200: List of content assets
            {
                "assets": [ { asset data }, ... ],
                "count": 10,
                "organization_id": 1
            }
        404: Organization not found
            {
                "error": "Organization not found"
            }
    """
    # Verify organization exists
    organization = db.session.get(Organization, organization_id)

    if not organization:
        return jsonify({'error': 'Organization not found'}), 404

    # Build query for content assets
    query = ContentAsset.query.filter_by(organization_id=organization_id)

    # Filter by status if provided
    status = request.args.get('status')
    if status:
        if status not in ContentAsset.VALID_STATUSES:
            return jsonify({
                'error': f"status must be one of: {', '.join(ContentAsset.VALID_STATUSES)}"
            }), 400
        query = query.filter_by(status=status)

    # Filter by category if provided
    category = request.args.get('category')
    if category:
        query = query.filter_by(category=category)

    # Execute query ordered by creation date (newest first)
    assets = query.order_by(ContentAsset.created_at.desc()).all()

    return jsonify({
        'assets': [asset.to_dict() for asset in assets],
        'count': len(assets),
        'organization_id': organization_id
    }), 200
