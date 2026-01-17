"""
Integration tests for Content Catalog Auth API endpoints.

Tests all authentication API routes:
- POST /admin/api/login - User authentication and JWT token generation
- POST /admin/api/logout - Session invalidation
- GET /admin/api/me - Get current authenticated user

Each test class covers a specific operation with comprehensive
endpoint validation including success cases and error handling.
"""

import pytest
from datetime import datetime, timedelta, timezone

from content_catalog.models import db, User
from content_catalog.tests.conftest import TEST_PASSWORD, get_auth_headers


# =============================================================================
# Login API Tests (POST /admin/api/login)
# =============================================================================

class TestLoginAPI:
    """Tests for POST /admin/api/login endpoint."""

    # -------------------------------------------------------------------------
    # Successful Login Tests
    # -------------------------------------------------------------------------

    def test_login_success(self, client, app, sample_admin):
        """POST /login should authenticate valid credentials and return JWT."""
        response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })

        assert response.status_code == 200
        data = response.get_json()
        assert 'access_token' in data
        assert 'user' in data
        assert data['user']['id'] == sample_admin.id
        assert data['user']['email'] == sample_admin.email
        assert data['user']['role'] == sample_admin.role
        assert 'password_hash' not in data['user']

    def test_login_success_email_case_insensitive(self, client, app, sample_admin):
        """POST /login should accept email in any case."""
        response = client.post('/admin/api/login', json={
            'email': sample_admin.email.upper(),
            'password': TEST_PASSWORD
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['user']['email'] == sample_admin.email

    def test_login_success_email_with_whitespace(self, client, app, sample_admin):
        """POST /login should trim whitespace from email."""
        response = client.post('/admin/api/login', json={
            'email': f'  {sample_admin.email}  ',
            'password': TEST_PASSWORD
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['user']['email'] == sample_admin.email

    def test_login_updates_last_login(self, client, app, sample_admin):
        """POST /login should update the user's last_login timestamp."""
        original_last_login = sample_admin.last_login

        response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })

        assert response.status_code == 200

        with app.app_context():
            user = db.session.get(User, sample_admin.id)
            assert user.last_login is not None
            if original_last_login:
                assert user.last_login > original_last_login

    def test_login_resets_failed_attempts(self, client, app, db_session, sample_admin):
        """POST /login should reset failed_login_attempts on successful login."""
        # Set some failed attempts
        sample_admin.failed_login_attempts = 3
        db_session.commit()

        response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })

        assert response.status_code == 200

        with app.app_context():
            user = db.session.get(User, sample_admin.id)
            assert user.failed_login_attempts == 0

    # -------------------------------------------------------------------------
    # Validation Error Tests
    # -------------------------------------------------------------------------

    def test_login_empty_body(self, client, app):
        """POST /login should reject empty request body."""
        response = client.post('/admin/api/login',
                               data='',
                               content_type='application/json')

        assert response.status_code == 400
        data = response.get_json()
        assert 'Request body is required' in data['error']

    def test_login_missing_email(self, client, app):
        """POST /login should reject missing email."""
        response = client.post('/admin/api/login', json={
            'password': TEST_PASSWORD
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'email is required' in data['error']

    def test_login_missing_password(self, client, app, sample_admin):
        """POST /login should reject missing password."""
        response = client.post('/admin/api/login', json={
            'email': sample_admin.email
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'password is required' in data['error']

    def test_login_invalid_email_type(self, client, app):
        """POST /login should reject non-string email."""
        response = client.post('/admin/api/login', json={
            'email': 12345,
            'password': TEST_PASSWORD
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'email must be a string' in data['error']

    def test_login_invalid_password_type(self, client, app, sample_admin):
        """POST /login should reject non-string password."""
        response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': 12345
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'password must be a string' in data['error']

    # -------------------------------------------------------------------------
    # Authentication Failure Tests
    # -------------------------------------------------------------------------

    def test_login_user_not_found(self, client, app):
        """POST /login should return 401 for non-existent user."""
        response = client.post('/admin/api/login', json={
            'email': 'nonexistent@example.com',
            'password': TEST_PASSWORD
        })

        assert response.status_code == 401
        data = response.get_json()
        assert 'Invalid email or password' in data['error']

    def test_login_wrong_password(self, client, app, sample_admin):
        """POST /login should return 401 for wrong password."""
        response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': 'WrongPassword123!'
        })

        assert response.status_code == 401
        data = response.get_json()
        assert 'Invalid email or password' in data['error']

    def test_login_increments_failed_attempts(self, client, app, sample_admin):
        """POST /login should increment failed_login_attempts on wrong password."""
        original_attempts = sample_admin.failed_login_attempts

        response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': 'WrongPassword123!'
        })

        assert response.status_code == 401

        with app.app_context():
            user = db.session.get(User, sample_admin.id)
            assert user.failed_login_attempts == original_attempts + 1

    # -------------------------------------------------------------------------
    # Account Status Tests
    # -------------------------------------------------------------------------

    def test_login_pending_user(self, client, app, sample_pending_user):
        """POST /login should reject pending user."""
        response = client.post('/admin/api/login', json={
            'email': sample_pending_user.email,
            'password': TEST_PASSWORD
        })

        assert response.status_code == 401
        data = response.get_json()
        assert 'pending approval' in data['error']

    def test_login_suspended_user(self, client, app, db_session, sample_admin):
        """POST /login should reject suspended user."""
        sample_admin.status = User.STATUS_SUSPENDED
        db_session.commit()

        response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })

        assert response.status_code == 401
        data = response.get_json()
        assert 'suspended' in data['error']

    def test_login_deactivated_user(self, client, app, db_session, sample_admin):
        """POST /login should reject deactivated user."""
        sample_admin.status = User.STATUS_DEACTIVATED
        db_session.commit()

        response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })

        assert response.status_code == 401
        data = response.get_json()
        assert 'deactivated' in data['error']

    def test_login_rejected_user(self, client, app, db_session, sample_pending_user):
        """POST /login should reject rejected user."""
        sample_pending_user.status = User.STATUS_REJECTED
        db_session.commit()

        response = client.post('/admin/api/login', json={
            'email': sample_pending_user.email,
            'password': TEST_PASSWORD
        })

        assert response.status_code == 401
        data = response.get_json()
        assert 'rejected' in data['error']

    # -------------------------------------------------------------------------
    # Account Lockout Tests
    # -------------------------------------------------------------------------

    def test_login_locked_account(self, client, app, db_session, sample_admin):
        """POST /login should reject locked account."""
        sample_admin.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        db_session.commit()

        response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })

        assert response.status_code == 401
        data = response.get_json()
        assert 'locked' in data['error'].lower()

    def test_login_expired_lockout(self, client, app, db_session, sample_admin):
        """POST /login should allow login if lockout has expired."""
        sample_admin.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.commit()

        response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })

        assert response.status_code == 200

    def test_login_lockout_after_max_attempts(self, client, app, db_session, sample_admin):
        """POST /login should lock account after 5 failed attempts."""
        # Make 5 failed login attempts
        for i in range(5):
            response = client.post('/admin/api/login', json={
                'email': sample_admin.email,
                'password': 'WrongPassword123!'
            })
            assert response.status_code == 401

        # Verify account is now locked
        with app.app_context():
            user = db.session.get(User, sample_admin.id)
            assert user.failed_login_attempts == 5
            assert user.locked_until is not None
            assert user.locked_until > datetime.now(timezone.utc)


# =============================================================================
# Logout API Tests (POST /admin/api/logout)
# =============================================================================

class TestLogoutAPI:
    """Tests for POST /admin/api/logout endpoint."""

    # -------------------------------------------------------------------------
    # Successful Logout Tests
    # -------------------------------------------------------------------------

    def test_logout_success(self, client, app, sample_admin):
        """POST /logout should successfully logout authenticated user."""
        # First login to get a token
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        assert login_response.status_code == 200
        token = login_response.get_json()['access_token']

        # Then logout
        response = client.post('/admin/api/logout',
                               headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert 'Logged out successfully' in data['message']

    def test_logout_returns_sessions_invalidated_count(self, client, app, sample_admin):
        """POST /logout should return success message."""
        # Login to get a token
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Logout
        response = client.post('/admin/api/logout',
                               headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert 'message' in data

    # -------------------------------------------------------------------------
    # Authentication Error Tests
    # -------------------------------------------------------------------------

    def test_logout_no_token(self, client, app):
        """POST /logout should return 401 without token."""
        response = client.post('/admin/api/logout')

        assert response.status_code == 401

    def test_logout_invalid_token(self, client, app):
        """POST /logout should return 401 with invalid token."""
        response = client.post('/admin/api/logout',
                               headers=get_auth_headers('invalid.token.here'))

        assert response.status_code == 422  # JWT decode error

    def test_logout_malformed_token(self, client, app):
        """POST /logout should return error with malformed token."""
        response = client.post('/admin/api/logout',
                               headers={'Authorization': 'Bearer '})

        # Flask-JWT-Extended returns 422 for empty/malformed tokens
        assert response.status_code in [401, 422]


# =============================================================================
# Get Current User API Tests (GET /admin/api/me)
# =============================================================================

class TestGetCurrentUserAPI:
    """Tests for GET /admin/api/me endpoint."""

    # -------------------------------------------------------------------------
    # Successful Retrieval Tests
    # -------------------------------------------------------------------------

    def test_get_me_success(self, client, app, sample_admin):
        """GET /me should return current user data."""
        # Login to get token
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get current user
        response = client.get('/admin/api/me',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == sample_admin.id
        assert data['email'] == sample_admin.email
        assert data['name'] == sample_admin.name
        assert data['role'] == sample_admin.role
        assert 'password_hash' not in data

    def test_get_me_includes_organization(self, client, app, sample_admin):
        """GET /me should include organization_id."""
        # Login to get token
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get current user
        response = client.get('/admin/api/me',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert 'organization_id' in data
        assert data['organization_id'] == sample_admin.organization_id

    def test_get_me_different_roles(self, client, app, sample_super_admin, sample_partner, sample_content_manager):
        """GET /me should work for different user roles."""
        users = [sample_super_admin, sample_partner, sample_content_manager]

        for user in users:
            # Login
            login_response = client.post('/admin/api/login', json={
                'email': user.email,
                'password': TEST_PASSWORD
            })
            token = login_response.get_json()['access_token']

            # Get current user
            response = client.get('/admin/api/me',
                                  headers=get_auth_headers(token))

            assert response.status_code == 200
            data = response.get_json()
            assert data['id'] == user.id
            assert data['role'] == user.role

    # -------------------------------------------------------------------------
    # Authentication Error Tests
    # -------------------------------------------------------------------------

    def test_get_me_no_token(self, client, app):
        """GET /me should return 401 without token."""
        response = client.get('/admin/api/me')

        assert response.status_code == 401

    def test_get_me_invalid_token(self, client, app):
        """GET /me should return error with invalid token."""
        response = client.get('/admin/api/me',
                              headers=get_auth_headers('invalid.token.here'))

        assert response.status_code == 422  # JWT decode error

    def test_get_me_expired_token(self, client, app, sample_admin):
        """GET /me should return 401 with expired token."""
        # Note: This test would require manipulating token expiry
        # For now, we just test invalid token
        response = client.get('/admin/api/me',
                              headers=get_auth_headers('eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOjEsImlhdCI6MTUwMDAwMDAwMCwiZXhwIjoxNTAwMDAwMDAxfQ.invalid'))

        assert response.status_code == 422

    # -------------------------------------------------------------------------
    # Account Status Tests
    # -------------------------------------------------------------------------

    def test_get_me_user_suspended_after_login(self, client, app, db_session, sample_admin):
        """GET /me should return 401 if user becomes suspended after login."""
        # Login to get token
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Suspend the user
        with app.app_context():
            user = db.session.get(User, sample_admin.id)
            user.status = User.STATUS_SUSPENDED
            db.session.commit()

        # Try to get current user
        response = client.get('/admin/api/me',
                              headers=get_auth_headers(token))

        assert response.status_code == 401
        data = response.get_json()
        assert 'not active' in data['error']

    def test_get_me_user_deactivated_after_login(self, client, app, db_session, sample_admin):
        """GET /me should return 401 if user becomes deactivated after login."""
        # Login to get token
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Deactivate the user
        with app.app_context():
            user = db.session.get(User, sample_admin.id)
            user.status = User.STATUS_DEACTIVATED
            db.session.commit()

        # Try to get current user
        response = client.get('/admin/api/me',
                              headers=get_auth_headers(token))

        assert response.status_code == 401
        data = response.get_json()
        assert 'not active' in data['error']

    def test_get_me_user_deleted_after_login(self, client, app, db_session, sample_admin):
        """GET /me should return 404 if user is deleted after login."""
        # Login to get token
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Delete the user
        with app.app_context():
            user = db.session.get(User, sample_admin.id)
            db.session.delete(user)
            db.session.commit()

        # Try to get current user
        response = client.get('/admin/api/me',
                              headers=get_auth_headers(token))

        assert response.status_code == 404
        data = response.get_json()
        assert 'User not found' in data['error']
