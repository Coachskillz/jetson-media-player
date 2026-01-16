"""
Integration tests for CMS Users API endpoints.

Tests all user management API routes:
- GET /api/v1/users - List all users
- GET /api/v1/users/<id> - Get user details
- PUT /api/v1/users/<id> - Update user information
- POST /api/v1/users/<id>/approve - Approve pending user
- POST /api/v1/users/<id>/reject - Reject pending user
- POST /api/v1/users/<id>/suspend - Suspend active user
- POST /api/v1/users/<id>/reactivate - Reactivate suspended user
- POST /api/v1/users/<id>/deactivate - Permanently deactivate user
- POST /api/v1/users/<id>/reset-password - Reset user's password
- GET /api/v1/users/<id>/sessions - List user sessions
- DELETE /api/v1/users/<id>/sessions - Revoke all user sessions
- DELETE /api/v1/users/<id>/sessions/<session_id> - Revoke specific session
- GET /api/v1/users/roles - Get available roles

Each test class covers a specific operation with comprehensive
endpoint validation including success cases, error handling,
and permission enforcement.
"""

import pytest
from datetime import datetime, timezone

from cms.models import db, User, UserSession
from cms.tests.conftest import create_test_user, create_test_session


# =============================================================================
# Helper Functions
# =============================================================================

def _get_auth_headers(session):
    """Create authorization headers with session token."""
    return {'Authorization': f'Bearer {session.token}'}


# =============================================================================
# List Users API Tests (GET /api/v1/users)
# =============================================================================

class TestListUsersAPI:
    """Tests for GET /api/v1/users endpoint."""

    # -------------------------------------------------------------------------
    # Successful List Tests
    # -------------------------------------------------------------------------

    def test_list_users_success_as_super_admin(
        self, client, app, db_session, sample_super_admin, sample_admin, sample_content_manager
    ):
        """GET /users should return all users for super admin."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/users',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert 'users' in data
        assert 'count' in data
        assert data['count'] >= 3  # At least super_admin, admin, content_manager

    def test_list_users_admin_only_sees_lower_roles(
        self, client, app, db_session, sample_super_admin, sample_admin, sample_content_manager, sample_viewer
    ):
        """GET /users should only show lower role users for regular admin."""
        session = create_test_session(db_session, sample_admin.id)

        response = client.get(
            '/api/v1/users',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()

        # Admin should not see super_admin or other admins
        for user in data['users']:
            assert user['role'] in ['content_manager', 'viewer']
            assert user['role'] not in ['super_admin', 'admin']

    def test_list_users_filter_by_status(
        self, client, app, db_session, sample_super_admin, sample_pending_user, sample_admin
    ):
        """GET /users?status=X should filter by status."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/users?status=pending',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert all(user['status'] == 'pending' for user in data['users'])

    def test_list_users_filter_by_role(
        self, client, app, db_session, sample_super_admin, sample_admin, sample_content_manager
    ):
        """GET /users?role=X should filter by role."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/users?role=admin',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert all(user['role'] == 'admin' for user in data['users'])

    def test_list_users_filter_by_network(
        self, client, app, db_session, sample_super_admin, sample_admin, sample_network
    ):
        """GET /users?network_id=X should filter by network."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            f'/api/v1/users?network_id={sample_network.id}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert all(user['network_id'] == sample_network.id for user in data['users'])

    def test_list_users_search_by_email(
        self, client, app, db_session, sample_super_admin, sample_admin
    ):
        """GET /users?search=X should search by email."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/users?search=admin@test',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert any('admin@test' in user['email'] for user in data['users'])

    def test_list_users_search_by_name(
        self, client, app, db_session, sample_super_admin, sample_admin
    ):
        """GET /users?search=X should search by name."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/users?search=Test Admin',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert any('Test Admin' in user['name'] for user in data['users'])

    # -------------------------------------------------------------------------
    # Validation Error Tests
    # -------------------------------------------------------------------------

    def test_list_users_invalid_status_filter(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /users?status=invalid should return 400."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/users?status=invalid',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid status' in data['error']

    def test_list_users_invalid_role_filter(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /users?role=invalid should return 400."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/users?role=invalid',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid role' in data['error']

    # -------------------------------------------------------------------------
    # Permission Tests
    # -------------------------------------------------------------------------

    def test_list_users_requires_authentication(self, client, app):
        """GET /users should reject unauthenticated requests."""
        response = client.get('/api/v1/users')

        assert response.status_code == 401
        data = response.get_json()
        assert data['code'] == 'missing_token'

    def test_list_users_requires_admin_role(
        self, client, app, db_session, sample_viewer
    ):
        """GET /users should reject non-admin users."""
        session = create_test_session(db_session, sample_viewer.id)

        response = client.get(
            '/api/v1/users',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 403
        data = response.get_json()
        assert 'Insufficient permissions' in data['error']


# =============================================================================
# Get User API Tests (GET /api/v1/users/<id>)
# =============================================================================

class TestGetUserAPI:
    """Tests for GET /api/v1/users/<id> endpoint."""

    def test_get_user_success(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """GET /users/<id> should return user details."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            f'/api/v1/users/{sample_content_manager.id}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == sample_content_manager.id
        assert data['email'] == sample_content_manager.email
        assert data['name'] == sample_content_manager.name
        assert data['role'] == sample_content_manager.role
        assert 'active_sessions' in data

    def test_get_user_includes_network_info(
        self, client, app, db_session, sample_super_admin, sample_admin, sample_network
    ):
        """GET /users/<id> should include network information."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            f'/api/v1/users/{sample_admin.id}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert 'network' in data
        assert data['network']['id'] == sample_network.id

    def test_get_user_not_found(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /users/<id> should return 404 for non-existent user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/users/non-existent-user-id',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 404
        data = response.get_json()
        assert 'not found' in data['error'].lower()

    def test_get_user_admin_cannot_view_other_admin(
        self, client, app, db_session, sample_admin, sample_network
    ):
        """GET /users/<id> should prevent admin from viewing another admin."""
        # Create another admin
        another_admin = create_test_user(
            db_session,
            email='another_admin@test.com',
            name='Another Admin',
            role='admin',
            network_id=sample_network.id
        )
        session = create_test_session(db_session, sample_admin.id)

        response = client.get(
            f'/api/v1/users/{another_admin.id}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 403
        data = response.get_json()
        assert 'Insufficient permissions' in data['error']

    def test_get_user_admin_can_view_self(
        self, client, app, db_session, sample_admin
    ):
        """GET /users/<id> should allow admin to view their own profile."""
        session = create_test_session(db_session, sample_admin.id)

        response = client.get(
            f'/api/v1/users/{sample_admin.id}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == sample_admin.id

    def test_get_user_requires_authentication(self, client, app, sample_content_manager):
        """GET /users/<id> should reject unauthenticated requests."""
        response = client.get(f'/api/v1/users/{sample_content_manager.id}')

        assert response.status_code == 401


# =============================================================================
# Update User API Tests (PUT /api/v1/users/<id>)
# =============================================================================

class TestUpdateUserAPI:
    """Tests for PUT /api/v1/users/<id> endpoint."""

    def test_update_user_name_success(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """PUT /users/<id> should update user name."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.put(
            f'/api/v1/users/{sample_content_manager.id}',
            headers=_get_auth_headers(session),
            json={'name': 'Updated Name'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'User updated successfully'
        assert data['user']['name'] == 'Updated Name'

    def test_update_user_phone_success(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """PUT /users/<id> should update user phone."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.put(
            f'/api/v1/users/{sample_content_manager.id}',
            headers=_get_auth_headers(session),
            json={'phone': '123-456-7890'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['user']['phone'] == '123-456-7890'

    def test_update_user_role_success(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """PUT /users/<id> should update user role."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.put(
            f'/api/v1/users/{sample_content_manager.id}',
            headers=_get_auth_headers(session),
            json={'role': 'viewer'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['user']['role'] == 'viewer'

    def test_update_user_no_changes(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """PUT /users/<id> should return message when no changes made."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.put(
            f'/api/v1/users/{sample_content_manager.id}',
            headers=_get_auth_headers(session),
            json={'name': sample_content_manager.name}  # Same as current
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'No changes made'

    def test_update_user_not_found(
        self, client, app, db_session, sample_super_admin
    ):
        """PUT /users/<id> should return 404 for non-existent user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.put(
            '/api/v1/users/non-existent-user-id',
            headers=_get_auth_headers(session),
            json={'name': 'Updated Name'}
        )

        assert response.status_code == 404

    def test_update_user_empty_body(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """PUT /users/<id> should reject empty body."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.put(
            f'/api/v1/users/{sample_content_manager.id}',
            headers=_get_auth_headers(session),
            data='',
            content_type='application/json'
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Request body is required' in data['error']

    def test_update_user_invalid_name(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """PUT /users/<id> should reject invalid name."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.put(
            f'/api/v1/users/{sample_content_manager.id}',
            headers=_get_auth_headers(session),
            json={'name': 'x' * 201}  # Too long
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'max 200 characters' in data['error']

    def test_update_user_invalid_role(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """PUT /users/<id> should reject invalid role."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.put(
            f'/api/v1/users/{sample_content_manager.id}',
            headers=_get_auth_headers(session),
            json={'role': 'invalid_role'}
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid role' in data['error']

    def test_update_user_cannot_escalate_role(
        self, client, app, db_session, sample_admin, sample_content_manager
    ):
        """PUT /users/<id> should prevent role escalation."""
        session = create_test_session(db_session, sample_admin.id)

        response = client.put(
            f'/api/v1/users/{sample_content_manager.id}',
            headers=_get_auth_headers(session),
            json={'role': 'admin'}  # Admin cannot assign admin role
        )

        assert response.status_code == 403
        data = response.get_json()
        assert 'Cannot assign role' in data['error']

    def test_update_user_cannot_change_own_role(
        self, client, app, db_session, sample_admin
    ):
        """PUT /users/<id> should prevent users from changing their own role."""
        session = create_test_session(db_session, sample_admin.id)

        response = client.put(
            f'/api/v1/users/{sample_admin.id}',
            headers=_get_auth_headers(session),
            json={'role': 'super_admin'}  # Try to escalate own role
        )

        # Role change should be ignored for self-updates
        assert response.status_code == 200
        data = response.get_json()
        assert data['user']['role'] == 'admin'  # Role unchanged


# =============================================================================
# Approve User API Tests (POST /api/v1/users/<id>/approve)
# =============================================================================

class TestApproveUserAPI:
    """Tests for POST /api/v1/users/<id>/approve endpoint."""

    def test_approve_user_success(
        self, client, app, db_session, sample_super_admin, sample_pending_user
    ):
        """POST /users/<id>/approve should approve pending user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_pending_user.id}/approve',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'User approved successfully'
        assert data['user']['status'] == 'active'
        assert data['user']['approved_by'] == sample_super_admin.id
        assert data['user']['approved_at'] is not None

    def test_approve_user_not_pending(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/approve should reject non-pending user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/approve',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Cannot approve user with status' in data['error']

    def test_approve_user_not_found(
        self, client, app, db_session, sample_super_admin
    ):
        """POST /users/<id>/approve should return 404 for non-existent user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            '/api/v1/users/non-existent-user-id/approve',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 404

    def test_approve_user_admin_cannot_approve_admin(
        self, client, app, db_session, sample_admin, sample_network
    ):
        """POST /users/<id>/approve should prevent admin from approving admin."""
        # Create a pending admin user
        pending_admin = create_test_user(
            db_session,
            email='pending_admin@test.com',
            name='Pending Admin',
            role='admin',
            status='pending',
            network_id=sample_network.id
        )
        session = create_test_session(db_session, sample_admin.id)

        response = client.post(
            f'/api/v1/users/{pending_admin.id}/approve',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 403


# =============================================================================
# Reject User API Tests (POST /api/v1/users/<id>/reject)
# =============================================================================

class TestRejectUserAPI:
    """Tests for POST /api/v1/users/<id>/reject endpoint."""

    def test_reject_user_success(
        self, client, app, db_session, sample_super_admin, sample_pending_user
    ):
        """POST /users/<id>/reject should reject pending user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_pending_user.id}/reject',
            headers=_get_auth_headers(session),
            json={'reason': 'Test rejection reason'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'User rejected successfully'
        assert data['user']['status'] == 'rejected'
        assert data['user']['rejection_reason'] == 'Test rejection reason'

    def test_reject_user_without_reason(
        self, client, app, db_session, sample_super_admin, sample_pending_user
    ):
        """POST /users/<id>/reject should allow rejection without reason."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_pending_user.id}/reject',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['user']['status'] == 'rejected'

    def test_reject_user_not_pending(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/reject should reject non-pending user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/reject',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Cannot reject user with status' in data['error']

    def test_reject_user_reason_too_long(
        self, client, app, db_session, sample_super_admin, sample_pending_user
    ):
        """POST /users/<id>/reject should reject reason > 1000 chars."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_pending_user.id}/reject',
            headers=_get_auth_headers(session),
            json={'reason': 'x' * 1001}
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'max 1000 characters' in data['error']


# =============================================================================
# Suspend User API Tests (POST /api/v1/users/<id>/suspend)
# =============================================================================

class TestSuspendUserAPI:
    """Tests for POST /api/v1/users/<id>/suspend endpoint."""

    def test_suspend_user_success(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/suspend should suspend active user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/suspend',
            headers=_get_auth_headers(session),
            json={'reason': 'Test suspension reason'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'User suspended successfully'
        assert data['user']['status'] == 'suspended'
        assert data['user']['suspended_by'] == sample_super_admin.id
        assert data['user']['suspended_reason'] == 'Test suspension reason'
        assert 'sessions_revoked' in data

    def test_suspend_user_revokes_sessions(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/suspend should revoke all user sessions."""
        # Create a session for the content manager
        user_session = create_test_session(db_session, sample_content_manager.id)
        admin_session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/suspend',
            headers=_get_auth_headers(admin_session),
            json={'reason': 'Test'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['sessions_revoked'] >= 1

        # Verify user's session is deleted
        deleted_session = db_session.get(UserSession, user_session.id)
        assert deleted_session is None

    def test_suspend_user_not_active(
        self, client, app, db_session, sample_super_admin, sample_pending_user
    ):
        """POST /users/<id>/suspend should reject non-active user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_pending_user.id}/suspend',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Cannot suspend user with status' in data['error']

    def test_suspend_user_cannot_suspend_self(
        self, client, app, db_session, sample_super_admin
    ):
        """POST /users/<id>/suspend should prevent self-suspension."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_super_admin.id}/suspend',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 403
        data = response.get_json()
        assert 'yourself' in data['error'].lower()


# =============================================================================
# Reactivate User API Tests (POST /api/v1/users/<id>/reactivate)
# =============================================================================

class TestReactivateUserAPI:
    """Tests for POST /api/v1/users/<id>/reactivate endpoint."""

    def test_reactivate_user_success(
        self, client, app, db_session, sample_super_admin, sample_suspended_user
    ):
        """POST /users/<id>/reactivate should reactivate suspended user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_suspended_user.id}/reactivate',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'User reactivated successfully'
        assert data['user']['status'] == 'active'
        assert data['user']['suspended_at'] is None
        assert data['user']['suspended_by'] is None
        assert data['user']['suspended_reason'] is None

    def test_reactivate_user_not_suspended(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/reactivate should reject non-suspended user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/reactivate',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Cannot reactivate user with status' in data['error']

    def test_reactivate_user_not_found(
        self, client, app, db_session, sample_super_admin
    ):
        """POST /users/<id>/reactivate should return 404 for non-existent user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            '/api/v1/users/non-existent-user-id/reactivate',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 404


# =============================================================================
# Deactivate User API Tests (POST /api/v1/users/<id>/deactivate)
# =============================================================================

class TestDeactivateUserAPI:
    """Tests for POST /api/v1/users/<id>/deactivate endpoint."""

    def test_deactivate_user_success(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/deactivate should permanently deactivate user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/deactivate',
            headers=_get_auth_headers(session),
            json={
                'reason': 'Test deactivation reason',
                'confirm': True
            }
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'User deactivated permanently'
        assert data['user']['status'] == 'deactivated'
        assert data['user']['deactivated_by'] == sample_super_admin.id
        assert data['user']['deactivated_reason'] == 'Test deactivation reason'

    def test_deactivate_user_requires_confirmation(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/deactivate should require confirmation."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/deactivate',
            headers=_get_auth_headers(session),
            json={'reason': 'Test reason'}  # Missing confirm
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Confirmation required' in data['error']

    def test_deactivate_user_requires_reason(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/deactivate should require reason."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/deactivate',
            headers=_get_auth_headers(session),
            json={'confirm': True}  # Missing reason
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'reason is required' in data['error']

    def test_deactivate_user_already_deactivated(
        self, client, app, db_session, sample_super_admin, sample_network
    ):
        """POST /users/<id>/deactivate should reject already deactivated user."""
        # Create a deactivated user
        deactivated_user = create_test_user(
            db_session,
            email='deactivated@test.com',
            name='Deactivated User',
            role='viewer',
            status='deactivated',
            network_id=sample_network.id
        )
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{deactivated_user.id}/deactivate',
            headers=_get_auth_headers(session),
            json={'reason': 'Test', 'confirm': True}
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'already deactivated' in data['error']

    def test_deactivate_user_cannot_deactivate_self(
        self, client, app, db_session, sample_super_admin
    ):
        """POST /users/<id>/deactivate should prevent self-deactivation."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_super_admin.id}/deactivate',
            headers=_get_auth_headers(session),
            json={'reason': 'Test', 'confirm': True}
        )

        assert response.status_code == 403
        data = response.get_json()
        assert 'yourself' in data['error'].lower()


# =============================================================================
# Reset Password API Tests (POST /api/v1/users/<id>/reset-password)
# =============================================================================

class TestResetPasswordAPI:
    """Tests for POST /api/v1/users/<id>/reset-password endpoint."""

    def test_reset_password_success(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/reset-password should reset user's password."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/reset-password',
            headers=_get_auth_headers(session),
            json={'new_password': 'NewSecurePass123!'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert 'Password reset successfully' in data['message']
        assert 'sessions_revoked' in data

    def test_reset_password_sets_must_change_flag(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/reset-password should set must_change_password flag."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/reset-password',
            headers=_get_auth_headers(session),
            json={'new_password': 'NewSecurePass123!'}
        )

        assert response.status_code == 200

        # Verify must_change_password is set
        db_session.refresh(sample_content_manager)
        assert sample_content_manager.must_change_password is True

    def test_reset_password_allows_login_with_new_password(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/reset-password should allow login with new password."""
        admin_session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/reset-password',
            headers=_get_auth_headers(admin_session),
            json={'new_password': 'NewSecurePass123!'}
        )
        assert response.status_code == 200

        # Try login with new password
        response = client.post('/api/v1/auth/login', json={
            'email': sample_content_manager.email,
            'password': 'NewSecurePass123!'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['must_change_password'] is True

    def test_reset_password_missing_new_password(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/reset-password should reject missing new_password."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/reset-password',
            headers=_get_auth_headers(session),
            json={}
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'new_password is required' in data['error']

    def test_reset_password_weak_password(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """POST /users/<id>/reset-password should reject weak passwords."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_content_manager.id}/reset-password',
            headers=_get_auth_headers(session),
            json={'new_password': 'weak'}
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Password must be at least 12 characters' in data['error']

    def test_reset_password_cannot_reset_own_password(
        self, client, app, db_session, sample_super_admin
    ):
        """POST /users/<id>/reset-password should prevent resetting own password."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.post(
            f'/api/v1/users/{sample_super_admin.id}/reset-password',
            headers=_get_auth_headers(session),
            json={'new_password': 'NewSecurePass123!'}
        )

        assert response.status_code == 403
        data = response.get_json()
        assert 'yourself' in data['error'].lower()


# =============================================================================
# List User Sessions API Tests (GET /api/v1/users/<id>/sessions)
# =============================================================================

class TestListUserSessionsAPI:
    """Tests for GET /api/v1/users/<id>/sessions endpoint."""

    def test_list_user_sessions_success(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """GET /users/<id>/sessions should return user's active sessions."""
        # Create a session for the content manager
        user_session = create_test_session(db_session, sample_content_manager.id)
        admin_session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            f'/api/v1/users/{sample_content_manager.id}/sessions',
            headers=_get_auth_headers(admin_session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert 'sessions' in data
        assert 'count' in data
        assert data['count'] >= 1

    def test_list_user_sessions_not_found(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /users/<id>/sessions should return 404 for non-existent user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/users/non-existent-user-id/sessions',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 404


# =============================================================================
# Revoke All User Sessions API Tests (DELETE /api/v1/users/<id>/sessions)
# =============================================================================

class TestRevokeAllSessionsAPI:
    """Tests for DELETE /api/v1/users/<id>/sessions endpoint."""

    def test_revoke_all_sessions_success(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """DELETE /users/<id>/sessions should revoke all user sessions."""
        # Create sessions for the content manager
        user_session_1 = create_test_session(
            db_session, sample_content_manager.id, ip_address='192.168.1.1'
        )
        user_session_2 = create_test_session(
            db_session, sample_content_manager.id, ip_address='192.168.1.2'
        )
        admin_session = create_test_session(db_session, sample_super_admin.id)

        response = client.delete(
            f'/api/v1/users/{sample_content_manager.id}/sessions',
            headers=_get_auth_headers(admin_session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'All sessions revoked successfully'
        assert data['sessions_revoked'] >= 2

    def test_revoke_all_sessions_not_found(
        self, client, app, db_session, sample_super_admin
    ):
        """DELETE /users/<id>/sessions should return 404 for non-existent user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.delete(
            '/api/v1/users/non-existent-user-id/sessions',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 404


# =============================================================================
# Revoke Specific Session API Tests (DELETE /api/v1/users/<id>/sessions/<session_id>)
# =============================================================================

class TestRevokeSpecificSessionAPI:
    """Tests for DELETE /api/v1/users/<id>/sessions/<session_id> endpoint."""

    def test_revoke_specific_session_success(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """DELETE /users/<id>/sessions/<session_id> should revoke specific session."""
        # Create a session for the content manager
        user_session = create_test_session(db_session, sample_content_manager.id)
        admin_session = create_test_session(db_session, sample_super_admin.id)

        response = client.delete(
            f'/api/v1/users/{sample_content_manager.id}/sessions/{user_session.id}',
            headers=_get_auth_headers(admin_session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Session revoked successfully'

        # Verify session is deleted
        deleted_session = db_session.get(UserSession, user_session.id)
        assert deleted_session is None

    def test_revoke_specific_session_not_found(
        self, client, app, db_session, sample_super_admin, sample_content_manager
    ):
        """DELETE /users/<id>/sessions/<session_id> should return 404 for non-existent session."""
        admin_session = create_test_session(db_session, sample_super_admin.id)

        response = client.delete(
            f'/api/v1/users/{sample_content_manager.id}/sessions/non-existent-session-id',
            headers=_get_auth_headers(admin_session)
        )

        assert response.status_code == 404

    def test_revoke_specific_session_user_not_found(
        self, client, app, db_session, sample_super_admin
    ):
        """DELETE /users/<id>/sessions/<session_id> should return 404 for non-existent user."""
        admin_session = create_test_session(db_session, sample_super_admin.id)

        response = client.delete(
            '/api/v1/users/non-existent-user-id/sessions/some-session-id',
            headers=_get_auth_headers(admin_session)
        )

        assert response.status_code == 404


# =============================================================================
# Get Available Roles API Tests (GET /api/v1/users/roles)
# =============================================================================

class TestGetRolesAPI:
    """Tests for GET /api/v1/users/roles endpoint."""

    def test_get_roles_as_super_admin(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /users/roles should return all lower roles for super admin."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/users/roles',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert 'roles' in data
        assert 'current_role' in data
        assert data['current_role'] == 'super_admin'

        # Super admin can assign admin, content_manager, viewer
        role_values = [r['value'] for r in data['roles']]
        assert 'admin' in role_values
        assert 'content_manager' in role_values
        assert 'viewer' in role_values
        # Cannot assign super_admin
        assert 'super_admin' not in role_values

    def test_get_roles_as_admin(
        self, client, app, db_session, sample_admin
    ):
        """GET /users/roles should return only lower roles for admin."""
        session = create_test_session(db_session, sample_admin.id)

        response = client.get(
            '/api/v1/users/roles',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['current_role'] == 'admin'

        # Admin can assign content_manager, viewer
        role_values = [r['value'] for r in data['roles']]
        assert 'content_manager' in role_values
        assert 'viewer' in role_values
        # Cannot assign admin or super_admin
        assert 'admin' not in role_values
        assert 'super_admin' not in role_values

    def test_get_roles_requires_authentication(self, client, app):
        """GET /users/roles should reject unauthenticated requests."""
        response = client.get('/api/v1/users/roles')

        assert response.status_code == 401

    def test_get_roles_requires_admin_role(
        self, client, app, db_session, sample_viewer
    ):
        """GET /users/roles should reject non-admin users."""
        session = create_test_session(db_session, sample_viewer.id)

        response = client.get(
            '/api/v1/users/roles',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 403
