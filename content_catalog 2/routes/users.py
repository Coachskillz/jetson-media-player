"""
Content Catalog Users Routes.

Blueprint for user management API endpoints:
- GET /: List all users with optional filtering
- POST /: Create a new user
- GET /<id>: Get a specific user by ID
- PUT /<id>: Update a user
- DELETE /<id>: Delete (deactivate) a user
- POST /<id>/suspend: Suspend a user account
- POST /<id>/reactivate: Reactivate a suspended/deactivated user

All endpoints are prefixed with /api/v1/users when registered with the app.
All endpoints require JWT authentication.
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from content_catalog.models import db, User, Organization
from content_catalog.services.auth_service import AuthService
from content_catalog.services.audit_service import AuditService
from content_catalog.services.user_service import UserService


# Create users blueprint
users_bp = Blueprint('users', __name__)


def _get_current_user():
    """
    Get the current authenticated user from JWT identity.

    Returns:
        User object or None if not found
    """
    current_user_id = get_jwt_identity()
    return db.session.get(User, current_user_id)


def _can_manage_users(user):
    """
    Check if the user has permission to manage other users.

    Only Super Admins, Admins, and Content Managers can manage users.

    Args:
        user: The User object to check permissions for

    Returns:
        True if user can manage other users, False otherwise
    """
    if not user:
        return False
    return user.role in [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER
    ]


@users_bp.route('', methods=['GET'])
@jwt_required()
def list_users():
    """
    List all users with optional filtering.

    Returns a paginated list of users with optional filtering by status, role,
    or organization.

    Query Parameters:
        status: Filter by status (pending, active, suspended, etc.)
        role: Filter by role (super_admin, admin, content_manager, etc.)
        organization_id: Filter by organization ID
        page: Page number (default: 1)
        per_page: Items per page (default: 20, max: 100)

    Returns:
        200: List of users
            {
                "users": [ { user data }, ... ],
                "count": 5,
                "page": 1,
                "per_page": 20,
                "total": 50
            }
        401: Unauthorized (missing or invalid token)
        403: Forbidden (insufficient permissions)
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to list users
    if not _can_manage_users(current_user):
        return jsonify({'error': 'Insufficient permissions to list users'}), 403

    # Build query with optional filters
    query = User.query

    # Filter by status
    status_filter = request.args.get('status')
    if status_filter:
        if status_filter not in User.VALID_STATUSES:
            return jsonify({
                'error': f"Invalid status. Must be one of: {', '.join(User.VALID_STATUSES)}"
            }), 400
        query = query.filter_by(status=status_filter)

    # Filter by role
    role_filter = request.args.get('role')
    if role_filter:
        if role_filter not in User.VALID_ROLES:
            return jsonify({
                'error': f"Invalid role. Must be one of: {', '.join(User.VALID_ROLES)}"
            }), 400
        query = query.filter_by(role=role_filter)

    # Filter by organization
    organization_id = request.args.get('organization_id')
    if organization_id:
        try:
            org_id = int(organization_id)
            query = query.filter_by(organization_id=org_id)
        except ValueError:
            return jsonify({'error': 'organization_id must be an integer'}), 400

    # Pagination parameters
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1

    try:
        per_page = int(request.args.get('per_page', 20))
        if per_page < 1:
            per_page = 20
        if per_page > 100:
            per_page = 100
    except ValueError:
        per_page = 20

    # Get total count before pagination
    total = query.count()

    # Apply pagination and ordering
    users = query.order_by(User.created_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return jsonify({
        'users': [user.to_dict() for user in users],
        'count': len(users),
        'page': page,
        'per_page': per_page,
        'total': total
    }), 200


@users_bp.route('', methods=['POST'])
@jwt_required()
def create_user():
    """
    Create a new user.

    Creates a new user with the specified details. The creating user must have
    sufficient permissions to create users with the requested role.

    Request Body:
        {
            "email": "user@example.com" (required),
            "password": "secure_password" (required),
            "name": "User Name" (required),
            "role": "partner" (required),
            "organization_id": 1 (optional),
            "phone": "+1234567890" (optional),
            "status": "active" (optional, defaults to "pending")
        }

    Returns:
        201: User created successfully
            {
                "id": 1,
                "email": "user@example.com",
                ...
            }
        400: Missing required field or invalid data
        401: Unauthorized
        403: Insufficient permissions
        409: User with email already exists
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to create users
    if not _can_manage_users(current_user):
        return jsonify({'error': 'Insufficient permissions to create users'}), 403

    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate email
    email = data.get('email')
    if not email:
        return jsonify({'error': 'email is required'}), 400

    if not isinstance(email, str) or len(email) > 255:
        return jsonify({'error': 'email must be a string with max 255 characters'}), 400

    email = email.lower().strip()

    # Check if email already exists
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({'error': 'A user with this email already exists'}), 409

    # Validate password
    password = data.get('password')
    if not password:
        return jsonify({'error': 'password is required'}), 400

    if not isinstance(password, str) or len(password) < 8:
        return jsonify({'error': 'password must be at least 8 characters'}), 400

    # Validate name
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400

    if not isinstance(name, str) or len(name) > 255:
        return jsonify({'error': 'name must be a string with max 255 characters'}), 400

    # Validate role
    role = data.get('role')
    if not role:
        return jsonify({'error': 'role is required'}), 400

    if role not in User.VALID_ROLES:
        return jsonify({
            'error': f"Invalid role. Must be one of: {', '.join(User.VALID_ROLES)}"
        }), 400

    # Check if current user can create users with this role
    if not current_user.can_approve_role(role):
        return jsonify({
            'error': f'Insufficient permissions to create users with role: {role}'
        }), 403

    # Validate organization_id if provided
    organization_id = data.get('organization_id')
    if organization_id:
        try:
            org_id = int(organization_id)
            organization = db.session.get(Organization, org_id)
            if not organization:
                return jsonify({'error': f'Organization with id {org_id} not found'}), 400
            organization_id = org_id
        except (ValueError, TypeError):
            return jsonify({'error': 'organization_id must be an integer'}), 400

    # Validate phone if provided
    phone = data.get('phone')
    if phone and (not isinstance(phone, str) or len(phone) > 50):
        return jsonify({'error': 'phone must be a string with max 50 characters'}), 400

    # Validate status if provided
    status = data.get('status', User.STATUS_PENDING)
    if status not in User.VALID_STATUSES:
        return jsonify({
            'error': f"Invalid status. Must be one of: {', '.join(User.VALID_STATUSES)}"
        }), 400

    # Hash the password
    password_hash = AuthService.hash_password(password)

    # Create new user
    user = User(
        email=email,
        password_hash=password_hash,
        name=name,
        role=role,
        organization_id=organization_id,
        phone=phone,
        status=status,
        invited_by=current_user.id
    )

    try:
        db.session.add(user)

        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='user.created',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='user',
            resource_id=None,  # Will be set after commit
            details={
                'created_email': email,
                'created_role': role,
                'created_by': current_user.id
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to create user: {str(e)}'}), 500

    return jsonify(user.to_dict()), 201


@users_bp.route('/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user(user_id):
    """
    Get a specific user by ID.

    Args:
        user_id: The user ID to retrieve

    Returns:
        200: User data
            {
                "id": 1,
                "email": "user@example.com",
                ...
            }
        401: Unauthorized
        403: Insufficient permissions
        404: User not found
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Users can view their own profile or admins can view any user
    if current_user.id != user_id and not _can_manage_users(current_user):
        return jsonify({'error': 'Insufficient permissions to view this user'}), 403

    user = db.session.get(User, user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    return jsonify(user.to_dict()), 200


@users_bp.route('/<int:user_id>', methods=['PUT'])
@jwt_required()
def update_user(user_id):
    """
    Update a user.

    Updates the specified user's information. Users can update their own
    profile (limited fields), admins can update other users.

    Args:
        user_id: The user ID to update

    Request Body:
        {
            "name": "New Name" (optional),
            "phone": "+1234567890" (optional),
            "role": "partner" (optional, admin only),
            "organization_id": 1 (optional, admin only),
            "status": "active" (optional, admin only)
        }

    Returns:
        200: User updated successfully
            {
                "id": 1,
                "email": "user@example.com",
                ...
            }
        400: Invalid data
        401: Unauthorized
        403: Insufficient permissions
        404: User not found
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    user = db.session.get(User, user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check permissions
    is_self = current_user.id == user_id
    is_admin = _can_manage_users(current_user)

    if not is_self and not is_admin:
        return jsonify({'error': 'Insufficient permissions to update this user'}), 403

    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Track changes for audit log
    changes = {}

    # Update name if provided
    name = data.get('name')
    if name is not None:
        if not isinstance(name, str) or len(name) > 255:
            return jsonify({'error': 'name must be a string with max 255 characters'}), 400
        if name != user.name:
            changes['name'] = {'from': user.name, 'to': name}
            user.name = name

    # Update phone if provided
    phone = data.get('phone')
    if phone is not None:
        if phone and (not isinstance(phone, str) or len(phone) > 50):
            return jsonify({'error': 'phone must be a string with max 50 characters'}), 400
        if phone != user.phone:
            changes['phone'] = {'from': user.phone, 'to': phone}
            user.phone = phone

    # Admin-only fields
    if is_admin:
        # Update role if provided
        role = data.get('role')
        if role is not None:
            if role not in User.VALID_ROLES:
                return jsonify({
                    'error': f"Invalid role. Must be one of: {', '.join(User.VALID_ROLES)}"
                }), 400
            # Check if current user can assign this role
            if not current_user.can_approve_role(role) and role != user.role:
                return jsonify({
                    'error': f'Insufficient permissions to assign role: {role}'
                }), 403
            if role != user.role:
                changes['role'] = {'from': user.role, 'to': role}
                user.role = role

        # Update organization_id if provided
        organization_id = data.get('organization_id')
        if organization_id is not None:
            if organization_id:
                try:
                    org_id = int(organization_id)
                    organization = db.session.get(Organization, org_id)
                    if not organization:
                        return jsonify({'error': f'Organization with id {org_id} not found'}), 400
                    if org_id != user.organization_id:
                        changes['organization_id'] = {'from': user.organization_id, 'to': org_id}
                        user.organization_id = org_id
                except (ValueError, TypeError):
                    return jsonify({'error': 'organization_id must be an integer'}), 400
            else:
                if user.organization_id is not None:
                    changes['organization_id'] = {'from': user.organization_id, 'to': None}
                    user.organization_id = None

        # Update status if provided
        status = data.get('status')
        if status is not None:
            if status not in User.VALID_STATUSES:
                return jsonify({
                    'error': f"Invalid status. Must be one of: {', '.join(User.VALID_STATUSES)}"
                }), 400
            if status != user.status:
                changes['status'] = {'from': user.status, 'to': status}
                user.status = status
    else:
        # Non-admin trying to update admin-only fields
        admin_fields = ['role', 'organization_id', 'status']
        for field in admin_fields:
            if field in data:
                return jsonify({
                    'error': f'Insufficient permissions to update {field}'
                }), 403

    if not changes:
        return jsonify(user.to_dict()), 200

    try:
        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='user.updated',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='user',
            resource_id=user.id,
            details={'changes': changes}
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update user: {str(e)}'}), 500

    return jsonify(user.to_dict()), 200


@users_bp.route('/<int:user_id>', methods=['DELETE'])
@jwt_required()
def delete_user(user_id):
    """
    Delete (deactivate) a user.

    Soft-deletes a user by setting their status to 'deactivated'.
    Users cannot delete themselves.

    Args:
        user_id: The user ID to delete

    Returns:
        200: User deactivated successfully
            {
                "message": "User deactivated successfully"
            }
        401: Unauthorized
        403: Insufficient permissions
        404: User not found
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to delete users
    if not _can_manage_users(current_user):
        return jsonify({'error': 'Insufficient permissions to delete users'}), 403

    # Users cannot delete themselves
    if current_user.id == user_id:
        return jsonify({'error': 'Cannot delete your own account'}), 403

    user = db.session.get(User, user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if current user can manage this user's role
    if not current_user.can_approve_role(user.role):
        return jsonify({
            'error': f'Insufficient permissions to delete users with role: {user.role}'
        }), 403

    # Soft delete - set status to deactivated
    previous_status = user.status
    user.status = User.STATUS_DEACTIVATED

    try:
        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='user.deleted',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='user',
            resource_id=user.id,
            details={
                'deleted_email': user.email,
                'previous_status': previous_status
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete user: {str(e)}'}), 500

    return jsonify({'message': 'User deactivated successfully'}), 200


@users_bp.route('/<int:user_id>/suspend', methods=['POST'])
@jwt_required()
def suspend_user(user_id):
    """
    Suspend a user account.

    Suspends a user by setting their status to 'suspended'. Users cannot
    suspend themselves. Only admins and super admins can suspend users.

    Args:
        user_id: The user ID to suspend

    Request Body (optional):
        {
            "reason": "Violation of terms" (optional)
        }

    Returns:
        200: User suspended successfully
            {
                "message": "User suspended successfully",
                "user": { user data }
            }
        401: Unauthorized
        403: Insufficient permissions or attempting to suspend self
        404: User not found
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to suspend users
    if not _can_manage_users(current_user):
        return jsonify({'error': 'Insufficient permissions to suspend users'}), 403

    # Users cannot suspend themselves
    if current_user.id == user_id:
        return jsonify({'error': 'Cannot suspend your own account'}), 403

    user = db.session.get(User, user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if current user can manage this user's role
    if not current_user.can_approve_role(user.role):
        return jsonify({
            'error': f'Insufficient permissions to suspend users with role: {user.role}'
        }), 403

    # Get optional reason from request body
    data = request.get_json(silent=True) or {}
    reason = data.get('reason', '')

    # Suspend the user
    previous_status = user.status
    suspended_user = UserService.suspend_user(db.session, user_id)

    if not suspended_user:
        return jsonify({'error': 'Failed to suspend user'}), 500

    try:
        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='user.suspended',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='user',
            resource_id=user.id,
            details={
                'suspended_email': user.email,
                'previous_status': previous_status,
                'reason': reason
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to suspend user: {str(e)}'}), 500

    return jsonify({
        'message': 'User suspended successfully',
        'user': suspended_user.to_dict()
    }), 200


@users_bp.route('/<int:user_id>/reactivate', methods=['POST'])
@jwt_required()
def reactivate_user(user_id):
    """
    Reactivate a suspended or deactivated user account.

    Reactivates a user by setting their status to 'active'. Only admins
    and super admins can reactivate users.

    Args:
        user_id: The user ID to reactivate

    Request Body (optional):
        {
            "reason": "Account review completed" (optional)
        }

    Returns:
        200: User reactivated successfully
            {
                "message": "User reactivated successfully",
                "user": { user data }
            }
        401: Unauthorized
        403: Insufficient permissions
        404: User not found
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to reactivate users
    if not _can_manage_users(current_user):
        return jsonify({'error': 'Insufficient permissions to reactivate users'}), 403

    user = db.session.get(User, user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if current user can manage this user's role
    if not current_user.can_approve_role(user.role):
        return jsonify({
            'error': f'Insufficient permissions to reactivate users with role: {user.role}'
        }), 403

    # Get optional reason from request body
    data = request.get_json(silent=True) or {}
    reason = data.get('reason', '')

    # Reactivate the user
    previous_status = user.status
    reactivated_user = UserService.reactivate_user(db.session, user_id)

    if not reactivated_user:
        return jsonify({'error': 'Failed to reactivate user'}), 500

    try:
        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='user.reactivated',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='user',
            resource_id=user.id,
            details={
                'reactivated_email': user.email,
                'previous_status': previous_status,
                'reason': reason
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to reactivate user: {str(e)}'}), 500

    return jsonify({
        'message': 'User reactivated successfully',
        'user': reactivated_user.to_dict()
    }), 200
