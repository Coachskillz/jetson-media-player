"""
Unit tests for User model in Content Catalog service.

Tests User model functionality including:
- Password hashing with bcrypt
- Role validation and hierarchy
- Status transitions (pending -> approved -> active, etc.)
- Account lockout (is_locked method)
- Approval permissions (can_approve_role method)
- Serialization (to_dict method)
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import pytest

from content_catalog.models import db, User, Organization


# =============================================================================
# Password Hashing Tests
# =============================================================================

class TestUserPasswordHashing:
    """Tests for User password hashing functionality."""

    def test_password_hash_stored_not_plaintext(self, app, db_session):
        """User should store hashed password, not plaintext."""
        plaintext_password = 'SecurePassword123!'
        password_hash = bcrypt.hashpw(
            plaintext_password.encode('utf-8'),
            bcrypt.gensalt(rounds=4)
        ).decode('utf-8')

        user = User(
            email='hash_test@example.com',
            password_hash=password_hash,
            name='Hash Test User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE
        )
        db_session.add(user)
        db_session.commit()

        # Password hash should not equal plaintext
        assert user.password_hash != plaintext_password
        # Password hash should be a bcrypt hash (starts with $2b$ or $2a$)
        assert user.password_hash.startswith('$2')

    def test_password_verification_with_bcrypt(self, app, db_session):
        """bcrypt should verify correct password against stored hash."""
        plaintext_password = 'VerifyMe123!'
        password_hash = bcrypt.hashpw(
            plaintext_password.encode('utf-8'),
            bcrypt.gensalt(rounds=4)
        ).decode('utf-8')

        user = User(
            email='verify_test@example.com',
            password_hash=password_hash,
            name='Verify Test User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE
        )
        db_session.add(user)
        db_session.commit()

        # Correct password should verify
        assert bcrypt.checkpw(
            plaintext_password.encode('utf-8'),
            user.password_hash.encode('utf-8')
        )

    def test_wrong_password_fails_verification(self, app, db_session):
        """bcrypt should reject incorrect password."""
        correct_password = 'CorrectPassword123!'
        wrong_password = 'WrongPassword456!'
        password_hash = bcrypt.hashpw(
            correct_password.encode('utf-8'),
            bcrypt.gensalt(rounds=4)
        ).decode('utf-8')

        user = User(
            email='wrong_pass_test@example.com',
            password_hash=password_hash,
            name='Wrong Pass Test User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE
        )
        db_session.add(user)
        db_session.commit()

        # Wrong password should fail verification
        assert not bcrypt.checkpw(
            wrong_password.encode('utf-8'),
            user.password_hash.encode('utf-8')
        )

    def test_same_password_different_hashes(self, app, db_session):
        """Same password should produce different hashes due to salt."""
        password = 'SamePassword123!'
        hash1 = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')
        hash2 = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user1 = User(
            email='salt_test1@example.com',
            password_hash=hash1,
            name='Salt Test User 1',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE
        )
        user2 = User(
            email='salt_test2@example.com',
            password_hash=hash2,
            name='Salt Test User 2',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE
        )
        db_session.add_all([user1, user2])
        db_session.commit()

        # Different users should have different hashes even with same password
        assert user1.password_hash != user2.password_hash

        # But both should verify with the original password
        assert bcrypt.checkpw(password.encode('utf-8'), user1.password_hash.encode('utf-8'))
        assert bcrypt.checkpw(password.encode('utf-8'), user2.password_hash.encode('utf-8'))


# =============================================================================
# Role Validation Tests
# =============================================================================

class TestUserRoleValidation:
    """Tests for User role validation."""

    def test_valid_roles_list(self, app):
        """User.VALID_ROLES should contain all expected roles."""
        expected_roles = [
            'super_admin',
            'admin',
            'content_manager',
            'partner',
            'advertiser',
            'viewer'
        ]
        assert User.VALID_ROLES == expected_roles

    def test_role_constants_match_valid_roles(self, app):
        """Role constants should match VALID_ROLES list."""
        assert User.ROLE_SUPER_ADMIN == 'super_admin'
        assert User.ROLE_ADMIN == 'admin'
        assert User.ROLE_CONTENT_MANAGER == 'content_manager'
        assert User.ROLE_PARTNER == 'partner'
        assert User.ROLE_ADVERTISER == 'advertiser'
        assert User.ROLE_VIEWER == 'viewer'

        # All constants should be in VALID_ROLES
        assert User.ROLE_SUPER_ADMIN in User.VALID_ROLES
        assert User.ROLE_ADMIN in User.VALID_ROLES
        assert User.ROLE_CONTENT_MANAGER in User.VALID_ROLES
        assert User.ROLE_PARTNER in User.VALID_ROLES
        assert User.ROLE_ADVERTISER in User.VALID_ROLES
        assert User.ROLE_VIEWER in User.VALID_ROLES

    def test_create_user_with_each_valid_role(self, app, db_session):
        """Should be able to create users with each valid role."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        for i, role in enumerate(User.VALID_ROLES):
            user = User(
                email=f'role_test_{i}@example.com',
                password_hash=password_hash,
                name=f'Role Test {role}',
                role=role,
                status=User.STATUS_ACTIVE
            )
            db_session.add(user)
            db_session.commit()

            assert user.role == role
            assert user.id is not None

    def test_role_hierarchy_order(self, app):
        """VALID_ROLES should be ordered from highest to lowest privilege."""
        # super_admin has highest privilege (index 0)
        # viewer has lowest privilege (last index)
        assert User.VALID_ROLES.index(User.ROLE_SUPER_ADMIN) < User.VALID_ROLES.index(User.ROLE_ADMIN)
        assert User.VALID_ROLES.index(User.ROLE_ADMIN) < User.VALID_ROLES.index(User.ROLE_CONTENT_MANAGER)
        assert User.VALID_ROLES.index(User.ROLE_CONTENT_MANAGER) < User.VALID_ROLES.index(User.ROLE_PARTNER)
        assert User.VALID_ROLES.index(User.ROLE_PARTNER) < User.VALID_ROLES.index(User.ROLE_ADVERTISER)
        assert User.VALID_ROLES.index(User.ROLE_ADVERTISER) < User.VALID_ROLES.index(User.ROLE_VIEWER)


# =============================================================================
# Status Transition Tests
# =============================================================================

class TestUserStatusTransitions:
    """Tests for User status transitions and valid status values."""

    def test_valid_statuses_list(self, app):
        """User.VALID_STATUSES should contain all expected statuses."""
        expected_statuses = [
            'pending',
            'approved',
            'active',
            'rejected',
            'suspended',
            'deactivated'
        ]
        assert User.VALID_STATUSES == expected_statuses

    def test_status_constants_match_valid_statuses(self, app):
        """Status constants should match VALID_STATUSES list."""
        assert User.STATUS_PENDING == 'pending'
        assert User.STATUS_APPROVED == 'approved'
        assert User.STATUS_ACTIVE == 'active'
        assert User.STATUS_REJECTED == 'rejected'
        assert User.STATUS_SUSPENDED == 'suspended'
        assert User.STATUS_DEACTIVATED == 'deactivated'

    def test_default_status_is_pending(self, app, db_session):
        """New user should default to pending status."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='default_status@example.com',
            password_hash=password_hash,
            name='Default Status User',
            role=User.ROLE_PARTNER
        )
        db_session.add(user)
        db_session.commit()

        assert user.status == User.STATUS_PENDING

    def test_transition_pending_to_approved(self, app, db_session, sample_super_admin):
        """User can transition from pending to approved."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='pending_to_approved@example.com',
            password_hash=password_hash,
            name='Pending User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_PENDING
        )
        db_session.add(user)
        db_session.commit()

        assert user.status == User.STATUS_PENDING

        # Transition to approved
        user.status = User.STATUS_APPROVED
        user.approved_by = sample_super_admin.id
        user.approved_at = datetime.now(timezone.utc)
        db_session.commit()

        assert user.status == User.STATUS_APPROVED
        assert user.approved_by == sample_super_admin.id
        assert user.approved_at is not None

    def test_transition_approved_to_active(self, app, db_session):
        """User can transition from approved to active."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='approved_to_active@example.com',
            password_hash=password_hash,
            name='Approved User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_APPROVED
        )
        db_session.add(user)
        db_session.commit()

        # Transition to active
        user.status = User.STATUS_ACTIVE
        db_session.commit()

        assert user.status == User.STATUS_ACTIVE

    def test_transition_pending_to_rejected(self, app, db_session):
        """User can transition from pending to rejected with reason."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='pending_to_rejected@example.com',
            password_hash=password_hash,
            name='Pending User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_PENDING
        )
        db_session.add(user)
        db_session.commit()

        # Transition to rejected
        user.status = User.STATUS_REJECTED
        user.rejection_reason = 'Did not meet requirements'
        db_session.commit()

        assert user.status == User.STATUS_REJECTED
        assert user.rejection_reason == 'Did not meet requirements'

    def test_transition_active_to_suspended(self, app, db_session):
        """Active user can be suspended."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='active_to_suspended@example.com',
            password_hash=password_hash,
            name='Active User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE
        )
        db_session.add(user)
        db_session.commit()

        # Transition to suspended
        user.status = User.STATUS_SUSPENDED
        db_session.commit()

        assert user.status == User.STATUS_SUSPENDED

    def test_transition_active_to_deactivated(self, app, db_session):
        """Active user can be deactivated."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='active_to_deactivated@example.com',
            password_hash=password_hash,
            name='Active User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE
        )
        db_session.add(user)
        db_session.commit()

        # Transition to deactivated
        user.status = User.STATUS_DEACTIVATED
        db_session.commit()

        assert user.status == User.STATUS_DEACTIVATED

    def test_transition_suspended_to_active(self, app, db_session):
        """Suspended user can be reactivated."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='suspended_to_active@example.com',
            password_hash=password_hash,
            name='Suspended User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_SUSPENDED
        )
        db_session.add(user)
        db_session.commit()

        # Transition back to active
        user.status = User.STATUS_ACTIVE
        db_session.commit()

        assert user.status == User.STATUS_ACTIVE


# =============================================================================
# Account Lockout Tests (is_locked method)
# =============================================================================

class TestUserAccountLockout:
    """Tests for User account lockout (is_locked method)."""

    def test_is_locked_when_not_locked(self, app, db_session):
        """User without locked_until should not be locked."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='not_locked@example.com',
            password_hash=password_hash,
            name='Not Locked User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE,
            locked_until=None
        )
        db_session.add(user)
        db_session.commit()

        assert user.is_locked() is False

    def test_is_locked_when_lock_expired(self, app, db_session):
        """User with expired locked_until should not be locked."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        # Lock expired 1 hour ago
        expired_lock = datetime.now(timezone.utc) - timedelta(hours=1)

        user = User(
            email='lock_expired@example.com',
            password_hash=password_hash,
            name='Lock Expired User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE,
            locked_until=expired_lock
        )
        db_session.add(user)
        db_session.commit()

        assert user.is_locked() is False

    def test_is_locked_when_currently_locked(self, app, db_session):
        """User with future locked_until should be locked."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        # Lock expires 1 hour from now
        future_lock = datetime.now(timezone.utc) + timedelta(hours=1)

        user = User(
            email='currently_locked@example.com',
            password_hash=password_hash,
            name='Currently Locked User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE,
            locked_until=future_lock
        )
        db_session.add(user)
        db_session.commit()

        assert user.is_locked() is True

    def test_failed_login_attempts_tracked(self, app, db_session):
        """Failed login attempts should be tracked."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='failed_attempts@example.com',
            password_hash=password_hash,
            name='Failed Attempts User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE,
            failed_login_attempts=0
        )
        db_session.add(user)
        db_session.commit()

        assert user.failed_login_attempts == 0

        # Simulate failed login attempts
        user.failed_login_attempts = 3
        db_session.commit()

        assert user.failed_login_attempts == 3

    def test_lockout_after_max_attempts(self, app, db_session):
        """User should be lockable after too many failed attempts."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='max_attempts@example.com',
            password_hash=password_hash,
            name='Max Attempts User',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE,
            failed_login_attempts=5
        )
        db_session.add(user)
        db_session.commit()

        # Simulate lockout
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=30)
        db_session.commit()

        assert user.is_locked() is True
        assert user.failed_login_attempts == 5


# =============================================================================
# Approval Permission Tests (can_approve_role method)
# =============================================================================

class TestUserCanApproveRole:
    """Tests for User approval permissions (can_approve_role method)."""

    def test_super_admin_can_approve_admin(self, app, db_session):
        """Super Admin should be able to approve Admin."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        super_admin = User(
            email='super_admin_approve@example.com',
            password_hash=password_hash,
            name='Super Admin',
            role=User.ROLE_SUPER_ADMIN,
            status=User.STATUS_ACTIVE
        )
        db_session.add(super_admin)
        db_session.commit()

        assert super_admin.can_approve_role(User.ROLE_ADMIN) is True

    def test_super_admin_can_approve_all_lower_roles(self, app, db_session):
        """Super Admin should be able to approve all roles below them."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        super_admin = User(
            email='super_admin_all@example.com',
            password_hash=password_hash,
            name='Super Admin',
            role=User.ROLE_SUPER_ADMIN,
            status=User.STATUS_ACTIVE
        )
        db_session.add(super_admin)
        db_session.commit()

        assert super_admin.can_approve_role(User.ROLE_ADMIN) is True
        assert super_admin.can_approve_role(User.ROLE_CONTENT_MANAGER) is True
        assert super_admin.can_approve_role(User.ROLE_PARTNER) is True
        assert super_admin.can_approve_role(User.ROLE_ADVERTISER) is True
        assert super_admin.can_approve_role(User.ROLE_VIEWER) is True

    def test_super_admin_cannot_approve_super_admin(self, app, db_session):
        """Super Admin should not be able to approve another Super Admin."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        super_admin = User(
            email='super_admin_self@example.com',
            password_hash=password_hash,
            name='Super Admin',
            role=User.ROLE_SUPER_ADMIN,
            status=User.STATUS_ACTIVE
        )
        db_session.add(super_admin)
        db_session.commit()

        assert super_admin.can_approve_role(User.ROLE_SUPER_ADMIN) is False

    def test_admin_can_approve_lower_roles(self, app, db_session):
        """Admin should be able to approve Content Manager, Partner, Advertiser, Viewer."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        admin = User(
            email='admin_lower@example.com',
            password_hash=password_hash,
            name='Admin',
            role=User.ROLE_ADMIN,
            status=User.STATUS_ACTIVE
        )
        db_session.add(admin)
        db_session.commit()

        assert admin.can_approve_role(User.ROLE_CONTENT_MANAGER) is True
        assert admin.can_approve_role(User.ROLE_PARTNER) is True
        assert admin.can_approve_role(User.ROLE_ADVERTISER) is True
        assert admin.can_approve_role(User.ROLE_VIEWER) is True

    def test_admin_cannot_approve_admin_or_higher(self, app, db_session):
        """Admin should not be able to approve Admin or Super Admin."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        admin = User(
            email='admin_higher@example.com',
            password_hash=password_hash,
            name='Admin',
            role=User.ROLE_ADMIN,
            status=User.STATUS_ACTIVE
        )
        db_session.add(admin)
        db_session.commit()

        assert admin.can_approve_role(User.ROLE_SUPER_ADMIN) is False
        assert admin.can_approve_role(User.ROLE_ADMIN) is False

    def test_content_manager_can_approve_lower_roles(self, app, db_session):
        """Content Manager should be able to approve Partner, Advertiser, Viewer."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        cm = User(
            email='cm_lower@example.com',
            password_hash=password_hash,
            name='Content Manager',
            role=User.ROLE_CONTENT_MANAGER,
            status=User.STATUS_ACTIVE
        )
        db_session.add(cm)
        db_session.commit()

        assert cm.can_approve_role(User.ROLE_PARTNER) is True
        assert cm.can_approve_role(User.ROLE_ADVERTISER) is True
        assert cm.can_approve_role(User.ROLE_VIEWER) is True

    def test_content_manager_cannot_approve_higher_roles(self, app, db_session):
        """Content Manager should not be able to approve higher roles."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        cm = User(
            email='cm_higher@example.com',
            password_hash=password_hash,
            name='Content Manager',
            role=User.ROLE_CONTENT_MANAGER,
            status=User.STATUS_ACTIVE
        )
        db_session.add(cm)
        db_session.commit()

        assert cm.can_approve_role(User.ROLE_SUPER_ADMIN) is False
        assert cm.can_approve_role(User.ROLE_ADMIN) is False
        assert cm.can_approve_role(User.ROLE_CONTENT_MANAGER) is False

    def test_partner_can_approve_advertiser_and_viewer(self, app, db_session):
        """Partner should be able to approve Advertiser and Viewer."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        partner = User(
            email='partner_approve@example.com',
            password_hash=password_hash,
            name='Partner',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE
        )
        db_session.add(partner)
        db_session.commit()

        assert partner.can_approve_role(User.ROLE_ADVERTISER) is True
        assert partner.can_approve_role(User.ROLE_VIEWER) is True

    def test_advertiser_can_approve_viewer_only(self, app, db_session):
        """Advertiser should only be able to approve Viewer."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        advertiser = User(
            email='advertiser_approve@example.com',
            password_hash=password_hash,
            name='Advertiser',
            role=User.ROLE_ADVERTISER,
            status=User.STATUS_ACTIVE
        )
        db_session.add(advertiser)
        db_session.commit()

        assert advertiser.can_approve_role(User.ROLE_VIEWER) is True
        assert advertiser.can_approve_role(User.ROLE_ADVERTISER) is False
        assert advertiser.can_approve_role(User.ROLE_PARTNER) is False

    def test_viewer_cannot_approve_anyone(self, app, db_session):
        """Viewer should not be able to approve any role."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        viewer = User(
            email='viewer_approve@example.com',
            password_hash=password_hash,
            name='Viewer',
            role=User.ROLE_VIEWER,
            status=User.STATUS_ACTIVE
        )
        db_session.add(viewer)
        db_session.commit()

        for role in User.VALID_ROLES:
            assert viewer.can_approve_role(role) is False

    def test_can_approve_role_with_invalid_target_role(self, app, db_session):
        """can_approve_role should return False for invalid target role."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        super_admin = User(
            email='super_admin_invalid@example.com',
            password_hash=password_hash,
            name='Super Admin',
            role=User.ROLE_SUPER_ADMIN,
            status=User.STATUS_ACTIVE
        )
        db_session.add(super_admin)
        db_session.commit()

        assert super_admin.can_approve_role('invalid_role') is False

    def test_can_approve_role_with_invalid_user_role(self, app, db_session):
        """can_approve_role should return False if user has invalid role."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        # Create user with invalid role (bypassing normal validation)
        user = User(
            email='invalid_role_user@example.com',
            password_hash=password_hash,
            name='Invalid Role User',
            role='invalid_role',
            status=User.STATUS_ACTIVE
        )
        db_session.add(user)
        db_session.commit()

        assert user.can_approve_role(User.ROLE_VIEWER) is False


# =============================================================================
# Serialization Tests (to_dict method)
# =============================================================================

class TestUserToDict:
    """Tests for User to_dict serialization method."""

    def test_to_dict_includes_required_fields(self, app, db_session):
        """to_dict should include all required fields."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='to_dict_test@example.com',
            password_hash=password_hash,
            name='To Dict Test',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE
        )
        db_session.add(user)
        db_session.commit()

        result = user.to_dict()

        assert 'id' in result
        assert 'email' in result
        assert 'name' in result
        assert 'role' in result
        assert 'status' in result
        assert 'created_at' in result

    def test_to_dict_excludes_sensitive_fields(self, app, db_session):
        """to_dict should not include password_hash or two_factor_secret."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='exclude_sensitive@example.com',
            password_hash=password_hash,
            name='Sensitive Test',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE,
            two_factor_secret='SECRETKEY123'
        )
        db_session.add(user)
        db_session.commit()

        result = user.to_dict()

        assert 'password_hash' not in result
        assert 'two_factor_secret' not in result

    def test_to_dict_formats_timestamps(self, app, db_session):
        """to_dict should format timestamps as ISO format strings."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')
        now = datetime.now(timezone.utc)

        user = User(
            email='timestamp_test@example.com',
            password_hash=password_hash,
            name='Timestamp Test',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE,
            approved_at=now,
            last_login=now
        )
        db_session.add(user)
        db_session.commit()

        result = user.to_dict()

        # Timestamps should be ISO format strings or None
        assert result['approved_at'] is not None
        assert isinstance(result['approved_at'], str)
        assert result['last_login'] is not None
        assert isinstance(result['last_login'], str)

    def test_to_dict_handles_none_timestamps(self, app, db_session):
        """to_dict should handle None timestamps gracefully."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='none_timestamp@example.com',
            password_hash=password_hash,
            name='None Timestamp Test',
            role=User.ROLE_PARTNER,
            status=User.STATUS_PENDING,
            approved_at=None,
            last_login=None
        )
        db_session.add(user)
        db_session.commit()

        result = user.to_dict()

        assert result['approved_at'] is None
        assert result['last_login'] is None

    def test_to_dict_includes_relationship_ids(self, app, db_session, sample_organization, sample_super_admin):
        """to_dict should include relationship foreign keys."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='relationship_test@example.com',
            password_hash=password_hash,
            name='Relationship Test',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE,
            organization_id=sample_organization.id,
            invited_by=sample_super_admin.id,
            approved_by=sample_super_admin.id
        )
        db_session.add(user)
        db_session.commit()

        result = user.to_dict()

        assert result['organization_id'] == sample_organization.id
        assert result['invited_by'] == sample_super_admin.id
        assert result['approved_by'] == sample_super_admin.id

    def test_to_dict_includes_two_factor_enabled(self, app, db_session):
        """to_dict should include two_factor_enabled boolean (but not secret)."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='2fa_test@example.com',
            password_hash=password_hash,
            name='2FA Test',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE,
            two_factor_enabled=True,
            two_factor_secret='SECRETKEY123'
        )
        db_session.add(user)
        db_session.commit()

        result = user.to_dict()

        assert result['two_factor_enabled'] is True
        assert 'two_factor_secret' not in result


# =============================================================================
# User Repr Tests
# =============================================================================

class TestUserRepr:
    """Tests for User string representation."""

    def test_repr_contains_email(self, app, db_session):
        """User repr should contain the email address."""
        password_hash = bcrypt.hashpw('test'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        user = User(
            email='repr_test@example.com',
            password_hash=password_hash,
            name='Repr Test',
            role=User.ROLE_PARTNER,
            status=User.STATUS_ACTIVE
        )
        db_session.add(user)
        db_session.commit()

        repr_str = repr(user)

        assert 'repr_test@example.com' in repr_str
        assert '<User' in repr_str
