"""
CMS Permission Utilities.

Provides role-based access control decorators and permission checking functions.

Role Hierarchy (highest to lowest):
- super_admin (level 4): Full system access, can manage all users including admins
- admin (level 3): Can manage content_managers and viewers within their network
- content_manager (level 2): Can manage content and playlists
- viewer (level 1): Read-only access

Usage:
    from cms.utils.permissions import require_role, has_permission, ROLE_HIERARCHY

    # Decorator to require minimum role
    @blueprint.route('/admin-only')
    @login_required
    @require_role('admin')
    def admin_route():
        return jsonify({'message': 'Admin access granted'})

    # Function to check permissions
    if has_permission(user, 'admin'):
        # User is admin or higher
        pass
"""

from functools import wraps

from flask import jsonify, g

# Re-export role hierarchy from models for convenience
from cms.models.user import ROLE_HIERARCHY

# Role level constants for common checks
ROLE_SUPER_ADMIN = 'super_admin'
ROLE_ADMIN = 'admin'
ROLE_CONTENT_MANAGER = 'content_manager'
ROLE_VIEWER = 'viewer'

# Valid roles list
VALID_ROLES = list(ROLE_HIERARCHY.keys())


def get_role_level(role):
    """
    Get the numeric level of a role.

    Higher numbers indicate more privileges.

    Args:
        role: Role name string

    Returns:
        Integer role level, or 0 if role is invalid
    """
    return ROLE_HIERARCHY.get(role, 0)


def has_permission(user, minimum_role):
    """
    Check if a user has at least the specified role level.

    This function checks if the user's role level is greater than or equal
    to the minimum required role level.

    Args:
        user: User object with a 'role' attribute, or None
        minimum_role: The minimum required role name string

    Returns:
        True if user has sufficient permission, False otherwise

    Examples:
        # Check if user is at least an admin
        if has_permission(user, 'admin'):
            # User is admin or super_admin
            pass

        # Check if user can view content
        if has_permission(user, 'viewer'):
            # User has any valid role
            pass
    """
    if user is None:
        return False

    user_level = get_role_level(user.role)
    required_level = get_role_level(minimum_role)

    return user_level >= required_level


def has_exact_role(user, role):
    """
    Check if a user has exactly the specified role.

    Args:
        user: User object with a 'role' attribute, or None
        role: The exact role to check for

    Returns:
        True if user has exactly this role, False otherwise
    """
    if user is None:
        return False

    return user.role == role


def is_super_admin(user):
    """
    Check if a user is a super admin.

    Args:
        user: User object with a 'role' attribute, or None

    Returns:
        True if user is a super admin, False otherwise
    """
    return has_exact_role(user, ROLE_SUPER_ADMIN)


def is_admin_or_higher(user):
    """
    Check if a user is an admin or super admin.

    Args:
        user: User object with a 'role' attribute, or None

    Returns:
        True if user is admin or higher, False otherwise
    """
    return has_permission(user, ROLE_ADMIN)


def can_manage_users(user):
    """
    Check if a user can manage other users.

    Only admins and super admins can manage users.

    Args:
        user: User object with a 'role' attribute, or None

    Returns:
        True if user can manage users, False otherwise
    """
    return is_admin_or_higher(user)


def can_manage_role(manager, target_role):
    """
    Check if a manager can create/modify users with the target role.

    Users can only manage users with strictly lower role levels.
    This prevents role escalation.

    Args:
        manager: User object performing the management action
        target_role: The role of the user being managed

    Returns:
        True if manager can manage users with target_role, False otherwise

    Examples:
        # Super admin can manage any role
        can_manage_role(super_admin_user, 'admin')  # True
        can_manage_role(super_admin_user, 'super_admin')  # False (equal level)

        # Admin can manage lower roles
        can_manage_role(admin_user, 'content_manager')  # True
        can_manage_role(admin_user, 'admin')  # False (equal level)
    """
    if manager is None:
        return False

    manager_level = get_role_level(manager.role)
    target_level = get_role_level(target_role)

    return manager_level > target_level


def can_manage_user(manager, target_user):
    """
    Check if a manager can perform management actions on the target user.

    Enforces:
    1. Cannot manage yourself
    2. Cannot manage users with equal or higher role levels

    Args:
        manager: User object performing the management action
        target_user: User object being managed

    Returns:
        True if manager can manage target_user, False otherwise
    """
    if manager is None or target_user is None:
        return False

    # Cannot manage yourself
    if manager.id == target_user.id:
        return False

    return can_manage_role(manager, target_user.role)


def require_role(minimum_role):
    """
    Decorator to require a minimum role level for a route.

    Must be used AFTER @login_required to ensure g.current_user is set.
    Returns 403 Forbidden if the user's role level is insufficient.

    Args:
        minimum_role: The minimum role required to access the route

    Returns:
        Decorator function

    Usage:
        @blueprint.route('/admin-only')
        @login_required
        @require_role('admin')
        def admin_route():
            return jsonify({'message': 'Admin access granted'})

    Note:
        The decorator order matters! @login_required must come before
        @require_role to ensure the user is authenticated first.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get current user from Flask's g object (set by @login_required)
            user = getattr(g, 'current_user', None)

            if not user:
                return jsonify({
                    'error': 'Authentication required',
                    'code': 'not_authenticated'
                }), 401

            if not has_permission(user, minimum_role):
                return jsonify({
                    'error': 'Insufficient permissions',
                    'code': 'forbidden',
                    'required_role': minimum_role,
                    'current_role': user.role
                }), 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def require_super_admin(f):
    """
    Decorator shorthand to require super_admin role.

    Equivalent to @require_role('super_admin').

    Must be used AFTER @login_required.

    Usage:
        @blueprint.route('/super-admin-only')
        @login_required
        @require_super_admin
        def super_admin_route():
            return jsonify({'message': 'Super admin access granted'})
    """
    return require_role(ROLE_SUPER_ADMIN)(f)


def require_admin(f):
    """
    Decorator shorthand to require admin or higher role.

    Equivalent to @require_role('admin').

    Must be used AFTER @login_required.

    Usage:
        @blueprint.route('/admin-only')
        @login_required
        @require_admin
        def admin_route():
            return jsonify({'message': 'Admin access granted'})
    """
    return require_role(ROLE_ADMIN)(f)


def require_content_manager(f):
    """
    Decorator shorthand to require content_manager or higher role.

    Equivalent to @require_role('content_manager').

    Must be used AFTER @login_required.

    Usage:
        @blueprint.route('/content-manager-only')
        @login_required
        @require_content_manager
        def content_manager_route():
            return jsonify({'message': 'Content manager access granted'})
    """
    return require_role(ROLE_CONTENT_MANAGER)(f)


def check_can_create_user_with_role(manager, target_role):
    """
    Check if a manager can create a new user with the specified role.

    Returns a tuple of (allowed, error_message) for use in API endpoints.

    Args:
        manager: User object performing the creation
        target_role: The role to assign to the new user

    Returns:
        Tuple of (bool, str or None): (True, None) if allowed,
        (False, error_message) if not allowed
    """
    if manager is None:
        return False, 'Authentication required'

    if target_role not in VALID_ROLES:
        return False, f'Invalid role: {target_role}'

    if not can_manage_role(manager, target_role):
        return False, f'Cannot create users with role: {target_role}'

    return True, None


def check_can_manage_user(manager, target_user, action='manage'):
    """
    Check if a manager can perform an action on the target user.

    Returns a tuple of (allowed, error_message) for use in API endpoints.

    Args:
        manager: User object performing the action
        target_user: User object being acted upon
        action: Description of the action for error message

    Returns:
        Tuple of (bool, str or None): (True, None) if allowed,
        (False, error_message) if not allowed
    """
    if manager is None:
        return False, 'Authentication required'

    if target_user is None:
        return False, 'User not found'

    if manager.id == target_user.id:
        return False, f'Cannot {action} yourself'

    if not can_manage_role(manager, target_user.role):
        return False, f'Insufficient permissions to {action} this user'

    return True, None
