"""
AuditLog Model for Content Catalog Service.

Tracks all significant user actions for compliance and security monitoring.
Provides a complete audit trail of who did what, when, and from where.
"""

from datetime import datetime, timezone

from content_catalog.models import db


class AuditLog(db.Model):
    """
    SQLAlchemy model representing an audit log entry.

    Audit logs track all significant actions in the system for compliance,
    security monitoring, and troubleshooting. Each entry captures who performed
    an action, what they did, what resource was affected, and client information.

    Common Action Types:
        - 'user.login': User logged in
        - 'user.logout': User logged out
        - 'user.login_failed': Failed login attempt
        - 'user.created': New user created
        - 'user.updated': User profile updated
        - 'user.approved': User was approved
        - 'user.rejected': User was rejected
        - 'user.suspended': User was suspended
        - 'user.deactivated': User was deactivated
        - 'content.uploaded': Content was uploaded
        - 'content.approved': Content was approved
        - 'content.rejected': Content was rejected
        - 'content.deleted': Content was deleted
        - 'organization.created': Organization created
        - 'organization.updated': Organization updated
        - 'invitation.sent': Invitation sent
        - 'invitation.revoked': Invitation revoked
        - 'session.created': New session created
        - 'session.revoked': Session manually revoked
        - 'password.changed': Password was changed
        - 'password.reset_requested': Password reset requested
        - '2fa.enabled': Two-factor authentication enabled
        - '2fa.disabled': Two-factor authentication disabled

    Resource Types:
        - 'user': User resource
        - 'organization': Organization resource
        - 'content': Content asset resource
        - 'invitation': User invitation resource
        - 'session': Admin session resource
        - 'approval_request': Approval request resource

    Attributes:
        id: Unique integer identifier
        user_id: Foreign key to the user who performed the action (nullable for failed logins)
        user_email: Email address of the user at time of action (preserved even if user deleted)
        action: Type of action performed (e.g., 'user.login', 'content.uploaded')
        resource_type: Type of resource affected (e.g., 'user', 'content')
        resource_id: ID of the specific resource affected
        details: JSON object with additional context about the action
        ip_address: IP address from which the action was performed
        user_agent: Browser/client user agent string
        created_at: Timestamp when the action occurred
    """

    __tablename__ = 'audit_logs'

    # Common action constants
    ACTION_USER_LOGIN = 'user.login'
    ACTION_USER_LOGOUT = 'user.logout'
    ACTION_USER_LOGIN_FAILED = 'user.login_failed'
    ACTION_USER_CREATED = 'user.created'
    ACTION_USER_UPDATED = 'user.updated'
    ACTION_USER_APPROVED = 'user.approved'
    ACTION_USER_REJECTED = 'user.rejected'
    ACTION_USER_SUSPENDED = 'user.suspended'
    ACTION_USER_DEACTIVATED = 'user.deactivated'
    ACTION_CONTENT_UPLOADED = 'content.uploaded'
    ACTION_CONTENT_APPROVED = 'content.approved'
    ACTION_CONTENT_REJECTED = 'content.rejected'
    ACTION_CONTENT_DELETED = 'content.deleted'
    ACTION_ORGANIZATION_CREATED = 'organization.created'
    ACTION_ORGANIZATION_UPDATED = 'organization.updated'
    ACTION_INVITATION_SENT = 'invitation.sent'
    ACTION_INVITATION_REVOKED = 'invitation.revoked'
    ACTION_SESSION_CREATED = 'session.created'
    ACTION_SESSION_REVOKED = 'session.revoked'
    ACTION_PASSWORD_CHANGED = 'password.changed'
    ACTION_PASSWORD_RESET_REQUESTED = 'password.reset_requested'
    ACTION_2FA_ENABLED = '2fa.enabled'
    ACTION_2FA_DISABLED = '2fa.disabled'

    # Resource type constants
    RESOURCE_USER = 'user'
    RESOURCE_ORGANIZATION = 'organization'
    RESOURCE_CONTENT = 'content'
    RESOURCE_INVITATION = 'invitation'
    RESOURCE_SESSION = 'session'
    RESOURCE_APPROVAL_REQUEST = 'approval_request'

    VALID_RESOURCE_TYPES = [
        RESOURCE_USER,
        RESOURCE_ORGANIZATION,
        RESOURCE_CONTENT,
        RESOURCE_INVITATION,
        RESOURCE_SESSION,
        RESOURCE_APPROVAL_REQUEST
    ]

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # User who performed the action (nullable for failed login attempts)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )

    # Store email separately so we have a record even if user is deleted
    user_email = db.Column(db.String(255), nullable=True, index=True)

    # Action performed
    action = db.Column(db.String(100), nullable=False, index=True)

    # Resource affected
    resource_type = db.Column(db.String(50), nullable=True, index=True)
    resource_id = db.Column(db.String(100), nullable=True, index=True)

    # Additional details as JSON text
    details = db.Column(db.Text, nullable=True)

    # Client information
    ip_address = db.Column(db.String(45), nullable=True)  # IPv6 can be up to 45 chars
    user_agent = db.Column(db.String(500), nullable=True)

    # Timestamp
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # Relationships
    user = db.relationship(
        'User',
        foreign_keys=[user_id],
        backref=db.backref('audit_logs', lazy='dynamic')
    )

    def to_dict(self):
        """
        Serialize the audit log to a dictionary for API responses.

        Returns:
            Dictionary containing all audit log fields
        """
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_email': self.user_email,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'details': self.details,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    @classmethod
    def log_action(cls, action, user_id=None, user_email=None, resource_type=None,
                   resource_id=None, details=None, ip_address=None, user_agent=None):
        """
        Create a new audit log entry.

        This is a convenience class method for creating audit log entries.

        Args:
            action: The action being performed (e.g., 'user.login')
            user_id: ID of the user performing the action (optional)
            user_email: Email of the user performing the action (optional)
            resource_type: Type of resource affected (optional)
            resource_id: ID of the resource affected (optional)
            details: JSON string with additional details (optional)
            ip_address: Client IP address (optional)
            user_agent: Client user agent (optional)

        Returns:
            AuditLog: The created audit log instance (not yet committed)
        """
        return cls(
            action=action,
            user_id=user_id,
            user_email=user_email,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )

    @classmethod
    def get_logs_for_user(cls, user_id, limit=100):
        """
        Get audit logs for a specific user.

        Args:
            user_id: The user ID to filter by
            limit: Maximum number of logs to return (default 100)

        Returns:
            list: List of AuditLog instances ordered by most recent first
        """
        return cls.query.filter_by(
            user_id=user_id
        ).order_by(cls.created_at.desc()).limit(limit).all()

    @classmethod
    def get_logs_for_resource(cls, resource_type, resource_id, limit=100):
        """
        Get audit logs for a specific resource.

        Args:
            resource_type: The type of resource to filter by
            resource_id: The resource ID to filter by
            limit: Maximum number of logs to return (default 100)

        Returns:
            list: List of AuditLog instances ordered by most recent first
        """
        return cls.query.filter_by(
            resource_type=resource_type,
            resource_id=str(resource_id)
        ).order_by(cls.created_at.desc()).limit(limit).all()

    @classmethod
    def get_logs_by_action(cls, action, limit=100):
        """
        Get audit logs for a specific action type.

        Args:
            action: The action type to filter by
            limit: Maximum number of logs to return (default 100)

        Returns:
            list: List of AuditLog instances ordered by most recent first
        """
        return cls.query.filter_by(
            action=action
        ).order_by(cls.created_at.desc()).limit(limit).all()

    def __repr__(self):
        """String representation for debugging."""
        return f'<AuditLog {self.action} user={self.user_email or self.user_id}>'
