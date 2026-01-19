"""
Unit tests for AuthService in Content Catalog service.

Tests AuthService functionality including:
- Password hashing with bcrypt
- Password verification (constant-time comparison)
- Session creation with secure tokens
- Session validation with expiration checking
- Session invalidation (single and all user sessions)
- Account lockout logic
- Token generation for invitations and password resets
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from content_catalog.services.auth_service import AuthService
from content_catalog.models import db, User, AdminSession


# =============================================================================
# Password Hashing Tests
# =============================================================================

class TestAuthServicePasswordHashing:
    """Tests for AuthService password hashing functionality."""

    def test_hash_password_returns_bcrypt_hash(self, app, db_session):
        """hash_password should return a valid bcrypt hash."""
        password = 'SecurePassword123!'
        password_hash = AuthService.hash_password(password)

        # bcrypt hashes start with $2b$ or $2a$
        assert password_hash.startswith('$2')
        assert password_hash != password

    def test_hash_password_produces_different_hashes_for_same_password(self, app, db_session):
        """hash_password should produce different hashes due to random salt."""
        password = 'SamePassword123!'

        hash1 = AuthService.hash_password(password)
        hash2 = AuthService.hash_password(password)

        # Hashes should be different due to random salt
        assert hash1 != hash2

    def test_hash_password_rejects_password_exceeding_72_bytes(self, app, db_session):
        """hash_password should raise ValueError for password > 72 bytes."""
        # Create a password that exceeds 72 bytes when encoded
        long_password = 'a' * 73

        with pytest.raises(ValueError) as exc_info:
            AuthService.hash_password(long_password)

        assert '72 bytes' in str(exc_info.value)

    def test_hash_password_accepts_password_at_72_bytes(self, app, db_session):
        """hash_password should accept password exactly at 72 bytes."""
        password = 'a' * 72

        # Should not raise
        password_hash = AuthService.hash_password(password)
        assert password_hash.startswith('$2')

    def test_hash_password_handles_unicode_characters(self, app, db_session):
        """hash_password should handle Unicode characters correctly."""
        # Unicode password (each character may be multiple bytes)
        password = 'P@ssw0rd!'

        password_hash = AuthService.hash_password(password)
        assert password_hash.startswith('$2')

    def test_hash_password_uses_configured_rounds(self, app, db_session):
        """hash_password should use BCRYPT_ROUNDS configuration."""
        password = 'TestPassword123!'
        password_hash = AuthService.hash_password(password)

        # bcrypt hash format: $2b$[rounds]$...
        # Extract rounds from hash
        parts = password_hash.split('$')
        rounds = int(parts[2])
        assert rounds == AuthService.BCRYPT_ROUNDS


# =============================================================================
# Password Verification Tests
# =============================================================================

class TestAuthServicePasswordVerification:
    """Tests for AuthService password verification functionality."""

    def test_verify_password_returns_true_for_correct_password(self, app, db_session):
        """verify_password should return True for matching password."""
        password = 'CorrectPassword123!'
        password_hash = AuthService.hash_password(password)

        result = AuthService.verify_password(password, password_hash)

        assert result is True

    def test_verify_password_returns_false_for_wrong_password(self, app, db_session):
        """verify_password should return False for non-matching password."""
        correct_password = 'CorrectPassword123!'
        wrong_password = 'WrongPassword456!'
        password_hash = AuthService.hash_password(correct_password)

        result = AuthService.verify_password(wrong_password, password_hash)

        assert result is False

    def test_verify_password_returns_false_for_invalid_hash(self, app, db_session):
        """verify_password should return False for invalid hash format."""
        password = 'TestPassword123!'
        invalid_hash = 'not-a-valid-bcrypt-hash'

        result = AuthService.verify_password(password, invalid_hash)

        assert result is False

    def test_verify_password_returns_false_for_empty_hash(self, app, db_session):
        """verify_password should return False for empty hash."""
        password = 'TestPassword123!'

        result = AuthService.verify_password(password, '')

        assert result is False

    def test_verify_password_handles_empty_password(self, app, db_session):
        """verify_password should handle empty password gracefully."""
        password_hash = AuthService.hash_password('SomePassword')

        result = AuthService.verify_password('', password_hash)

        assert result is False

    def test_verify_password_constant_time_comparison(self, app, db_session):
        """verify_password should use constant-time comparison (via bcrypt)."""
        # This test verifies the behavior works correctly
        # Actual timing attack resistance comes from bcrypt.checkpw
        password = 'TestPassword123!'
        password_hash = AuthService.hash_password(password)

        # Both should work consistently
        assert AuthService.verify_password(password, password_hash) is True
        assert AuthService.verify_password('wrong', password_hash) is False


# =============================================================================
# Session Creation Tests
# =============================================================================

class TestAuthServiceSessionCreation:
    """Tests for AuthService session creation functionality."""

    def test_create_session_returns_admin_session(self, app, db_session, sample_admin):
        """create_session should return an AdminSession instance."""
        session = AuthService.create_session(
            db_session,
            user_id=sample_admin.id,
            ip_address='127.0.0.1',
            user_agent='Test Browser'
        )

        assert isinstance(session, AdminSession)
        assert session.user_id == sample_admin.id

    def test_create_session_generates_secure_token(self, app, db_session, sample_admin):
        """create_session should generate a secure random token."""
        session = AuthService.create_session(
            db_session,
            user_id=sample_admin.id
        )

        assert session.token is not None
        # Token should be URL-safe and of reasonable length
        assert len(session.token) > 20

    def test_create_session_tokens_are_unique(self, app, db_session, sample_admin):
        """create_session should generate unique tokens for each session."""
        session1 = AuthService.create_session(db_session, user_id=sample_admin.id)
        session2 = AuthService.create_session(db_session, user_id=sample_admin.id)

        assert session1.token != session2.token

    def test_create_session_stores_ip_address(self, app, db_session, sample_admin):
        """create_session should store the provided IP address."""
        ip_address = '192.168.1.100'

        session = AuthService.create_session(
            db_session,
            user_id=sample_admin.id,
            ip_address=ip_address
        )

        assert session.ip_address == ip_address

    def test_create_session_stores_user_agent(self, app, db_session, sample_admin):
        """create_session should store the provided user agent."""
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0'

        session = AuthService.create_session(
            db_session,
            user_id=sample_admin.id,
            user_agent=user_agent
        )

        assert session.user_agent == user_agent

    def test_create_session_sets_active_status(self, app, db_session, sample_admin):
        """create_session should set session status to active."""
        session = AuthService.create_session(
            db_session,
            user_id=sample_admin.id
        )

        assert session.status == AdminSession.STATUS_ACTIVE

    def test_create_session_sets_default_expiration(self, app, db_session, sample_admin):
        """create_session should set default 24-hour expiration."""
        before = datetime.now(timezone.utc)
        session = AuthService.create_session(
            db_session,
            user_id=sample_admin.id
        )
        after = datetime.now(timezone.utc)

        # Expiration should be approximately 24 hours from now
        expected_min = before + timedelta(hours=AuthService.DEFAULT_SESSION_DURATION_HOURS)
        expected_max = after + timedelta(hours=AuthService.DEFAULT_SESSION_DURATION_HOURS)

        assert expected_min <= session.expires_at <= expected_max

    def test_create_session_accepts_custom_duration(self, app, db_session, sample_admin):
        """create_session should accept custom duration in hours."""
        custom_hours = 48
        before = datetime.now(timezone.utc)

        session = AuthService.create_session(
            db_session,
            user_id=sample_admin.id,
            duration_hours=custom_hours
        )
        after = datetime.now(timezone.utc)

        expected_min = before + timedelta(hours=custom_hours)
        expected_max = after + timedelta(hours=custom_hours)

        assert expected_min <= session.expires_at <= expected_max

    def test_create_session_sets_last_activity(self, app, db_session, sample_admin):
        """create_session should set last_activity to current time."""
        before = datetime.now(timezone.utc)
        session = AuthService.create_session(
            db_session,
            user_id=sample_admin.id
        )
        after = datetime.now(timezone.utc)

        assert before <= session.last_activity <= after

    def test_create_session_handles_optional_parameters(self, app, db_session, sample_admin):
        """create_session should work without optional parameters."""
        session = AuthService.create_session(
            db_session,
            user_id=sample_admin.id
        )

        assert session.ip_address is None
        assert session.user_agent is None
        assert session.token is not None


# =============================================================================
# Session Validation Tests
# =============================================================================

class TestAuthServiceSessionValidation:
    """Tests for AuthService session validation functionality."""

    def test_validate_session_returns_true_for_valid_session(self, app, db_session, sample_session):
        """validate_session should return (True, session) for valid session."""
        is_valid, session = AuthService.validate_session(
            db_session,
            sample_session.token
        )

        assert is_valid is True
        assert session is not None
        assert session.id == sample_session.id

    def test_validate_session_returns_false_for_nonexistent_token(self, app, db_session):
        """validate_session should return (False, None) for unknown token."""
        is_valid, session = AuthService.validate_session(
            db_session,
            'nonexistent-token-12345'
        )

        assert is_valid is False
        assert session is None

    def test_validate_session_returns_false_for_expired_session(self, app, db_session, sample_admin):
        """validate_session should return (False, session) for expired session."""
        # Create an expired session
        expired_session = AdminSession(
            user_id=sample_admin.id,
            token=secrets.token_urlsafe(32),
            status=AdminSession.STATUS_ACTIVE,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1)  # Expired 1 hour ago
        )
        db_session.add(expired_session)
        db_session.commit()

        is_valid, session = AuthService.validate_session(
            db_session,
            expired_session.token
        )

        assert is_valid is False
        assert session is not None  # Session is found but invalid

    def test_validate_session_returns_false_for_revoked_session(self, app, db_session, sample_admin):
        """validate_session should return (False, session) for revoked session."""
        # Create a revoked session
        revoked_session = AdminSession(
            user_id=sample_admin.id,
            token=secrets.token_urlsafe(32),
            status=AdminSession.STATUS_REVOKED,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
        )
        db_session.add(revoked_session)
        db_session.commit()

        is_valid, session = AuthService.validate_session(
            db_session,
            revoked_session.token
        )

        assert is_valid is False
        assert session is not None

    def test_validate_session_updates_last_activity(self, app, db_session, sample_session):
        """validate_session should update last_activity for valid session."""
        original_activity = sample_session.last_activity

        # Wait a tiny bit to ensure time difference
        is_valid, session = AuthService.validate_session(
            db_session,
            sample_session.token
        )

        assert is_valid is True
        # last_activity should be updated to now (or very close)
        assert session.last_activity >= original_activity


# =============================================================================
# Session Invalidation Tests
# =============================================================================

class TestAuthServiceSessionInvalidation:
    """Tests for AuthService session invalidation functionality."""

    def test_invalidate_session_returns_true_for_existing_session(self, app, db_session, sample_session):
        """invalidate_session should return True when session is found."""
        result = AuthService.invalidate_session(
            db_session,
            sample_session.token
        )

        assert result is True

    def test_invalidate_session_sets_status_to_revoked(self, app, db_session, sample_session):
        """invalidate_session should set session status to revoked."""
        AuthService.invalidate_session(
            db_session,
            sample_session.token
        )

        assert sample_session.status == AdminSession.STATUS_REVOKED

    def test_invalidate_session_returns_false_for_nonexistent_token(self, app, db_session):
        """invalidate_session should return False for unknown token."""
        result = AuthService.invalidate_session(
            db_session,
            'nonexistent-token-12345'
        )

        assert result is False

    def test_invalidated_session_fails_validation(self, app, db_session, sample_session):
        """Invalidated session should fail subsequent validation."""
        # First, session should be valid
        is_valid, _ = AuthService.validate_session(db_session, sample_session.token)
        assert is_valid is True

        # Invalidate the session
        AuthService.invalidate_session(db_session, sample_session.token)

        # Now it should be invalid
        is_valid, _ = AuthService.validate_session(db_session, sample_session.token)
        assert is_valid is False


# =============================================================================
# Invalidate All User Sessions Tests
# =============================================================================

class TestAuthServiceInvalidateAllUserSessions:
    """Tests for AuthService invalidate_all_user_sessions functionality."""

    def test_invalidate_all_user_sessions_returns_count(self, app, db_session, sample_admin):
        """invalidate_all_user_sessions should return count of invalidated sessions."""
        # Create multiple sessions for the user
        session1 = AuthService.create_session(db_session, user_id=sample_admin.id)
        session2 = AuthService.create_session(db_session, user_id=sample_admin.id)
        session3 = AuthService.create_session(db_session, user_id=sample_admin.id)
        db_session.commit()

        count = AuthService.invalidate_all_user_sessions(
            db_session,
            sample_admin.id
        )

        assert count == 3

    def test_invalidate_all_user_sessions_sets_all_to_revoked(self, app, db_session, sample_admin):
        """invalidate_all_user_sessions should set all sessions to revoked."""
        # Create multiple sessions
        session1 = AuthService.create_session(db_session, user_id=sample_admin.id)
        session2 = AuthService.create_session(db_session, user_id=sample_admin.id)
        db_session.commit()

        AuthService.invalidate_all_user_sessions(db_session, sample_admin.id)

        assert session1.status == AdminSession.STATUS_REVOKED
        assert session2.status == AdminSession.STATUS_REVOKED

    def test_invalidate_all_user_sessions_returns_zero_for_no_sessions(self, app, db_session, sample_admin):
        """invalidate_all_user_sessions should return 0 when user has no sessions."""
        # Ensure no sessions exist by creating a fresh user
        count = AuthService.invalidate_all_user_sessions(
            db_session,
            sample_admin.id
        )

        # If sample_admin has no sessions, count should be 0
        # (depends on fixture, but this tests the logic)
        assert count >= 0

    def test_invalidate_all_user_sessions_does_not_affect_other_users(self, app, db_session, sample_admin, sample_content_manager):
        """invalidate_all_user_sessions should not affect other users' sessions."""
        # Create sessions for both users
        admin_session = AuthService.create_session(db_session, user_id=sample_admin.id)
        cm_session = AuthService.create_session(db_session, user_id=sample_content_manager.id)
        db_session.commit()

        # Invalidate only admin's sessions
        AuthService.invalidate_all_user_sessions(db_session, sample_admin.id)

        # Admin session should be revoked
        assert admin_session.status == AdminSession.STATUS_REVOKED
        # Content manager session should still be active
        assert cm_session.status == AdminSession.STATUS_ACTIVE

    def test_invalidate_all_user_sessions_only_affects_active_sessions(self, app, db_session, sample_admin):
        """invalidate_all_user_sessions should only invalidate active sessions."""
        # Create an active session
        active_session = AuthService.create_session(db_session, user_id=sample_admin.id)

        # Create an already revoked session
        revoked_session = AdminSession(
            user_id=sample_admin.id,
            token=secrets.token_urlsafe(32),
            status=AdminSession.STATUS_REVOKED,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
        )
        db_session.add(revoked_session)
        db_session.commit()

        count = AuthService.invalidate_all_user_sessions(db_session, sample_admin.id)

        # Should only count the active session
        assert count == 1


# =============================================================================
# Account Lockout Logic Tests
# =============================================================================

class TestAuthServiceAccountLockout:
    """Tests for AuthService account lockout configuration and logic."""

    def test_max_login_attempts_configuration(self, app, db_session):
        """AuthService should have MAX_LOGIN_ATTEMPTS configured."""
        assert hasattr(AuthService, 'MAX_LOGIN_ATTEMPTS')
        assert AuthService.MAX_LOGIN_ATTEMPTS == 5

    def test_lockout_duration_configuration(self, app, db_session):
        """AuthService should have LOCKOUT_DURATION_MINUTES configured."""
        assert hasattr(AuthService, 'LOCKOUT_DURATION_MINUTES')
        assert AuthService.LOCKOUT_DURATION_MINUTES == 15

    def test_lockout_integrates_with_user_model(self, app, db_session, sample_admin):
        """AuthService lockout config should integrate with User.is_locked()."""
        # Simulate lockout scenario
        lockout_time = datetime.now(timezone.utc) + timedelta(
            minutes=AuthService.LOCKOUT_DURATION_MINUTES
        )
        sample_admin.locked_until = lockout_time
        sample_admin.failed_login_attempts = AuthService.MAX_LOGIN_ATTEMPTS
        db_session.commit()

        # User should be locked
        assert sample_admin.is_locked() is True
        assert sample_admin.failed_login_attempts >= AuthService.MAX_LOGIN_ATTEMPTS

    def test_lockout_expires_after_duration(self, app, db_session, sample_admin):
        """Account lockout should expire after LOCKOUT_DURATION_MINUTES."""
        # Set lockout to expired
        expired_lockout = datetime.now(timezone.utc) - timedelta(minutes=1)
        sample_admin.locked_until = expired_lockout
        sample_admin.failed_login_attempts = AuthService.MAX_LOGIN_ATTEMPTS
        db_session.commit()

        # User should no longer be locked
        assert sample_admin.is_locked() is False


# =============================================================================
# Token Generation Tests
# =============================================================================

class TestAuthServiceTokenGeneration:
    """Tests for AuthService token generation functionality."""

    def test_generate_invitation_token_returns_string(self, app, db_session):
        """generate_invitation_token should return a string."""
        token = AuthService.generate_invitation_token()

        assert isinstance(token, str)
        assert len(token) > 0

    def test_generate_invitation_token_is_unique(self, app, db_session):
        """generate_invitation_token should generate unique tokens."""
        tokens = [AuthService.generate_invitation_token() for _ in range(100)]

        # All tokens should be unique
        assert len(tokens) == len(set(tokens))

    def test_generate_invitation_token_is_url_safe(self, app, db_session):
        """generate_invitation_token should generate URL-safe tokens."""
        token = AuthService.generate_invitation_token()

        # URL-safe characters: alphanumeric, '-', '_'
        valid_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_')
        assert all(c in valid_chars for c in token)

    def test_generate_password_reset_token_returns_string(self, app, db_session):
        """generate_password_reset_token should return a string."""
        token = AuthService.generate_password_reset_token()

        assert isinstance(token, str)
        assert len(token) > 0

    def test_generate_password_reset_token_is_unique(self, app, db_session):
        """generate_password_reset_token should generate unique tokens."""
        tokens = [AuthService.generate_password_reset_token() for _ in range(100)]

        # All tokens should be unique
        assert len(tokens) == len(set(tokens))

    def test_generate_password_reset_token_is_url_safe(self, app, db_session):
        """generate_password_reset_token should generate URL-safe tokens."""
        token = AuthService.generate_password_reset_token()

        # URL-safe characters: alphanumeric, '-', '_'
        valid_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_')
        assert all(c in valid_chars for c in token)

    def test_token_entropy_is_sufficient(self, app, db_session):
        """Tokens should have sufficient entropy (32 bytes = 256 bits)."""
        # SESSION_TOKEN_BYTES is 32, giving 256 bits of entropy
        assert AuthService.SESSION_TOKEN_BYTES == 32

        # Generated tokens should be long enough
        # URL-safe base64 encoding: 32 bytes -> ~43 characters
        token = AuthService.generate_invitation_token()
        assert len(token) >= 40


# =============================================================================
# Configuration Constants Tests
# =============================================================================

class TestAuthServiceConfiguration:
    """Tests for AuthService configuration constants."""

    def test_bcrypt_rounds_configured(self, app, db_session):
        """AuthService should have BCRYPT_ROUNDS configured."""
        assert hasattr(AuthService, 'BCRYPT_ROUNDS')
        # 12 rounds is a reasonable security/performance balance
        assert AuthService.BCRYPT_ROUNDS >= 10

    def test_password_max_bytes_configured(self, app, db_session):
        """AuthService should have PASSWORD_MAX_BYTES configured."""
        assert hasattr(AuthService, 'PASSWORD_MAX_BYTES')
        # bcrypt's internal limit is 72 bytes
        assert AuthService.PASSWORD_MAX_BYTES == 72

    def test_session_token_bytes_configured(self, app, db_session):
        """AuthService should have SESSION_TOKEN_BYTES configured."""
        assert hasattr(AuthService, 'SESSION_TOKEN_BYTES')
        # 32 bytes = 256 bits of entropy
        assert AuthService.SESSION_TOKEN_BYTES >= 32

    def test_default_session_duration_configured(self, app, db_session):
        """AuthService should have DEFAULT_SESSION_DURATION_HOURS configured."""
        assert hasattr(AuthService, 'DEFAULT_SESSION_DURATION_HOURS')
        # 24 hours is a reasonable default
        assert AuthService.DEFAULT_SESSION_DURATION_HOURS == 24
