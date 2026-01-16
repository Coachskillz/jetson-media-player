"""
Integration tests for CMS Permission System.

Tests all permission utilities and role hierarchy:
- Role hierarchy constants and levels
- has_permission() function for role level checks
- can_manage_role() function for role escalation prevention
- can_manage_user() function for user management permissions
- require_role() decorator for route protection
- Helper functions for API endpoints

Each test class covers a specific operation with comprehensive
endpoint validation including success cases and error handling.
"""

import pytest

from flask import g

from cms.models import db, User
from cms.utils.permissions import (
    ROLE_HIERARCHY,
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN,
    ROLE_CONTENT_MANAGER,
    ROLE_VIEWER,
    VALID_ROLES,
    get_role_level,
    has_permission,
    has_exact_role,
    is_super_admin,
    is_admin_or_higher,
    can_manage_users,
    can_manage_role,
    can_manage_user,
    require_role,
    require_super_admin,
    require_admin,
    require_content_manager,
    check_can_create_user_with_role,
    check_can_manage_user,
)


# =============================================================================
# Role Hierarchy Constants Tests
# =============================================================================

class TestRoleHierarchyConstants:
    """Tests for role hierarchy constants and validation."""

    def test_role_hierarchy_has_all_roles(self):
        """ROLE_HIERARCHY should contain all four roles."""
        assert 'super_admin' in ROLE_HIERARCHY
        assert 'admin' in ROLE_HIERARCHY
        assert 'content_manager' in ROLE_HIERARCHY
        assert 'viewer' in ROLE_HIERARCHY
        assert len(ROLE_HIERARCHY) == 4

    def test_role_hierarchy_levels_are_ordered(self):
        """ROLE_HIERARCHY should have correct ordering (super_admin highest)."""
        assert ROLE_HIERARCHY['super_admin'] > ROLE_HIERARCHY['admin']
        assert ROLE_HIERARCHY['admin'] > ROLE_HIERARCHY['content_manager']
        assert ROLE_HIERARCHY['content_manager'] > ROLE_HIERARCHY['viewer']

    def test_role_hierarchy_numeric_values(self):
        """ROLE_HIERARCHY should have expected numeric levels."""
        assert ROLE_HIERARCHY['super_admin'] == 4
        assert ROLE_HIERARCHY['admin'] == 3
        assert ROLE_HIERARCHY['content_manager'] == 2
        assert ROLE_HIERARCHY['viewer'] == 1

    def test_role_constants_match_hierarchy(self):
        """Role constants should match hierarchy keys."""
        assert ROLE_SUPER_ADMIN == 'super_admin'
        assert ROLE_ADMIN == 'admin'
        assert ROLE_CONTENT_MANAGER == 'content_manager'
        assert ROLE_VIEWER == 'viewer'

    def test_valid_roles_list(self):
        """VALID_ROLES should contain all hierarchy keys."""
        assert set(VALID_ROLES) == set(ROLE_HIERARCHY.keys())


# =============================================================================
# get_role_level() Tests
# =============================================================================

class TestGetRoleLevel:
    """Tests for get_role_level() function."""

    def test_get_role_level_super_admin(self):
        """get_role_level should return 4 for super_admin."""
        assert get_role_level('super_admin') == 4

    def test_get_role_level_admin(self):
        """get_role_level should return 3 for admin."""
        assert get_role_level('admin') == 3

    def test_get_role_level_content_manager(self):
        """get_role_level should return 2 for content_manager."""
        assert get_role_level('content_manager') == 2

    def test_get_role_level_viewer(self):
        """get_role_level should return 1 for viewer."""
        assert get_role_level('viewer') == 1

    def test_get_role_level_invalid_role_returns_zero(self):
        """get_role_level should return 0 for invalid roles."""
        assert get_role_level('invalid') == 0
        assert get_role_level('') == 0
        assert get_role_level('ADMIN') == 0  # Case sensitive

    def test_get_role_level_none_returns_zero(self):
        """get_role_level should return 0 for None."""
        assert get_role_level(None) == 0


# =============================================================================
# has_permission() Tests
# =============================================================================

class TestHasPermission:
    """Tests for has_permission() function."""

    def test_has_permission_super_admin_can_access_all(
        self, app, sample_super_admin
    ):
        """Super admin should have permission for any minimum role."""
        assert has_permission(sample_super_admin, 'viewer') is True
        assert has_permission(sample_super_admin, 'content_manager') is True
        assert has_permission(sample_super_admin, 'admin') is True
        assert has_permission(sample_super_admin, 'super_admin') is True

    def test_has_permission_admin_can_access_admin_and_below(
        self, app, sample_admin
    ):
        """Admin should have permission for admin and below."""
        assert has_permission(sample_admin, 'viewer') is True
        assert has_permission(sample_admin, 'content_manager') is True
        assert has_permission(sample_admin, 'admin') is True
        assert has_permission(sample_admin, 'super_admin') is False

    def test_has_permission_content_manager_limited_access(
        self, app, sample_content_manager
    ):
        """Content manager should have permission for content_manager and below."""
        assert has_permission(sample_content_manager, 'viewer') is True
        assert has_permission(sample_content_manager, 'content_manager') is True
        assert has_permission(sample_content_manager, 'admin') is False
        assert has_permission(sample_content_manager, 'super_admin') is False

    def test_has_permission_viewer_minimum_access(self, app, sample_viewer):
        """Viewer should only have permission for viewer."""
        assert has_permission(sample_viewer, 'viewer') is True
        assert has_permission(sample_viewer, 'content_manager') is False
        assert has_permission(sample_viewer, 'admin') is False
        assert has_permission(sample_viewer, 'super_admin') is False

    def test_has_permission_none_user_returns_false(self, app):
        """has_permission should return False for None user."""
        assert has_permission(None, 'viewer') is False
        assert has_permission(None, 'admin') is False

    def test_has_permission_invalid_minimum_role(self, app, sample_super_admin):
        """has_permission should return True when minimum role is invalid (level 0)."""
        # Invalid role has level 0, so any user should have permission
        assert has_permission(sample_super_admin, 'invalid') is True


# =============================================================================
# has_exact_role() Tests
# =============================================================================

class TestHasExactRole:
    """Tests for has_exact_role() function."""

    def test_has_exact_role_matches(self, app, sample_super_admin, sample_admin):
        """has_exact_role should return True when role matches exactly."""
        assert has_exact_role(sample_super_admin, 'super_admin') is True
        assert has_exact_role(sample_admin, 'admin') is True

    def test_has_exact_role_no_match(self, app, sample_super_admin, sample_admin):
        """has_exact_role should return False when role doesn't match."""
        assert has_exact_role(sample_super_admin, 'admin') is False
        assert has_exact_role(sample_admin, 'super_admin') is False

    def test_has_exact_role_none_user(self, app):
        """has_exact_role should return False for None user."""
        assert has_exact_role(None, 'admin') is False


# =============================================================================
# is_super_admin() Tests
# =============================================================================

class TestIsSuperAdmin:
    """Tests for is_super_admin() function."""

    def test_is_super_admin_true(self, app, sample_super_admin):
        """is_super_admin should return True for super_admin."""
        assert is_super_admin(sample_super_admin) is True

    def test_is_super_admin_false_for_admin(self, app, sample_admin):
        """is_super_admin should return False for admin."""
        assert is_super_admin(sample_admin) is False

    def test_is_super_admin_false_for_content_manager(
        self, app, sample_content_manager
    ):
        """is_super_admin should return False for content_manager."""
        assert is_super_admin(sample_content_manager) is False

    def test_is_super_admin_false_for_viewer(self, app, sample_viewer):
        """is_super_admin should return False for viewer."""
        assert is_super_admin(sample_viewer) is False

    def test_is_super_admin_none_user(self, app):
        """is_super_admin should return False for None user."""
        assert is_super_admin(None) is False


# =============================================================================
# is_admin_or_higher() Tests
# =============================================================================

class TestIsAdminOrHigher:
    """Tests for is_admin_or_higher() function."""

    def test_is_admin_or_higher_super_admin(self, app, sample_super_admin):
        """is_admin_or_higher should return True for super_admin."""
        assert is_admin_or_higher(sample_super_admin) is True

    def test_is_admin_or_higher_admin(self, app, sample_admin):
        """is_admin_or_higher should return True for admin."""
        assert is_admin_or_higher(sample_admin) is True

    def test_is_admin_or_higher_content_manager(self, app, sample_content_manager):
        """is_admin_or_higher should return False for content_manager."""
        assert is_admin_or_higher(sample_content_manager) is False

    def test_is_admin_or_higher_viewer(self, app, sample_viewer):
        """is_admin_or_higher should return False for viewer."""
        assert is_admin_or_higher(sample_viewer) is False

    def test_is_admin_or_higher_none_user(self, app):
        """is_admin_or_higher should return False for None user."""
        assert is_admin_or_higher(None) is False


# =============================================================================
# can_manage_users() Tests
# =============================================================================

class TestCanManageUsers:
    """Tests for can_manage_users() function."""

    def test_can_manage_users_super_admin(self, app, sample_super_admin):
        """can_manage_users should return True for super_admin."""
        assert can_manage_users(sample_super_admin) is True

    def test_can_manage_users_admin(self, app, sample_admin):
        """can_manage_users should return True for admin."""
        assert can_manage_users(sample_admin) is True

    def test_can_manage_users_content_manager(self, app, sample_content_manager):
        """can_manage_users should return False for content_manager."""
        assert can_manage_users(sample_content_manager) is False

    def test_can_manage_users_viewer(self, app, sample_viewer):
        """can_manage_users should return False for viewer."""
        assert can_manage_users(sample_viewer) is False


# =============================================================================
# can_manage_role() Tests
# =============================================================================

class TestCanManageRole:
    """Tests for can_manage_role() function - role escalation prevention."""

    # -------------------------------------------------------------------------
    # Super Admin Tests
    # -------------------------------------------------------------------------

    def test_super_admin_can_manage_admin(self, app, sample_super_admin):
        """Super admin should be able to manage admin role."""
        assert can_manage_role(sample_super_admin, 'admin') is True

    def test_super_admin_can_manage_content_manager(self, app, sample_super_admin):
        """Super admin should be able to manage content_manager role."""
        assert can_manage_role(sample_super_admin, 'content_manager') is True

    def test_super_admin_can_manage_viewer(self, app, sample_super_admin):
        """Super admin should be able to manage viewer role."""
        assert can_manage_role(sample_super_admin, 'viewer') is True

    def test_super_admin_cannot_manage_super_admin(self, app, sample_super_admin):
        """Super admin cannot manage equal-level super_admin role."""
        assert can_manage_role(sample_super_admin, 'super_admin') is False

    # -------------------------------------------------------------------------
    # Admin Tests
    # -------------------------------------------------------------------------

    def test_admin_can_manage_content_manager(self, app, sample_admin):
        """Admin should be able to manage content_manager role."""
        assert can_manage_role(sample_admin, 'content_manager') is True

    def test_admin_can_manage_viewer(self, app, sample_admin):
        """Admin should be able to manage viewer role."""
        assert can_manage_role(sample_admin, 'viewer') is True

    def test_admin_cannot_manage_admin(self, app, sample_admin):
        """Admin cannot manage equal-level admin role."""
        assert can_manage_role(sample_admin, 'admin') is False

    def test_admin_cannot_manage_super_admin(self, app, sample_admin):
        """Admin cannot manage higher-level super_admin role."""
        assert can_manage_role(sample_admin, 'super_admin') is False

    # -------------------------------------------------------------------------
    # Content Manager Tests
    # -------------------------------------------------------------------------

    def test_content_manager_can_manage_viewer(self, app, sample_content_manager):
        """Content manager should be able to manage viewer role."""
        assert can_manage_role(sample_content_manager, 'viewer') is True

    def test_content_manager_cannot_manage_content_manager(
        self, app, sample_content_manager
    ):
        """Content manager cannot manage equal-level content_manager role."""
        assert can_manage_role(sample_content_manager, 'content_manager') is False

    def test_content_manager_cannot_manage_admin(self, app, sample_content_manager):
        """Content manager cannot manage higher-level admin role."""
        assert can_manage_role(sample_content_manager, 'admin') is False

    # -------------------------------------------------------------------------
    # Viewer Tests
    # -------------------------------------------------------------------------

    def test_viewer_cannot_manage_any_role(self, app, sample_viewer):
        """Viewer should not be able to manage any role."""
        assert can_manage_role(sample_viewer, 'viewer') is False
        assert can_manage_role(sample_viewer, 'content_manager') is False
        assert can_manage_role(sample_viewer, 'admin') is False
        assert can_manage_role(sample_viewer, 'super_admin') is False

    # -------------------------------------------------------------------------
    # Edge Cases
    # -------------------------------------------------------------------------

    def test_can_manage_role_none_manager(self, app):
        """can_manage_role should return False for None manager."""
        assert can_manage_role(None, 'viewer') is False

    def test_can_manage_role_invalid_target(self, app, sample_super_admin):
        """can_manage_role should return True for invalid target role (level 0)."""
        # Invalid role has level 0, so any valid user should be able to manage it
        assert can_manage_role(sample_super_admin, 'invalid') is True


# =============================================================================
# can_manage_user() Tests
# =============================================================================

class TestCanManageUser:
    """Tests for can_manage_user() function - user management permissions."""

    # -------------------------------------------------------------------------
    # Super Admin Management Tests
    # -------------------------------------------------------------------------

    def test_super_admin_can_manage_admin(
        self, app, sample_super_admin, sample_admin
    ):
        """Super admin should be able to manage admin user."""
        assert can_manage_user(sample_super_admin, sample_admin) is True

    def test_super_admin_can_manage_content_manager(
        self, app, sample_super_admin, sample_content_manager
    ):
        """Super admin should be able to manage content_manager user."""
        assert can_manage_user(sample_super_admin, sample_content_manager) is True

    def test_super_admin_can_manage_viewer(
        self, app, sample_super_admin, sample_viewer
    ):
        """Super admin should be able to manage viewer user."""
        assert can_manage_user(sample_super_admin, sample_viewer) is True

    def test_super_admin_cannot_manage_self(self, app, sample_super_admin):
        """Super admin should not be able to manage themselves."""
        assert can_manage_user(sample_super_admin, sample_super_admin) is False

    # -------------------------------------------------------------------------
    # Admin Management Tests
    # -------------------------------------------------------------------------

    def test_admin_can_manage_content_manager(
        self, app, sample_admin, sample_content_manager
    ):
        """Admin should be able to manage content_manager user."""
        assert can_manage_user(sample_admin, sample_content_manager) is True

    def test_admin_can_manage_viewer(self, app, sample_admin, sample_viewer):
        """Admin should be able to manage viewer user."""
        assert can_manage_user(sample_admin, sample_viewer) is True

    def test_admin_cannot_manage_admin(self, app, db_session, sample_network):
        """Admin cannot manage another admin user (mutual exclusion)."""
        # Create two admin users
        admin1 = User(
            email='admin1@test.com',
            name='Admin One',
            role='admin',
            status='active',
            network_id=sample_network.id
        )
        admin1.set_password('TestPassword123!')
        db_session.add(admin1)

        admin2 = User(
            email='admin2@test.com',
            name='Admin Two',
            role='admin',
            status='active',
            network_id=sample_network.id
        )
        admin2.set_password('TestPassword123!')
        db_session.add(admin2)
        db_session.commit()

        assert can_manage_user(admin1, admin2) is False
        assert can_manage_user(admin2, admin1) is False

    def test_admin_cannot_manage_super_admin(
        self, app, sample_admin, sample_super_admin
    ):
        """Admin cannot manage super_admin user."""
        assert can_manage_user(sample_admin, sample_super_admin) is False

    def test_admin_cannot_manage_self(self, app, sample_admin):
        """Admin should not be able to manage themselves."""
        assert can_manage_user(sample_admin, sample_admin) is False

    # -------------------------------------------------------------------------
    # Content Manager Management Tests
    # -------------------------------------------------------------------------

    def test_content_manager_can_manage_viewer(
        self, app, sample_content_manager, sample_viewer
    ):
        """Content manager should be able to manage viewer user."""
        assert can_manage_user(sample_content_manager, sample_viewer) is True

    def test_content_manager_cannot_manage_content_manager(
        self, app, db_session, sample_network
    ):
        """Content manager cannot manage another content_manager user."""
        cm1 = User(
            email='cm1@test.com',
            name='Content Manager One',
            role='content_manager',
            status='active',
            network_id=sample_network.id
        )
        cm1.set_password('TestPassword123!')
        db_session.add(cm1)

        cm2 = User(
            email='cm2@test.com',
            name='Content Manager Two',
            role='content_manager',
            status='active',
            network_id=sample_network.id
        )
        cm2.set_password('TestPassword123!')
        db_session.add(cm2)
        db_session.commit()

        assert can_manage_user(cm1, cm2) is False

    def test_content_manager_cannot_manage_admin(
        self, app, sample_content_manager, sample_admin
    ):
        """Content manager cannot manage admin user."""
        assert can_manage_user(sample_content_manager, sample_admin) is False

    # -------------------------------------------------------------------------
    # Viewer Management Tests
    # -------------------------------------------------------------------------

    def test_viewer_cannot_manage_any_user(
        self, app, sample_viewer, sample_content_manager, sample_admin
    ):
        """Viewer should not be able to manage any user."""
        assert can_manage_user(sample_viewer, sample_content_manager) is False
        assert can_manage_user(sample_viewer, sample_admin) is False

    # -------------------------------------------------------------------------
    # Edge Cases
    # -------------------------------------------------------------------------

    def test_can_manage_user_none_manager(self, app, sample_admin):
        """can_manage_user should return False for None manager."""
        assert can_manage_user(None, sample_admin) is False

    def test_can_manage_user_none_target(self, app, sample_admin):
        """can_manage_user should return False for None target."""
        assert can_manage_user(sample_admin, None) is False

    def test_can_manage_user_both_none(self, app):
        """can_manage_user should return False when both are None."""
        assert can_manage_user(None, None) is False


# =============================================================================
# check_can_create_user_with_role() Tests
# =============================================================================

class TestCheckCanCreateUserWithRole:
    """Tests for check_can_create_user_with_role() API helper function."""

    def test_super_admin_can_create_admin(self, app, sample_super_admin):
        """Super admin should be allowed to create admin user."""
        allowed, error = check_can_create_user_with_role(
            sample_super_admin, 'admin'
        )
        assert allowed is True
        assert error is None

    def test_admin_can_create_content_manager(self, app, sample_admin):
        """Admin should be allowed to create content_manager user."""
        allowed, error = check_can_create_user_with_role(
            sample_admin, 'content_manager'
        )
        assert allowed is True
        assert error is None

    def test_admin_cannot_create_admin(self, app, sample_admin):
        """Admin should not be allowed to create admin user."""
        allowed, error = check_can_create_user_with_role(sample_admin, 'admin')
        assert allowed is False
        assert 'Cannot create users with role' in error

    def test_admin_cannot_create_super_admin(self, app, sample_admin):
        """Admin should not be allowed to create super_admin user."""
        allowed, error = check_can_create_user_with_role(
            sample_admin, 'super_admin'
        )
        assert allowed is False
        assert 'Cannot create users with role' in error

    def test_invalid_role_returns_error(self, app, sample_super_admin):
        """Invalid role should return error."""
        allowed, error = check_can_create_user_with_role(
            sample_super_admin, 'invalid_role'
        )
        assert allowed is False
        assert 'Invalid role' in error

    def test_none_manager_returns_error(self, app):
        """None manager should return authentication error."""
        allowed, error = check_can_create_user_with_role(None, 'viewer')
        assert allowed is False
        assert 'Authentication required' in error


# =============================================================================
# check_can_manage_user() Tests
# =============================================================================

class TestCheckCanManageUser:
    """Tests for check_can_manage_user() API helper function."""

    def test_super_admin_can_manage_admin(
        self, app, sample_super_admin, sample_admin
    ):
        """Super admin should be allowed to manage admin."""
        allowed, error = check_can_manage_user(
            sample_super_admin, sample_admin, 'suspend'
        )
        assert allowed is True
        assert error is None

    def test_cannot_manage_self(self, app, sample_admin):
        """Should not be allowed to manage self."""
        allowed, error = check_can_manage_user(
            sample_admin, sample_admin, 'deactivate'
        )
        assert allowed is False
        assert 'Cannot deactivate yourself' in error

    def test_admin_cannot_manage_other_admin(
        self, app, db_session, sample_network
    ):
        """Admin cannot manage another admin."""
        admin1 = User(
            email='admin_a@test.com',
            name='Admin A',
            role='admin',
            status='active',
            network_id=sample_network.id
        )
        admin1.set_password('TestPassword123!')
        db_session.add(admin1)

        admin2 = User(
            email='admin_b@test.com',
            name='Admin B',
            role='admin',
            status='active',
            network_id=sample_network.id
        )
        admin2.set_password('TestPassword123!')
        db_session.add(admin2)
        db_session.commit()

        allowed, error = check_can_manage_user(admin1, admin2, 'suspend')
        assert allowed is False
        assert 'Insufficient permissions' in error

    def test_none_manager_returns_error(self, app, sample_admin):
        """None manager should return authentication error."""
        allowed, error = check_can_manage_user(None, sample_admin, 'update')
        assert allowed is False
        assert 'Authentication required' in error

    def test_none_target_returns_error(self, app, sample_admin):
        """None target should return not found error."""
        allowed, error = check_can_manage_user(sample_admin, None, 'update')
        assert allowed is False
        assert 'User not found' in error


# =============================================================================
# require_role() Decorator Tests
# =============================================================================

class TestRequireRoleDecorator:
    """Tests for require_role() decorator and shorthand decorators."""

    def test_require_role_allows_sufficient_permission(
        self, app, sample_admin, client
    ):
        """require_role should allow users with sufficient permission."""
        # Create a test route with require_role
        from flask import Blueprint, jsonify
        from cms.utils.auth import login_required

        test_bp = Blueprint('test_require_role', __name__)

        @test_bp.route('/test-admin')
        @login_required
        @require_role('admin')
        def admin_only():
            return jsonify({'message': 'success'})

        app.register_blueprint(test_bp, url_prefix='/test')

        # Simulate login by setting session token
        from cms.models import UserSession
        session = UserSession.create_session(
            user_id=sample_admin.id,
            ip_address='127.0.0.1',
            user_agent='Test'
        )
        with app.app_context():
            db.session.add(session)
            db.session.commit()
            token = session.token

        response = client.get(
            '/test/test-admin',
            headers={'Authorization': f'Bearer {token}'}
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'success'

    def test_require_role_blocks_insufficient_permission(
        self, app, sample_viewer, client
    ):
        """require_role should block users with insufficient permission."""
        from flask import Blueprint, jsonify
        from cms.utils.auth import login_required

        test_bp = Blueprint('test_require_role_block', __name__)

        @test_bp.route('/test-admin-block')
        @login_required
        @require_role('admin')
        def admin_only_block():
            return jsonify({'message': 'success'})

        app.register_blueprint(test_bp, url_prefix='/test')

        # Simulate login with viewer
        from cms.models import UserSession
        session = UserSession.create_session(
            user_id=sample_viewer.id,
            ip_address='127.0.0.1',
            user_agent='Test'
        )
        with app.app_context():
            db.session.add(session)
            db.session.commit()
            token = session.token

        response = client.get(
            '/test/test-admin-block',
            headers={'Authorization': f'Bearer {token}'}
        )
        assert response.status_code == 403
        data = response.get_json()
        assert data['error'] == 'Insufficient permissions'
        assert data['code'] == 'forbidden'
        assert data['required_role'] == 'admin'
        assert data['current_role'] == 'viewer'

    def test_require_role_without_authentication(self, app, client):
        """require_role should return 401 when not authenticated."""
        from flask import Blueprint, jsonify
        from cms.utils.auth import login_required

        test_bp = Blueprint('test_require_role_noauth', __name__)

        @test_bp.route('/test-noauth')
        @login_required
        @require_role('admin')
        def admin_noauth():
            return jsonify({'message': 'success'})

        app.register_blueprint(test_bp, url_prefix='/test')

        response = client.get('/test/test-noauth')
        assert response.status_code == 401


# =============================================================================
# Role Hierarchy Edge Cases Tests
# =============================================================================

class TestRoleHierarchyEdgeCases:
    """Tests for edge cases in role hierarchy enforcement."""

    def test_super_admin_manages_another_super_admin_user(
        self, app, db_session
    ):
        """Super admin cannot manage another super_admin user."""
        # Create two super admins
        sa1 = User(
            email='superadmin1@test.com',
            name='Super Admin One',
            role='super_admin',
            status='active',
            network_id=None
        )
        sa1.set_password('TestPassword123!')
        db_session.add(sa1)

        sa2 = User(
            email='superadmin2@test.com',
            name='Super Admin Two',
            role='super_admin',
            status='active',
            network_id=None
        )
        sa2.set_password('TestPassword123!')
        db_session.add(sa2)
        db_session.commit()

        # Super admins cannot manage each other
        assert can_manage_user(sa1, sa2) is False
        assert can_manage_user(sa2, sa1) is False

    def test_user_with_invalid_role_has_no_permissions(
        self, app, db_session, sample_network
    ):
        """User with invalid role should have no management permissions."""
        # Create a user with invalid role (should not happen in practice)
        invalid_user = User(
            email='invalid_role@test.com',
            name='Invalid Role User',
            role='invalid_role',
            status='active',
            network_id=sample_network.id
        )
        invalid_user.set_password('TestPassword123!')
        db_session.add(invalid_user)
        db_session.commit()

        # Invalid role user should not be able to manage anyone
        assert can_manage_role(invalid_user, 'viewer') is False
        assert has_permission(invalid_user, 'viewer') is False

    def test_pending_user_permissions(self, app, sample_pending_user):
        """Pending users still have role-based permissions (but can't login)."""
        # The permission functions only check role, not status
        # Status is checked by authentication, not authorization
        assert has_permission(sample_pending_user, 'content_manager') is True
        assert has_permission(sample_pending_user, 'admin') is False

    def test_suspended_user_permissions(self, app, sample_suspended_user):
        """Suspended users still have role-based permissions (but can't login)."""
        # The permission functions only check role, not status
        assert has_permission(sample_suspended_user, 'content_manager') is True
        assert has_permission(sample_suspended_user, 'admin') is False


# =============================================================================
# User Model Permission Methods Tests
# =============================================================================

class TestUserModelPermissionMethods:
    """Tests for permission methods on the User model itself."""

    def test_user_get_role_level(self, app, sample_admin):
        """User.get_role_level() should return correct level."""
        assert sample_admin.get_role_level() == 3

    def test_user_can_manage_role(self, app, sample_admin):
        """User.can_manage_role() should work correctly."""
        assert sample_admin.can_manage_role('content_manager') is True
        assert sample_admin.can_manage_role('admin') is False

    def test_user_can_manage_user(
        self, app, sample_admin, sample_content_manager
    ):
        """User.can_manage_user() should work correctly."""
        assert sample_admin.can_manage_user(sample_content_manager) is True
        assert sample_admin.can_manage_user(sample_admin) is False  # Self
