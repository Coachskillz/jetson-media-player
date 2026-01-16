"""
Integration tests for CMS Authentication API endpoints.

Tests all authentication API routes:
- POST /api/v1/auth/login - User login with email/password
- POST /api/v1/auth/logout - User logout
- GET /api/v1/auth/me - Get current user info
- PUT /api/v1/auth/password - Change own password

Each test class covers a specific operation with comprehensive
endpoint validation including success cases and error handling.
"""

import pytest
from datetime import datetime, timedelta, timezone

from cms.models import db, User, UserSession
from cms.tests.conftest import create_test_user, create_test_session


# =============================================================================
# Login API Tests (POST /api/v1/auth/login)
# =============================================================================

class TestLoginAPI:
    """Tests for POST /api/v1/auth/login endpoint."""

    # -------------------------------------------------------------------------
    # Successful Login Tests
    # -------------------------------------------------------------------------

    def test_login_success(self, client, app, sample_admin):
        """POST /auth/login should authenticate valid credentials."""
        response = client.post('/api/v1/auth/login', json={
            'email': 'admin@test.com',
            'password': 'TestPassword123!'
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Login successful'
        assert 'user' in data
        assert 'session' in data
        assert data['user']['email'] == 'admin@test.com'
        assert data['user']['role'] == 'admin'
        assert 'token' in data['session']
        assert data['must_change_password'] is False

    def test_login_success_case_insensitive_email(self, client, app, sample_admin):
        """POST /auth/login should handle email case-insensitively."""
        response = client.post('/api/v1/auth/login', json={
            'email': 'ADMIN@TEST.COM',
            'password': 'TestPassword123!'
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Login successful'
        assert data['user']['email'] == 'admin@test.com'

    def test_login_success_with_email_whitespace(self, client, app, sample_admin):
        """POST /auth/login should trim whitespace from email."""
        response = client.post('/api/v1/auth/login', json={
            'email': '  admin@test.com  ',
            'password': 'TestPassword123!'
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Login successful'

    def test_login_success_with_remember_me(self, client, app, sample_admin):
        """POST /auth/login with remember_me should create extended session."""
        response = client.post('/api/v1/auth/login', json={
            'email': 'admin@test.com',
            'password': 'TestPassword123!',
            'remember_me': True
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Login successful'
        assert 'session' in data
        # Session should be created (expires_at will be further in the future)
        assert 'expires_at' in data['session']

    def test_login_returns_must_change_password_flag(self, client, app, sample_user_with_must_change_password):
        """POST /auth/login should indicate when password change is required."""
        response = client.post('/api/v1/auth/login', json={
            'email': 'must_change@test.com',
            'password': 'TempPassword123!'
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Login successful'
        assert data['must_change_password'] is True

    # -------------------------------------------------------------------------
    # Invalid Credentials Tests
    # -------------------------------------------------------------------------

    def test_login_invalid_password(self, client, app, sample_admin):
        """POST /auth/login should reject incorrect password."""
        response = client.post('/api/v1/auth/login', json={
            'email': 'admin@test.com',
            'password': 'WrongPassword123!'
        })

        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] == 'Invalid email or password'
        assert data['code'] == 'invalid_credentials'

    def test_login_user_not_found(self, client, app):
        """POST /auth/login should reject non-existent user."""
        response = client.post('/api/v1/auth/login', json={
            'email': 'nonexistent@test.com',
            'password': 'TestPassword123!'
        })

        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] == 'Invalid email or password'
        assert data['code'] == 'invalid_credentials'

    # -------------------------------------------------------------------------
    # Account Status Tests
    # -------------------------------------------------------------------------

    def test_login_pending_account(self, client, app, sample_pending_user):
        """POST /auth/login should reject pending account."""
        response = client.post('/api/v1/auth/login', json={
            'email': 'pending@test.com',
            'password': 'TestPassword123!'
        })

        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] == 'Account pending approval'
        assert data['code'] == 'account_pending'

    def test_login_suspended_account(self, client, app, sample_suspended_user):
        """POST /auth/login should reject suspended account."""
        response = client.post('/api/v1/auth/login', json={
            'email': 'suspended@test.com',
            'password': 'TestPassword123!'
        })

        assert response.status_code == 403
        data = response.get_json()
        assert data['error'] == 'Account suspended'
        assert data['code'] == 'account_suspended'
        assert 'reason' in data

    def test_login_locked_account(self, client, app, sample_locked_user):
        """POST /auth/login should reject locked account."""
        response = client.post('/api/v1/auth/login', json={
            'email': 'locked@test.com',
            'password': 'TestPassword123!'
        })

        assert response.status_code == 423
        data = response.get_json()
        assert data['error'] == 'Account locked due to too many failed attempts'
        assert data['code'] == 'account_locked'
        assert 'locked_until' in data

    def test_login_deactivated_account(self, client, app, db_session, sample_network):
        """POST /auth/login should reject deactivated account."""
        user = create_test_user(
            db_session,
            email='deactivated@test.com',
            name='Deactivated User',
            role='content_manager',
            status='deactivated',
            network_id=sample_network.id
        )

        response = client.post('/api/v1/auth/login', json={
            'email': 'deactivated@test.com',
            'password': 'TestPassword123!'
        })

        assert response.status_code == 403
        data = response.get_json()
        assert data['error'] == 'Account has been deactivated'
        assert data['code'] == 'account_deactivated'

    def test_login_rejected_account(self, client, app, db_session, sample_network):
        """POST /auth/login should reject rejected account."""
        user = create_test_user(
            db_session,
            email='rejected@test.com',
            name='Rejected User',
            role='content_manager',
            status='rejected',
            network_id=sample_network.id
        )

        response = client.post('/api/v1/auth/login', json={
            'email': 'rejected@test.com',
            'password': 'TestPassword123!'
        })

        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] == 'Account has been rejected'
        assert data['code'] == 'account_rejected'

    # -------------------------------------------------------------------------
    # Account Lockout Tests
    # -------------------------------------------------------------------------

    def test_login_increments_failed_attempts(self, client, app, sample_admin, db_session):
        """POST /auth/login should increment failed login attempts."""
        initial_attempts = sample_admin.failed_login_attempts

        response = client.post('/api/v1/auth/login', json={
            'email': 'admin@test.com',
            'password': 'WrongPassword123!'
        })

        assert response.status_code == 401

        # Refresh from database
        db_session.refresh(sample_admin)
        assert sample_admin.failed_login_attempts == initial_attempts + 1

    def test_login_locks_account_after_max_attempts(self, client, app, db_session, sample_network):
        """POST /auth/login should lock account after 5 failed attempts."""
        user = create_test_user(
            db_session,
            email='locktest@test.com',
            name='Lock Test User',
            role='content_manager',
            network_id=sample_network.id
        )
        user.failed_login_attempts = 4  # One away from lockout
        db_session.commit()

        response = client.post('/api/v1/auth/login', json={
            'email': 'locktest@test.com',
            'password': 'WrongPassword123!'
        })

        assert response.status_code == 423
        data = response.get_json()
        assert data['code'] == 'account_locked'
        assert 'locked_until' in data

    # -------------------------------------------------------------------------
    # Validation Error Tests
    # -------------------------------------------------------------------------

    def test_login_empty_body(self, client, app):
        """POST /auth/login should reject empty body."""
        response = client.post('/api/v1/auth/login',
                               data='',
                               content_type='application/json')

        assert response.status_code == 400
        data = response.get_json()
        assert 'Request body is required' in data['error']

    def test_login_missing_email(self, client, app):
        """POST /auth/login should reject missing email."""
        response = client.post('/api/v1/auth/login', json={
            'password': 'TestPassword123!'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'email is required' in data['error']

    def test_login_missing_password(self, client, app, sample_admin):
        """POST /auth/login should reject missing password."""
        response = client.post('/api/v1/auth/login', json={
            'email': 'admin@test.com'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'password is required' in data['error']

    def test_login_invalid_email_type(self, client, app):
        """POST /auth/login should reject non-string email."""
        response = client.post('/api/v1/auth/login', json={
            'email': 12345,
            'password': 'TestPassword123!'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'email must be a string' in data['error']

    def test_login_invalid_password_type(self, client, app):
        """POST /auth/login should reject non-string password."""
        response = client.post('/api/v1/auth/login', json={
            'email': 'admin@test.com',
            'password': 12345
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'password must be a string' in data['error']


# =============================================================================
# Logout API Tests (POST /api/v1/auth/logout)
# =============================================================================

class TestLogoutAPI:
    """Tests for POST /api/v1/auth/logout endpoint."""

    def test_logout_success(self, client, app, sample_admin, sample_user_session):
        """POST /auth/logout should invalidate current session."""
        response = client.post(
            '/api/v1/auth/logout',
            headers={'Authorization': f'Bearer {sample_user_session.token}'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Logged out successfully'

    def test_logout_deletes_session(self, client, app, sample_admin, sample_user_session, db_session):
        """POST /auth/logout should delete the session from database."""
        session_token = sample_user_session.token
        session_id = sample_user_session.id

        response = client.post(
            '/api/v1/auth/logout',
            headers={'Authorization': f'Bearer {session_token}'}
        )

        assert response.status_code == 200

        # Verify session is deleted
        deleted_session = db_session.get(UserSession, session_id)
        assert deleted_session is None

    def test_logout_invalidates_token(self, client, app, sample_admin, sample_user_session):
        """POST /auth/logout should make token unusable for subsequent requests."""
        token = sample_user_session.token

        # Logout
        response = client.post(
            '/api/v1/auth/logout',
            headers={'Authorization': f'Bearer {token}'}
        )
        assert response.status_code == 200

        # Try to use the same token again
        response = client.get(
            '/api/v1/auth/me',
            headers={'Authorization': f'Bearer {token}'}
        )
        assert response.status_code == 401

    def test_logout_requires_authentication(self, client, app):
        """POST /auth/logout should reject unauthenticated requests."""
        response = client.post('/api/v1/auth/logout')

        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] == 'Authentication required'
        assert data['code'] == 'missing_token'

    def test_logout_rejects_invalid_token(self, client, app):
        """POST /auth/logout should reject invalid tokens."""
        response = client.post(
            '/api/v1/auth/logout',
            headers={'Authorization': 'Bearer invalid-token-12345'}
        )

        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] == 'Invalid or expired session'
        assert data['code'] == 'invalid_session'


# =============================================================================
# Get Current User API Tests (GET /api/v1/auth/me)
# =============================================================================

class TestGetMeAPI:
    """Tests for GET /api/v1/auth/me endpoint."""

    def test_get_me_success(self, client, app, sample_admin, sample_user_session):
        """GET /auth/me should return current user info."""
        response = client.get(
            '/api/v1/auth/me',
            headers={'Authorization': f'Bearer {sample_user_session.token}'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert 'user' in data
        assert 'session' in data
        assert data['user']['email'] == sample_admin.email
        assert data['user']['name'] == sample_admin.name
        assert data['user']['role'] == sample_admin.role

    def test_get_me_returns_session_info(self, client, app, sample_admin, sample_user_session):
        """GET /auth/me should include session information."""
        response = client.get(
            '/api/v1/auth/me',
            headers={'Authorization': f'Bearer {sample_user_session.token}'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert 'session' in data
        assert 'created_at' in data['session']
        assert 'expires_at' in data['session']

    def test_get_me_requires_authentication(self, client, app):
        """GET /auth/me should reject unauthenticated requests."""
        response = client.get('/api/v1/auth/me')

        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] == 'Authentication required'
        assert data['code'] == 'missing_token'

    def test_get_me_rejects_invalid_token(self, client, app):
        """GET /auth/me should reject invalid tokens."""
        response = client.get(
            '/api/v1/auth/me',
            headers={'Authorization': 'Bearer invalid-token-12345'}
        )

        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] == 'Invalid or expired session'
        assert data['code'] == 'invalid_session'

    def test_get_me_rejects_expired_session(self, client, app, sample_admin, db_session):
        """GET /auth/me should reject expired sessions."""
        # Create an expired session
        session = UserSession.create_session(
            user_id=sample_admin.id,
            ip_address='127.0.0.1',
            user_agent='Test Agent'
        )
        session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.add(session)
        db_session.commit()

        response = client.get(
            '/api/v1/auth/me',
            headers={'Authorization': f'Bearer {session.token}'}
        )

        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] == 'Invalid or expired session'

    def test_get_me_rejects_malformed_auth_header(self, client, app):
        """GET /auth/me should reject malformed Authorization headers."""
        # Missing Bearer prefix
        response = client.get(
            '/api/v1/auth/me',
            headers={'Authorization': 'some-token'}
        )
        assert response.status_code == 401

        # Invalid format
        response = client.get(
            '/api/v1/auth/me',
            headers={'Authorization': 'Bearer'}
        )
        assert response.status_code == 401


# =============================================================================
# Change Password API Tests (PUT /api/v1/auth/password)
# =============================================================================

class TestChangePasswordAPI:
    """Tests for PUT /api/v1/auth/password endpoint."""

    # -------------------------------------------------------------------------
    # Successful Password Change Tests
    # -------------------------------------------------------------------------

    def test_change_password_success(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should change password with valid credentials."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'current_password': 'TestPassword123!',
                'new_password': 'NewSecurePass456@'
            }
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Password changed successfully'

    def test_change_password_allows_login_with_new_password(self, client, app, sample_admin, sample_user_session, db_session):
        """PUT /auth/password should allow login with new password."""
        # Change password
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'current_password': 'TestPassword123!',
                'new_password': 'NewSecurePass456@'
            }
        )
        assert response.status_code == 200

        # Logout current session
        client.post(
            '/api/v1/auth/logout',
            headers={'Authorization': f'Bearer {sample_user_session.token}'}
        )

        # Try login with new password
        response = client.post('/api/v1/auth/login', json={
            'email': sample_admin.email,
            'password': 'NewSecurePass456@'
        })
        assert response.status_code == 200

    def test_change_password_clears_must_change_flag(self, client, app, sample_user_with_must_change_password, db_session):
        """PUT /auth/password should clear must_change_password flag."""
        # Create session for user who must change password
        session = create_test_session(
            db_session,
            user_id=sample_user_with_must_change_password.id
        )

        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {session.token}'},
            json={
                'current_password': 'TempPassword123!',
                'new_password': 'NewSecurePass456@'
            }
        )

        assert response.status_code == 200

        # Refresh user and verify flag is cleared
        db_session.refresh(sample_user_with_must_change_password)
        assert sample_user_with_must_change_password.must_change_password is False

    # -------------------------------------------------------------------------
    # Incorrect Current Password Tests
    # -------------------------------------------------------------------------

    def test_change_password_wrong_current_password(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should reject incorrect current password."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'current_password': 'WrongPassword123!',
                'new_password': 'NewSecurePass456@'
            }
        )

        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] == 'Current password is incorrect'
        assert data['code'] == 'invalid_password'

    # -------------------------------------------------------------------------
    # Password Validation Tests
    # -------------------------------------------------------------------------

    def test_change_password_too_short(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should reject password shorter than 12 chars."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'current_password': 'TestPassword123!',
                'new_password': 'Short1!'
            }
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'at least 12 characters' in data['error']

    def test_change_password_missing_uppercase(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should reject password without uppercase."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'current_password': 'TestPassword123!',
                'new_password': 'newpassword123!'
            }
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'uppercase' in data['error']

    def test_change_password_missing_lowercase(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should reject password without lowercase."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'current_password': 'TestPassword123!',
                'new_password': 'NEWPASSWORD123!'
            }
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'lowercase' in data['error']

    def test_change_password_missing_number(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should reject password without number."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'current_password': 'TestPassword123!',
                'new_password': 'NewPasswordOnly!'
            }
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'number' in data['error']

    def test_change_password_missing_special_char(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should reject password without special character."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'current_password': 'TestPassword123!',
                'new_password': 'NewPassword12345'
            }
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'special character' in data['error']

    def test_change_password_same_as_current(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should reject password same as current."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'current_password': 'TestPassword123!',
                'new_password': 'TestPassword123!'
            }
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'different from current' in data['error']

    # -------------------------------------------------------------------------
    # Validation Error Tests
    # -------------------------------------------------------------------------

    def test_change_password_empty_body(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should reject empty body."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            data='',
            content_type='application/json'
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Request body is required' in data['error']

    def test_change_password_missing_current_password(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should reject missing current_password."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'new_password': 'NewSecurePass456@'
            }
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'current_password is required' in data['error']

    def test_change_password_missing_new_password(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should reject missing new_password."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'current_password': 'TestPassword123!'
            }
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'new_password is required' in data['error']

    def test_change_password_invalid_current_password_type(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should reject non-string current_password."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'current_password': 12345,
                'new_password': 'NewSecurePass456@'
            }
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'current_password must be a string' in data['error']

    def test_change_password_invalid_new_password_type(self, client, app, sample_admin, sample_user_session):
        """PUT /auth/password should reject non-string new_password."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': f'Bearer {sample_user_session.token}'},
            json={
                'current_password': 'TestPassword123!',
                'new_password': 12345
            }
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'new_password must be a string' in data['error']

    # -------------------------------------------------------------------------
    # Authentication Tests
    # -------------------------------------------------------------------------

    def test_change_password_requires_authentication(self, client, app):
        """PUT /auth/password should reject unauthenticated requests."""
        response = client.put('/api/v1/auth/password', json={
            'current_password': 'TestPassword123!',
            'new_password': 'NewSecurePass456@'
        })

        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] == 'Authentication required'
        assert data['code'] == 'missing_token'

    def test_change_password_rejects_invalid_token(self, client, app):
        """PUT /auth/password should reject invalid tokens."""
        response = client.put(
            '/api/v1/auth/password',
            headers={'Authorization': 'Bearer invalid-token-12345'},
            json={
                'current_password': 'TestPassword123!',
                'new_password': 'NewSecurePass456@'
            }
        )

        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] == 'Invalid or expired session'
        assert data['code'] == 'invalid_session'
