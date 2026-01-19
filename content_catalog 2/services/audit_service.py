"""
Audit Service for Content Catalog.

Provides centralized audit logging for all system actions.
Automatically captures IP address and user agent from Flask requests
and integrates with the AuditLog model for persistence.

Key features:
- Automatic IP and user agent extraction from Flask requests
- Support for both authenticated and anonymous action logging
- JSON details serialization for complex audit data
- Query methods for retrieving audit history
"""

import json
from typing import Any, Dict, Optional

from flask import has_request_context, request


class AuditService:
    """
    Audit service for logging system actions.

    This service handles:
    1. Logging actions with automatic request context extraction
    2. JSON serialization of audit details
    3. Querying audit logs by various criteria

    Usage:
        # Log an authenticated action
        AuditService.log_action(
            db_session=db.session,
            action='user.login',
            user_id=user.id,
            user_email=user.email,
            resource_type='user',
            resource_id=user.id,
            details={'method': 'password'}
        )

        # Log a failed login attempt (no user_id)
        AuditService.log_action(
            db_session=db.session,
            action='user.login_failed',
            user_email='attempted@email.com',
            details={'reason': 'invalid_password'}
        )

        # Log with explicit IP/user agent (for testing or non-Flask contexts)
        AuditService.log_action(
            db_session=db.session,
            action='content.uploaded',
            user_id=user.id,
            user_email=user.email,
            resource_type='content',
            resource_id=asset.id,
            ip_address='192.168.1.1',
            user_agent='CustomClient/1.0'
        )
    """

    @classmethod
    def log_action(
        cls,
        db_session,
        action: str,
        user_id: Optional[int] = None,
        user_email: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ):
        """
        Log an action to the audit log.

        Automatically extracts IP address and user agent from the Flask
        request context if not explicitly provided. Details are automatically
        serialized to JSON if provided as a dictionary.

        Args:
            db_session: SQLAlchemy database session
            action: The action being performed (e.g., 'user.login', 'content.uploaded')
            user_id: ID of the user performing the action (optional, nullable for failed logins)
            user_email: Email of the user performing the action (optional, preserved for audit trail)
            resource_type: Type of resource affected (e.g., 'user', 'content', 'organization')
            resource_id: ID of the specific resource affected (optional)
            details: Dictionary of additional details about the action (optional)
            ip_address: Client IP address (optional, auto-extracted from request if not provided)
            user_agent: Client user agent string (optional, auto-extracted from request if not provided)

        Returns:
            AuditLog: The created audit log instance

        Note:
            The audit log is added to the database session but not committed.
            The caller is responsible for committing the transaction.
        """
        from content_catalog.models.audit import AuditLog

        # Extract IP and user agent from Flask request context if not provided
        if ip_address is None:
            ip_address = cls._get_client_ip()

        if user_agent is None:
            user_agent = cls._get_user_agent()

        # Serialize details to JSON if provided as a dictionary
        details_json = None
        if details is not None:
            details_json = json.dumps(details)

        # Create the audit log entry using the model's factory method
        audit_log = AuditLog.log_action(
            action=action,
            user_id=user_id,
            user_email=user_email,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details_json,
            ip_address=ip_address,
            user_agent=user_agent
        )

        # Add to session
        db_session.add(audit_log)

        return audit_log

    @classmethod
    def _get_client_ip(cls) -> Optional[str]:
        """
        Extract the client IP address from the Flask request context.

        Handles proxy headers (X-Forwarded-For, X-Real-IP) for proper
        IP extraction when behind reverse proxies or load balancers.

        Returns:
            The client IP address, or None if not in a request context
        """
        if not has_request_context():
            return None

        # Check for proxy headers first (common in production)
        # X-Forwarded-For can contain multiple IPs: client, proxy1, proxy2
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            # Return the first (client) IP
            return forwarded_for.split(',')[0].strip()

        # Check X-Real-IP (common with nginx)
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip.strip()

        # Fall back to remote_addr
        return request.remote_addr

    @classmethod
    def _get_user_agent(cls) -> Optional[str]:
        """
        Extract the user agent string from the Flask request context.

        Returns:
            The user agent string, or None if not in a request context
        """
        if not has_request_context():
            return None

        # request.user_agent is a UserAgent object, get the string representation
        if request.user_agent:
            return request.user_agent.string

        return None

    @classmethod
    def get_logs_for_user(cls, db_session, user_id: int, limit: int = 100):
        """
        Get audit logs for a specific user.

        Args:
            db_session: SQLAlchemy database session
            user_id: The user ID to filter by
            limit: Maximum number of logs to return (default 100)

        Returns:
            list: List of AuditLog instances ordered by most recent first
        """
        from content_catalog.models.audit import AuditLog

        return db_session.query(AuditLog).filter_by(
            user_id=user_id
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()

    @classmethod
    def get_logs_for_resource(
        cls,
        db_session,
        resource_type: str,
        resource_id: Any,
        limit: int = 100
    ):
        """
        Get audit logs for a specific resource.

        Args:
            db_session: SQLAlchemy database session
            resource_type: The type of resource to filter by
            resource_id: The resource ID to filter by
            limit: Maximum number of logs to return (default 100)

        Returns:
            list: List of AuditLog instances ordered by most recent first
        """
        from content_catalog.models.audit import AuditLog

        return db_session.query(AuditLog).filter_by(
            resource_type=resource_type,
            resource_id=str(resource_id)
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()

    @classmethod
    def get_logs_by_action(cls, db_session, action: str, limit: int = 100):
        """
        Get audit logs for a specific action type.

        Args:
            db_session: SQLAlchemy database session
            action: The action type to filter by (e.g., 'user.login')
            limit: Maximum number of logs to return (default 100)

        Returns:
            list: List of AuditLog instances ordered by most recent first
        """
        from content_catalog.models.audit import AuditLog

        return db_session.query(AuditLog).filter_by(
            action=action
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()

    @classmethod
    def get_recent_logs(cls, db_session, limit: int = 100):
        """
        Get the most recent audit logs.

        Args:
            db_session: SQLAlchemy database session
            limit: Maximum number of logs to return (default 100)

        Returns:
            list: List of AuditLog instances ordered by most recent first
        """
        from content_catalog.models.audit import AuditLog

        return db_session.query(AuditLog).order_by(
            AuditLog.created_at.desc()
        ).limit(limit).all()

    @classmethod
    def get_failed_login_attempts(
        cls,
        db_session,
        user_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        limit: int = 100
    ):
        """
        Get failed login attempts, optionally filtered by email or IP.

        Useful for security monitoring and detecting brute force attacks.

        Args:
            db_session: SQLAlchemy database session
            user_email: Filter by attempted email (optional)
            ip_address: Filter by source IP (optional)
            limit: Maximum number of logs to return (default 100)

        Returns:
            list: List of AuditLog instances for failed logins
        """
        from content_catalog.models.audit import AuditLog

        query = db_session.query(AuditLog).filter_by(
            action=AuditLog.ACTION_USER_LOGIN_FAILED
        )

        if user_email:
            query = query.filter_by(user_email=user_email)

        if ip_address:
            query = query.filter_by(ip_address=ip_address)

        return query.order_by(AuditLog.created_at.desc()).limit(limit).all()
