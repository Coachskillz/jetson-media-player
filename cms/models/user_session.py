"""
UserSession Model for CMS Service.

Represents an active user session with token-based authentication.
Sessions can be revoked for immediate credential invalidation.

Features:
- Token-based authentication using cryptographically secure tokens
- Configurable expiration (default 8 hours, 30 days for "remember me")
- Activity tracking via last_active timestamp
- Device/client information storage for security auditing
- Immediate revocation capability for credential management
"""

from datetime import datetime, timezone, timedelta
import secrets
import uuid

from cms.models import db


# Default session durations
DEFAULT_SESSION_HOURS = 8
REMEMBER_ME_SESSION_DAYS = 30


class UserSession(db.Model):
    """
    SQLAlchemy model representing a user login session.

    Sessions are created upon successful login and validated on each
    authenticated request. Revoking a session (by deleting it) immediately
    invalidates the associated token.

    Attributes:
        id: Unique UUID identifier (internal database ID)
        user_id: Foreign key reference to the user who owns this session
        token: Unique, cryptographically secure session token
        ip_address: IP address from which the session was created
        user_agent: Browser/client user agent string
        device_info: Additional device information (JSON-compatible string)
        expires_at: Timestamp when the session expires
        last_active: Timestamp of last activity using this session
        created_at: Timestamp when the session was created
    """

    __tablename__ = 'user_sessions'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    device_info = db.Column(db.Text, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    last_active = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = db.relationship('User', backref=db.backref('sessions', lazy='dynamic', cascade='all, delete-orphan'))

    @classmethod
    def generate_token(cls):
        """
        Generate a cryptographically secure session token.

        Uses secrets.token_urlsafe for secure random token generation.

        Returns:
            A 43-character URL-safe base64-encoded token (32 bytes of randomness)
        """
        return secrets.token_urlsafe(32)

    @classmethod
    def create_session(cls, user_id, ip_address=None, user_agent=None, device_info=None, remember_me=False):
        """
        Create a new session for a user.

        Args:
            user_id: ID of the user to create session for
            ip_address: Client IP address
            user_agent: Client user agent string
            device_info: Additional device information
            remember_me: If True, session lasts 30 days instead of 8 hours

        Returns:
            New UserSession instance (not yet committed to database)
        """
        now = datetime.now(timezone.utc)

        if remember_me:
            expires_at = now + timedelta(days=REMEMBER_ME_SESSION_DAYS)
        else:
            expires_at = now + timedelta(hours=DEFAULT_SESSION_HOURS)

        return cls(
            user_id=user_id,
            token=cls.generate_token(),
            ip_address=ip_address,
            user_agent=user_agent[:500] if user_agent and len(user_agent) > 500 else user_agent,
            device_info=device_info,
            expires_at=expires_at,
            last_active=now
        )

    def is_expired(self):
        """
        Check if the session has expired.

        Returns:
            True if current time is past expires_at, False otherwise
        """
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self):
        """
        Check if the session is currently valid (not expired).

        Returns:
            True if session is still valid, False if expired
        """
        return not self.is_expired()

    def update_activity(self):
        """
        Update the last_active timestamp to current time.

        Call this method on each authenticated request to track session usage.
        """
        self.last_active = datetime.now(timezone.utc)

    def extend_expiration(self, hours=None, days=None):
        """
        Extend the session expiration time.

        Args:
            hours: Number of hours to extend (default: DEFAULT_SESSION_HOURS)
            days: Number of days to extend (overrides hours if provided)
        """
        now = datetime.now(timezone.utc)
        if days is not None:
            self.expires_at = now + timedelta(days=days)
        elif hours is not None:
            self.expires_at = now + timedelta(hours=hours)
        else:
            self.expires_at = now + timedelta(hours=DEFAULT_SESSION_HOURS)

    def time_remaining(self):
        """
        Get the time remaining until session expiration.

        Returns:
            timedelta of remaining time, or timedelta(0) if expired
        """
        remaining = self.expires_at - datetime.now(timezone.utc)
        return remaining if remaining.total_seconds() > 0 else timedelta(0)

    def to_dict(self, include_token=False):
        """
        Serialize the session to a dictionary for API responses.

        Args:
            include_token: If True, include the session token in response
                          (only include when creating session or for user's own sessions)

        Returns:
            Dictionary containing session fields
        """
        result = {
            'id': self.id,
            'user_id': self.user_id,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'device_info': self.device_info,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'last_active': self.last_active.isoformat() if self.last_active else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_expired': self.is_expired(),
        }

        if include_token:
            result['token'] = self.token

        return result

    def __repr__(self):
        """String representation for debugging."""
        return f'<UserSession {self.id} user={self.user_id} expired={self.is_expired()}>'
