"""
End-to-end tests for User Invitation -> Registration -> Approval -> Login flow.

This test module verifies the complete user onboarding workflow:
1. Super Admin logs in
2. Super Admin creates an invitation for a new Admin
3. New user accepts invitation and registers
4. Super Admin approves the user (if pending)
5. New Admin can log in and access the system

Also tests the related approval workflow for users created with pending status.
"""

import pytest

from content_catalog.models import db, User, UserInvitation, Organization, AuditLog
from content_catalog.tests.conftest import TEST_PASSWORD, get_auth_headers


class TestUserInvitationApprovalFlow:
    """
    End-to-end test for the complete user invitation flow.

    Verifies that:
    - Super Admin can log in
    - Super Admin can create invitations for Admin role
    - Invitations generate valid tokens
    - Users can accept invitations and register
    - Users can log in after registration
    """

    def test_complete_invitation_flow_for_admin(self, client, app, sample_super_admin, sample_internal_organization):
        """
        E2E test: Super Admin invites Admin -> Admin registers -> Admin can login.

        Steps:
        1. Login as Super Admin
        2. Create invitation for Admin role
        3. Accept invitation and register with password
        4. New Admin can login
        """
        # =========================================================================
        # Step 1: Login as Super Admin
        # =========================================================================
        login_response = client.post('/admin/api/login', json={
            'email': sample_super_admin.email,
            'password': TEST_PASSWORD
        })

        assert login_response.status_code == 200, f"Super Admin login failed: {login_response.get_json()}"
        super_admin_token = login_response.get_json()['access_token']

        # Verify Super Admin can access /me endpoint
        me_response = client.get('/admin/api/me', headers=get_auth_headers(super_admin_token))
        assert me_response.status_code == 200
        assert me_response.get_json()['role'] == User.ROLE_SUPER_ADMIN

        # =========================================================================
        # Step 2: Create invitation for Admin
        # =========================================================================
        new_admin_email = 'new.admin@skillzmedia.com'

        create_invitation_response = client.post(
            '/api/v1/invitations',
            headers=get_auth_headers(super_admin_token),
            json={
                'email': new_admin_email,
                'role': User.ROLE_ADMIN,
                'organization_id': sample_internal_organization.id
            }
        )

        assert create_invitation_response.status_code == 201, \
            f"Create invitation failed: {create_invitation_response.get_json()}"

        invitation_data = create_invitation_response.get_json()
        assert invitation_data['email'] == new_admin_email
        assert invitation_data['role'] == User.ROLE_ADMIN
        assert invitation_data['status'] == UserInvitation.STATUS_PENDING
        invitation_id = invitation_data['id']

        # Get the token from the database (not exposed in API response for security)
        with app.app_context():
            invitation = db.session.get(UserInvitation, invitation_id)
            invitation_token = invitation.token
            assert invitation_token is not None

        # =========================================================================
        # Step 3: Accept invitation and register
        # =========================================================================
        new_admin_password = 'NewAdmin123!'
        new_admin_name = 'New Admin User'

        accept_response = client.post(
            f'/api/v1/invitations/{invitation_token}/accept',
            json={
                'password': new_admin_password,
                'name': new_admin_name,
                'phone': '+1234567890'
            }
        )

        assert accept_response.status_code == 201, \
            f"Accept invitation failed: {accept_response.get_json()}"

        accept_data = accept_response.get_json()
        assert accept_data['message'] == 'Invitation accepted successfully'
        assert accept_data['user']['email'] == new_admin_email
        assert accept_data['user']['role'] == User.ROLE_ADMIN
        assert accept_data['user']['name'] == new_admin_name
        new_admin_id = accept_data['user']['id']

        # Verify invitation is now marked as accepted
        with app.app_context():
            invitation = db.session.get(UserInvitation, invitation_id)
            assert invitation.status == UserInvitation.STATUS_ACCEPTED
            assert invitation.accepted_at is not None

        # =========================================================================
        # Step 4: Verify user status (invited users are active immediately)
        # =========================================================================
        with app.app_context():
            new_admin = db.session.get(User, new_admin_id)
            # Invited users become active immediately upon accepting invitation
            assert new_admin.status == User.STATUS_ACTIVE
            assert new_admin.invited_by == sample_super_admin.id

        # =========================================================================
        # Step 5: New Admin can login
        # =========================================================================
        new_admin_login_response = client.post('/admin/api/login', json={
            'email': new_admin_email,
            'password': new_admin_password
        })

        assert new_admin_login_response.status_code == 200, \
            f"New Admin login failed: {new_admin_login_response.get_json()}"

        new_admin_token = new_admin_login_response.get_json()['access_token']

        # Verify new Admin can access protected resources
        new_admin_me_response = client.get('/admin/api/me', headers=get_auth_headers(new_admin_token))
        assert new_admin_me_response.status_code == 200
        assert new_admin_me_response.get_json()['email'] == new_admin_email
        assert new_admin_me_response.get_json()['role'] == User.ROLE_ADMIN

    def test_complete_invitation_flow_for_partner(self, client, app, sample_admin, sample_organization):
        """
        E2E test: Admin invites Partner -> Partner registers -> Partner can login.

        Steps:
        1. Login as Admin
        2. Create invitation for Partner role
        3. Accept invitation and register
        4. New Partner can login
        """
        # Step 1: Login as Admin
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })

        assert login_response.status_code == 200
        admin_token = login_response.get_json()['access_token']

        # Step 2: Create invitation for Partner
        new_partner_email = 'new.partner@testorg.com'

        create_invitation_response = client.post(
            '/api/v1/invitations',
            headers=get_auth_headers(admin_token),
            json={
                'email': new_partner_email,
                'role': User.ROLE_PARTNER,
                'organization_id': sample_organization.id
            }
        )

        assert create_invitation_response.status_code == 201
        invitation_id = create_invitation_response.get_json()['id']

        with app.app_context():
            invitation = db.session.get(UserInvitation, invitation_id)
            invitation_token = invitation.token

        # Step 3: Accept invitation and register
        accept_response = client.post(
            f'/api/v1/invitations/{invitation_token}/accept',
            json={
                'password': 'Partner123!',
                'name': 'New Partner User'
            }
        )

        assert accept_response.status_code == 201

        # Step 4: New Partner can login
        partner_login_response = client.post('/admin/api/login', json={
            'email': new_partner_email,
            'password': 'Partner123!'
        })

        assert partner_login_response.status_code == 200
        partner_token = partner_login_response.get_json()['access_token']

        # Verify partner can access /me
        me_response = client.get('/admin/api/me', headers=get_auth_headers(partner_token))
        assert me_response.status_code == 200
        assert me_response.get_json()['role'] == User.ROLE_PARTNER


class TestPendingUserApprovalFlow:
    """
    End-to-end test for the user approval workflow.

    Tests the flow where a user is created with pending status
    and must be approved before they can login.
    """

    def test_pending_user_cannot_login_until_approved(self, client, app, db_session,
                                                       sample_super_admin, sample_organization):
        """
        E2E test: Pending user cannot login -> Super Admin approves -> User can login.

        Steps:
        1. Create a pending user directly in database
        2. Verify pending user cannot login
        3. Super Admin logs in
        4. Super Admin approves the pending user
        5. Approved user can now login
        """
        # =========================================================================
        # Step 1: Create a pending user
        # =========================================================================
        import bcrypt
        pending_user_email = 'pending.test@testorg.com'
        pending_user_password = 'PendingUser123!'
        password_hash = bcrypt.hashpw(
            pending_user_password.encode('utf-8'),
            bcrypt.gensalt(rounds=4)
        ).decode('utf-8')

        pending_user = User(
            email=pending_user_email,
            password_hash=password_hash,
            name='Pending Test User',
            role=User.ROLE_PARTNER,
            organization_id=sample_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(pending_user)
        db_session.commit()
        pending_user_id = pending_user.id

        # =========================================================================
        # Step 2: Verify pending user cannot login
        # =========================================================================
        pending_login_response = client.post('/admin/api/login', json={
            'email': pending_user_email,
            'password': pending_user_password
        })

        assert pending_login_response.status_code == 401
        assert 'pending approval' in pending_login_response.get_json()['error']

        # =========================================================================
        # Step 3: Super Admin logs in
        # =========================================================================
        super_admin_login_response = client.post('/admin/api/login', json={
            'email': sample_super_admin.email,
            'password': TEST_PASSWORD
        })

        assert super_admin_login_response.status_code == 200
        super_admin_token = super_admin_login_response.get_json()['access_token']

        # =========================================================================
        # Step 4: Super Admin approves the pending user
        # =========================================================================
        approve_response = client.post(
            f'/api/v1/approvals/{pending_user_id}/approve',
            headers=get_auth_headers(super_admin_token),
            json={'notes': 'Approved after verification'}
        )

        assert approve_response.status_code == 200, \
            f"Approval failed: {approve_response.get_json()}"

        approve_data = approve_response.get_json()
        assert approve_data['message'] == 'User approved successfully'
        assert approve_data['user']['status'] == User.STATUS_ACTIVE

        # Verify in database
        with app.app_context():
            approved_user = db.session.get(User, pending_user_id)
            assert approved_user.status == User.STATUS_ACTIVE
            assert approved_user.approved_by == sample_super_admin.id
            assert approved_user.approved_at is not None

        # =========================================================================
        # Step 5: Approved user can now login
        # =========================================================================
        approved_login_response = client.post('/admin/api/login', json={
            'email': pending_user_email,
            'password': pending_user_password
        })

        assert approved_login_response.status_code == 200, \
            f"Approved user login failed: {approved_login_response.get_json()}"

        approved_token = approved_login_response.get_json()['access_token']

        # Verify user can access protected resources
        me_response = client.get('/admin/api/me', headers=get_auth_headers(approved_token))
        assert me_response.status_code == 200
        assert me_response.get_json()['email'] == pending_user_email

    def test_admin_approves_content_manager(self, client, app, db_session,
                                            sample_admin, sample_internal_organization):
        """
        E2E test: Admin creates and approves Content Manager.

        Tests the role hierarchy where Admin can approve Content Manager.
        """
        import bcrypt

        # Create pending content manager
        cm_email = 'pending.cm@skillzmedia.com'
        cm_password = 'ContentMgr123!'
        password_hash = bcrypt.hashpw(cm_password.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        pending_cm = User(
            email=cm_email,
            password_hash=password_hash,
            name='Pending Content Manager',
            role=User.ROLE_CONTENT_MANAGER,
            organization_id=sample_internal_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(pending_cm)
        db_session.commit()
        cm_id = pending_cm.id

        # Admin logs in
        admin_login = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        assert admin_login.status_code == 200
        admin_token = admin_login.get_json()['access_token']

        # Admin approves content manager
        approve_response = client.post(
            f'/api/v1/approvals/{cm_id}/approve',
            headers=get_auth_headers(admin_token)
        )
        assert approve_response.status_code == 200

        # Content manager can now login
        cm_login = client.post('/admin/api/login', json={
            'email': cm_email,
            'password': cm_password
        })
        assert cm_login.status_code == 200
        assert cm_login.get_json()['user']['role'] == User.ROLE_CONTENT_MANAGER


class TestRoleHierarchyEnforcement:
    """
    Tests that verify role hierarchy is enforced during invitation and approval.
    """

    def test_partner_cannot_invite_admin(self, client, app, sample_partner, sample_organization):
        """Verify Partner cannot create invitation for Admin role."""
        # Partner logs in
        login_response = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        assert login_response.status_code == 200
        partner_token = login_response.get_json()['access_token']

        # Partner tries to invite Admin (should fail)
        invite_response = client.post(
            '/api/v1/invitations',
            headers=get_auth_headers(partner_token),
            json={
                'email': 'would-be-admin@test.com',
                'role': User.ROLE_ADMIN,
                'organization_id': sample_organization.id
            }
        )

        assert invite_response.status_code == 403
        assert 'Insufficient permissions' in invite_response.get_json()['error']

    def test_content_manager_cannot_approve_admin(self, client, app, db_session,
                                                   sample_content_manager, sample_internal_organization):
        """Verify Content Manager cannot approve Admin role users."""
        import bcrypt

        # Create pending admin
        admin_email = 'pending.admin@skillzmedia.com'
        admin_password = 'PendingAdmin123!'
        password_hash = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        pending_admin = User(
            email=admin_email,
            password_hash=password_hash,
            name='Pending Admin',
            role=User.ROLE_ADMIN,
            organization_id=sample_internal_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(pending_admin)
        db_session.commit()
        admin_id = pending_admin.id

        # Content Manager logs in
        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        assert cm_login.status_code == 200
        cm_token = cm_login.get_json()['access_token']

        # Content Manager tries to approve Admin (should fail)
        approve_response = client.post(
            f'/api/v1/approvals/{admin_id}/approve',
            headers=get_auth_headers(cm_token)
        )

        assert approve_response.status_code == 403
        assert 'Insufficient permissions' in approve_response.get_json()['error']

    def test_super_admin_can_approve_admin(self, client, app, db_session,
                                           sample_super_admin, sample_internal_organization):
        """Verify Super Admin can approve Admin role users."""
        import bcrypt

        # Create pending admin
        admin_email = 'pending.admin2@skillzmedia.com'
        admin_password = 'PendingAdmin123!'
        password_hash = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        pending_admin = User(
            email=admin_email,
            password_hash=password_hash,
            name='Pending Admin 2',
            role=User.ROLE_ADMIN,
            organization_id=sample_internal_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(pending_admin)
        db_session.commit()
        admin_id = pending_admin.id

        # Super Admin logs in
        sa_login = client.post('/admin/api/login', json={
            'email': sample_super_admin.email,
            'password': TEST_PASSWORD
        })
        assert sa_login.status_code == 200
        sa_token = sa_login.get_json()['access_token']

        # Super Admin approves Admin
        approve_response = client.post(
            f'/api/v1/approvals/{admin_id}/approve',
            headers=get_auth_headers(sa_token)
        )

        assert approve_response.status_code == 200
        assert approve_response.get_json()['user']['status'] == User.STATUS_ACTIVE


class TestUserRejectionFlow:
    """
    Tests the user rejection workflow.
    """

    def test_reject_pending_user(self, client, app, db_session,
                                  sample_super_admin, sample_organization):
        """
        E2E test: Pending user is rejected -> User cannot login.
        """
        import bcrypt

        # Create pending user
        user_email = 'to-reject@testorg.com'
        user_password = 'ToReject123!'
        password_hash = bcrypt.hashpw(user_password.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')

        pending_user = User(
            email=user_email,
            password_hash=password_hash,
            name='User To Reject',
            role=User.ROLE_PARTNER,
            organization_id=sample_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(pending_user)
        db_session.commit()
        user_id = pending_user.id

        # Super Admin logs in
        sa_login = client.post('/admin/api/login', json={
            'email': sample_super_admin.email,
            'password': TEST_PASSWORD
        })
        sa_token = sa_login.get_json()['access_token']

        # Super Admin rejects the user
        reject_response = client.post(
            f'/api/v1/approvals/{user_id}/reject',
            headers=get_auth_headers(sa_token),
            json={'reason': 'Failed background check'}
        )

        assert reject_response.status_code == 200
        assert reject_response.get_json()['user']['status'] == User.STATUS_REJECTED

        # Verify rejected user cannot login
        login_response = client.post('/admin/api/login', json={
            'email': user_email,
            'password': user_password
        })

        assert login_response.status_code == 401
        assert 'rejected' in login_response.get_json()['error']


class TestInvitationEdgeCases:
    """
    Tests edge cases in the invitation flow.
    """

    def test_expired_invitation_cannot_be_accepted(self, client, app, sample_expired_invitation):
        """Verify expired invitation cannot be accepted."""
        accept_response = client.post(
            f'/api/v1/invitations/{sample_expired_invitation.token}/accept',
            json={
                'password': 'SomePassword123!',
                'name': 'Would-be User'
            }
        )

        assert accept_response.status_code == 410
        assert 'expired' in accept_response.get_json()['error'].lower()

    def test_cannot_accept_same_invitation_twice(self, client, app, db_session,
                                                  sample_admin, sample_organization):
        """Verify invitation can only be accepted once."""
        from datetime import datetime, timedelta, timezone
        import secrets

        # Create a valid invitation
        invitation = UserInvitation(
            email='double-accept@test.com',
            role=User.ROLE_PARTNER,
            organization_id=sample_organization.id,
            invited_by=sample_admin.id,
            token=secrets.token_urlsafe(32),
            status=UserInvitation.STATUS_PENDING,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        db_session.add(invitation)
        db_session.commit()
        token = invitation.token

        # First acceptance should succeed
        first_accept = client.post(
            f'/api/v1/invitations/{token}/accept',
            json={
                'password': 'FirstAccept123!',
                'name': 'First Accepter'
            }
        )
        assert first_accept.status_code == 201

        # Second acceptance should fail
        second_accept = client.post(
            f'/api/v1/invitations/{token}/accept',
            json={
                'password': 'SecondAccept123!',
                'name': 'Second Accepter'
            }
        )
        assert second_accept.status_code == 410
        assert 'no longer valid' in second_accept.get_json()['error']

    def test_invalid_token_returns_404(self, client, app):
        """Verify invalid invitation token returns 404."""
        accept_response = client.post(
            '/api/v1/invitations/invalid-token-that-does-not-exist/accept',
            json={
                'password': 'SomePassword123!',
                'name': 'Some User'
            }
        )

        assert accept_response.status_code == 404
        assert 'not found' in accept_response.get_json()['error'].lower()


class TestAuditLogging:
    """
    Verify that audit logs are created during the invitation/approval flow.
    """

    def test_invitation_creates_audit_log(self, client, app, db_session,
                                          sample_super_admin, sample_internal_organization):
        """Verify invitation creation is logged."""
        # Login as Super Admin
        login_response = client.post('/admin/api/login', json={
            'email': sample_super_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Count existing audit logs
        with app.app_context():
            initial_count = AuditLog.query.filter_by(action='invitation.created').count()

        # Create invitation
        create_response = client.post(
            '/api/v1/invitations',
            headers=get_auth_headers(token),
            json={
                'email': 'audit-test-invite@skillzmedia.com',
                'role': User.ROLE_PARTNER,
                'organization_id': sample_internal_organization.id
            }
        )
        assert create_response.status_code == 201

        # Verify audit log was created
        with app.app_context():
            final_count = AuditLog.query.filter_by(action='invitation.created').count()
            assert final_count == initial_count + 1

    def test_approval_creates_audit_log(self, client, app, db_session,
                                        sample_super_admin, sample_organization):
        """Verify user approval is logged."""
        import bcrypt

        # Create pending user
        password_hash = bcrypt.hashpw('Test123!'.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')
        pending_user = User(
            email='audit-test-approve@test.com',
            password_hash=password_hash,
            name='Audit Test User',
            role=User.ROLE_PARTNER,
            organization_id=sample_organization.id,
            status=User.STATUS_PENDING
        )
        db_session.add(pending_user)
        db_session.commit()
        user_id = pending_user.id

        # Login as Super Admin
        login_response = client.post('/admin/api/login', json={
            'email': sample_super_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Count existing audit logs
        with app.app_context():
            initial_count = AuditLog.query.filter_by(action='user.approved').count()

        # Approve user
        approve_response = client.post(
            f'/api/v1/approvals/{user_id}/approve',
            headers=get_auth_headers(token)
        )
        assert approve_response.status_code == 200

        # Verify audit log was created
        with app.app_context():
            final_count = AuditLog.query.filter_by(action='user.approved').count()
            assert final_count == initial_count + 1

            # Verify log details
            log = AuditLog.query.filter_by(action='user.approved').order_by(AuditLog.id.desc()).first()
            assert log.user_id == sample_super_admin.id
            assert log.resource_type == 'user'
            assert log.resource_id == str(user_id)
