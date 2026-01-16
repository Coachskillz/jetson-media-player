"""
CMS Users Routes

Blueprint for user management API endpoints:
- GET /: List all users (with filtering)
- GET /<id>: Get user details
- PUT /<id>: Update user information
- POST /<id>/approve: Approve a pending user
- POST /<id>/reject: Reject a pending user
- POST /<id>/suspend: Suspend an active user
- POST /<id>/reactivate: Reactivate a suspended user
- POST /<id>/deactivate: Permanently deactivate a user
- POST /<id>/reset-password: Reset a user's password
- DELETE /<id>/sessions: Revoke all user sessions
- DELETE /<id>/sessions/<session_id>: Revoke a specific session

All endpoints are prefixed with /api/v1/users when registered with the app.
All endpoints require authentication and admin or higher role.
"""

from datetime import datetime, timezone
import secrets

from flask import Blueprint, request, jsonify

from cms.models import db, User, UserSession
from cms.models.user import ROLE_HIERARCHY, USER_STATUSES
from cms.utils.auth import login_required, get_current_user
from cms.utils.permissions import (
    require_role,
    can_manage_user,
    can_manage_role,
    check_can_manage_user,
    VALID_ROLES,
)
from cms.utils.audit import log_user_management_action


# Create users blueprint
users_bp = Blueprint('users', __name__)


def _validate_password(password):
    """
    Validate password meets requirements.

    Requirements:
    - Minimum 12 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - At least one special character

    Args:
        password: Password string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not password or len(password) < 12:
        return False, 'Password must be at least 12 characters long'

    if not any(c.isupper() for c in password):
        return False, 'Password must contain at least one uppercase letter'

    if not any(c.islower() for c in password):
        return False, 'Password must contain at least one lowercase letter'

    if not any(c.isdigit() for c in password):
        return False, 'Password must contain at least one number'

    special_chars = set('!@#$%^&*()_+-=[]{}|;:,.<>?/~`')
    if not any(c in special_chars for c in password):
        return False, 'Password must contain at least one special character'

    return True, None


@users_bp.route('', methods=['GET'])
@login_required
@require_role('admin')
def list_users():
    """
    List all users with optional filtering.

    Returns a list of all users in the system. Super admins see all users,
    regular admins only see users in their network.

    Query Parameters:
        status: Filter by status (pending, active, suspended, deactivated)
        role: Filter by role (super_admin, admin, content_manager, viewer)
        network_id: Filter by network UUID
        search: Search by name or email (partial match)

    Returns:
        200: List of users
            {
                "users": [ { user data }, ... ],
                "count": 5
            }
        400: Invalid filter value
    """
    current_user = get_current_user()

    # Build query with optional filters
    query = User.query

    # Filter by status
    status_filter = request.args.get('status')
    if status_filter:
        if status_filter not in USER_STATUSES:
            return jsonify({
                'error': f"Invalid status. Must be one of: {', '.join(USER_STATUSES)}"
            }), 400
        query = query.filter_by(status=status_filter)

    # Filter by role
    role_filter = request.args.get('role')
    if role_filter:
        if role_filter not in VALID_ROLES:
            return jsonify({
                'error': f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}"
            }), 400
        query = query.filter_by(role=role_filter)

    # Filter by network
    network_id = request.args.get('network_id')
    if network_id:
        query = query.filter_by(network_id=network_id)

    # Non-super admins can only see users in their network
    # and cannot see other admins (unless they are super_admin)
    if current_user.role != 'super_admin':
        # Filter to same network
        if current_user.network_id:
            query = query.filter_by(network_id=current_user.network_id)
        # Filter out admins and super_admins (can only see lower roles)
        query = query.filter(User.role.in_(['content_manager', 'viewer']))

    # Search by name or email
    search = request.args.get('search')
    if search:
        search_pattern = f'%{search}%'
        query = query.filter(
            db.or_(
                User.name.ilike(search_pattern),
                User.email.ilike(search_pattern)
            )
        )

    # Execute query ordered by created_at descending
    users = query.order_by(User.created_at.desc()).all()

    return jsonify({
        'users': [user.to_dict() for user in users],
        'count': len(users)
    }), 200


@users_bp.route('/<user_id>', methods=['GET'])
@login_required
@require_role('admin')
def get_user(user_id):
    """
    Get a single user by ID.

    Args:
        user_id: User UUID

    Returns:
        200: User details with related information
        403: Insufficient permissions to view this user
        404: User not found
    """
    current_user = get_current_user()

    # Find user by ID
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Non-super admins can only view users they can manage
    if current_user.role != 'super_admin':
        if not can_manage_user(current_user, user) and current_user.id != user.id:
            return jsonify({
                'error': 'Insufficient permissions to view this user'
            }), 403

    # Get user data
    user_data = user.to_dict()

    # Add inviter info if available
    if user.inviter:
        user_data['inviter'] = {
            'id': user.inviter.id,
            'email': user.inviter.email,
            'name': user.inviter.name
        }

    # Add approver info if available
    if user.approver:
        user_data['approver'] = {
            'id': user.approver.id,
            'email': user.approver.email,
            'name': user.approver.name
        }

    # Add network info if available
    if user.network:
        user_data['network'] = {
            'id': user.network.id,
            'name': user.network.name
        }

    # Add active sessions count (for admins viewing users)
    active_sessions = UserSession.query.filter(
        UserSession.user_id == user.id,
        UserSession.expires_at > datetime.now(timezone.utc)
    ).count()
    user_data['active_sessions'] = active_sessions

    return jsonify(user_data), 200


@users_bp.route('/<user_id>', methods=['PUT'])
@login_required
@require_role('admin')
def update_user(user_id):
    """
    Update a user's information.

    Only allows updating non-security fields. Role changes must respect
    the hierarchy (cannot assign a role equal or higher than your own).

    Args:
        user_id: User UUID

    Request Body:
        {
            "name": "Updated Name",
            "phone": "123-456-7890",
            "role": "content_manager",
            "network_id": "uuid-of-network"
        }

    Returns:
        200: User updated successfully
        400: Invalid data
        403: Insufficient permissions
        404: User not found
    """
    current_user = get_current_user()

    # Find user by ID
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if current user can manage this user
    # Users can update their own non-role fields
    is_self = current_user.id == user.id
    if not is_self:
        allowed, error = check_can_manage_user(current_user, user, 'update')
        if not allowed:
            return jsonify({'error': error}), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Track changes for audit log
    changes = {}

    # Update name if provided
    if 'name' in data:
        name = data['name']
        if not name or not isinstance(name, str) or len(name) > 200:
            return jsonify({
                'error': 'name must be a non-empty string with max 200 characters'
            }), 400
        if user.name != name:
            changes['name'] = {'before': user.name, 'after': name}
            user.name = name

    # Update phone if provided
    if 'phone' in data:
        phone = data['phone']
        if phone is not None and (not isinstance(phone, str) or len(phone) > 50):
            return jsonify({
                'error': 'phone must be a string with max 50 characters'
            }), 400
        if user.phone != phone:
            changes['phone'] = {'before': user.phone, 'after': phone}
            user.phone = phone

    # Update role if provided (not allowed for self-updates)
    if 'role' in data and not is_self:
        new_role = data['role']
        if new_role not in VALID_ROLES:
            return jsonify({
                'error': f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}"
            }), 400

        # Check if current user can assign this role
        if not can_manage_role(current_user, new_role):
            return jsonify({
                'error': f'Cannot assign role: {new_role}'
            }), 403

        if user.role != new_role:
            changes['role'] = {'before': user.role, 'after': new_role}
            user.role = new_role

    # Update network_id if provided (not allowed for self-updates)
    if 'network_id' in data and not is_self:
        new_network_id = data['network_id']
        # Network can be null for super_admin
        if new_network_id is not None:
            from cms.models import Network
            network = db.session.get(Network, new_network_id)
            if not network:
                return jsonify({
                    'error': f'Network with id {new_network_id} not found'
                }), 400

        if user.network_id != new_network_id:
            changes['network_id'] = {'before': user.network_id, 'after': new_network_id}
            user.network_id = new_network_id

    if not changes:
        return jsonify({
            'message': 'No changes made',
            'user': user.to_dict()
        }), 200

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update user: {str(e)}'
        }), 500

    # Log the action
    log_user_management_action(
        action='update',
        target_user_id=user.id,
        target_user_email=user.email,
        target_user_name=user.name,
        details={'changes': changes}
    )

    return jsonify({
        'message': 'User updated successfully',
        'user': user.to_dict()
    }), 200


@users_bp.route('/<user_id>/approve', methods=['POST'])
@login_required
@require_role('admin')
def approve_user(user_id):
    """
    Approve a pending user.

    Changes the user's status from 'pending' to 'active'.

    Args:
        user_id: User UUID

    Returns:
        200: User approved successfully
        400: User is not in pending status
        403: Insufficient permissions
        404: User not found
    """
    current_user = get_current_user()

    # Find user by ID
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if current user can manage this user
    allowed, error = check_can_manage_user(current_user, user, 'approve')
    if not allowed:
        return jsonify({'error': error}), 403

    # Check if user is pending
    if user.status != 'pending':
        return jsonify({
            'error': f'Cannot approve user with status: {user.status}'
        }), 400

    # Approve the user
    user.status = 'active'
    user.approved_by = current_user.id
    user.approved_at = datetime.now(timezone.utc)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to approve user: {str(e)}'
        }), 500

    # Log the action
    log_user_management_action(
        action='approve',
        target_user_id=user.id,
        target_user_email=user.email,
        target_user_name=user.name,
        details={'previous_status': 'pending'}
    )

    return jsonify({
        'message': 'User approved successfully',
        'user': user.to_dict()
    }), 200


@users_bp.route('/<user_id>/reject', methods=['POST'])
@login_required
@require_role('admin')
def reject_user(user_id):
    """
    Reject a pending user.

    Changes the user's status from 'pending' to 'rejected'.

    Args:
        user_id: User UUID

    Request Body:
        {
            "reason": "Rejection reason" (optional)
        }

    Returns:
        200: User rejected successfully
        400: User is not in pending status
        403: Insufficient permissions
        404: User not found
    """
    current_user = get_current_user()

    # Find user by ID
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if current user can manage this user
    allowed, error = check_can_manage_user(current_user, user, 'reject')
    if not allowed:
        return jsonify({'error': error}), 403

    # Check if user is pending
    if user.status != 'pending':
        return jsonify({
            'error': f'Cannot reject user with status: {user.status}'
        }), 400

    # Get optional reason
    data = request.get_json(silent=True) or {}
    reason = data.get('reason')

    if reason and (not isinstance(reason, str) or len(reason) > 1000):
        return jsonify({
            'error': 'reason must be a string with max 1000 characters'
        }), 400

    # Reject the user
    user.status = 'rejected'
    user.rejection_reason = reason

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to reject user: {str(e)}'
        }), 500

    # Log the action
    log_user_management_action(
        action='reject',
        target_user_id=user.id,
        target_user_email=user.email,
        target_user_name=user.name,
        details={'reason': reason}
    )

    return jsonify({
        'message': 'User rejected successfully',
        'user': user.to_dict()
    }), 200


@users_bp.route('/<user_id>/suspend', methods=['POST'])
@login_required
@require_role('admin')
def suspend_user(user_id):
    """
    Suspend an active user.

    Suspends the user account and revokes all their sessions.
    Suspended users cannot log in but can be reactivated.

    Args:
        user_id: User UUID

    Request Body:
        {
            "reason": "Suspension reason" (optional)
        }

    Returns:
        200: User suspended successfully
        400: User is not in active status
        403: Insufficient permissions or cannot suspend yourself
        404: User not found
    """
    current_user = get_current_user()

    # Find user by ID
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if current user can manage this user
    allowed, error = check_can_manage_user(current_user, user, 'suspend')
    if not allowed:
        return jsonify({'error': error}), 403

    # Check if user is active
    if user.status != 'active':
        return jsonify({
            'error': f'Cannot suspend user with status: {user.status}'
        }), 400

    # Get optional reason
    data = request.get_json(silent=True) or {}
    reason = data.get('reason')

    if reason and (not isinstance(reason, str) or len(reason) > 1000):
        return jsonify({
            'error': 'reason must be a string with max 1000 characters'
        }), 400

    # Suspend the user
    user.status = 'suspended'
    user.suspended_at = datetime.now(timezone.utc)
    user.suspended_by = current_user.id
    user.suspended_reason = reason

    # Revoke all user sessions
    sessions_revoked = UserSession.query.filter_by(user_id=user.id).delete()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to suspend user: {str(e)}'
        }), 500

    # Log the action
    log_user_management_action(
        action='suspend',
        target_user_id=user.id,
        target_user_email=user.email,
        target_user_name=user.name,
        details={'reason': reason, 'sessions_revoked': sessions_revoked}
    )

    return jsonify({
        'message': 'User suspended successfully',
        'user': user.to_dict(),
        'sessions_revoked': sessions_revoked
    }), 200


@users_bp.route('/<user_id>/reactivate', methods=['POST'])
@login_required
@require_role('admin')
def reactivate_user(user_id):
    """
    Reactivate a suspended user.

    Changes the user's status from 'suspended' to 'active'.
    The user will be able to log in again.

    Args:
        user_id: User UUID

    Returns:
        200: User reactivated successfully
        400: User is not in suspended status
        403: Insufficient permissions
        404: User not found
    """
    current_user = get_current_user()

    # Find user by ID
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if current user can manage this user
    allowed, error = check_can_manage_user(current_user, user, 'reactivate')
    if not allowed:
        return jsonify({'error': error}), 403

    # Check if user is suspended
    if user.status != 'suspended':
        return jsonify({
            'error': f'Cannot reactivate user with status: {user.status}'
        }), 400

    # Reactivate the user
    previous_suspended_at = user.suspended_at
    previous_suspended_by = user.suspended_by
    previous_suspended_reason = user.suspended_reason

    user.status = 'active'
    user.suspended_at = None
    user.suspended_by = None
    user.suspended_reason = None

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to reactivate user: {str(e)}'
        }), 500

    # Log the action
    log_user_management_action(
        action='reactivate',
        target_user_id=user.id,
        target_user_email=user.email,
        target_user_name=user.name,
        details={
            'previous_suspended_at': previous_suspended_at.isoformat() if previous_suspended_at else None,
            'previous_suspended_by': previous_suspended_by,
            'previous_suspended_reason': previous_suspended_reason
        }
    )

    return jsonify({
        'message': 'User reactivated successfully',
        'user': user.to_dict()
    }), 200


@users_bp.route('/<user_id>/deactivate', methods=['POST'])
@login_required
@require_role('admin')
def deactivate_user(user_id):
    """
    Permanently deactivate a user.

    This action is IRREVERSIBLE. The user account will be permanently
    disabled and cannot be reactivated. All sessions will be revoked.

    Args:
        user_id: User UUID

    Request Body:
        {
            "reason": "Deactivation reason" (required),
            "confirm": true (required for confirmation)
        }

    Returns:
        200: User deactivated successfully
        400: User is already deactivated or missing confirmation
        403: Insufficient permissions or cannot deactivate yourself
        404: User not found
    """
    current_user = get_current_user()

    # Find user by ID
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if current user can manage this user
    allowed, error = check_can_manage_user(current_user, user, 'deactivate')
    if not allowed:
        return jsonify({'error': error}), 403

    # Check if user is already deactivated
    if user.status == 'deactivated':
        return jsonify({
            'error': 'User is already deactivated'
        }), 400

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Require confirmation
    if not data.get('confirm'):
        return jsonify({
            'error': 'Confirmation required. Set "confirm": true in the request body.'
        }), 400

    # Require reason
    reason = data.get('reason')
    if not reason or not isinstance(reason, str):
        return jsonify({
            'error': 'reason is required'
        }), 400

    if len(reason) > 1000:
        return jsonify({
            'error': 'reason must be max 1000 characters'
        }), 400

    # Store previous status for audit log
    previous_status = user.status

    # Deactivate the user
    user.status = 'deactivated'
    user.deactivated_at = datetime.now(timezone.utc)
    user.deactivated_by = current_user.id
    user.deactivated_reason = reason

    # Revoke all user sessions
    sessions_revoked = UserSession.query.filter_by(user_id=user.id).delete()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to deactivate user: {str(e)}'
        }), 500

    # Log the action
    log_user_management_action(
        action='deactivate',
        target_user_id=user.id,
        target_user_email=user.email,
        target_user_name=user.name,
        details={
            'reason': reason,
            'previous_status': previous_status,
            'sessions_revoked': sessions_revoked
        }
    )

    return jsonify({
        'message': 'User deactivated permanently',
        'user': user.to_dict(),
        'sessions_revoked': sessions_revoked
    }), 200


@users_bp.route('/<user_id>/reset-password', methods=['POST'])
@login_required
@require_role('admin')
def reset_user_password(user_id):
    """
    Reset a user's password.

    Sets a new password for the user. The user will be required to change
    their password on next login.

    Args:
        user_id: User UUID

    Request Body:
        {
            "new_password": "NewPassword123!" (required)
        }

    Returns:
        200: Password reset successfully
        400: Invalid password or missing required field
        403: Insufficient permissions
        404: User not found
    """
    current_user = get_current_user()

    # Find user by ID
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if current user can manage this user (cannot reset own password this way)
    allowed, error = check_can_manage_user(current_user, user, 'reset password for')
    if not allowed:
        return jsonify({'error': error}), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate new password
    new_password = data.get('new_password')
    if not new_password:
        return jsonify({'error': 'new_password is required'}), 400

    is_valid, error_msg = _validate_password(new_password)
    if not is_valid:
        return jsonify({'error': error_msg}), 400

    # Set the new password and require change on next login
    user.set_password(new_password)
    user.must_change_password = True

    # Revoke all existing sessions to force re-login
    sessions_revoked = UserSession.query.filter_by(user_id=user.id).delete()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to reset password: {str(e)}'
        }), 500

    # Log the action (don't include the password itself)
    log_user_management_action(
        action='reset_password',
        target_user_id=user.id,
        target_user_email=user.email,
        target_user_name=user.name,
        details={
            'must_change_password': True,
            'sessions_revoked': sessions_revoked
        }
    )

    return jsonify({
        'message': 'Password reset successfully. User must change password on next login.',
        'sessions_revoked': sessions_revoked
    }), 200


@users_bp.route('/<user_id>/sessions', methods=['GET'])
@login_required
@require_role('admin')
def list_user_sessions(user_id):
    """
    List all active sessions for a user.

    Args:
        user_id: User UUID

    Returns:
        200: List of active sessions
        403: Insufficient permissions
        404: User not found
    """
    current_user = get_current_user()

    # Find user by ID
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check permissions (users can view their own sessions, admins can view managed users)
    is_self = current_user.id == user.id
    if not is_self:
        allowed, error = check_can_manage_user(current_user, user, 'view sessions for')
        if not allowed:
            return jsonify({'error': error}), 403

    # Get active sessions
    now = datetime.now(timezone.utc)
    sessions = UserSession.query.filter(
        UserSession.user_id == user.id,
        UserSession.expires_at > now
    ).order_by(UserSession.created_at.desc()).all()

    return jsonify({
        'sessions': [session.to_dict() for session in sessions],
        'count': len(sessions)
    }), 200


@users_bp.route('/<user_id>/sessions', methods=['DELETE'])
@login_required
@require_role('admin')
def revoke_all_user_sessions(user_id):
    """
    Revoke all sessions for a user.

    This will immediately log out the user from all devices.

    Args:
        user_id: User UUID

    Returns:
        200: All sessions revoked
        403: Insufficient permissions
        404: User not found
    """
    current_user = get_current_user()

    # Find user by ID
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if current user can manage this user
    allowed, error = check_can_manage_user(current_user, user, 'revoke sessions for')
    if not allowed:
        return jsonify({'error': error}), 403

    # Revoke all sessions
    sessions_revoked = UserSession.query.filter_by(user_id=user.id).delete()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to revoke sessions: {str(e)}'
        }), 500

    # Log the action
    log_user_management_action(
        action='revoke_all_sessions',
        target_user_id=user.id,
        target_user_email=user.email,
        target_user_name=user.name,
        details={'sessions_revoked': sessions_revoked}
    )

    return jsonify({
        'message': 'All sessions revoked successfully',
        'sessions_revoked': sessions_revoked
    }), 200


@users_bp.route('/<user_id>/sessions/<session_id>', methods=['DELETE'])
@login_required
@require_role('admin')
def revoke_user_session(user_id, session_id):
    """
    Revoke a specific session for a user.

    Args:
        user_id: User UUID
        session_id: Session UUID

    Returns:
        200: Session revoked
        403: Insufficient permissions
        404: User or session not found
    """
    current_user = get_current_user()

    # Find user by ID
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if current user can manage this user
    allowed, error = check_can_manage_user(current_user, user, 'revoke session for')
    if not allowed:
        return jsonify({'error': error}), 403

    # Find the session
    session = UserSession.query.filter_by(
        id=session_id,
        user_id=user.id
    ).first()

    if not session:
        return jsonify({'error': 'Session not found'}), 404

    try:
        db.session.delete(session)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to revoke session: {str(e)}'
        }), 500

    # Log the action
    log_user_management_action(
        action='revoke_session',
        target_user_id=user.id,
        target_user_email=user.email,
        target_user_name=user.name,
        details={'session_id': session_id}
    )

    return jsonify({
        'message': 'Session revoked successfully'
    }), 200


@users_bp.route('/roles', methods=['GET'])
@login_required
@require_role('admin')
def get_available_roles():
    """
    Get list of roles the current user can assign.

    Returns the roles that are lower in the hierarchy than the
    current user's role.

    Returns:
        200: List of assignable roles with descriptions
    """
    current_user = get_current_user()

    role_info = {
        'super_admin': {
            'value': 'super_admin',
            'label': 'Super Admin',
            'level': 4,
            'description': 'Full system access, can manage all users'
        },
        'admin': {
            'value': 'admin',
            'label': 'Admin',
            'level': 3,
            'description': 'Can manage users within their network'
        },
        'content_manager': {
            'value': 'content_manager',
            'label': 'Content Manager',
            'level': 2,
            'description': 'Can manage content and playlists'
        },
        'viewer': {
            'value': 'viewer',
            'label': 'Viewer',
            'level': 1,
            'description': 'Read-only access'
        }
    }

    # Filter to roles the current user can assign
    current_level = ROLE_HIERARCHY.get(current_user.role, 0)
    assignable_roles = [
        info for role, info in role_info.items()
        if info['level'] < current_level
    ]

    return jsonify({
        'roles': sorted(assignable_roles, key=lambda x: -x['level']),
        'current_role': current_user.role
    }), 200
