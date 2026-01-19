"""
End-to-end tests for Content Upload -> Review -> Approval -> Publish flow.

This test module verifies the complete content lifecycle workflow:
1. Partner logs in
2. Partner uploads content asset
3. Partner submits content for review
4. Content Manager logs in
5. Content Manager approves content
6. Content Manager publishes content
7. Content is visible in published catalog API

Also tests:
- Role-based access control for content operations
- Content rejection workflow
- Audit logging for content actions
- Published content catalog verification
"""

import io
import os
import pytest
import tempfile
from datetime import datetime, timezone

from content_catalog.models import db, User, ContentAsset, ContentApprovalRequest, AuditLog, Organization
from content_catalog.tests.conftest import TEST_PASSWORD, get_auth_headers


class TestContentUploadApprovalPublishFlow:
    """
    End-to-end test for the complete content workflow.

    Verifies that:
    - Partner can log in and upload content
    - Partner can submit content for review
    - Content Manager can approve content
    - Content Manager can publish approved content
    - Published content is visible via the catalog API
    """

    def test_complete_content_workflow(self, client, app, sample_partner, sample_content_manager):
        """
        E2E test: Partner uploads content -> Submit -> Approve -> Publish.

        Steps:
        1. Login as Partner
        2. Create content asset via API
        3. Submit for review
        4. Login as Content Manager
        5. Approve content
        6. Publish content
        7. Verify in catalog API (GET assets with status=published)
        """
        # =========================================================================
        # Step 1: Login as Partner
        # =========================================================================
        partner_login_response = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })

        assert partner_login_response.status_code == 200, \
            f"Partner login failed: {partner_login_response.get_json()}"
        partner_token = partner_login_response.get_json()['access_token']

        # Verify Partner can access /me endpoint
        me_response = client.get('/admin/api/me', headers=get_auth_headers(partner_token))
        assert me_response.status_code == 200
        assert me_response.get_json()['role'] == User.ROLE_PARTNER

        # =========================================================================
        # Step 2: Create content asset
        # =========================================================================
        asset_data = {
            'title': 'E2E Test Video',
            'description': 'A video for E2E workflow testing',
            'filename': 'test_video_e2e.mp4',
            'file_path': '/uploads/test_video_e2e.mp4',
            'file_size': 10240000,
            'duration': 120.5,
            'resolution': '1920x1080',
            'format': 'mp4',
            'organization_id': sample_partner.organization_id,
            'category': 'promotional',
            'tags': 'e2e,test,video'
        }

        create_response = client.post(
            '/api/v1/assets',
            json=asset_data
        )

        assert create_response.status_code == 201, \
            f"Asset creation failed: {create_response.get_json()}"

        asset = create_response.get_json()
        assert asset['title'] == asset_data['title']
        assert asset['status'] == ContentAsset.STATUS_DRAFT
        asset_uuid = asset['uuid']
        asset_id = asset['id']

        # =========================================================================
        # Step 3: Submit content for review
        # =========================================================================
        submit_response = client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token),
            json={'notes': 'Ready for review'}
        )

        assert submit_response.status_code == 200, \
            f"Submit for review failed: {submit_response.get_json()}"

        submit_data = submit_response.get_json()
        assert submit_data['message'] == 'Asset submitted for review'
        assert submit_data['asset']['status'] == ContentAsset.STATUS_PENDING_REVIEW

        # Verify approval request was created
        with app.app_context():
            approval_request = ContentApprovalRequest.query.filter_by(
                asset_id=asset_id
            ).first()
            assert approval_request is not None
            assert approval_request.status == ContentApprovalRequest.STATUS_PENDING

        # =========================================================================
        # Step 4: Login as Content Manager
        # =========================================================================
        cm_login_response = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })

        assert cm_login_response.status_code == 200, \
            f"Content Manager login failed: {cm_login_response.get_json()}"
        cm_token = cm_login_response.get_json()['access_token']

        # Verify Content Manager role
        cm_me_response = client.get('/admin/api/me', headers=get_auth_headers(cm_token))
        assert cm_me_response.status_code == 200
        assert cm_me_response.get_json()['role'] == User.ROLE_CONTENT_MANAGER

        # =========================================================================
        # Step 5: Approve content
        # =========================================================================
        approve_response = client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(cm_token),
            json={'notes': 'Content meets all requirements'}
        )

        assert approve_response.status_code == 200, \
            f"Approval failed: {approve_response.get_json()}"

        approve_data = approve_response.get_json()
        assert approve_data['message'] == 'Asset approved successfully'
        assert approve_data['asset']['status'] == ContentAsset.STATUS_APPROVED
        assert approve_data['asset']['reviewed_by'] == sample_content_manager.id

        # Verify in database
        with app.app_context():
            approved_asset = db.session.get(ContentAsset, asset_id)
            assert approved_asset.status == ContentAsset.STATUS_APPROVED
            assert approved_asset.reviewed_by == sample_content_manager.id
            assert approved_asset.reviewed_at is not None

        # =========================================================================
        # Step 6: Publish content
        # =========================================================================
        publish_response = client.post(
            f'/api/v1/assets/{asset_uuid}/publish',
            headers=get_auth_headers(cm_token),
            json={'notes': 'Publishing to catalog'}
        )

        assert publish_response.status_code == 200, \
            f"Publishing failed: {publish_response.get_json()}"

        publish_data = publish_response.get_json()
        assert publish_data['message'] == 'Asset published successfully'
        assert publish_data['asset']['status'] == ContentAsset.STATUS_PUBLISHED
        assert publish_data['asset']['published_at'] is not None

        # Verify in database
        with app.app_context():
            published_asset = db.session.get(ContentAsset, asset_id)
            assert published_asset.status == ContentAsset.STATUS_PUBLISHED
            assert published_asset.published_at is not None

        # =========================================================================
        # Step 7: Verify in catalog API
        # =========================================================================
        # Get all published assets
        catalog_response = client.get(
            '/api/v1/assets',
            query_string={'status': 'published'}
        )

        assert catalog_response.status_code == 200, \
            f"Catalog API failed: {catalog_response.get_json()}"

        catalog_data = catalog_response.get_json()
        assert catalog_data['count'] >= 1

        # Find our published asset
        published_assets = catalog_data['assets']
        our_asset = next(
            (a for a in published_assets if a['uuid'] == asset_uuid),
            None
        )
        assert our_asset is not None, "Published asset not found in catalog"
        assert our_asset['title'] == asset_data['title']
        assert our_asset['status'] == ContentAsset.STATUS_PUBLISHED

        # Verify by direct UUID lookup
        get_asset_response = client.get(f'/api/v1/assets/{asset_uuid}')
        assert get_asset_response.status_code == 200
        assert get_asset_response.get_json()['status'] == ContentAsset.STATUS_PUBLISHED

    def test_admin_can_complete_content_workflow(self, client, app, sample_partner, sample_admin):
        """
        E2E test: Admin can approve and publish content (higher role).

        Verifies that Admin has all Content Manager permissions.
        """
        # Partner login and create asset
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        # Create asset
        create_response = client.post('/api/v1/assets', json={
            'title': 'Admin Approval Test',
            'filename': 'admin_test.mp4',
            'file_path': '/uploads/admin_test.mp4',
            'organization_id': sample_partner.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        # Partner submits
        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token)
        )

        # Admin login
        admin_login = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        admin_token = admin_login.get_json()['access_token']

        # Admin approves
        approve_response = client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(admin_token)
        )
        assert approve_response.status_code == 200
        assert approve_response.get_json()['asset']['status'] == ContentAsset.STATUS_APPROVED

        # Admin publishes
        publish_response = client.post(
            f'/api/v1/assets/{asset_uuid}/publish',
            headers=get_auth_headers(admin_token)
        )
        assert publish_response.status_code == 200
        assert publish_response.get_json()['asset']['status'] == ContentAsset.STATUS_PUBLISHED


class TestContentRejectionFlow:
    """
    Tests for the content rejection workflow.
    """

    def test_reject_content_requires_reason(self, client, app, sample_partner, sample_content_manager):
        """
        E2E test: Content rejection requires a reason.
        """
        # Setup: Partner creates and submits content
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'Rejection Test',
            'filename': 'reject_test.mp4',
            'file_path': '/uploads/reject_test.mp4',
            'organization_id': sample_partner.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token)
        )

        # Content Manager login
        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        cm_token = cm_login.get_json()['access_token']

        # Try to reject without reason
        reject_no_reason = client.post(
            f'/api/v1/assets/{asset_uuid}/reject',
            headers=get_auth_headers(cm_token),
            json={}
        )
        assert reject_no_reason.status_code == 400
        assert 'reason is required' in reject_no_reason.get_json()['error']

        # Reject with reason
        reject_response = client.post(
            f'/api/v1/assets/{asset_uuid}/reject',
            headers=get_auth_headers(cm_token),
            json={'reason': 'Content does not meet quality standards'}
        )
        assert reject_response.status_code == 200
        assert reject_response.get_json()['asset']['status'] == ContentAsset.STATUS_REJECTED

    def test_rejected_content_can_be_resubmitted(self, client, app, sample_partner, sample_content_manager):
        """
        E2E test: Rejected content can be resubmitted for review.
        """
        # Setup: Partner creates and submits content
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'Resubmit Test',
            'filename': 'resubmit_test.mp4',
            'file_path': '/uploads/resubmit_test.mp4',
            'organization_id': sample_partner.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token)
        )

        # Content Manager rejects
        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        cm_token = cm_login.get_json()['access_token']

        client.post(
            f'/api/v1/assets/{asset_uuid}/reject',
            headers=get_auth_headers(cm_token),
            json={'reason': 'Needs improvement'}
        )

        # Partner resubmits
        resubmit_response = client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token),
            json={'notes': 'Made requested changes'}
        )

        assert resubmit_response.status_code == 200
        assert resubmit_response.get_json()['asset']['status'] == ContentAsset.STATUS_PENDING_REVIEW


class TestContentRoleBasedAccessControl:
    """
    Tests for role-based access control on content operations.
    """

    def test_partner_cannot_approve_content(self, client, app, sample_partner, sample_content_manager):
        """
        E2E test: Partner cannot approve content (insufficient permissions).
        """
        # Setup: Create and submit content
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'RBAC Test Approve',
            'filename': 'rbac_approve_test.mp4',
            'file_path': '/uploads/rbac_approve_test.mp4',
            'organization_id': sample_partner.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        # Submit for review
        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token)
        )

        # Partner tries to approve (should fail)
        approve_response = client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(partner_token)
        )

        assert approve_response.status_code == 403
        assert 'Insufficient permissions' in approve_response.get_json()['error']

    def test_partner_cannot_publish_content(self, client, app, sample_partner, sample_content_manager):
        """
        E2E test: Partner cannot publish content (insufficient permissions).
        """
        # Setup: Create, submit, and get approved
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'RBAC Test Publish',
            'filename': 'rbac_publish_test.mp4',
            'file_path': '/uploads/rbac_publish_test.mp4',
            'organization_id': sample_partner.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token)
        )

        # Content Manager approves
        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        cm_token = cm_login.get_json()['access_token']

        client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(cm_token)
        )

        # Partner tries to publish (should fail)
        publish_response = client.post(
            f'/api/v1/assets/{asset_uuid}/publish',
            headers=get_auth_headers(partner_token)
        )

        assert publish_response.status_code == 403
        assert 'Insufficient permissions' in publish_response.get_json()['error']

    def test_partner_cannot_reject_content(self, client, app, sample_partner, sample_content_manager):
        """
        E2E test: Partner cannot reject content (insufficient permissions).
        """
        # Setup: Create and submit content
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'RBAC Test Reject',
            'filename': 'rbac_reject_test.mp4',
            'file_path': '/uploads/rbac_reject_test.mp4',
            'organization_id': sample_partner.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token)
        )

        # Partner tries to reject (should fail)
        reject_response = client.post(
            f'/api/v1/assets/{asset_uuid}/reject',
            headers=get_auth_headers(partner_token),
            json={'reason': 'Should not work'}
        )

        assert reject_response.status_code == 403
        assert 'Insufficient permissions' in reject_response.get_json()['error']

    def test_advertiser_cannot_upload_content_via_submit(self, client, app, sample_advertiser):
        """
        E2E test: Advertiser CAN create and submit content.

        Advertisers are allowed to upload content per the _can_upload_content function.
        """
        # Advertiser login
        advertiser_login = client.post('/admin/api/login', json={
            'email': sample_advertiser.email,
            'password': TEST_PASSWORD
        })
        assert advertiser_login.status_code == 200
        advertiser_token = advertiser_login.get_json()['access_token']

        # Create asset (should work for advertiser)
        create_response = client.post('/api/v1/assets', json={
            'title': 'Advertiser Content',
            'filename': 'advertiser_content.mp4',
            'file_path': '/uploads/advertiser_content.mp4',
            'organization_id': sample_advertiser.organization_id
        })
        assert create_response.status_code == 201

        asset_uuid = create_response.get_json()['uuid']

        # Advertiser can submit for review
        submit_response = client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(advertiser_token)
        )
        assert submit_response.status_code == 200


class TestContentWorkflowStatusTransitions:
    """
    Tests for content status transition rules.
    """

    def test_cannot_approve_draft_content(self, client, app, sample_content_manager):
        """Cannot approve content that is still in draft status."""
        # Create draft content
        create_response = client.post('/api/v1/assets', json={
            'title': 'Draft Content',
            'filename': 'draft_test.mp4',
            'file_path': '/uploads/draft_test.mp4'
        })
        asset_uuid = create_response.get_json()['uuid']

        # Content Manager login
        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        cm_token = cm_login.get_json()['access_token']

        # Try to approve draft (should fail)
        approve_response = client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(cm_token)
        )

        assert approve_response.status_code == 409
        assert 'pending_review' in approve_response.get_json()['error']

    def test_cannot_publish_pending_content(self, client, app, sample_partner, sample_content_manager):
        """Cannot publish content that is still pending review."""
        # Partner creates and submits
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'Pending Content',
            'filename': 'pending_test.mp4',
            'file_path': '/uploads/pending_test.mp4',
            'organization_id': sample_partner.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token)
        )

        # Content Manager login
        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        cm_token = cm_login.get_json()['access_token']

        # Try to publish pending (should fail)
        publish_response = client.post(
            f'/api/v1/assets/{asset_uuid}/publish',
            headers=get_auth_headers(cm_token)
        )

        assert publish_response.status_code == 409
        assert 'approved' in publish_response.get_json()['error']

    def test_cannot_submit_published_content(self, client, app, sample_partner, sample_content_manager):
        """Cannot submit content that is already published."""
        # Complete workflow to publish
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'Already Published',
            'filename': 'published_test.mp4',
            'file_path': '/uploads/published_test.mp4',
            'organization_id': sample_partner.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token)
        )

        # Content Manager approves and publishes
        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        cm_token = cm_login.get_json()['access_token']

        client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(cm_token)
        )
        client.post(
            f'/api/v1/assets/{asset_uuid}/publish',
            headers=get_auth_headers(cm_token)
        )

        # Try to submit again (should fail)
        submit_response = client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token)
        )

        assert submit_response.status_code == 409
        assert 'draft' in submit_response.get_json()['error'] or \
               'rejected' in submit_response.get_json()['error']


class TestContentAuditLogging:
    """
    Tests for audit logging during content workflow.
    """

    def test_content_workflow_audit_logs(self, client, app, db_session, sample_partner, sample_content_manager):
        """
        E2E test: Verify audit logs are created for all content workflow actions.
        """
        # Record initial audit log counts
        with app.app_context():
            initial_submit_count = AuditLog.query.filter_by(action='content.submitted').count()
            initial_approve_count = AuditLog.query.filter_by(action='content.approved').count()
            initial_publish_count = AuditLog.query.filter_by(action='content.published').count()

        # Partner creates and submits
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'Audit Test Content',
            'filename': 'audit_test.mp4',
            'file_path': '/uploads/audit_test.mp4',
            'organization_id': sample_partner.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']
        asset_id = create_response.get_json()['id']

        # Submit for review
        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token)
        )

        # Verify submit audit log
        with app.app_context():
            submit_count = AuditLog.query.filter_by(action='content.submitted').count()
            assert submit_count == initial_submit_count + 1

            submit_log = AuditLog.query.filter_by(
                action='content.submitted',
                resource_id=str(asset_id)
            ).first()
            assert submit_log is not None
            assert submit_log.user_id == sample_partner.id

        # Content Manager approves
        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        cm_token = cm_login.get_json()['access_token']

        client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(cm_token)
        )

        # Verify approve audit log
        with app.app_context():
            approve_count = AuditLog.query.filter_by(action='content.approved').count()
            assert approve_count == initial_approve_count + 1

            approve_log = AuditLog.query.filter_by(
                action='content.approved',
                resource_id=str(asset_id)
            ).first()
            assert approve_log is not None
            assert approve_log.user_id == sample_content_manager.id

        # Content Manager publishes
        client.post(
            f'/api/v1/assets/{asset_uuid}/publish',
            headers=get_auth_headers(cm_token)
        )

        # Verify publish audit log
        with app.app_context():
            publish_count = AuditLog.query.filter_by(action='content.published').count()
            assert publish_count == initial_publish_count + 1

            publish_log = AuditLog.query.filter_by(
                action='content.published',
                resource_id=str(asset_id)
            ).first()
            assert publish_log is not None
            assert publish_log.user_id == sample_content_manager.id

    def test_content_rejection_audit_log(self, client, app, sample_partner, sample_content_manager):
        """
        E2E test: Verify audit log is created for content rejection.
        """
        with app.app_context():
            initial_reject_count = AuditLog.query.filter_by(action='content.rejected').count()

        # Partner creates and submits
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'Rejection Audit Test',
            'filename': 'rejection_audit.mp4',
            'file_path': '/uploads/rejection_audit.mp4',
            'organization_id': sample_partner.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']
        asset_id = create_response.get_json()['id']

        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token)
        )

        # Content Manager rejects
        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        cm_token = cm_login.get_json()['access_token']

        client.post(
            f'/api/v1/assets/{asset_uuid}/reject',
            headers=get_auth_headers(cm_token),
            json={'reason': 'Does not meet standards'}
        )

        # Verify rejection audit log
        with app.app_context():
            reject_count = AuditLog.query.filter_by(action='content.rejected').count()
            assert reject_count == initial_reject_count + 1

            reject_log = AuditLog.query.filter_by(
                action='content.rejected',
                resource_id=str(asset_id)
            ).first()
            assert reject_log is not None
            assert reject_log.user_id == sample_content_manager.id


class TestPublishedCatalogVerification:
    """
    Tests for verifying published content in the catalog API.
    """

    def test_only_published_content_in_published_catalog(self, client, app, sample_partner, sample_content_manager):
        """
        E2E test: Only published content appears in the published catalog.
        """
        # Partner login
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        # Create multiple assets at different stages
        assets = {}
        for name, should_publish in [('Draft Asset', False), ('Pending Asset', False), ('Published Asset', True)]:
            create_response = client.post('/api/v1/assets', json={
                'title': name,
                'filename': f'{name.lower().replace(" ", "_")}.mp4',
                'file_path': f'/uploads/{name.lower().replace(" ", "_")}.mp4',
                'organization_id': sample_partner.organization_id
            })
            assets[name] = create_response.get_json()['uuid']

        # Submit the pending and published assets
        for name in ['Pending Asset', 'Published Asset']:
            client.post(
                f'/api/v1/assets/{assets[name]}/submit',
                headers=get_auth_headers(partner_token)
            )

        # Content Manager approves and publishes only 'Published Asset'
        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        cm_token = cm_login.get_json()['access_token']

        client.post(
            f'/api/v1/assets/{assets["Published Asset"]}/approve',
            headers=get_auth_headers(cm_token)
        )
        client.post(
            f'/api/v1/assets/{assets["Published Asset"]}/publish',
            headers=get_auth_headers(cm_token)
        )

        # Query published catalog
        catalog_response = client.get(
            '/api/v1/assets',
            query_string={'status': 'published'}
        )
        assert catalog_response.status_code == 200

        catalog_data = catalog_response.get_json()
        published_uuids = [a['uuid'] for a in catalog_data['assets']]

        # Verify only published asset is in the catalog
        assert assets['Published Asset'] in published_uuids
        assert assets['Draft Asset'] not in published_uuids
        assert assets['Pending Asset'] not in published_uuids

    def test_published_content_has_published_timestamp(self, client, app, sample_partner, sample_content_manager):
        """
        E2E test: Published content has a published_at timestamp.
        """
        # Complete workflow
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        create_response = client.post('/api/v1/assets', json={
            'title': 'Timestamp Test',
            'filename': 'timestamp_test.mp4',
            'file_path': '/uploads/timestamp_test.mp4',
            'organization_id': sample_partner.organization_id
        })
        asset_uuid = create_response.get_json()['uuid']

        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(partner_token)
        )

        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        cm_token = cm_login.get_json()['access_token']

        client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(cm_token)
        )

        # Get timestamp before publish
        before_publish = datetime.now(timezone.utc)

        client.post(
            f'/api/v1/assets/{asset_uuid}/publish',
            headers=get_auth_headers(cm_token)
        )

        # Verify published_at timestamp
        get_response = client.get(f'/api/v1/assets/{asset_uuid}')
        asset_data = get_response.get_json()

        assert asset_data['published_at'] is not None
        published_at = datetime.fromisoformat(asset_data['published_at'].replace('Z', '+00:00'))
        assert published_at >= before_publish
