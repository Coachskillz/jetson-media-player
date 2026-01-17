"""
Unit tests for ApprovalService in Content Catalog service.

Tests ApprovalService functionality including:
- Role hierarchy configuration and enforcement
- User approval workflow (can_approve_user, approve_user, reject_user)
- Self-approval prevention
- Circular approval detection
- Content approval workflow (can_approve_content, approve_content, reject_content)
- Content publishing workflow (can_publish_content, publish_content)
- Approval request creation and management
"""

from datetime import datetime, timedelta, timezone

import pytest

from content_catalog.services.approval_service import ApprovalService
from content_catalog.models import (
    db,
    User,
    UserApprovalRequest,
    ContentAsset,
    ContentApprovalRequest,
)


# =============================================================================
# Role Hierarchy Configuration Tests
# =============================================================================

class TestApprovalServiceRoleHierarchy:
    """Tests for ApprovalService role hierarchy configuration."""

    def test_role_hierarchy_includes_all_roles(self, app, db_session):
        """ROLE_HIERARCHY should include all valid user roles."""
        expected_roles = [
            User.ROLE_SUPER_ADMIN,
            User.ROLE_ADMIN,
            User.ROLE_CONTENT_MANAGER,
            User.ROLE_PARTNER,
            User.ROLE_ADVERTISER,
            User.ROLE_VIEWER
        ]

        for role in expected_roles:
            assert role in ApprovalService.ROLE_HIERARCHY

    def test_role_hierarchy_super_admin_is_highest(self, app, db_session):
        """Super Admin should have the highest privilege (level 0)."""
        assert ApprovalService.ROLE_HIERARCHY[User.ROLE_SUPER_ADMIN] == 0

    def test_role_hierarchy_viewer_is_lowest(self, app, db_session):
        """Viewer should have the lowest privilege (level 5)."""
        assert ApprovalService.ROLE_HIERARCHY[User.ROLE_VIEWER] == 5

    def test_role_hierarchy_order_is_correct(self, app, db_session):
        """Role hierarchy levels should follow expected order."""
        hierarchy = ApprovalService.ROLE_HIERARCHY

        assert hierarchy[User.ROLE_SUPER_ADMIN] < hierarchy[User.ROLE_ADMIN]
        assert hierarchy[User.ROLE_ADMIN] < hierarchy[User.ROLE_CONTENT_MANAGER]
        assert hierarchy[User.ROLE_CONTENT_MANAGER] < hierarchy[User.ROLE_PARTNER]
        assert hierarchy[User.ROLE_PARTNER] < hierarchy[User.ROLE_ADVERTISER]
        assert hierarchy[User.ROLE_ADVERTISER] < hierarchy[User.ROLE_VIEWER]


# =============================================================================
# get_role_level Tests
# =============================================================================

class TestApprovalServiceGetRoleLevel:
    """Tests for ApprovalService.get_role_level method."""

    def test_get_role_level_returns_correct_level_for_super_admin(self, app, db_session):
        """get_role_level should return 0 for super_admin."""
        level = ApprovalService.get_role_level(User.ROLE_SUPER_ADMIN)
        assert level == 0

    def test_get_role_level_returns_correct_level_for_admin(self, app, db_session):
        """get_role_level should return 1 for admin."""
        level = ApprovalService.get_role_level(User.ROLE_ADMIN)
        assert level == 1

    def test_get_role_level_returns_correct_level_for_content_manager(self, app, db_session):
        """get_role_level should return 2 for content_manager."""
        level = ApprovalService.get_role_level(User.ROLE_CONTENT_MANAGER)
        assert level == 2

    def test_get_role_level_returns_correct_level_for_partner(self, app, db_session):
        """get_role_level should return 3 for partner."""
        level = ApprovalService.get_role_level(User.ROLE_PARTNER)
        assert level == 3

    def test_get_role_level_returns_correct_level_for_advertiser(self, app, db_session):
        """get_role_level should return 4 for advertiser."""
        level = ApprovalService.get_role_level(User.ROLE_ADVERTISER)
        assert level == 4

    def test_get_role_level_returns_correct_level_for_viewer(self, app, db_session):
        """get_role_level should return 5 for viewer."""
        level = ApprovalService.get_role_level(User.ROLE_VIEWER)
        assert level == 5

    def test_get_role_level_returns_minus_one_for_invalid_role(self, app, db_session):
        """get_role_level should return -1 for invalid role."""
        level = ApprovalService.get_role_level('invalid_role')
        assert level == -1

    def test_get_role_level_returns_minus_one_for_empty_string(self, app, db_session):
        """get_role_level should return -1 for empty string."""
        level = ApprovalService.get_role_level('')
        assert level == -1

    def test_get_role_level_returns_minus_one_for_none(self, app, db_session):
        """get_role_level should return -1 for None."""
        level = ApprovalService.get_role_level(None)
        assert level == -1


# =============================================================================
# can_approve_role Tests
# =============================================================================

class TestApprovalServiceCanApproveRole:
    """Tests for ApprovalService.can_approve_role method."""

    def test_super_admin_can_approve_admin(self, app, db_session):
        """Super Admin should be able to approve Admin."""
        result = ApprovalService.can_approve_role(User.ROLE_SUPER_ADMIN, User.ROLE_ADMIN)
        assert result is True

    def test_super_admin_can_approve_all_lower_roles(self, app, db_session):
        """Super Admin should be able to approve all lower roles."""
        lower_roles = [
            User.ROLE_ADMIN,
            User.ROLE_CONTENT_MANAGER,
            User.ROLE_PARTNER,
            User.ROLE_ADVERTISER,
            User.ROLE_VIEWER
        ]

        for role in lower_roles:
            assert ApprovalService.can_approve_role(User.ROLE_SUPER_ADMIN, role) is True

    def test_admin_can_approve_content_manager(self, app, db_session):
        """Admin should be able to approve Content Manager."""
        result = ApprovalService.can_approve_role(User.ROLE_ADMIN, User.ROLE_CONTENT_MANAGER)
        assert result is True

    def test_admin_cannot_approve_super_admin(self, app, db_session):
        """Admin should NOT be able to approve Super Admin."""
        result = ApprovalService.can_approve_role(User.ROLE_ADMIN, User.ROLE_SUPER_ADMIN)
        assert result is False

    def test_admin_cannot_approve_admin(self, app, db_session):
        """Admin should NOT be able to approve another Admin (same level)."""
        result = ApprovalService.can_approve_role(User.ROLE_ADMIN, User.ROLE_ADMIN)
        assert result is False

    def test_content_manager_can_approve_partner(self, app, db_session):
        """Content Manager should be able to approve Partner."""
        result = ApprovalService.can_approve_role(User.ROLE_CONTENT_MANAGER, User.ROLE_PARTNER)
        assert result is True

    def test_content_manager_cannot_approve_admin(self, app, db_session):
        """Content Manager should NOT be able to approve Admin."""
        result = ApprovalService.can_approve_role(User.ROLE_CONTENT_MANAGER, User.ROLE_ADMIN)
        assert result is False

    def test_partner_can_approve_advertiser(self, app, db_session):
        """Partner should be able to approve Advertiser."""
        result = ApprovalService.can_approve_role(User.ROLE_PARTNER, User.ROLE_ADVERTISER)
        assert result is True

    def test_partner_can_approve_viewer(self, app, db_session):
        """Partner should be able to approve Viewer."""
        result = ApprovalService.can_approve_role(User.ROLE_PARTNER, User.ROLE_VIEWER)
        assert result is True

    def test_advertiser_can_approve_viewer(self, app, db_session):
        """Advertiser should be able to approve Viewer."""
        result = ApprovalService.can_approve_role(User.ROLE_ADVERTISER, User.ROLE_VIEWER)
        assert result is True

    def test_viewer_cannot_approve_anyone(self, app, db_session):
        """Viewer should NOT be able to approve any role."""
        for role in User.VALID_ROLES:
            assert ApprovalService.can_approve_role(User.ROLE_VIEWER, role) is False

    def test_invalid_approver_role_returns_false(self, app, db_session):
        """Invalid approver role should return False."""
        result = ApprovalService.can_approve_role('invalid', User.ROLE_PARTNER)
        assert result is False

    def test_invalid_target_role_returns_false(self, app, db_session):
        """Invalid target role should return False."""
        result = ApprovalService.can_approve_role(User.ROLE_ADMIN, 'invalid')
        assert result is False


# =============================================================================
# can_approve_user Tests
# =============================================================================

class TestApprovalServiceCanApproveUser:
    """Tests for ApprovalService.can_approve_user method."""

    def test_can_approve_user_returns_true_for_valid_approval(self, app, db_session, sample_admin, sample_pending_user):
        """can_approve_user should return (True, 'ok') for valid approval."""
        # sample_admin is admin, sample_pending_user is pending partner
        can_approve, reason = ApprovalService.can_approve_user(
            db_session,
            approver_id=sample_admin.id,
            user_id=sample_pending_user.id
        )

        assert can_approve is True
        assert reason == 'ok'

    def test_can_approve_user_returns_false_for_nonexistent_approver(self, app, db_session, sample_pending_user):
        """can_approve_user should return False for nonexistent approver."""
        can_approve, reason = ApprovalService.can_approve_user(
            db_session,
            approver_id=99999,
            user_id=sample_pending_user.id
        )

        assert can_approve is False
        assert 'Approver not found' in reason

    def test_can_approve_user_returns_false_for_nonexistent_target(self, app, db_session, sample_admin):
        """can_approve_user should return False for nonexistent target user."""
        can_approve, reason = ApprovalService.can_approve_user(
            db_session,
            approver_id=sample_admin.id,
            user_id=99999
        )

        assert can_approve is False
        assert 'User to approve not found' in reason

    def test_can_approve_user_prevents_self_approval(self, app, db_session, sample_pending_user):
        """can_approve_user should prevent users from approving themselves."""
        can_approve, reason = ApprovalService.can_approve_user(
            db_session,
            approver_id=sample_pending_user.id,
            user_id=sample_pending_user.id
        )

        assert can_approve is False
        assert 'cannot approve themselves' in reason

    def test_can_approve_user_rejects_non_pending_user(self, app, db_session, sample_admin, sample_partner):
        """can_approve_user should reject users not in pending status."""
        # sample_partner is already active, not pending
        can_approve, reason = ApprovalService.can_approve_user(
            db_session,
            approver_id=sample_admin.id,
            user_id=sample_partner.id
        )

        assert can_approve is False
        assert 'not eligible for approval' in reason

    def test_can_approve_user_enforces_role_hierarchy(self, app, db_session, sample_partner, sample_internal_organization):
        """can_approve_user should enforce role hierarchy."""
        # Create a pending admin that a partner tries to approve
        pending_admin = User(
            email='pending_admin@test.com',
            password_hash='hash',
            name='Pending Admin',
            role=User.ROLE_ADMIN,
            organization_id=sample_internal_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(pending_admin)
        db_session.commit()

        # Partner cannot approve Admin (higher role)
        can_approve, reason = ApprovalService.can_approve_user(
            db_session,
            approver_id=sample_partner.id,
            user_id=pending_admin.id
        )

        assert can_approve is False
        assert 'cannot approve role' in reason

    def test_can_approve_user_rejects_inactive_approver(self, app, db_session, sample_organization):
        """can_approve_user should reject approval from inactive approver."""
        # Create a suspended admin
        suspended_admin = User(
            email='suspended_admin@test.com',
            password_hash='hash',
            name='Suspended Admin',
            role=User.ROLE_ADMIN,
            organization_id=sample_organization.id,
            status=User.STATUS_SUSPENDED
        )
        db_session.add(suspended_admin)

        # Create pending partner
        pending_partner = User(
            email='pending_partner@test.com',
            password_hash='hash',
            name='Pending Partner',
            role=User.ROLE_PARTNER,
            organization_id=sample_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(pending_partner)
        db_session.commit()

        can_approve, reason = ApprovalService.can_approve_user(
            db_session,
            approver_id=suspended_admin.id,
            user_id=pending_partner.id
        )

        assert can_approve is False
        assert 'not active' in reason

    def test_can_approve_user_detects_circular_approval(self, app, db_session, sample_internal_organization):
        """can_approve_user should detect and prevent circular approval."""
        # Create user A who was approved by user B
        user_b = User(
            email='user_b@test.com',
            password_hash='hash',
            name='User B',
            role=User.ROLE_ADMIN,
            organization_id=sample_internal_organization.id,
            status=User.STATUS_ACTIVE
        )
        db_session.add(user_b)
        db_session.commit()

        user_a = User(
            email='user_a@test.com',
            password_hash='hash',
            name='User A',
            role=User.ROLE_ADMIN,
            organization_id=sample_internal_organization.id,
            status=User.STATUS_ACTIVE,
            approved_by=user_b.id  # A was approved by B
        )
        db_session.add(user_a)

        # Now B is pending and A tries to approve B (circular)
        user_b.status = User.STATUS_PENDING
        user_b.role = User.ROLE_CONTENT_MANAGER  # Make B approvable by A
        db_session.commit()

        can_approve, reason = ApprovalService.can_approve_user(
            db_session,
            approver_id=user_a.id,
            user_id=user_b.id
        )

        assert can_approve is False
        assert 'Circular approval' in reason


# =============================================================================
# approve_user Tests
# =============================================================================

class TestApprovalServiceApproveUser:
    """Tests for ApprovalService.approve_user method."""

    def test_approve_user_succeeds_for_valid_approval(self, app, db_session, sample_admin, sample_pending_user):
        """approve_user should succeed and update user status."""
        result = ApprovalService.approve_user(
            db_session,
            approver_id=sample_admin.id,
            user_id=sample_pending_user.id,
            notes='Approved after verification'
        )

        assert result['success'] is True
        assert result['user'] is not None
        assert result['user'].status == User.STATUS_APPROVED
        assert result['user'].approved_by == sample_admin.id
        assert result['user'].approved_at is not None
        assert result['error'] is None

    def test_approve_user_fails_for_invalid_hierarchy(self, app, db_session, sample_partner, sample_internal_organization):
        """approve_user should fail when approver lacks permission."""
        # Create pending admin
        pending_admin = User(
            email='pending_admin2@test.com',
            password_hash='hash',
            name='Pending Admin',
            role=User.ROLE_ADMIN,
            organization_id=sample_internal_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(pending_admin)
        db_session.commit()

        result = ApprovalService.approve_user(
            db_session,
            approver_id=sample_partner.id,
            user_id=pending_admin.id
        )

        assert result['success'] is False
        assert result['user'] is None
        assert result['error'] is not None

    def test_approve_user_resolves_approval_request(self, app, db_session, sample_admin, sample_pending_user, sample_approval_request):
        """approve_user should resolve any pending approval request."""
        result = ApprovalService.approve_user(
            db_session,
            approver_id=sample_admin.id,
            user_id=sample_pending_user.id,
            notes='Approved with notes'
        )

        assert result['success'] is True
        assert result['approval_request'] is not None
        assert result['approval_request'].status == UserApprovalRequest.STATUS_APPROVED
        assert result['approval_request'].resolved_at is not None
        assert result['approval_request'].notes == 'Approved with notes'

    def test_approve_user_without_approval_request(self, app, db_session, sample_admin, sample_organization):
        """approve_user should work even without existing approval request."""
        # Create pending user without approval request
        new_pending = User(
            email='new_pending@test.com',
            password_hash='hash',
            name='New Pending',
            role=User.ROLE_PARTNER,
            organization_id=sample_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(new_pending)
        db_session.commit()

        result = ApprovalService.approve_user(
            db_session,
            approver_id=sample_admin.id,
            user_id=new_pending.id
        )

        assert result['success'] is True
        assert result['user'].status == User.STATUS_APPROVED
        assert result['approval_request'] is None


# =============================================================================
# reject_user Tests
# =============================================================================

class TestApprovalServiceRejectUser:
    """Tests for ApprovalService.reject_user method."""

    def test_reject_user_succeeds_with_reason(self, app, db_session, sample_admin, sample_pending_user):
        """reject_user should succeed and update user status."""
        result = ApprovalService.reject_user(
            db_session,
            approver_id=sample_admin.id,
            user_id=sample_pending_user.id,
            reason='Missing required documentation'
        )

        assert result['success'] is True
        assert result['user'] is not None
        assert result['user'].status == User.STATUS_REJECTED
        assert result['user'].rejection_reason == 'Missing required documentation'
        assert result['user'].approved_by == sample_admin.id
        assert result['error'] is None

    def test_reject_user_fails_without_reason(self, app, db_session, sample_admin, sample_pending_user):
        """reject_user should fail when reason is not provided."""
        result = ApprovalService.reject_user(
            db_session,
            approver_id=sample_admin.id,
            user_id=sample_pending_user.id,
            reason=''
        )

        assert result['success'] is False
        assert result['error'] == 'Rejection reason is required'

    def test_reject_user_fails_with_whitespace_only_reason(self, app, db_session, sample_admin, sample_pending_user):
        """reject_user should fail when reason is only whitespace."""
        result = ApprovalService.reject_user(
            db_session,
            approver_id=sample_admin.id,
            user_id=sample_pending_user.id,
            reason='   '
        )

        assert result['success'] is False
        assert result['error'] == 'Rejection reason is required'

    def test_reject_user_resolves_approval_request(self, app, db_session, sample_admin, sample_pending_user, sample_approval_request):
        """reject_user should resolve any pending approval request."""
        result = ApprovalService.reject_user(
            db_session,
            approver_id=sample_admin.id,
            user_id=sample_pending_user.id,
            reason='Rejected for testing'
        )

        assert result['success'] is True
        assert result['approval_request'] is not None
        assert result['approval_request'].status == UserApprovalRequest.STATUS_REJECTED
        assert result['approval_request'].notes == 'Rejected for testing'

    def test_reject_user_enforces_hierarchy(self, app, db_session, sample_partner, sample_internal_organization):
        """reject_user should enforce role hierarchy same as approve."""
        # Create pending admin
        pending_admin = User(
            email='pending_admin3@test.com',
            password_hash='hash',
            name='Pending Admin',
            role=User.ROLE_ADMIN,
            organization_id=sample_internal_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(pending_admin)
        db_session.commit()

        result = ApprovalService.reject_user(
            db_session,
            approver_id=sample_partner.id,
            user_id=pending_admin.id,
            reason='Should fail'
        )

        assert result['success'] is False
        assert 'cannot approve role' in result['error']


# =============================================================================
# get_approvable_roles_for_user Tests
# =============================================================================

class TestApprovalServiceGetApprovableRoles:
    """Tests for ApprovalService.get_approvable_roles_for_user method."""

    def test_get_approvable_roles_for_super_admin(self, app, db_session, sample_super_admin):
        """Super Admin should be able to approve all lower roles."""
        roles = ApprovalService.get_approvable_roles_for_user(db_session, sample_super_admin.id)

        assert User.ROLE_ADMIN in roles
        assert User.ROLE_CONTENT_MANAGER in roles
        assert User.ROLE_PARTNER in roles
        assert User.ROLE_ADVERTISER in roles
        assert User.ROLE_VIEWER in roles
        assert User.ROLE_SUPER_ADMIN not in roles

    def test_get_approvable_roles_for_admin(self, app, db_session, sample_admin):
        """Admin should be able to approve Content Manager and below."""
        roles = ApprovalService.get_approvable_roles_for_user(db_session, sample_admin.id)

        assert User.ROLE_CONTENT_MANAGER in roles
        assert User.ROLE_PARTNER in roles
        assert User.ROLE_ADVERTISER in roles
        assert User.ROLE_VIEWER in roles
        assert User.ROLE_SUPER_ADMIN not in roles
        assert User.ROLE_ADMIN not in roles

    def test_get_approvable_roles_for_partner(self, app, db_session, sample_partner):
        """Partner should be able to approve Advertiser and Viewer."""
        roles = ApprovalService.get_approvable_roles_for_user(db_session, sample_partner.id)

        assert User.ROLE_ADVERTISER in roles
        assert User.ROLE_VIEWER in roles
        assert len(roles) == 2

    def test_get_approvable_roles_for_viewer(self, app, db_session, sample_organization):
        """Viewer should not be able to approve any role."""
        viewer = User(
            email='viewer@test.com',
            password_hash='hash',
            name='Viewer',
            role=User.ROLE_VIEWER,
            organization_id=sample_organization.id,
            status=User.STATUS_ACTIVE
        )
        db_session.add(viewer)
        db_session.commit()

        roles = ApprovalService.get_approvable_roles_for_user(db_session, viewer.id)

        assert roles == []

    def test_get_approvable_roles_for_nonexistent_user(self, app, db_session):
        """get_approvable_roles_for_user should return empty list for nonexistent user."""
        roles = ApprovalService.get_approvable_roles_for_user(db_session, 99999)

        assert roles == []


# =============================================================================
# get_pending_approvals_for_user Tests
# =============================================================================

class TestApprovalServiceGetPendingApprovals:
    """Tests for ApprovalService.get_pending_approvals_for_user method."""

    def test_get_pending_approvals_returns_approvable_users(self, app, db_session, sample_admin, sample_pending_user):
        """get_pending_approvals_for_user should return pending users that can be approved."""
        pending_users = ApprovalService.get_pending_approvals_for_user(db_session, sample_admin.id)

        assert len(pending_users) >= 1
        assert sample_pending_user in pending_users

    def test_get_pending_approvals_excludes_unapprrovable_roles(self, app, db_session, sample_partner, sample_internal_organization):
        """get_pending_approvals_for_user should exclude users with higher roles."""
        # Create pending admin
        pending_admin = User(
            email='pending_admin4@test.com',
            password_hash='hash',
            name='Pending Admin',
            role=User.ROLE_ADMIN,
            organization_id=sample_internal_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(pending_admin)
        db_session.commit()

        pending_users = ApprovalService.get_pending_approvals_for_user(db_session, sample_partner.id)

        # Partner should not see pending Admin
        assert pending_admin not in pending_users

    def test_get_pending_approvals_excludes_self(self, app, db_session, sample_pending_user):
        """get_pending_approvals_for_user should exclude the user themselves."""
        pending_users = ApprovalService.get_pending_approvals_for_user(db_session, sample_pending_user.id)

        assert sample_pending_user not in pending_users

    def test_get_pending_approvals_returns_empty_for_viewer(self, app, db_session, sample_organization):
        """Viewer should see no pending approvals."""
        viewer = User(
            email='viewer2@test.com',
            password_hash='hash',
            name='Viewer',
            role=User.ROLE_VIEWER,
            organization_id=sample_organization.id,
            status=User.STATUS_ACTIVE
        )
        db_session.add(viewer)
        db_session.commit()

        pending_users = ApprovalService.get_pending_approvals_for_user(db_session, viewer.id)

        assert pending_users == []

    def test_get_pending_approvals_excludes_circular_approval(self, app, db_session, sample_internal_organization):
        """get_pending_approvals_for_user should exclude users who approved the approver."""
        # Create user A and B
        user_a = User(
            email='user_a2@test.com',
            password_hash='hash',
            name='User A',
            role=User.ROLE_ADMIN,
            organization_id=sample_internal_organization.id,
            status=User.STATUS_ACTIVE
        )
        db_session.add(user_a)
        db_session.commit()

        user_b = User(
            email='user_b2@test.com',
            password_hash='hash',
            name='User B',
            role=User.ROLE_CONTENT_MANAGER,
            organization_id=sample_internal_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(user_b)
        db_session.commit()

        # A was approved by B (circular scenario)
        user_a.approved_by = user_b.id
        db_session.commit()

        pending_users = ApprovalService.get_pending_approvals_for_user(db_session, user_a.id)

        # user_b should be excluded due to circular approval potential
        assert user_b not in pending_users


# =============================================================================
# create_approval_request Tests
# =============================================================================

class TestApprovalServiceCreateApprovalRequest:
    """Tests for ApprovalService.create_approval_request method."""

    def test_create_approval_request_succeeds(self, app, db_session, sample_pending_user, sample_admin):
        """create_approval_request should create a new approval request."""
        request = ApprovalService.create_approval_request(
            db_session,
            user_id=sample_pending_user.id,
            requested_by=sample_pending_user.id,
            assigned_to=sample_admin.id,
            notes='Please approve'
        )

        assert request is not None
        assert request.user_id == sample_pending_user.id
        assert request.requested_role == sample_pending_user.role
        assert request.current_status == sample_pending_user.status
        assert request.assigned_to == sample_admin.id
        assert request.status == UserApprovalRequest.STATUS_PENDING
        assert request.notes == 'Please approve'

    def test_create_approval_request_raises_for_nonexistent_user(self, app, db_session):
        """create_approval_request should raise ValueError for nonexistent user."""
        with pytest.raises(ValueError) as exc_info:
            ApprovalService.create_approval_request(
                db_session,
                user_id=99999
            )

        assert 'not found' in str(exc_info.value)

    def test_create_approval_request_uses_user_id_as_default_requested_by(self, app, db_session, sample_pending_user):
        """create_approval_request should default requested_by to user_id."""
        request = ApprovalService.create_approval_request(
            db_session,
            user_id=sample_pending_user.id
        )

        assert request.requested_by == sample_pending_user.id


# =============================================================================
# Content Approval - can_approve_content Tests
# =============================================================================

class TestApprovalServiceCanApproveContent:
    """Tests for ApprovalService.can_approve_content method."""

    def test_can_approve_content_returns_true_for_content_manager(self, app, db_session, sample_content_manager, sample_pending_content):
        """Content Manager should be able to approve pending content."""
        can_approve, reason = ApprovalService.can_approve_content(
            db_session,
            approver_id=sample_content_manager.id,
            asset_id=sample_pending_content.id
        )

        assert can_approve is True
        assert reason == 'ok'

    def test_can_approve_content_returns_true_for_admin(self, app, db_session, sample_admin, sample_pending_content):
        """Admin should be able to approve pending content."""
        can_approve, reason = ApprovalService.can_approve_content(
            db_session,
            approver_id=sample_admin.id,
            asset_id=sample_pending_content.id
        )

        assert can_approve is True
        assert reason == 'ok'

    def test_can_approve_content_returns_false_for_partner(self, app, db_session, sample_organization, sample_pending_content):
        """Partner should NOT be able to approve content."""
        # Create a different partner to avoid self-approval issue
        other_partner = User(
            email='other_partner@test.com',
            password_hash='hash',
            name='Other Partner',
            role=User.ROLE_PARTNER,
            organization_id=sample_organization.id,
            status=User.STATUS_ACTIVE
        )
        db_session.add(other_partner)
        db_session.commit()

        can_approve, reason = ApprovalService.can_approve_content(
            db_session,
            approver_id=other_partner.id,
            asset_id=sample_pending_content.id
        )

        assert can_approve is False
        assert 'cannot approve content' in reason

    def test_can_approve_content_prevents_self_approval(self, app, db_session, sample_content_manager, sample_organization):
        """Users should not be able to approve their own uploaded content."""
        # Create content uploaded by content manager
        own_content = ContentAsset(
            title='Own Content',
            filename='own.mp4',
            file_path='/uploads/own.mp4',
            organization_id=sample_organization.id,
            uploaded_by=sample_content_manager.id,
            status=ContentAsset.STATUS_PENDING_REVIEW
        )
        db_session.add(own_content)
        db_session.commit()

        can_approve, reason = ApprovalService.can_approve_content(
            db_session,
            approver_id=sample_content_manager.id,
            asset_id=own_content.id
        )

        assert can_approve is False
        assert 'cannot approve their own uploaded content' in reason

    def test_can_approve_content_rejects_non_pending_content(self, app, db_session, sample_content_manager, sample_content_asset):
        """can_approve_content should reject content not in pending_review status."""
        # sample_content_asset is in draft status
        can_approve, reason = ApprovalService.can_approve_content(
            db_session,
            approver_id=sample_content_manager.id,
            asset_id=sample_content_asset.id
        )

        assert can_approve is False
        assert 'not eligible for approval' in reason

    def test_can_approve_content_rejects_inactive_approver(self, app, db_session, sample_organization, sample_pending_content):
        """can_approve_content should reject approval from inactive approver."""
        suspended_cm = User(
            email='suspended_cm@test.com',
            password_hash='hash',
            name='Suspended CM',
            role=User.ROLE_CONTENT_MANAGER,
            organization_id=sample_organization.id,
            status=User.STATUS_SUSPENDED
        )
        db_session.add(suspended_cm)
        db_session.commit()

        can_approve, reason = ApprovalService.can_approve_content(
            db_session,
            approver_id=suspended_cm.id,
            asset_id=sample_pending_content.id
        )

        assert can_approve is False
        assert 'not active' in reason

    def test_can_approve_content_rejects_nonexistent_asset(self, app, db_session, sample_content_manager):
        """can_approve_content should reject nonexistent asset."""
        can_approve, reason = ApprovalService.can_approve_content(
            db_session,
            approver_id=sample_content_manager.id,
            asset_id=99999
        )

        assert can_approve is False
        assert 'Content asset not found' in reason


# =============================================================================
# Content Approval - approve_content Tests
# =============================================================================

class TestApprovalServiceApproveContent:
    """Tests for ApprovalService.approve_content method."""

    def test_approve_content_succeeds(self, app, db_session, sample_content_manager, sample_pending_content):
        """approve_content should update asset status to approved."""
        result = ApprovalService.approve_content(
            db_session,
            approver_id=sample_content_manager.id,
            asset_id=sample_pending_content.id,
            notes='Content approved for quality'
        )

        assert result['success'] is True
        assert result['asset'] is not None
        assert result['asset'].status == ContentAsset.STATUS_APPROVED
        assert result['asset'].reviewed_by == sample_content_manager.id
        assert result['asset'].reviewed_at is not None
        assert result['asset'].review_notes == 'Content approved for quality'

    def test_approve_content_fails_for_unauthorized(self, app, db_session, sample_partner, sample_organization, sample_pending_content):
        """approve_content should fail for unauthorized user."""
        # Create another partner (not the uploader)
        other_partner = User(
            email='other_partner2@test.com',
            password_hash='hash',
            name='Other Partner 2',
            role=User.ROLE_PARTNER,
            organization_id=sample_organization.id,
            status=User.STATUS_ACTIVE
        )
        db_session.add(other_partner)
        db_session.commit()

        result = ApprovalService.approve_content(
            db_session,
            approver_id=other_partner.id,
            asset_id=sample_pending_content.id
        )

        assert result['success'] is False
        assert result['asset'] is None

    def test_approve_content_resolves_approval_request(self, app, db_session, sample_content_manager, sample_pending_content, sample_content_approval_request):
        """approve_content should resolve any pending content approval request."""
        result = ApprovalService.approve_content(
            db_session,
            approver_id=sample_content_manager.id,
            asset_id=sample_pending_content.id,
            notes='Approved'
        )

        assert result['success'] is True
        assert result['approval_request'] is not None
        assert result['approval_request'].status == ContentApprovalRequest.STATUS_APPROVED


# =============================================================================
# Content Approval - reject_content Tests
# =============================================================================

class TestApprovalServiceRejectContent:
    """Tests for ApprovalService.reject_content method."""

    def test_reject_content_succeeds_with_reason(self, app, db_session, sample_content_manager, sample_pending_content):
        """reject_content should update asset status to rejected."""
        result = ApprovalService.reject_content(
            db_session,
            approver_id=sample_content_manager.id,
            asset_id=sample_pending_content.id,
            reason='Video quality too low'
        )

        assert result['success'] is True
        assert result['asset'] is not None
        assert result['asset'].status == ContentAsset.STATUS_REJECTED
        assert result['asset'].review_notes == 'Video quality too low'
        assert result['asset'].reviewed_by == sample_content_manager.id

    def test_reject_content_fails_without_reason(self, app, db_session, sample_content_manager, sample_pending_content):
        """reject_content should fail when reason is not provided."""
        result = ApprovalService.reject_content(
            db_session,
            approver_id=sample_content_manager.id,
            asset_id=sample_pending_content.id,
            reason=''
        )

        assert result['success'] is False
        assert result['error'] == 'Rejection reason is required'

    def test_reject_content_resolves_approval_request(self, app, db_session, sample_content_manager, sample_pending_content, sample_content_approval_request):
        """reject_content should resolve any pending content approval request."""
        result = ApprovalService.reject_content(
            db_session,
            approver_id=sample_content_manager.id,
            asset_id=sample_pending_content.id,
            reason='Does not meet standards'
        )

        assert result['success'] is True
        assert result['approval_request'] is not None
        assert result['approval_request'].status == ContentApprovalRequest.STATUS_REJECTED


# =============================================================================
# Content Publishing - can_publish_content Tests
# =============================================================================

class TestApprovalServiceCanPublishContent:
    """Tests for ApprovalService.can_publish_content method."""

    def test_can_publish_content_returns_true_for_approved_content(self, app, db_session, sample_content_manager, sample_organization, sample_partner):
        """can_publish_content should return True for approved content."""
        approved_content = ContentAsset(
            title='Approved Content',
            filename='approved.mp4',
            file_path='/uploads/approved.mp4',
            organization_id=sample_organization.id,
            uploaded_by=sample_partner.id,
            status=ContentAsset.STATUS_APPROVED
        )
        db_session.add(approved_content)
        db_session.commit()

        can_publish, reason = ApprovalService.can_publish_content(
            db_session,
            publisher_id=sample_content_manager.id,
            asset_id=approved_content.id
        )

        assert can_publish is True
        assert reason == 'ok'

    def test_can_publish_content_rejects_non_approved_content(self, app, db_session, sample_content_manager, sample_pending_content):
        """can_publish_content should reject content not in approved status."""
        can_publish, reason = ApprovalService.can_publish_content(
            db_session,
            publisher_id=sample_content_manager.id,
            asset_id=sample_pending_content.id
        )

        assert can_publish is False
        assert 'not eligible for publishing' in reason

    def test_can_publish_content_rejects_partner(self, app, db_session, sample_partner, sample_organization):
        """Partner should not be able to publish content."""
        approved_content = ContentAsset(
            title='Approved Content 2',
            filename='approved2.mp4',
            file_path='/uploads/approved2.mp4',
            organization_id=sample_organization.id,
            uploaded_by=sample_partner.id,
            status=ContentAsset.STATUS_APPROVED
        )
        db_session.add(approved_content)
        db_session.commit()

        can_publish, reason = ApprovalService.can_publish_content(
            db_session,
            publisher_id=sample_partner.id,
            asset_id=approved_content.id
        )

        assert can_publish is False
        assert 'cannot publish content' in reason


# =============================================================================
# Content Publishing - publish_content Tests
# =============================================================================

class TestApprovalServicePublishContent:
    """Tests for ApprovalService.publish_content method."""

    def test_publish_content_succeeds(self, app, db_session, sample_content_manager, sample_organization, sample_partner):
        """publish_content should update asset status to published."""
        approved_content = ContentAsset(
            title='Approved For Publish',
            filename='for_publish.mp4',
            file_path='/uploads/for_publish.mp4',
            organization_id=sample_organization.id,
            uploaded_by=sample_partner.id,
            status=ContentAsset.STATUS_APPROVED
        )
        db_session.add(approved_content)
        db_session.commit()

        result = ApprovalService.publish_content(
            db_session,
            publisher_id=sample_content_manager.id,
            asset_id=approved_content.id
        )

        assert result['success'] is True
        assert result['asset'] is not None
        assert result['asset'].status == ContentAsset.STATUS_PUBLISHED
        assert result['asset'].published_at is not None

    def test_publish_content_fails_for_non_approved(self, app, db_session, sample_content_manager, sample_pending_content):
        """publish_content should fail for content not in approved status."""
        result = ApprovalService.publish_content(
            db_session,
            publisher_id=sample_content_manager.id,
            asset_id=sample_pending_content.id
        )

        assert result['success'] is False
        assert result['asset'] is None


# =============================================================================
# get_pending_content_approvals Tests
# =============================================================================

class TestApprovalServiceGetPendingContentApprovals:
    """Tests for ApprovalService.get_pending_content_approvals method."""

    def test_get_pending_content_approvals_returns_pending_content(self, app, db_session, sample_content_manager, sample_pending_content):
        """get_pending_content_approvals should return pending review content."""
        pending_content = ApprovalService.get_pending_content_approvals(
            db_session,
            approver_id=sample_content_manager.id
        )

        assert len(pending_content) >= 1
        assert sample_pending_content in pending_content

    def test_get_pending_content_approvals_excludes_own_uploads(self, app, db_session, sample_content_manager, sample_organization):
        """get_pending_content_approvals should exclude approver's own uploads."""
        # Create content uploaded by the content manager
        own_content = ContentAsset(
            title='Own Upload',
            filename='own_upload.mp4',
            file_path='/uploads/own_upload.mp4',
            organization_id=sample_organization.id,
            uploaded_by=sample_content_manager.id,
            status=ContentAsset.STATUS_PENDING_REVIEW
        )
        db_session.add(own_content)
        db_session.commit()

        pending_content = ApprovalService.get_pending_content_approvals(
            db_session,
            approver_id=sample_content_manager.id
        )

        assert own_content not in pending_content

    def test_get_pending_content_approvals_filters_by_organization(self, app, db_session, sample_content_manager, sample_organization, sample_pending_content):
        """get_pending_content_approvals should filter by organization when provided."""
        pending_content = ApprovalService.get_pending_content_approvals(
            db_session,
            approver_id=sample_content_manager.id,
            organization_id=sample_organization.id
        )

        for asset in pending_content:
            assert asset.organization_id == sample_organization.id

    def test_get_pending_content_approvals_returns_empty_for_partner(self, app, db_session, sample_partner):
        """Partner should not see any pending content for approval."""
        pending_content = ApprovalService.get_pending_content_approvals(
            db_session,
            approver_id=sample_partner.id
        )

        assert pending_content == []


# =============================================================================
# create_content_approval_request Tests
# =============================================================================

class TestApprovalServiceCreateContentApprovalRequest:
    """Tests for ApprovalService.create_content_approval_request method."""

    def test_create_content_approval_request_succeeds(self, app, db_session, sample_content_asset, sample_partner, sample_content_manager):
        """create_content_approval_request should create a new request."""
        request = ApprovalService.create_content_approval_request(
            db_session,
            asset_id=sample_content_asset.id,
            requested_by=sample_partner.id,
            assigned_to=sample_content_manager.id,
            notes='Please review this content'
        )

        assert request is not None
        assert request.asset_id == sample_content_asset.id
        assert request.requested_by == sample_partner.id
        assert request.assigned_to == sample_content_manager.id
        assert request.status == ContentApprovalRequest.STATUS_PENDING
        assert request.notes == 'Please review this content'

    def test_create_content_approval_request_raises_for_nonexistent_asset(self, app, db_session):
        """create_content_approval_request should raise ValueError for nonexistent asset."""
        with pytest.raises(ValueError) as exc_info:
            ApprovalService.create_content_approval_request(
                db_session,
                asset_id=99999
            )

        assert 'not found' in str(exc_info.value)

    def test_create_content_approval_request_defaults_requested_by_to_uploader(self, app, db_session, sample_content_asset):
        """create_content_approval_request should default requested_by to uploader."""
        request = ApprovalService.create_content_approval_request(
            db_session,
            asset_id=sample_content_asset.id
        )

        assert request.requested_by == sample_content_asset.uploaded_by


# =============================================================================
# CONTENT_APPROVER_ROLES and CONTENT_PUBLISHER_ROLES Configuration Tests
# =============================================================================

class TestApprovalServiceContentRolesConfiguration:
    """Tests for ApprovalService content approval/publishing roles configuration."""

    def test_content_approver_roles_configured(self, app, db_session):
        """ApprovalService should have CONTENT_APPROVER_ROLES configured."""
        assert hasattr(ApprovalService, 'CONTENT_APPROVER_ROLES')
        assert User.ROLE_SUPER_ADMIN in ApprovalService.CONTENT_APPROVER_ROLES
        assert User.ROLE_ADMIN in ApprovalService.CONTENT_APPROVER_ROLES
        assert User.ROLE_CONTENT_MANAGER in ApprovalService.CONTENT_APPROVER_ROLES

    def test_content_approver_roles_excludes_lower_roles(self, app, db_session):
        """CONTENT_APPROVER_ROLES should not include Partner, Advertiser, Viewer."""
        assert User.ROLE_PARTNER not in ApprovalService.CONTENT_APPROVER_ROLES
        assert User.ROLE_ADVERTISER not in ApprovalService.CONTENT_APPROVER_ROLES
        assert User.ROLE_VIEWER not in ApprovalService.CONTENT_APPROVER_ROLES

    def test_content_publisher_roles_configured(self, app, db_session):
        """ApprovalService should have CONTENT_PUBLISHER_ROLES configured."""
        assert hasattr(ApprovalService, 'CONTENT_PUBLISHER_ROLES')
        assert User.ROLE_SUPER_ADMIN in ApprovalService.CONTENT_PUBLISHER_ROLES
        assert User.ROLE_ADMIN in ApprovalService.CONTENT_PUBLISHER_ROLES
        assert User.ROLE_CONTENT_MANAGER in ApprovalService.CONTENT_PUBLISHER_ROLES

    def test_content_publisher_roles_excludes_lower_roles(self, app, db_session):
        """CONTENT_PUBLISHER_ROLES should not include Partner, Advertiser, Viewer."""
        assert User.ROLE_PARTNER not in ApprovalService.CONTENT_PUBLISHER_ROLES
        assert User.ROLE_ADVERTISER not in ApprovalService.CONTENT_PUBLISHER_ROLES
        assert User.ROLE_VIEWER not in ApprovalService.CONTENT_PUBLISHER_ROLES
