"""
Content Catalog Catalogs and Categories Routes

Blueprint for catalog and category management API endpoints:
- GET /: List all catalogs
- POST /: Create a new catalog
- GET /<catalog_id>: Get a specific catalog by UUID
- PUT /<catalog_id>: Update a catalog
- DELETE /<catalog_id>: Delete a catalog
- GET /categories: List all categories
- POST /categories: Create a new category
- GET /categories/<category_id>: Get a specific category by UUID
- PUT /categories/<category_id>: Update a category
- DELETE /categories/<category_id>: Delete a category

All endpoints require JWT authentication and are prefixed with /api/v1/catalogs.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from content_catalog.models import db
from content_catalog.models.user import User
from content_catalog.models.catalog import Catalog, Category


# Create catalogs blueprint
catalogs_bp = Blueprint('catalogs', __name__)


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


def _can_manage_catalogs(user):
    """
    Check if the user has permission to manage catalogs.

    Only Super Admins, Admins, and Content Managers can manage catalogs.

    Args:
        user: The User object to check permissions for

    Returns:
        True if user can manage catalogs, False otherwise
    """
    if not user:
        return False
    return user.role in [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER
    ]


# ============================================================================
# Catalog Endpoints
# ============================================================================

@catalogs_bp.route('', methods=['GET'])
@jwt_required()
def list_catalogs():
    """
    List all catalogs.

    Returns a list of all active catalogs, with optional filtering by tenant.
    Internal-only catalogs are only visible to users with appropriate permissions.

    Query Parameters:
        tenant_id: Filter by tenant ID (optional)
        include_inactive: Include inactive catalogs (optional, default: false)

    Returns:
        200: List of catalogs
            {
                "catalogs": [ { catalog data }, ... ],
                "count": 10
            }
        401: Unauthorized (missing or invalid token)
    """
    current_user = _get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Build query
    query = Catalog.query

    # Filter by tenant_id if provided
    tenant_id = request.args.get('tenant_id')
    if tenant_id:
        try:
            tenant_id = int(tenant_id)
            # Include global catalogs (tenant_id=None) and tenant-specific ones
            query = query.filter(
                db.or_(Catalog.tenant_id == tenant_id, Catalog.tenant_id.is_(None))
            )
        except ValueError:
            return jsonify({
                'error': 'tenant_id must be a valid integer'
            }), 400

    # Filter by active status unless include_inactive is true
    include_inactive = request.args.get('include_inactive', '').lower() == 'true'
    if not include_inactive:
        query = query.filter_by(is_active=True)

    # Filter internal-only catalogs for non-privileged users
    if not _can_manage_catalogs(current_user):
        query = query.filter_by(is_internal_only=False)

    # Execute query ordered by name
    catalogs = query.order_by(Catalog.name.asc()).all()

    return jsonify({
        'catalogs': [catalog.to_dict() for catalog in catalogs],
        'count': len(catalogs)
    }), 200


@catalogs_bp.route('', methods=['POST'])
@jwt_required()
def create_catalog():
    """
    Create a new catalog.

    Only Super Admins, Admins, and Content Managers can create catalogs.

    Request Body:
        {
            "name": "Catalog Name" (required),
            "description": "Description of the catalog" (optional),
            "tenant_id": 1 (optional, null for global catalog),
            "is_internal_only": false (optional, default: false)
        }

    Returns:
        201: Catalog created successfully
            { catalog data }
        400: Missing required field or invalid data
            { "error": "error message" }
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions
    """
    current_user = _get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check permissions
    if not _can_manage_catalogs(current_user):
        return jsonify({'error': 'Insufficient permissions to create catalogs'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate required fields
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400

    if not isinstance(name, str) or len(name) > 255:
        return jsonify({
            'error': 'name must be a string with max 255 characters'
        }), 400

    # Validate description if provided
    description = data.get('description')
    if description is not None and not isinstance(description, str):
        return jsonify({
            'error': 'description must be a string'
        }), 400

    # Validate tenant_id if provided
    tenant_id = data.get('tenant_id')
    if tenant_id is not None:
        try:
            tenant_id = int(tenant_id)
        except (ValueError, TypeError):
            return jsonify({
                'error': 'tenant_id must be a valid integer'
            }), 400

    # Validate is_internal_only if provided
    is_internal_only = data.get('is_internal_only', False)
    if not isinstance(is_internal_only, bool):
        return jsonify({
            'error': 'is_internal_only must be a boolean'
        }), 400

    # Create catalog
    catalog = Catalog(
        name=name,
        description=description,
        tenant_id=tenant_id,
        is_internal_only=is_internal_only
    )

    try:
        db.session.add(catalog)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create catalog: {str(e)}'
        }), 500

    return jsonify(catalog.to_dict()), 201


@catalogs_bp.route('/<catalog_id>', methods=['GET'])
@jwt_required()
def get_catalog(catalog_id):
    """
    Get a specific catalog by UUID.

    Args:
        catalog_id: Catalog UUID

    Returns:
        200: Catalog data
            { catalog data }
        400: Invalid catalog_id format
            { "error": "Invalid catalog_id format" }
        401: Unauthorized (missing or invalid token)
        404: Catalog not found
            { "error": "Catalog not found" }
    """
    current_user = _get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Validate catalog_id format
    if not isinstance(catalog_id, str) or len(catalog_id) > 64:
        return jsonify({
            'error': 'Invalid catalog_id format'
        }), 400

    # Look up by UUID
    catalog = Catalog.get_by_uuid(catalog_id)
    if not catalog:
        return jsonify({'error': 'Catalog not found'}), 404

    # Check visibility for internal-only catalogs
    if catalog.is_internal_only and not _can_manage_catalogs(current_user):
        return jsonify({'error': 'Catalog not found'}), 404

    return jsonify(catalog.to_dict()), 200


@catalogs_bp.route('/<catalog_id>', methods=['PUT'])
@jwt_required()
def update_catalog(catalog_id):
    """
    Update an existing catalog.

    Only Super Admins, Admins, and Content Managers can update catalogs.

    Args:
        catalog_id: Catalog UUID

    Request Body:
        {
            "name": "Updated Name" (optional),
            "description": "Updated description" (optional),
            "tenant_id": 1 (optional),
            "is_internal_only": true (optional),
            "is_active": false (optional)
        }

    Returns:
        200: Updated catalog
            { catalog data }
        400: Invalid data
            { "error": "error message" }
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions
        404: Catalog not found
    """
    current_user = _get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check permissions
    if not _can_manage_catalogs(current_user):
        return jsonify({'error': 'Insufficient permissions to update catalogs'}), 403

    # Validate catalog_id format
    if not isinstance(catalog_id, str) or len(catalog_id) > 64:
        return jsonify({
            'error': 'Invalid catalog_id format'
        }), 400

    # Look up by UUID
    catalog = Catalog.get_by_uuid(catalog_id)
    if not catalog:
        return jsonify({'error': 'Catalog not found'}), 404

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
        catalog.name = name

    # Update description if provided
    if 'description' in data:
        description = data['description']
        if description is not None and not isinstance(description, str):
            return jsonify({
                'error': 'description must be a string'
            }), 400
        catalog.description = description

    # Update tenant_id if provided
    if 'tenant_id' in data:
        tenant_id = data['tenant_id']
        if tenant_id is not None:
            try:
                tenant_id = int(tenant_id)
            except (ValueError, TypeError):
                return jsonify({
                    'error': 'tenant_id must be a valid integer'
                }), 400
        catalog.tenant_id = tenant_id

    # Update is_internal_only if provided
    if 'is_internal_only' in data:
        is_internal_only = data['is_internal_only']
        if not isinstance(is_internal_only, bool):
            return jsonify({
                'error': 'is_internal_only must be a boolean'
            }), 400
        catalog.is_internal_only = is_internal_only

    # Update is_active if provided
    if 'is_active' in data:
        is_active = data['is_active']
        if not isinstance(is_active, bool):
            return jsonify({
                'error': 'is_active must be a boolean'
            }), 400
        catalog.is_active = is_active

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update catalog: {str(e)}'
        }), 500

    return jsonify(catalog.to_dict()), 200


@catalogs_bp.route('/<catalog_id>', methods=['DELETE'])
@jwt_required()
def delete_catalog(catalog_id):
    """
    Delete a catalog.

    Only Super Admins and Admins can delete catalogs.
    Note: This will also delete all categories in the catalog.

    Args:
        catalog_id: Catalog UUID

    Returns:
        200: Catalog deleted successfully
            {
                "message": "Catalog deleted successfully",
                "id": 1,
                "uuid": "uuid-string"
            }
        400: Invalid catalog_id format
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions
        404: Catalog not found
    """
    current_user = _get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Only Super Admins and Admins can delete catalogs
    if current_user.role not in [User.ROLE_SUPER_ADMIN, User.ROLE_ADMIN]:
        return jsonify({'error': 'Insufficient permissions to delete catalogs'}), 403

    # Validate catalog_id format
    if not isinstance(catalog_id, str) or len(catalog_id) > 64:
        return jsonify({
            'error': 'Invalid catalog_id format'
        }), 400

    # Look up by UUID
    catalog = Catalog.get_by_uuid(catalog_id)
    if not catalog:
        return jsonify({'error': 'Catalog not found'}), 404

    # Store info for response
    catalog_id_response = catalog.id
    catalog_uuid = catalog.uuid

    try:
        db.session.delete(catalog)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to delete catalog: {str(e)}'
        }), 500

    return jsonify({
        'message': 'Catalog deleted successfully',
        'id': catalog_id_response,
        'uuid': catalog_uuid
    }), 200


# ============================================================================
# Category Endpoints
# ============================================================================

@catalogs_bp.route('/categories', methods=['GET'])
@jwt_required()
def list_categories():
    """
    List all categories.

    Returns a list of all active categories, with optional filtering.

    Query Parameters:
        catalog_id: Filter by catalog ID (optional)
        parent_id: Filter by parent category ID (optional, use 'root' for root categories)
        include_inactive: Include inactive categories (optional, default: false)

    Returns:
        200: List of categories
            {
                "categories": [ { category data }, ... ],
                "count": 10
            }
        401: Unauthorized (missing or invalid token)
    """
    current_user = _get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Build query
    query = Category.query

    # Filter by catalog_id if provided
    catalog_id = request.args.get('catalog_id')
    if catalog_id:
        try:
            catalog_id = int(catalog_id)
            query = query.filter_by(catalog_id=catalog_id)
        except ValueError:
            return jsonify({
                'error': 'catalog_id must be a valid integer'
            }), 400

    # Filter by parent_id if provided
    parent_id = request.args.get('parent_id')
    if parent_id:
        if parent_id.lower() == 'root':
            query = query.filter(Category.parent_id.is_(None))
        else:
            try:
                parent_id = int(parent_id)
                query = query.filter_by(parent_id=parent_id)
            except ValueError:
                return jsonify({
                    'error': 'parent_id must be a valid integer or "root"'
                }), 400

    # Filter by active status unless include_inactive is true
    include_inactive = request.args.get('include_inactive', '').lower() == 'true'
    if not include_inactive:
        query = query.filter_by(is_active=True)

    # Execute query ordered by sort_order and name
    categories = query.order_by(Category.sort_order.asc(), Category.name.asc()).all()

    return jsonify({
        'categories': [category.to_dict() for category in categories],
        'count': len(categories)
    }), 200


@catalogs_bp.route('/categories', methods=['POST'])
@jwt_required()
def create_category():
    """
    Create a new category.

    Only Super Admins, Admins, and Content Managers can create categories.

    Request Body:
        {
            "name": "Category Name" (required),
            "catalog_id": 1 (required),
            "description": "Description of the category" (optional),
            "parent_id": 1 (optional, null for root category),
            "tenant_id": 1 (optional),
            "sort_order": 0 (optional, default: 0)
        }

    Returns:
        201: Category created successfully
            { category data }
        400: Missing required field or invalid data
            { "error": "error message" }
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions
    """
    current_user = _get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check permissions
    if not _can_manage_catalogs(current_user):
        return jsonify({'error': 'Insufficient permissions to create categories'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate required fields
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400

    if not isinstance(name, str) or len(name) > 255:
        return jsonify({
            'error': 'name must be a string with max 255 characters'
        }), 400

    # Validate catalog_id (required)
    catalog_id = data.get('catalog_id')
    if catalog_id is None:
        return jsonify({'error': 'catalog_id is required'}), 400

    try:
        catalog_id = int(catalog_id)
    except (ValueError, TypeError):
        return jsonify({
            'error': 'catalog_id must be a valid integer'
        }), 400

    # Verify catalog exists
    catalog = db.session.get(Catalog, catalog_id)
    if not catalog:
        return jsonify({
            'error': f'Catalog with id {catalog_id} not found'
        }), 400

    # Validate description if provided
    description = data.get('description')
    if description is not None and not isinstance(description, str):
        return jsonify({
            'error': 'description must be a string'
        }), 400

    # Validate parent_id if provided
    parent_id = data.get('parent_id')
    if parent_id is not None:
        try:
            parent_id = int(parent_id)
        except (ValueError, TypeError):
            return jsonify({
                'error': 'parent_id must be a valid integer'
            }), 400

        # Verify parent category exists and belongs to same catalog
        parent = db.session.get(Category, parent_id)
        if not parent:
            return jsonify({
                'error': f'Parent category with id {parent_id} not found'
            }), 400
        if parent.catalog_id != catalog_id:
            return jsonify({
                'error': 'Parent category must belong to the same catalog'
            }), 400

    # Validate tenant_id if provided
    tenant_id = data.get('tenant_id')
    if tenant_id is not None:
        try:
            tenant_id = int(tenant_id)
        except (ValueError, TypeError):
            return jsonify({
                'error': 'tenant_id must be a valid integer'
            }), 400
    else:
        # Default to catalog's tenant_id
        tenant_id = catalog.tenant_id

    # Validate sort_order if provided
    sort_order = data.get('sort_order', 0)
    try:
        sort_order = int(sort_order)
    except (ValueError, TypeError):
        return jsonify({
            'error': 'sort_order must be a valid integer'
        }), 400

    # Create category
    category = Category(
        name=name,
        catalog_id=catalog_id,
        description=description,
        parent_id=parent_id,
        tenant_id=tenant_id,
        sort_order=sort_order
    )

    try:
        db.session.add(category)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create category: {str(e)}'
        }), 500

    return jsonify(category.to_dict()), 201


@catalogs_bp.route('/categories/<category_id>', methods=['GET'])
@jwt_required()
def get_category(category_id):
    """
    Get a specific category by UUID.

    Args:
        category_id: Category UUID

    Query Parameters:
        include_children: Include child categories in response (optional, default: false)

    Returns:
        200: Category data
            { category data }
        400: Invalid category_id format
            { "error": "Invalid category_id format" }
        401: Unauthorized (missing or invalid token)
        404: Category not found
            { "error": "Category not found" }
    """
    current_user = _get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Validate category_id format
    if not isinstance(category_id, str) or len(category_id) > 64:
        return jsonify({
            'error': 'Invalid category_id format'
        }), 400

    # Look up by UUID
    category = Category.get_by_uuid(category_id)
    if not category:
        return jsonify({'error': 'Category not found'}), 404

    # Check if children should be included
    include_children = request.args.get('include_children', '').lower() == 'true'

    return jsonify(category.to_dict(include_children=include_children)), 200


@catalogs_bp.route('/categories/<category_id>', methods=['PUT'])
@jwt_required()
def update_category(category_id):
    """
    Update an existing category.

    Only Super Admins, Admins, and Content Managers can update categories.

    Args:
        category_id: Category UUID

    Request Body:
        {
            "name": "Updated Name" (optional),
            "description": "Updated description" (optional),
            "parent_id": 1 (optional, null to make root category),
            "sort_order": 0 (optional),
            "is_active": false (optional)
        }

    Returns:
        200: Updated category
            { category data }
        400: Invalid data
            { "error": "error message" }
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions
        404: Category not found
    """
    current_user = _get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check permissions
    if not _can_manage_catalogs(current_user):
        return jsonify({'error': 'Insufficient permissions to update categories'}), 403

    # Validate category_id format
    if not isinstance(category_id, str) or len(category_id) > 64:
        return jsonify({
            'error': 'Invalid category_id format'
        }), 400

    # Look up by UUID
    category = Category.get_by_uuid(category_id)
    if not category:
        return jsonify({'error': 'Category not found'}), 404

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
        category.name = name

    # Update description if provided
    if 'description' in data:
        description = data['description']
        if description is not None and not isinstance(description, str):
            return jsonify({
                'error': 'description must be a string'
            }), 400
        category.description = description

    # Update parent_id if provided
    if 'parent_id' in data:
        parent_id = data['parent_id']
        if parent_id is not None:
            try:
                parent_id = int(parent_id)
            except (ValueError, TypeError):
                return jsonify({
                    'error': 'parent_id must be a valid integer'
                }), 400

            # Prevent self-reference
            if parent_id == category.id:
                return jsonify({
                    'error': 'Category cannot be its own parent'
                }), 400

            # Verify parent exists and belongs to same catalog
            parent = db.session.get(Category, parent_id)
            if not parent:
                return jsonify({
                    'error': f'Parent category with id {parent_id} not found'
                }), 400
            if parent.catalog_id != category.catalog_id:
                return jsonify({
                    'error': 'Parent category must belong to the same catalog'
                }), 400

            # Prevent circular references
            ancestors = parent.get_ancestors()
            if category.id in [a.id for a in ancestors]:
                return jsonify({
                    'error': 'Circular reference detected: parent is a descendant of this category'
                }), 400

        category.parent_id = parent_id

    # Update sort_order if provided
    if 'sort_order' in data:
        sort_order = data['sort_order']
        try:
            sort_order = int(sort_order)
        except (ValueError, TypeError):
            return jsonify({
                'error': 'sort_order must be a valid integer'
            }), 400
        category.sort_order = sort_order

    # Update is_active if provided
    if 'is_active' in data:
        is_active = data['is_active']
        if not isinstance(is_active, bool):
            return jsonify({
                'error': 'is_active must be a boolean'
            }), 400
        category.is_active = is_active

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update category: {str(e)}'
        }), 500

    return jsonify(category.to_dict()), 200


@catalogs_bp.route('/categories/<category_id>', methods=['DELETE'])
@jwt_required()
def delete_category(category_id):
    """
    Delete a category.

    Only Super Admins and Admins can delete categories.
    Child categories will have their parent_id set to null.

    Args:
        category_id: Category UUID

    Returns:
        200: Category deleted successfully
            {
                "message": "Category deleted successfully",
                "id": 1,
                "uuid": "uuid-string"
            }
        400: Invalid category_id format
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions
        404: Category not found
    """
    current_user = _get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Only Super Admins and Admins can delete categories
    if current_user.role not in [User.ROLE_SUPER_ADMIN, User.ROLE_ADMIN]:
        return jsonify({'error': 'Insufficient permissions to delete categories'}), 403

    # Validate category_id format
    if not isinstance(category_id, str) or len(category_id) > 64:
        return jsonify({
            'error': 'Invalid category_id format'
        }), 400

    # Look up by UUID
    category = Category.get_by_uuid(category_id)
    if not category:
        return jsonify({'error': 'Category not found'}), 404

    # Store info for response
    category_id_response = category.id
    category_uuid = category.uuid

    try:
        db.session.delete(category)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to delete category: {str(e)}'
        }), 500

    return jsonify({
        'message': 'Category deleted successfully',
        'id': category_id_response,
        'uuid': category_uuid
    }), 200
