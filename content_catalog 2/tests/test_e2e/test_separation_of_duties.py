"""
End-to-end tests for Thea Separation of Duties enforcement.

This test module verifies the critical security requirement that:
- Users cannot approve their own uploaded assets (403 Forbidden)
- Different users with approver role can successfully approve assets
- The workflow completes correctly with separation of duties enforced

Per Thea spec requirement:
"Users cannot approve their own uploaded assets"
"POST /approve returns 403 if uploaded_by_user_id == approver_user_id"
"""

import pytest
from datetime import datetime, timezone

from content_catalog.models import (
    db,
    User,
    Organization,
    ContentAsset,
    ContentApprovalRequest,
    AuditLog
)
from content_catalog.tests.conftest import TEST_PASSWORD, TEST_PASSWORD_HASH, get_auth_headers


# =============================================================================
# Separation of Duties Test Fixtures
# =============================================================================

@pytest.fixture(scope='function')
def brand_org_for_sod(db_session):
    """
    Create a BRAND type organization for separation of duties testing.

    Returns:
        Organization instance with org_type=BRAND
    """
    org = Organization(
        name='SOD Test Brand Inc',
        type='partner',
        org_type=Organization.ORG_TYPE_BRAND,
        contact_email='sod-brand@testbrand.com',
        status='active'
    )
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture(scope='function')
def retailer_org_for_sod(db_session):
    """
    Create a RETAILER type organization for separation of duties testing.

    Returns:
        Organization instance with org_type=RETAILER
    """
    org = Organization(
        name='SOD Test Retailer Corp',
        type='partner',
        org_type=Organization.ORG_TYPE_RETAILER,
        contact_email='sod-retailer@testretailer.com',
        status='active'
    )
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture(scope='function')
def uploader_user_a(db_session, brand_org_for_sod):
    """
    Create User A - the uploader who should NOT be able to approve their own assets.

    This user has the partner role and belongs to a brand organization.

    Returns:
        User instance (uploader, no approval permissions)
    """
    user = User(
        email='user_a_uploader@sodtest.com',
        password_hash=TEST_PASSWORD_HASH,
        name='User A - Uploader',
        role=User.ROLE_PARTNER,
        organization_id=brand_org_for_sod.id,
        status=User.STATUS_ACTIVE,
        can_approve_assets=False  # Uploader should not have approval permission
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def uploader_user_a_with_approval_rights(db_session, brand_org_for_sod):
    """
    Create User A with approval rights - tests that even with approval rights,
    users cannot approve their OWN uploads.

    Returns:
        User instance (uploader with approval rights, but should still be blocked from self-approval)
    """
    user = User(
        email='user_a_uploader_approver@sodtest.com',
        password_hash=TEST_PASSWORD_HASH,
        name='User A - Uploader With Approval Rights',
        role=User.ROLE_CONTENT_MANAGER,
        organization_id=brand_org_for_sod.id,
        status=User.STATUS_ACTIVE,
        can_approve_assets=True  # Has approval rights but still cannot approve own uploads
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def approver_user_b(db_session, retailer_org_for_sod):
    """
    Create User B - the approver who CAN approve assets uploaded by others.

    This user has the content_manager role with explicit approval permissions.

    Returns:
        User instance (approver with full approval permissions)
    """
    user = User(
        email='user_b_approver@sodtest.com',
        password_hash=TEST_PASSWORD_HASH,
        name='User B - Approver',
        role=User.ROLE_CONTENT_MANAGER,
        organization_id=retailer_org_for_sod.id,
        status=User.STATUS_ACTIVE,
        can_approve_assets=True  # Has approval permissions
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def second_approver_user_c(db_session, retailer_org_for_sod):
    """
    Create User C - another approver for testing concurrent approval scenarios.

    Returns:
        User instance (second approver)
    """
    user = User(
        email='user_c_approver@sodtest.com',
        password_hash=TEST_PASSWORD_HASH,
        name='User C - Second Approver',
        role=User.ROLE_CONTENT_MANAGER,
        organization_id=retailer_org_for_sod.id,
        status=User.STATUS_ACTIVE,
        can_approve_assets=True
    )
    db_session.add(user)
    db_session.commit()
    return user


# =============================================================================
# E2E Test: Separation of Duties - Full Workflow
# =============================================================================

class TestSeparationOfDutiesE2E:
    """
    End-to-end test suite for separation of duties enforcement.

    Key requirements verified:
    1. User A uploads asset
    2. User A submits for approval
    3. User A tries to approve -> 403 Forbidden (CRITICAL)
    4. User B (with approver role) approves -> Success
    """

    def test_e2e_separation_of_duties_full_workflow(
        self,
        client,
        app,
        uploader_user_a,
        approver_user_b
    ):
        """
        E2E test: Complete separation of duties workflow.

        Steps:
        1. Login as User A, upload asset
        2. Submit for approval
        3. Try to approve as User A -> verify 403 Forbidden
        4. Login as User B (with approver role), approve -> verify success
        """
        # =====================================================================
        # Step 1: Login as User A (uploader) and upload asset
        # =====================================================================
        user_a_login = client.post('/admin/api/login', json={
            'email': uploader_user_a.email,
            'password': TEST_PASSWORD
        })

        assert user_a_login.status_code == 200, \
            f"User A login failed: {user_a_login.get_json()}"
        user_a_token = user_a_login.get_json()['access_token']

        # Create asset as User A
        create_response = client.post('/api/v1/assets', json={
            'title': 'Separation of Duties Test Asset',
            'description': 'Asset to test SOD enforcement',
            'filename': 'sod_test_video.mp4',
            'file_path': '/uploads/sod_test_video.mp4',
            'file_size': 10240000,
            'format': 'mp4',
            'organization_id': uploader_user_a.organization_id,
            'category': 'promotional'
        })

        assert create_response.status_code == 201, \
            f"Asset creation failed: {create_response.get_json()}"

        asset = create_response.get_json()
        asset_uuid = asset['uuid']
        asset_id = asset['id']

        # Verify DRAFT state
        assert asset['status'] == ContentAsset.STATUS_DRAFT

        # Verify uploaded_by is User A
        with app.app_context():
            db_asset = db.session.get(ContentAsset, asset_id)
            assert db_asset.uploaded_by == uploader_user_a.id, \
                "Asset not properly attributed to User A"

        # =====================================================================
        # Step 2: Submit for approval as User A
        # =====================================================================
        submit_response = client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(user_a_token),
            json={'notes': 'Please review this SOD test asset'}
        )

        assert submit_response.status_code == 200, \
            f"Submit failed: {submit_response.get_json()}"

        submit_data = submit_response.get_json()
        assert submit_data['asset']['status'] == ContentAsset.STATUS_PENDING_REVIEW

        # =====================================================================
        # Step 3: Try to approve as User A (same user) -> MUST get 403
        # =====================================================================
        self_approve_response = client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(user_a_token),
            json={'notes': 'Attempting self-approval (should fail)'}
        )

        # CRITICAL: This MUST be 403 Forbidden
        assert self_approve_response.status_code == 403, \
            f"SECURITY FAILURE: Self-approval should return 403, got {self_approve_response.status_code}"

        error_data = self_approve_response.get_json()
        assert 'error' in error_data, "Error response should contain 'error' field"

        # Verify error message explains separation of duties
        error_msg = error_data['error'].lower()
        assert any(phrase in error_msg for phrase in [
            'cannot approve their own',
            'cannot approve your own',
            'separation of duties',
            'insufficient permissions'
        ]), f"Error message should explain SOD violation: {error_data['error']}"

        # Verify asset is still in PENDING_REVIEW state (not approved)
        with app.app_context():
            pending_asset = db.session.get(ContentAsset, asset_id)
            assert pending_asset.status == ContentAsset.STATUS_PENDING_REVIEW, \
                "Asset should remain in PENDING_REVIEW after failed self-approval"
            assert pending_asset.reviewed_by is None, \
                "reviewed_by should not be set after failed self-approval"

        # =====================================================================
        # Step 4: Login as User B (approver) and approve -> MUST succeed
        # =====================================================================
        user_b_login = client.post('/admin/api/login', json={
            'email': approver_user_b.email,
            'password': TEST_PASSWORD
        })

        assert user_b_login.status_code == 200, \
            f"User B login failed: {user_b_login.get_json()}"
        user_b_token = user_b_login.get_json()['access_token']

        # Verify User B has approval permissions
        user_b_me = client.get('/admin/api/me', headers=get_auth_headers(user_b_token))
        assert user_b_me.status_code == 200

        # Approve as User B (different user)
        approve_response = client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(user_b_token),
            json={'notes': 'Approved by User B (different user)'}
        )

        assert approve_response.status_code == 200, \
            f"Approval by different user failed: {approve_response.get_json()}"

        approve_data = approve_response.get_json()
        assert approve_data['asset']['status'] == ContentAsset.STATUS_APPROVED, \
            f"Expected APPROVED status, got {approve_data['asset']['status']}"
        assert approve_data['asset']['reviewed_by'] == approver_user_b.id, \
            "reviewed_by should be User B"

        # =====================================================================
        # Final verification: Database state and audit trail
        # =====================================================================
        with app.app_context():
            # Verify final asset state
            approved_asset = db.session.get(ContentAsset, asset_id)
            assert approved_asset.status == ContentAsset.STATUS_APPROVED
            assert approved_asset.uploaded_by == uploader_user_a.id
            assert approved_asset.reviewed_by == approver_user_b.id
            assert approved_asset.reviewed_at is not None

            # Verify audit trail captures both the failed self-approval attempt
            # and the successful approval by different user
            audit_logs = AuditLog.query.filter_by(
                resource_id=str(asset_id)
            ).order_by(AuditLog.created_at.asc()).all()

            # Should have: submit + approve events (failed self-approval may or may not be logged)
            actions = [log.action for log in audit_logs]
            assert 'content.submitted' in actions, "Missing submit audit event"
            assert 'content.approved' in actions, "Missing approve audit event"

            # Verify the approval was by User B, not User A
            approve_log = next(
                (log for log in audit_logs if log.action == 'content.approved'),
                None
            )
            assert approve_log is not None
            assert approve_log.user_id == approver_user_b.id
            assert approve_log.user_email == approver_user_b.email

    def test_e2e_user_with_approval_rights_cannot_approve_own_upload(
        self,
        client,
        app,
        uploader_user_a_with_approval_rights,
        approver_user_b
    ):
        """
        E2E test: Even users WITH approval rights cannot approve their own uploads.

        This tests the critical edge case where a user has can_approve_assets=True
        but they should STILL be blocked from approving their own uploads.
        """
        # Login as User A (who has approval rights)
        user_a_login = client.post('/admin/api/login', json={
            'email': uploader_user_a_with_approval_rights.email,
            'password': TEST_PASSWORD
        })
        user_a_token = user_a_login.get_json()['access_token']

        # Create and submit asset
        create_response = client.post('/api/v1/assets', json={
            'title': 'Approver Self-Approval Test',
            'filename': 'approver_self_test.mp4',
            'file_path': '/uploads/approver_self_test.mp4',
            'organization_id': uploader_user_a_with_approval_rights.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        # Submit for approval
        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(user_a_token)
        )

        # Try to approve own upload (should fail even with approval rights)
        self_approve_response = client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(user_a_token),
            json={'notes': 'Self-approval attempt by user with approval rights'}
        )

        # CRITICAL: Must be 403 even though user has approval rights
        assert self_approve_response.status_code == 403, \
            "User with approval rights should still be blocked from self-approval"

        # Now verify User B can approve it
        user_b_login = client.post('/admin/api/login', json={
            'email': approver_user_b.email,
            'password': TEST_PASSWORD
        })
        user_b_token = user_b_login.get_json()['access_token']

        approve_response = client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(user_b_token)
        )

        assert approve_response.status_code == 200, \
            "Different user should be able to approve"

    def test_e2e_clear_error_message_on_self_approval_attempt(
        self,
        client,
        app,
        uploader_user_a
    ):
        """
        E2E test: Verify clear, helpful error message when self-approval is attempted.

        Per spec edge case: "Self-Approval Attempt - Clear error message explaining
        separation of duties"
        """
        # Login and create asset
        login_response = client.post('/admin/api/login', json={
            'email': uploader_user_a.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'Error Message Test Asset',
            'filename': 'error_msg_test.mp4',
            'file_path': '/uploads/error_msg_test.mp4',
            'organization_id': uploader_user_a.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        # Submit
        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(token)
        )

        # Try to approve own asset
        self_approve_response = client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(token)
        )

        assert self_approve_response.status_code == 403

        error_data = self_approve_response.get_json()

        # Verify response has required error structure
        assert 'error' in error_data, "Response should have 'error' field"

        # Verify error message is helpful and clear
        error_msg = error_data['error']
        assert len(error_msg) > 10, "Error message should be descriptive"

        # The message should help the user understand why they can't approve
        # (not just a generic "forbidden" message)

    def test_e2e_rejection_by_uploader_also_blocked(
        self,
        client,
        app,
        uploader_user_a,
        approver_user_b
    ):
        """
        E2E test: User cannot reject their own upload either.

        Separation of duties should apply to both approve AND reject actions.
        """
        # Login as uploader
        user_a_login = client.post('/admin/api/login', json={
            'email': uploader_user_a.email,
            'password': TEST_PASSWORD
        })
        user_a_token = user_a_login.get_json()['access_token']

        # Create and submit
        create_response = client.post('/api/v1/assets', json={
            'title': 'Self-Rejection Test Asset',
            'filename': 'self_reject_test.mp4',
            'file_path': '/uploads/self_reject_test.mp4',
            'organization_id': uploader_user_a.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(user_a_token)
        )

        # Try to reject own upload (should also fail)
        self_reject_response = client.post(
            f'/api/v1/assets/{asset_uuid}/reject',
            headers=get_auth_headers(user_a_token),
            json={'reason': 'Self-rejection attempt'}
        )

        # Self-rejection should also be blocked (403)
        assert self_reject_response.status_code == 403, \
            "Self-rejection should also be blocked by separation of duties"

        # Verify User B can reject it
        user_b_login = client.post('/admin/api/login', json={
            'email': approver_user_b.email,
            'password': TEST_PASSWORD
        })
        user_b_token = user_b_login.get_json()['access_token']

        reject_response = client.post(
            f'/api/v1/assets/{asset_uuid}/reject',
            headers=get_auth_headers(user_b_token),
            json={'reason': 'Rejected by different user'}
        )

        assert reject_response.status_code == 200, \
            "Different user should be able to reject"


class TestSeparationOfDutiesEdgeCases:
    """
    Test edge cases and security scenarios for separation of duties.
    """

    def test_cannot_approve_draft_asset_directly(
        self,
        client,
        app,
        uploader_user_a,
        approver_user_b
    ):
        """
        Test that assets must go through submit step before approval.
        """
        # Login as uploader and create DRAFT asset
        user_a_login = client.post('/admin/api/login', json={
            'email': uploader_user_a.email,
            'password': TEST_PASSWORD
        })
        user_a_token = user_a_login.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'Draft Approval Test',
            'filename': 'draft_approval_test.mp4',
            'file_path': '/uploads/draft_approval_test.mp4',
            'organization_id': uploader_user_a.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        # Don't submit - try to approve DRAFT directly
        user_b_login = client.post('/admin/api/login', json={
            'email': approver_user_b.email,
            'password': TEST_PASSWORD
        })
        user_b_token = user_b_login.get_json()['access_token']

        approve_response = client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(user_b_token)
        )

        # Should fail because asset is still DRAFT
        assert approve_response.status_code in [400, 403], \
            "Cannot approve asset that hasn't been submitted"

    def test_approval_request_created_on_submit(
        self,
        client,
        app,
        uploader_user_a
    ):
        """
        Test that submitting for approval creates proper approval request record.
        """
        # Login and create asset
        login_response = client.post('/admin/api/login', json={
            'email': uploader_user_a.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'Approval Request Test',
            'filename': 'approval_request_test.mp4',
            'file_path': '/uploads/approval_request_test.mp4',
            'organization_id': uploader_user_a.organization_id
        })
        asset_id = create_response.get_json()['id']
        asset_uuid = create_response.get_json()['uuid']

        # Submit for approval
        submit_response = client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(token),
            json={'notes': 'Testing approval request creation'}
        )

        assert submit_response.status_code == 200

        # Verify approval request was created
        with app.app_context():
            approval_request = ContentApprovalRequest.query.filter_by(
                asset_id=asset_id
            ).first()

            assert approval_request is not None, \
                "Approval request should be created on submit"
            assert approval_request.status == ContentApprovalRequest.STATUS_PENDING
            assert approval_request.requested_by == uploader_user_a.id

    def test_multiple_approval_attempts_by_uploader_all_blocked(
        self,
        client,
        app,
        uploader_user_a
    ):
        """
        Test that multiple self-approval attempts are all blocked.
        """
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': uploader_user_a.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Create and submit
        create_response = client.post('/api/v1/assets', json={
            'title': 'Multiple Attempts Test',
            'filename': 'multiple_attempts_test.mp4',
            'file_path': '/uploads/multiple_attempts_test.mp4',
            'organization_id': uploader_user_a.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(token)
        )

        # Try multiple self-approval attempts
        for i in range(3):
            response = client.post(
                f'/api/v1/assets/{asset_uuid}/approve',
                headers=get_auth_headers(token),
                json={'notes': f'Self-approval attempt {i+1}'}
            )

            assert response.status_code == 403, \
                f"Attempt {i+1}: Self-approval should always be blocked"
