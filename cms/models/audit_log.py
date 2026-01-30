"""
AuditLog Model for CMS Service.

Represents an audit log entry for tracking all privileged actions performed
in the system. Captures user information, action details, and context for
security and compliance purposes.
"""

from datetime import datetime, timezone
import uuid

from cms.models import db, DateTimeUTC


class AuditLog(db.Model):
    """
    SQLAlchemy model representing an audit log entry.

    Audit logs track all privileged actions in the system including user
    management, content changes, device operations, and authentication events.
    Each entry captures who performed the action, what was done, and context
    like IP address and session information.

    Attributes:
        id: Unique UUID identifier
        user_id: ID of the user who performed the action (NULL for system actions)
        user_email: Email of the user (denormalized for historical accuracy)
        user_name: Name of the user at time of action
        user_role: Role of the user at time of action
        action: Specific action performed (e.g., 'user.create', 'device.update')
        action_category: Category of the action ('auth', 'users', 'devices', etc.)
        resource_type: Type of resource affected (e.g., 'user', 'device', 'content')
        resource_id: ID of the affected resource
        resource_name: Name/identifier of the affected resource
        details: JSON string containing before/after values and additional context
        ip_address: IP address of the request
        user_agent: User agent string from the request
        session_id: Session ID used for the action
        created_at: Timestamp when the action occurred
    """

    __tablename__ = 'audit_logs'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True, index=True)
    user_email = db.Column(db.String(255), nullable=False, index=True)
    user_name = db.Column(db.String(200), nullable=True)
    user_role = db.Column(db.String(50), nullable=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    action_category = db.Column(db.String(50), nullable=False, index=True)
    resource_type = db.Column(db.String(50), nullable=True, index=True)
    resource_id = db.Column(db.String(36), nullable=True, index=True)
    resource_name = db.Column(db.String(255), nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    session_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(DateTimeUTC(), default=lambda: datetime.now(timezone.utc), index=True)

    # Relationship to User (optional - user may be deleted)
    user = db.relationship('User', backref=db.backref('audit_logs', lazy='dynamic'))

    # Valid action categories
    VALID_CATEGORIES = [
        'auth',        # Authentication events (login, logout, password change)
        'users',       # User management (create, update, suspend, etc.)
        'devices',     # Device operations
        'content',     # Content management
        'playlists',   # Playlist operations
        'layouts',     # Layout changes
        'hubs',        # Hub operations
        'system'       # System-level actions
    ]

    def to_dict(self):
        """
        Serialize the audit log entry to a dictionary for API responses.

        Returns:
            Dictionary containing all audit log fields
        """
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_email': self.user_email,
            'user_name': self.user_name,
            'user_role': self.user_role,
            'action': self.action,
            'action_category': self.action_category,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'resource_name': self.resource_name,
            'details': self.details,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'session_id': self.session_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        """String representation for debugging."""
        return f'<AuditLog {self.action} by {self.user_email}>'
