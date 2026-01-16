"""
CMS Audit Logging Utilities.

Provides helper functions for creating audit log entries that track all
privileged actions in the system.

Features:
- log_action() helper for creating audit entries
- Automatic capture of user, session, IP, and user agent information
- JSON serialization for action details
- Support for both authenticated and system-level actions

Usage:
    from cms.utils.audit import log_action, ACTION_CATEGORIES

    # Log a user action (within a request context)
    log_action(
        action='user.create',
        action_category='users',
        resource_type='user',
        resource_id=new_user.id,
        resource_name=new_user.email,
        details={'role': new_user.role}
    )

    # Log a system action (no authenticated user)
    log_action(
        action='system.seed_users',
        action_category='system',
        user_email='system',
        details={'users_created': 2}
    )
"""

import json
from typing import Optional, Any

from flask import has_request_context

from cms.models import db, AuditLog
from cms.utils.auth import get_current_user, get_current_session, get_client_ip, get_user_agent


# Re-export action categories from the AuditLog model for convenience
ACTION_CATEGORIES = AuditLog.VALID_CATEGORIES


def log_action(
    action: str,
    action_category: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    resource_name: Optional[str] = None,
    details: Optional[dict] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
    user_role: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[AuditLog]:
    """
    Create an audit log entry for a privileged action.

    This function automatically captures context from the current request
    including the authenticated user, session, IP address, and user agent.
    These values can be overridden by passing explicit parameters.

    Args:
        action: Specific action performed (e.g., 'user.create', 'device.update')
        action_category: Category of the action - must be one of ACTION_CATEGORIES
        resource_type: Type of resource affected (e.g., 'user', 'device', 'content')
        resource_id: ID of the affected resource
        resource_name: Name/identifier of the affected resource for display
        details: Dictionary of additional details (before/after values, etc.)
                 Will be JSON-serialized before storage
        user_id: Override for the user ID (for system actions)
        user_email: Override for the user email (required for system actions)
        user_name: Override for the user name
        user_role: Override for the user role
        ip_address: Override for the IP address
        user_agent: Override for the user agent
        session_id: Override for the session ID

    Returns:
        The created AuditLog entry, or None if creation failed

    Examples:
        # Log user creation by an admin
        log_action(
            action='user.create',
            action_category='users',
            resource_type='user',
            resource_id=new_user.id,
            resource_name=new_user.email,
            details={'role': new_user.role, 'network_id': new_user.network_id}
        )

        # Log a login attempt (successful or failed)
        log_action(
            action='auth.login',
            action_category='auth',
            user_email=email,
            details={'success': True, 'method': 'password'}
        )

        # Log device status change
        log_action(
            action='device.update',
            action_category='devices',
            resource_type='device',
            resource_id=device.id,
            resource_name=device.name,
            details={
                'changes': {'status': {'before': 'offline', 'after': 'online'}}
            }
        )

        # System action (no authenticated user)
        log_action(
            action='system.seed_users',
            action_category='system',
            user_email='system',
            details={'users_created': 2}
        )

    Raises:
        ValueError: If action_category is not in ACTION_CATEGORIES
    """
    # Validate action category
    if action_category not in ACTION_CATEGORIES:
        raise ValueError(
            f"Invalid action_category '{action_category}'. "
            f"Must be one of: {', '.join(ACTION_CATEGORIES)}"
        )

    # Get user information from current request context if available
    current_user = None
    current_session = None

    if has_request_context():
        current_user = get_current_user()
        current_session = get_current_session()

    # Determine user information (explicit params override auto-detected)
    audit_user_id = user_id
    audit_user_email = user_email
    audit_user_name = user_name
    audit_user_role = user_role

    if current_user and not user_id:
        audit_user_id = current_user.id
    if current_user and not user_email:
        audit_user_email = current_user.email
    if current_user and not user_name:
        audit_user_name = current_user.name
    if current_user and not user_role:
        audit_user_role = current_user.role

    # Require user_email for all entries
    if not audit_user_email:
        audit_user_email = 'anonymous'

    # Get request context information if available
    audit_ip_address = ip_address
    audit_user_agent = user_agent
    audit_session_id = session_id

    if has_request_context():
        if not audit_ip_address:
            audit_ip_address = get_client_ip()
        if not audit_user_agent:
            audit_user_agent = get_user_agent()

    if current_session and not audit_session_id:
        audit_session_id = current_session.id

    # Serialize details to JSON if provided
    details_json = None
    if details is not None:
        try:
            details_json = json.dumps(details, default=_json_serializer)
        except (TypeError, ValueError) as e:
            # If serialization fails, store error message
            details_json = json.dumps({'_serialization_error': str(e)})

    # Create the audit log entry
    try:
        audit_log = AuditLog(
            user_id=audit_user_id,
            user_email=audit_user_email,
            user_name=audit_user_name,
            user_role=audit_user_role,
            action=action,
            action_category=action_category,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            details=details_json,
            ip_address=audit_ip_address,
            user_agent=audit_user_agent,
            session_id=audit_session_id,
        )

        db.session.add(audit_log)
        db.session.commit()

        return audit_log

    except Exception:
        # Don't let audit logging failures break the main operation
        db.session.rollback()
        return None


def _json_serializer(obj: Any) -> Any:
    """
    Custom JSON serializer for objects not serializable by default.

    Handles:
    - datetime objects (converts to ISO format)
    - Objects with to_dict() method
    - Sets (converts to list)
    - Other objects (converts to string representation)

    Args:
        obj: Object to serialize

    Returns:
        JSON-serializable representation of the object
    """
    from datetime import datetime, date

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    if isinstance(obj, set):
        return list(obj)

    # Fallback: convert to string
    return str(obj)


def log_auth_action(
    action: str,
    user_email: str,
    success: bool,
    details: Optional[dict] = None,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    user_role: Optional[str] = None,
) -> Optional[AuditLog]:
    """
    Convenience function for logging authentication actions.

    Args:
        action: The auth action (e.g., 'login', 'logout', 'password_change')
        user_email: Email of the user performing the action
        success: Whether the action was successful
        details: Additional details to include
        user_id: User ID if available
        user_name: User name if available
        user_role: User role if available

    Returns:
        The created AuditLog entry, or None if creation failed
    """
    auth_details = {'success': success}
    if details:
        auth_details.update(details)

    return log_action(
        action=f'auth.{action}',
        action_category='auth',
        user_id=user_id,
        user_email=user_email,
        user_name=user_name,
        user_role=user_role,
        details=auth_details,
    )


def log_user_management_action(
    action: str,
    target_user_id: str,
    target_user_email: str,
    target_user_name: Optional[str] = None,
    details: Optional[dict] = None,
) -> Optional[AuditLog]:
    """
    Convenience function for logging user management actions.

    Args:
        action: The user management action (e.g., 'create', 'suspend', 'deactivate')
        target_user_id: ID of the user being managed
        target_user_email: Email of the user being managed
        target_user_name: Name of the user being managed
        details: Additional details to include

    Returns:
        The created AuditLog entry, or None if creation failed
    """
    return log_action(
        action=f'user.{action}',
        action_category='users',
        resource_type='user',
        resource_id=target_user_id,
        resource_name=target_user_email,
        details=details,
    )


def log_resource_action(
    action: str,
    category: str,
    resource_type: str,
    resource_id: str,
    resource_name: Optional[str] = None,
    details: Optional[dict] = None,
) -> Optional[AuditLog]:
    """
    Convenience function for logging resource operations.

    Args:
        action: The action performed (e.g., 'create', 'update', 'delete')
        category: The resource category (e.g., 'devices', 'content', 'playlists')
        resource_type: Type of resource (e.g., 'device', 'content_item', 'playlist')
        resource_id: ID of the resource
        resource_name: Display name of the resource
        details: Additional details including before/after values

    Returns:
        The created AuditLog entry, or None if creation failed
    """
    return log_action(
        action=f'{resource_type}.{action}',
        action_category=category,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        details=details,
    )
