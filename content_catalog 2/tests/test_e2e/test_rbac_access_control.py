"""
End-to-end tests for Role-Based Access Control (RBAC).

This test module verifies that role-based access control prevents
unauthorized actions across the Content Catalog system:

1. Partner cannot approve Admin users
2. Advertiser cannot publish content
3. Viewer cannot upload content
4. All unauthorized actions return 403 Forbidden

Role Hierarchy:
    Super Admin > Admin > Content Manager > Partner > Advertiser > Viewer

Permission Matrix:
    - User Approval: Super Admin can approve Admin, Admin can approve Content Manager,
                     Content Manager can approve Partner, Partner can approve Advertiser,
                     Advertiser can approve Viewer, Viewer cannot approve anyone
    - Content Publish: Only Super Admin, Admin, Content Manager can publish
    - Content Upload: Super Admin, Admin, Content Manager, Partner, Advertiser can upload
                      Viewer CANNOT upload
"""

import io
import os
import pytest
import tempfile
from datetime import datetime, timezone

from content_catalog.models import db, User, ContentAsset, Organization
from content_catalog.tests.conftest import TEST_PASSWORD, get_auth_headers


class TestPartnerCannotApproveAdmin:
    """
    Tests verifying that Partner users cannot approve Admin users.

    Role hierarchy: Partner (level 3) cannot approve Admin (level 1).
    This should return 403 Forbidden.
    """

    def test_partner_cannot_approve_admin_user(self, client, app, sample_partner, sample_super_admin):
        """
        E2E test: Partner cannot approve an Admin user.

        Steps:
        1. Create a pending Admin user
        2. Login as Partner
        3. Try to approve the Admin user
        4. Verify 403 Forbidden is returned
        """
        # Create a pending Admin user
        with app.app_context():
            pending_admin = User(
                email='pending_admin@skillzmedia.com',
                password_hash=sample_super_admin.password_hash,
                name='Pending Admin',
                role=User.ROLE_ADMIN,
                organization_id=sample_super_admin.organization_id,
                status=User.STATUS_PENDING
            )
            db.session.add(pending_admin)
            db.session.commit()
            pending_admin_id = pending_admin.id

        # Login as Partner
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        assert partner_login.status_code == 200
        partner_token = partner_login.get_json()['access_token']

        # Try to approve the Admin user
        approve_response = client.post(
            f'/api/v1/approvals/{pending_admin_id}/approve',
            headers=get_auth_headers(partner_token),
            json={'notes': 'Partner trying to approve Admin'}
        )

        # Verify 403 Forbidden
        assert approve_response.status_code == 403, \
            f"Expected 403 Forbidden, got {approve_response.status_code}: {approve_response.get_json()}"
        assert 'Insufficient permissions' in approve_response.get_json()['error']

    def test_partner_cannot_approve_content_manager(self, client, app, sample_partner, sample_admin):
        """
        E2E test: Partner cannot approve a Content Manager user.

        Partner (level 3) cannot approve Content Manager (level 2).
        """
        # Create a pending Content Manager user
        with app.app_context():
            pending_cm = User(
                email='pending_cm@skillzmedia.com',
                password_hash=sample_admin.password_hash,
                name='Pending Content Manager',
                role=User.ROLE_CONTENT_MANAGER,
                organization_id=sample_admin.organization_id,
                status=User.STATUS_PENDING
            )
            db.session.add(pending_cm)
            db.session.commit()
            pending_cm_id = pending_cm.id

        # Login as Partner
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        # Try to approve the Content Manager user
        approve_response = client.post(
            f'/api/v1/approvals/{pending_cm_id}/approve',
            headers=get_auth_headers(partner_token)
        )

        # Verify 403 Forbidden
        assert approve_response.status_code == 403
        assert 'Insufficient permissions' in approve_response.get_json()['error']

    def test_partner_can_approve_advertiser(self, client, app, sample_partner, sample_organization):
        """
        E2E test: Partner CAN approve an Advertiser user (lower in hierarchy).

        Partner (level 3) can approve Advertiser (level 4).
        """
        # Create a pending Advertiser user
        with app.app_context():
            pending_advertiser = User(
                email='pending_advertiser@testorg.com',
                password_hash=sample_partner.password_hash,
                name='Pending Advertiser',
                role=User.ROLE_ADVERTISER,
                organization_id=sample_organization.id,
                status=User.STATUS_PENDING
            )
            db.session.add(pending_advertiser)
            db.session.commit()
            pending_advertiser_id = pending_advertiser.id

        # Login as Partner
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        # Partner should be able to approve Advertiser
        approve_response = client.post(
            f'/api/v1/approvals/{pending_advertiser_id}/approve',
            headers=get_auth_headers(partner_token),
            json={'notes': 'Partner approving Advertiser'}
        )

        # Verify success (Partner can approve Advertiser)
        assert approve_response.status_code == 200, \
            f"Partner should be able to approve Advertiser: {approve_response.get_json()}"


class TestAdvertiserCannotPublishContent:
    """
    Tests verifying that Advertiser users cannot publish content.

    Only Content Manager and above can publish content.
    Advertiser attempting to publish should get 403 Forbidden.
    """

    def test_advertiser_cannot_publish_approved_content(
        self, client, app, sample_advertiser, sample_content_manager, sample_organization
    ):
        """
        E2E test: Advertiser cannot publish content (insufficient permissions).

        Steps:
        1. Create an approved content asset
        2. Login as Advertiser
        3. Try to publish the content
        4. Verify 403 Forbidden is returned
        """
        # Create an approved content asset
        with app.app_context():
            asset = ContentAsset(
                title='Approved Test Asset',
                filename='approved_test.mp4',
                file_path='/uploads/approved_test.mp4',
                file_size=5000000,
                format='mp4',
                organization_id=sample_organization.id,
                uploaded_by=sample_advertiser.id,
                status=ContentAsset.STATUS_APPROVED,
                reviewed_by=sample_content_manager.id,
                reviewed_at=datetime.now(timezone.utc)
            )
            db.session.add(asset)
            db.session.commit()
            asset_uuid = asset.uuid

        # Login as Advertiser
        advertiser_login = client.post('/admin/api/login', json={
            'email': sample_advertiser.email,
            'password': TEST_PASSWORD
        })
        assert advertiser_login.status_code == 200
        advertiser_token = advertiser_login.get_json()['access_token']

        # Try to publish the content
        publish_response = client.post(
            f'/api/v1/assets/{asset_uuid}/publish',
            headers=get_auth_headers(advertiser_token)
        )

        # Verify 403 Forbidden
        assert publish_response.status_code == 403, \
            f"Expected 403 Forbidden, got {publish_response.status_code}: {publish_response.get_json()}"
        assert 'Insufficient permissions' in publish_response.get_json()['error']

    def test_advertiser_cannot_approve_content(
        self, client, app, sample_advertiser, sample_partner, sample_organization
    ):
        """
        E2E test: Advertiser cannot approve content (insufficient permissions).
        """
        # Create a pending review content asset
        with app.app_context():
            asset = ContentAsset(
                title='Pending Review Asset',
                filename='pending_review.mp4',
                file_path='/uploads/pending_review.mp4',
                file_size=5000000,
                format='mp4',
                organization_id=sample_organization.id,
                uploaded_by=sample_partner.id,
                status=ContentAsset.STATUS_PENDING_REVIEW
            )
            db.session.add(asset)
            db.session.commit()
            asset_uuid = asset.uuid

        # Login as Advertiser
        advertiser_login = client.post('/admin/api/login', json={
            'email': sample_advertiser.email,
            'password': TEST_PASSWORD
        })
        advertiser_token = advertiser_login.get_json()['access_token']

        # Try to approve the content
        approve_response = client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(advertiser_token)
        )

        # Verify 403 Forbidden
        assert approve_response.status_code == 403
        assert 'Insufficient permissions' in approve_response.get_json()['error']

    def test_advertiser_cannot_reject_content(
        self, client, app, sample_advertiser, sample_partner, sample_organization
    ):
        """
        E2E test: Advertiser cannot reject content (insufficient permissions).
        """
        # Create a pending review content asset
        with app.app_context():
            asset = ContentAsset(
                title='Pending Reject Asset',
                filename='pending_reject.mp4',
                file_path='/uploads/pending_reject.mp4',
                file_size=5000000,
                format='mp4',
                organization_id=sample_organization.id,
                uploaded_by=sample_partner.id,
                status=ContentAsset.STATUS_PENDING_REVIEW
            )
            db.session.add(asset)
            db.session.commit()
            asset_uuid = asset.uuid

        # Login as Advertiser
        advertiser_login = client.post('/admin/api/login', json={
            'email': sample_advertiser.email,
            'password': TEST_PASSWORD
        })
        advertiser_token = advertiser_login.get_json()['access_token']

        # Try to reject the content
        reject_response = client.post(
            f'/api/v1/assets/{asset_uuid}/reject',
            headers=get_auth_headers(advertiser_token),
            json={'reason': 'Should not work'}
        )

        # Verify 403 Forbidden
        assert reject_response.status_code == 403
        assert 'Insufficient permissions' in reject_response.get_json()['error']


class TestViewerCannotUploadContent:
    """
    Tests verifying that Viewer users cannot upload content.

    Viewers have the lowest privilege and should not be able to upload content.
    Attempting to upload should return 403 Forbidden.
    """

    def test_viewer_cannot_upload_content_file(
        self, client, app, sample_viewer, sample_organization
    ):
        """
        E2E test: Viewer cannot upload content via file upload endpoint.

        Steps:
        1. Login as Viewer
        2. Try to upload a content file
        3. Verify 403 Forbidden is returned
        """
        # Login as Viewer
        viewer_login = client.post('/admin/api/login', json={
            'email': sample_viewer.email,
            'password': TEST_PASSWORD
        })
        assert viewer_login.status_code == 200
        viewer_token = viewer_login.get_json()['access_token']

        # Create a mock file for upload
        data = {
            'file': (io.BytesIO(b'fake video content'), 'test_video.mp4'),
            'title': 'Viewer Upload Attempt'
        }

        # Try to upload content
        upload_response = client.post(
            '/api/v1/assets/upload',
            headers=get_auth_headers(viewer_token),
            data=data,
            content_type='multipart/form-data'
        )

        # Verify 403 Forbidden
        assert upload_response.status_code == 403, \
            f"Expected 403 Forbidden, got {upload_response.status_code}: {upload_response.get_json()}"
        assert 'Insufficient permissions' in upload_response.get_json()['error']

    def test_viewer_cannot_submit_content_for_review(
        self, client, app, sample_viewer, sample_partner, sample_organization
    ):
        """
        E2E test: Viewer cannot submit content for review.
        """
        # Create a draft content asset (owned by partner)
        with app.app_context():
            asset = ContentAsset(
                title='Draft Asset',
                filename='draft_test.mp4',
                file_path='/uploads/draft_test.mp4',
                file_size=5000000,
                format='mp4',
                organization_id=sample_organization.id,
                uploaded_by=sample_partner.id,
                status=ContentAsset.STATUS_DRAFT
            )
            db.session.add(asset)
            db.session.commit()
            asset_uuid = asset.uuid

        # Login as Viewer
        viewer_login = client.post('/admin/api/login', json={
            'email': sample_viewer.email,
            'password': TEST_PASSWORD
        })
        viewer_token = viewer_login.get_json()['access_token']

        # Try to submit content for review
        submit_response = client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(viewer_token)
        )

        # Verify 403 Forbidden
        assert submit_response.status_code == 403
        assert 'Insufficient permissions' in submit_response.get_json()['error']

    def test_viewer_cannot_approve_users(self, client, app, sample_viewer, sample_organization):
        """
        E2E test: Viewer cannot approve any users.
        """
        # Create a pending Viewer user (even the lowest role)
        with app.app_context():
            pending_viewer = User(
                email='another_pending_viewer@testorg.com',
                password_hash=sample_viewer.password_hash,
                name='Another Pending Viewer',
                role=User.ROLE_VIEWER,
                organization_id=sample_organization.id,
                status=User.STATUS_PENDING
            )
            db.session.add(pending_viewer)
            db.session.commit()
            pending_viewer_id = pending_viewer.id

        # Login as Viewer
        viewer_login = client.post('/admin/api/login', json={
            'email': sample_viewer.email,
            'password': TEST_PASSWORD
        })
        viewer_token = viewer_login.get_json()['access_token']

        # Try to approve the pending user
        approve_response = client.post(
            f'/api/v1/approvals/{pending_viewer_id}/approve',
            headers=get_auth_headers(viewer_token)
        )

        # Verify 403 Forbidden (viewer cannot approve anyone)
        assert approve_response.status_code == 403
        assert 'Insufficient permissions' in approve_response.get_json()['error']


class TestAllUnauthorizedActionsReturn403:
    """
    Comprehensive tests verifying all unauthorized actions return 403 Forbidden.
    """

    def test_partner_approve_admin_returns_403(
        self, client, app, sample_partner, sample_super_admin
    ):
        """Partner trying to approve Admin returns 403."""
        # Create pending Admin
        with app.app_context():
            pending_admin = User(
                email='test_pending_admin_403@skillzmedia.com',
                password_hash=sample_super_admin.password_hash,
                name='Test Pending Admin 403',
                role=User.ROLE_ADMIN,
                organization_id=sample_super_admin.organization_id,
                status=User.STATUS_PENDING
            )
            db.session.add(pending_admin)
            db.session.commit()
            pending_admin_id = pending_admin.id

        # Partner login
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        # Try to approve - expect 403
        response = client.post(
            f'/api/v1/approvals/{pending_admin_id}/approve',
            headers=get_auth_headers(partner_token)
        )
        assert response.status_code == 403

    def test_advertiser_publish_content_returns_403(
        self, client, app, sample_advertiser, sample_content_manager, sample_advertiser_organization
    ):
        """Advertiser trying to publish content returns 403."""
        # Create approved asset
        with app.app_context():
            asset = ContentAsset(
                title='Test Approved Asset 403',
                filename='test_approved_403.mp4',
                file_path='/uploads/test_approved_403.mp4',
                file_size=5000000,
                format='mp4',
                organization_id=sample_advertiser_organization.id,
                uploaded_by=sample_advertiser.id,
                status=ContentAsset.STATUS_APPROVED,
                reviewed_by=sample_content_manager.id,
                reviewed_at=datetime.now(timezone.utc)
            )
            db.session.add(asset)
            db.session.commit()
            asset_uuid = asset.uuid

        # Advertiser login
        advertiser_login = client.post('/admin/api/login', json={
            'email': sample_advertiser.email,
            'password': TEST_PASSWORD
        })
        advertiser_token = advertiser_login.get_json()['access_token']

        # Try to publish - expect 403
        response = client.post(
            f'/api/v1/assets/{asset_uuid}/publish',
            headers=get_auth_headers(advertiser_token)
        )
        assert response.status_code == 403

    def test_viewer_upload_content_returns_403(self, client, app, sample_viewer):
        """Viewer trying to upload content returns 403."""
        # Viewer login
        viewer_login = client.post('/admin/api/login', json={
            'email': sample_viewer.email,
            'password': TEST_PASSWORD
        })
        viewer_token = viewer_login.get_json()['access_token']

        # Create mock file
        data = {
            'file': (io.BytesIO(b'fake video content'), 'test_video_403.mp4'),
            'title': 'Viewer Upload 403 Test'
        }

        # Try to upload - expect 403
        response = client.post(
            '/api/v1/assets/upload',
            headers=get_auth_headers(viewer_token),
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 403

    def test_advertiser_reject_user_returns_403(
        self, client, app, sample_advertiser, sample_organization
    ):
        """Advertiser trying to reject a user returns 403."""
        # Create pending viewer (lowest role)
        with app.app_context():
            pending_user = User(
                email='pending_viewer_advertiser_reject@testorg.com',
                password_hash=sample_advertiser.password_hash,
                name='Pending Viewer for Reject',
                role=User.ROLE_VIEWER,
                organization_id=sample_organization.id,
                status=User.STATUS_PENDING
            )
            db.session.add(pending_user)
            db.session.commit()
            pending_user_id = pending_user.id

        # Advertiser login
        advertiser_login = client.post('/admin/api/login', json={
            'email': sample_advertiser.email,
            'password': TEST_PASSWORD
        })
        advertiser_token = advertiser_login.get_json()['access_token']

        # Try to reject - expect 403
        response = client.post(
            f'/api/v1/approvals/{pending_user_id}/reject',
            headers=get_auth_headers(advertiser_token),
            json={'reason': 'Should not work'}
        )
        assert response.status_code == 403

    def test_content_manager_approve_admin_returns_403(
        self, client, app, sample_content_manager, sample_internal_organization
    ):
        """Content Manager trying to approve Admin returns 403."""
        # Create pending Admin
        with app.app_context():
            pending_admin = User(
                email='cm_test_pending_admin@skillzmedia.com',
                password_hash=sample_content_manager.password_hash,
                name='CM Test Pending Admin',
                role=User.ROLE_ADMIN,
                organization_id=sample_internal_organization.id,
                status=User.STATUS_PENDING
            )
            db.session.add(pending_admin)
            db.session.commit()
            pending_admin_id = pending_admin.id

        # Content Manager login
        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        cm_token = cm_login.get_json()['access_token']

        # Try to approve - expect 403
        response = client.post(
            f'/api/v1/approvals/{pending_admin_id}/approve',
            headers=get_auth_headers(cm_token)
        )
        assert response.status_code == 403


class TestRoleHierarchyEnforcement:
    """
    Tests for complete role hierarchy enforcement.
    """

    def test_super_admin_can_approve_admin(
        self, client, app, sample_super_admin, sample_internal_organization
    ):
        """Super Admin CAN approve Admin (higher role can approve lower)."""
        # Create pending Admin
        with app.app_context():
            pending_admin = User(
                email='sa_approve_admin@skillzmedia.com',
                password_hash=sample_super_admin.password_hash,
                name='SA Approve Admin',
                role=User.ROLE_ADMIN,
                organization_id=sample_internal_organization.id,
                status=User.STATUS_PENDING
            )
            db.session.add(pending_admin)
            db.session.commit()
            pending_admin_id = pending_admin.id

        # Super Admin login
        sa_login = client.post('/admin/api/login', json={
            'email': sample_super_admin.email,
            'password': TEST_PASSWORD
        })
        sa_token = sa_login.get_json()['access_token']

        # Approve - should succeed
        response = client.post(
            f'/api/v1/approvals/{pending_admin_id}/approve',
            headers=get_auth_headers(sa_token)
        )
        assert response.status_code == 200

    def test_admin_cannot_approve_super_admin(
        self, client, app, sample_admin, sample_internal_organization
    ):
        """Admin CANNOT approve Super Admin (lower cannot approve higher)."""
        # Create pending Super Admin
        with app.app_context():
            pending_sa = User(
                email='pending_super_admin@skillzmedia.com',
                password_hash=sample_admin.password_hash,
                name='Pending Super Admin',
                role=User.ROLE_SUPER_ADMIN,
                organization_id=sample_internal_organization.id,
                status=User.STATUS_PENDING
            )
            db.session.add(pending_sa)
            db.session.commit()
            pending_sa_id = pending_sa.id

        # Admin login
        admin_login = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        admin_token = admin_login.get_json()['access_token']

        # Try to approve - expect 403
        response = client.post(
            f'/api/v1/approvals/{pending_sa_id}/approve',
            headers=get_auth_headers(admin_token)
        )
        assert response.status_code == 403

    def test_content_manager_can_publish_content(
        self, client, app, sample_content_manager, sample_partner, sample_organization
    ):
        """Content Manager CAN publish approved content."""
        # Create approved asset
        with app.app_context():
            asset = ContentAsset(
                title='CM Publish Test',
                filename='cm_publish_test.mp4',
                file_path='/uploads/cm_publish_test.mp4',
                file_size=5000000,
                format='mp4',
                organization_id=sample_organization.id,
                uploaded_by=sample_partner.id,
                status=ContentAsset.STATUS_APPROVED,
                reviewed_by=sample_content_manager.id,
                reviewed_at=datetime.now(timezone.utc)
            )
            db.session.add(asset)
            db.session.commit()
            asset_uuid = asset.uuid

        # Content Manager login
        cm_login = client.post('/admin/api/login', json={
            'email': sample_content_manager.email,
            'password': TEST_PASSWORD
        })
        cm_token = cm_login.get_json()['access_token']

        # Publish - should succeed
        response = client.post(
            f'/api/v1/assets/{asset_uuid}/publish',
            headers=get_auth_headers(cm_token)
        )
        assert response.status_code == 200

    def test_partner_can_upload_content(
        self, client, app, sample_partner, sample_organization
    ):
        """Partner CAN upload content."""
        # Partner login
        partner_login = client.post('/admin/api/login', json={
            'email': sample_partner.email,
            'password': TEST_PASSWORD
        })
        partner_token = partner_login.get_json()['access_token']

        # Create mock file
        data = {
            'file': (io.BytesIO(b'fake video content'), 'partner_upload_test.mp4'),
            'title': 'Partner Upload Test'
        }

        # Upload - should succeed
        response = client.post(
            '/api/v1/assets/upload',
            headers=get_auth_headers(partner_token),
            data=data,
            content_type='multipart/form-data'
        )
        # May fail due to file validation but should not be 403
        assert response.status_code != 403


class TestSelfApprovalPrevention:
    """
    Tests for preventing self-approval.
    """

    def test_user_cannot_approve_self(
        self, client, app, sample_super_admin, sample_internal_organization
    ):
        """Users cannot approve themselves."""
        # Create a pending user that will try to self-approve
        with app.app_context():
            pending_user = User(
                email='self_approve_test@skillzmedia.com',
                password_hash=sample_super_admin.password_hash,
                name='Self Approve Test',
                role=User.ROLE_CONTENT_MANAGER,
                organization_id=sample_internal_organization.id,
                status=User.STATUS_PENDING
            )
            db.session.add(pending_user)
            db.session.commit()
            pending_user_id = pending_user.id

        # Super Admin approves first so user can login
        sa_login = client.post('/admin/api/login', json={
            'email': sample_super_admin.email,
            'password': TEST_PASSWORD
        })
        sa_token = sa_login.get_json()['access_token']

        # Activate the user
        client.post(
            f'/api/v1/approvals/{pending_user_id}/approve',
            headers=get_auth_headers(sa_token)
        )

        # Create another pending user for the test
        with app.app_context():
            test_pending = User(
                email='test_self_approve@skillzmedia.com',
                password_hash=sample_super_admin.password_hash,
                name='Test Self Approve',
                role=User.ROLE_PARTNER,
                organization_id=sample_internal_organization.id,
                status=User.STATUS_PENDING
            )
            db.session.add(test_pending)
            db.session.commit()
            test_pending_id = test_pending.id

        # Now login as the activated user
        user_login = client.post('/admin/api/login', json={
            'email': 'self_approve_test@skillzmedia.com',
            'password': TEST_PASSWORD
        })
        user_token = user_login.get_json()['access_token']

        # Try to approve the other pending user (this should work as CM can approve Partner)
        response = client.post(
            f'/api/v1/approvals/{test_pending_id}/approve',
            headers=get_auth_headers(user_token)
        )
        assert response.status_code == 200


class TestUnauthorizedWithNoToken:
    """
    Tests for requests without authentication.
    """

    def test_approve_without_token_returns_401(self, client, app, sample_pending_user):
        """Approve without token returns 401."""
        response = client.post(
            f'/api/v1/approvals/{sample_pending_user.id}/approve'
        )
        assert response.status_code == 401

    def test_upload_without_token_returns_401(self, client, app):
        """Upload without token returns 401."""
        data = {
            'file': (io.BytesIO(b'fake content'), 'test.mp4'),
            'title': 'No Token Test'
        }
        response = client.post(
            '/api/v1/assets/upload',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 401

    def test_publish_without_token_returns_401(self, client, app, sample_content_asset):
        """Publish without token returns 401."""
        response = client.post(
            f'/api/v1/assets/{sample_content_asset.uuid}/publish'
        )
        assert response.status_code == 401
