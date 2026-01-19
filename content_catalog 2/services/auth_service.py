"""
Authentication Service for Content Catalog.

Provides secure password hashing, verification, and session management
using bcrypt for password security and secure token generation for sessions.

Key features:
- Password hashing with bcrypt (12 rounds by default)
- Password length validation (bcrypt has a 72-byte limit)
- Secure session token generation
- Session creation and validation with expiration
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple


class AuthService:
    """
    Authentication service for secure password and session management.

    This service handles:
    1. Password hashing and verification using bcrypt
    2. Session creation with secure random tokens
    3. Session validation with expiration checking

    Usage:
        # Password operations
        password_hash = AuthService.hash_password("my_secure_password")
        is_valid = AuthService.verify_password("my_secure_password", password_hash)

        # Session operations
        session = AuthService.create_session(db_session, user_id, ip_address, user_agent)
        is_valid, session = AuthService.validate_session(db_session, token)
    """

    # bcrypt configuration
    BCRYPT_ROUNDS = 12
    PASSWORD_MAX_BYTES = 72  # bcrypt's internal limit

    # Session configuration
    SESSION_TOKEN_BYTES = 32  # 256 bits of entropy
    DEFAULT_SESSION_DURATION_HOURS = 24

    # Account lockout configuration
    MAX_LOGIN_ATTEMPTS = 5  # Lock account after this many failed attempts
    LOCKOUT_DURATION_MINUTES = 15  # Duration of account lockout in minutes

    @classmethod
    def hash_password(cls, password: str) -> str:
        """
        Hash a password using bcrypt.

        Uses bcrypt with 12 rounds of hashing for secure password storage.
        Validates password length before hashing to prevent bcrypt truncation.

        Args:
            password: The plaintext password to hash

        Returns:
            The bcrypt hash as a string

        Raises:
            ValueError: If password exceeds 72 bytes when encoded as UTF-8
        """
        import bcrypt

        # Validate password length (bcrypt truncates at 72 bytes)
        password_bytes = password.encode('utf-8')
        if len(password_bytes) > cls.PASSWORD_MAX_BYTES:
            raise ValueError(
                f"Password exceeds maximum length of {cls.PASSWORD_MAX_BYTES} bytes"
            )

        # Generate salt and hash
        salt = bcrypt.gensalt(rounds=cls.BCRYPT_ROUNDS)
        password_hash = bcrypt.hashpw(password_bytes, salt)

        return password_hash.decode('utf-8')

    @classmethod
    def verify_password(cls, password: str, password_hash: str) -> bool:
        """
        Verify a password against a bcrypt hash.

        Performs constant-time comparison to prevent timing attacks.

        Args:
            password: The plaintext password to verify
            password_hash: The bcrypt hash to verify against

        Returns:
            True if the password matches the hash, False otherwise
        """
        import bcrypt

        try:
            password_bytes = password.encode('utf-8')
            hash_bytes = password_hash.encode('utf-8')
            return bcrypt.checkpw(password_bytes, hash_bytes)
        except (ValueError, TypeError):
            # Invalid hash format or encoding error
            return False

    @classmethod
    def create_session(
        cls,
        db_session,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        duration_hours: Optional[int] = None
    ):
        """
        Create a new admin session for a user.

        Generates a secure random token and creates a session record
        in the database with expiration time.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user to create the session for
            ip_address: Client IP address (optional)
            user_agent: Client user agent string (optional)
            duration_hours: Session duration in hours (defaults to 24)

        Returns:
            AdminSession: The created session instance

        Note:
            The session is added to the database session but not committed.
            The caller is responsible for committing the transaction.
        """
        from content_catalog.models.user import AdminSession

        # Generate secure random token
        token = secrets.token_urlsafe(cls.SESSION_TOKEN_BYTES)

        # Calculate expiration time
        duration = duration_hours or cls.DEFAULT_SESSION_DURATION_HOURS
        expires_at = datetime.now(timezone.utc) + timedelta(hours=duration)

        # Create session record
        session = AdminSession(
            user_id=user_id,
            token=token,
            ip_address=ip_address,
            user_agent=user_agent,
            status=AdminSession.STATUS_ACTIVE,
            expires_at=expires_at,
            last_activity=datetime.now(timezone.utc)
        )

        db_session.add(session)
        return session

    @classmethod
    def validate_session(
        cls,
        db_session,
        token: str
    ) -> Tuple[bool, Optional['AdminSession']]:
        """
        Validate a session token.

        Checks if the token exists, is active, and has not expired.
        Updates the last_activity timestamp for valid sessions.

        Args:
            db_session: SQLAlchemy database session
            token: The session token to validate

        Returns:
            Tuple of (is_valid, session):
                - is_valid: True if session is valid, False otherwise
                - session: The AdminSession instance if found, None otherwise

        Note:
            If the session is valid, last_activity is updated but not committed.
            The caller is responsible for committing the transaction.
        """
        from content_catalog.models.user import AdminSession

        # Find session by token
        session = db_session.query(AdminSession).filter_by(token=token).first()

        if session is None:
            return False, None

        # Check if session is valid (active and not expired)
        if not session.is_valid():
            return False, session

        # Update last activity
        session.last_activity = datetime.now(timezone.utc)

        return True, session

    @classmethod
    def invalidate_session(cls, db_session, token: str) -> bool:
        """
        Invalidate (revoke) a session by its token.

        Marks the session as revoked, preventing further use.

        Args:
            db_session: SQLAlchemy database session
            token: The session token to invalidate

        Returns:
            True if session was found and invalidated, False if not found

        Note:
            Changes are added to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        from content_catalog.models.user import AdminSession

        session = db_session.query(AdminSession).filter_by(token=token).first()

        if session is None:
            return False

        session.status = AdminSession.STATUS_REVOKED
        return True

    @classmethod
    def invalidate_all_user_sessions(cls, db_session, user_id: int) -> int:
        """
        Invalidate all active sessions for a user.

        Useful for security events like password changes or account suspension.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user whose sessions should be invalidated

        Returns:
            Number of sessions invalidated

        Note:
            Changes are added to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        from content_catalog.models.user import AdminSession

        sessions = db_session.query(AdminSession).filter_by(
            user_id=user_id,
            status=AdminSession.STATUS_ACTIVE
        ).all()

        count = 0
        for session in sessions:
            session.status = AdminSession.STATUS_REVOKED
            count += 1

        return count

    @classmethod
    def generate_invitation_token(cls) -> str:
        """
        Generate a secure token for user invitations.

        Returns:
            A URL-safe random token string
        """
        return secrets.token_urlsafe(cls.SESSION_TOKEN_BYTES)

    @classmethod
    def generate_password_reset_token(cls) -> str:
        """
        Generate a secure token for password reset requests.

        Returns:
            A URL-safe random token string
        """
        return secrets.token_urlsafe(cls.SESSION_TOKEN_BYTES)
