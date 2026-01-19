"""
End-to-end tests for Fast-Track Checkout functionality.

This test module verifies the critical Thea requirement that:
- Regular users cannot checkout DRAFT/SUBMITTED assets (403 Forbidden)
- Fast-track users can checkout DRAFT/SUBMITTED assets for urgent needs
- Fast-track checkouts are logged with FASTTRACK_CHECKOUT audit event

Per Thea spec requirement:
"Fast-Track Permissions: Privileged users can checkout DRAFT/SUBMITTED assets for urgent needs"
"Acceptance: Fast-track checkout works for authorized users; logged as FASTTRACK_CHECKOUT"
"""

import pytest
from datetime import datetime, timezone, timedelta

from content_catalog.models import (
    db,
    User,
    Organization,
    ContentAsset,
    AuditLog
)
from content_catalog.tests.conftest import TEST_PASSWORD, TEST_PASSWORD_HASH, get_auth_headers


# =============================================================================
# Fast-Track Checkout Test Fixtures
# =============================================================================

@pytest.fixture(scope='function')
def brand_org_for_fasttrack(db_session):
    """
    Create a BRAND type organization for fast-track testing.

    Returns:
        Organization instance with org_type=BRAND
    """
    org = Organization(
        name='Fast-Track Test Brand',
        type='partner',
        org_type=Organization.ORG_TYPE_BRAND,
        contact_email='fasttrack-brand@testbrand.com',
        status='active'
    )
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture(scope='function')
def skillz_org_for_fasttrack(db_session):
    """
    Create a SKILLZ type organization for fast-track testing.

    Returns:
        Organization instance with org_type=SKILLZ
    """
    org = Organization(
        name='Skillz Media Fast-Track',
        type='internal',
        org_type=Organization.ORG_TYPE_SKILLZ,
        contact_email='fasttrack-admin@skillzmedia.com',
        status='active'
    )
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture(scope='function')
def regular_user(db_session, brand_org_for_fasttrack):
    """
    Create a regular user WITHOUT fast-track permission.

    This user should NOT be able to checkout DRAFT/SUBMITTED assets.

    Returns:
        User instance without fast-track permission
    """
    user = User(
        email='regular_user@fasttracktest.com',
        password_hash=TEST_PASSWORD_HASH,
        name='Regular User - No Fast-Track',
        role=User.ROLE_PARTNER,
        organization_id=brand_org_for_fasttrack.id,
        status=User.STATUS_ACTIVE,
        can_fasttrack_unapproved_assets=False
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def fasttrack_user(db_session, skillz_org_for_fasttrack):
    """
    Create a user WITH fast-track permission.

    This user should be able to checkout DRAFT/SUBMITTED assets.

    Returns:
        User instance with fast-track permission (no expiry)
    """
    user = User(
        email='fasttrack_user@skillzmedia.com',
        password_hash=TEST_PASSWORD_HASH,
        name='Fast-Track User',
        role=User.ROLE_CONTENT_MANAGER,
        organization_id=skillz_org_for_fasttrack.id,
        status=User.STATUS_ACTIVE,
        can_fasttrack_unapproved_assets=True,
        fasttrack_expires_at=None  # No expiry - always valid
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def fasttrack_user_with_expiry(db_session, skillz_org_for_fasttrack):
    """
    Create a user with fast-track permission that has a future expiry.

    Returns:
        User instance with fast-track permission (valid for 7 days)
    """
    user = User(
        email='fasttrack_expiring@skillzmedia.com',
        password_hash=TEST_PASSWORD_HASH,
        name='Fast-Track User With Expiry',
        role=User.ROLE_CONTENT_MANAGER,
        organization_id=skillz_org_for_fasttrack.id,
        status=User.STATUS_ACTIVE,
        can_fasttrack_unapproved_assets=True,
        fasttrack_expires_at=datetime.now(timezone.utc) + timedelta(days=7)
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def expired_fasttrack_user(db_session, skillz_org_for_fasttrack):
    """
    Create a user with EXPIRED fast-track permission.

    This user should NOT be able to checkout DRAFT/SUBMITTED assets
    because their fast-track permission has expired.

    Returns:
        User instance with expired fast-track permission
    """
    user = User(
        email='expired_fasttrack@skillzmedia.com',
        password_hash=TEST_PASSWORD_HASH,
        name='Expired Fast-Track User',
        role=User.ROLE_CONTENT_MANAGER,
        organization_id=skillz_org_for_fasttrack.id,
        status=User.STATUS_ACTIVE,
        can_fasttrack_unapproved_assets=True,
        fasttrack_expires_at=datetime.now(timezone.utc) - timedelta(hours=1)  # Expired 1 hour ago
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def content_uploader(db_session, brand_org_for_fasttrack):
    """
    Create a content uploader user for creating test assets.

    Returns:
        User instance with partner role (can upload content)
    """
    user = User(
        email='content_uploader@fasttracktest.com',
        password_hash=TEST_PASSWORD_HASH,
        name='Content Uploader',
        role=User.ROLE_PARTNER,
        organization_id=brand_org_for_fasttrack.id,
        status=User.STATUS_ACTIVE
    )
    db_session.add(user)
    db_session.commit()
    return user


# =============================================================================
# E2E Test: Fast-Track Checkout - Full Workflow
# =============================================================================

class TestFastTrackCheckoutE2E:
    """
    End-to-end test suite for fast-track checkout functionality.

    Key requirements verified:
    1. Regular users cannot checkout DRAFT assets (403 Forbidden)
    2. Fast-track users can checkout DRAFT assets (200 Success)
    3. Audit log captures FASTTRACK_CHECKOUT event with correct details
    """

    def test_e2e_fasttrack_checkout_full_workflow(
        self,
        client,
        app,
        regular_user,
        fasttrack_user,
        content_uploader,
        brand_org_for_fasttrack
    ):
        """
        E2E test: Complete fast-track checkout workflow.

        Steps:
        1. Create DRAFT asset
        2. Login as regular user, try checkout -> verify 403
        3. Login as fast-track user, checkout -> verify success
        4. Verify audit log shows FASTTRACK_CHECKOUT event
        """
        # =====================================================================
        # Step 1: Create DRAFT asset
        # =====================================================================
        # Assets are created in DRAFT state by default
        create_response = client.post('/api/v1/assets', json={
            'title': 'Fast-Track Test Asset',
            'description': 'Asset for fast-track checkout testing',
            'filename': 'fasttrack_test_video.mp4',
            'file_path': '/uploads/fasttrack_test_video.mp4',
            'file_size': 10240000,
            'format': 'mp4',
            'organization_id': brand_org_for_fasttrack.id,
            'category': 'promotional'
        })

        assert create_response.status_code == 201, \
            f"Asset creation failed: {create_response.get_json()}"

        asset = create_response.get_json()
        asset_uuid = asset['uuid']
        asset_id = asset['id']

        # Verify asset is in DRAFT state
        assert asset['status'] == ContentAsset.STATUS_DRAFT, \
            f"Expected DRAFT status, got {asset['status']}"

        # =====================================================================
        # Step 2: Login as regular user and try to checkout DRAFT asset
        # =====================================================================
        regular_login = client.post('/admin/api/login', json={
            'email': regular_user.email,
            'password': TEST_PASSWORD
        })

        assert regular_login.status_code == 200, \
            f"Regular user login failed: {regular_login.get_json()}"
        regular_token = regular_login.get_json()['access_token']

        # Verify user does not have fast-track permission
        regular_me = client.get('/admin/api/me', headers=get_auth_headers(regular_token))
        assert regular_me.status_code == 200
        assert regular_me.get_json()['can_fasttrack_unapproved_assets'] is False, \
            "Regular user should not have fast-track permission"

        # Try to checkout DRAFT asset (should fail with 403)
        regular_checkout_response = client.post(
            f'/api/v1/assets/{asset_uuid}/checkout',
            headers=get_auth_headers(regular_token)
        )

        # CRITICAL: Regular user must be blocked from checking out DRAFT assets
        assert regular_checkout_response.status_code == 403, \
            f"Regular user should get 403 for DRAFT checkout, got {regular_checkout_response.status_code}"

        error_data = regular_checkout_response.get_json()
        assert 'error' in error_data, "Error response should contain 'error' field"

        # Verify error message indicates fast-track is required
        error_msg = error_data['error'].lower()
        assert 'fast-track' in error_msg or 'fasttrack' in error_msg or 'permission' in error_msg, \
            f"Error message should indicate fast-track required: {error_data['error']}"

        # =====================================================================
        # Step 3: Login as fast-track user and checkout DRAFT asset
        # =====================================================================
        fasttrack_login = client.post('/admin/api/login', json={
            'email': fasttrack_user.email,
            'password': TEST_PASSWORD
        })

        assert fasttrack_login.status_code == 200, \
            f"Fast-track user login failed: {fasttrack_login.get_json()}"
        fasttrack_token = fasttrack_login.get_json()['access_token']

        # Verify user has fast-track permission
        fasttrack_me = client.get('/admin/api/me', headers=get_auth_headers(fasttrack_token))
        assert fasttrack_me.status_code == 200
        assert fasttrack_me.get_json()['can_fasttrack_unapproved_assets'] is True, \
            "Fast-track user should have fast-track permission"

        # Checkout DRAFT asset (should succeed)
        fasttrack_checkout_response = client.post(
            f'/api/v1/assets/{asset_uuid}/checkout',
            headers=get_auth_headers(fasttrack_token)
        )

        # CRITICAL: Fast-track user must succeed
        assert fasttrack_checkout_response.status_code == 200, \
            f"Fast-track checkout failed: {fasttrack_checkout_response.get_json()}"

        checkout_data = fasttrack_checkout_response.get_json()

        # Verify checkout response structure
        assert 'token' in checkout_data, "Checkout response missing 'token'"
        assert 'download_url' in checkout_data, "Checkout response missing 'download_url'"
        assert 'expires_at' in checkout_data, "Checkout response missing 'expires_at'"
        assert 'is_fasttrack' in checkout_data, "Checkout response missing 'is_fasttrack'"
        assert 'asset' in checkout_data, "Checkout response missing 'asset'"

        # Verify this is a fast-track checkout
        assert checkout_data['is_fasttrack'] is True, \
            "Checkout of DRAFT asset should be marked as fast-track"

        # Verify token is present and non-empty
        assert checkout_data['token'] is not None
        assert len(checkout_data['token']) > 20, "Token seems too short"

        # Verify download URL format
        assert checkout_data['download_url'].startswith('/api/v1/download/')
        assert checkout_data['token'] in checkout_data['download_url']

        # Verify expiration timestamp is valid
        expires_at = datetime.fromisoformat(checkout_data['expires_at'].replace('Z', '+00:00'))
        assert expires_at > datetime.now(timezone.utc), "Token already expired"

        # Verify asset data is included
        assert checkout_data['asset']['uuid'] == asset_uuid
        assert checkout_data['asset']['status'] == ContentAsset.STATUS_DRAFT

        # =====================================================================
        # Step 4: Verify audit log shows FASTTRACK_CHECKOUT event
        # =====================================================================
        with app.app_context():
            # Query for FASTTRACK_CHECKOUT audit event
            fasttrack_audit_logs = AuditLog.query.filter_by(
                action=AuditLog.ACTION_FASTTRACK_CHECKOUT,
                resource_id=str(asset_id)
            ).all()

            assert len(fasttrack_audit_logs) >= 1, \
                f"Expected FASTTRACK_CHECKOUT audit event, found {len(fasttrack_audit_logs)} events"

            # Verify audit log details
            fasttrack_log = fasttrack_audit_logs[0]
            assert fasttrack_log.user_id == fasttrack_user.id, \
                f"Audit log user_id should be fast-track user, got {fasttrack_log.user_id}"
            assert fasttrack_log.user_email == fasttrack_user.email, \
                "Audit log should contain fast-track user's email"
            assert fasttrack_log.resource_type == AuditLog.RESOURCE_CHECKOUT_TOKEN, \
                f"Resource type should be checkout_token, got {fasttrack_log.resource_type}"

            # Verify audit log details contain fast-track indicator
            import json
            if fasttrack_log.details:
                details = json.loads(fasttrack_log.details)
                assert details.get('is_fasttrack') is True, \
                    "Audit log details should indicate is_fasttrack=True"
                assert details.get('asset_status') == ContentAsset.STATUS_DRAFT, \
                    "Audit log should capture asset was DRAFT status"

    def test_e2e_fasttrack_checkout_submitted_asset(
        self,
        client,
        app,
        regular_user,
        fasttrack_user,
        content_uploader,
        brand_org_for_fasttrack
    ):
        """
        E2E test: Fast-track checkout of SUBMITTED (pending_review) asset.

        Verifies fast-track works for PENDING_REVIEW state, not just DRAFT.
        """
        # Create asset
        create_response = client.post('/api/v1/assets', json={
            'title': 'Submitted Asset Fast-Track Test',
            'filename': 'submitted_fasttrack_test.mp4',
            'file_path': '/uploads/submitted_fasttrack_test.mp4',
            'organization_id': brand_org_for_fasttrack.id
        })
        asset_uuid = create_response.get_json()['uuid']
        asset_id = create_response.get_json()['id']

        # Submit for review (change to PENDING_REVIEW)
        uploader_login = client.post('/admin/api/login', json={
            'email': content_uploader.email,
            'password': TEST_PASSWORD
        })
        uploader_token = uploader_login.get_json()['access_token']

        submit_response = client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(uploader_token)
        )
        assert submit_response.status_code == 200, \
            f"Submit failed: {submit_response.get_json()}"

        # Verify asset is now in PENDING_REVIEW state
        get_response = client.get(f'/api/v1/assets/{asset_uuid}')
        assert get_response.get_json()['status'] == ContentAsset.STATUS_PENDING_REVIEW

        # Regular user should be blocked
        regular_login = client.post('/admin/api/login', json={
            'email': regular_user.email,
            'password': TEST_PASSWORD
        })
        regular_token = regular_login.get_json()['access_token']

        regular_checkout = client.post(
            f'/api/v1/assets/{asset_uuid}/checkout',
            headers=get_auth_headers(regular_token)
        )
        assert regular_checkout.status_code == 403, \
            "Regular user should not be able to checkout PENDING_REVIEW asset"

        # Fast-track user should succeed
        fasttrack_login = client.post('/admin/api/login', json={
            'email': fasttrack_user.email,
            'password': TEST_PASSWORD
        })
        fasttrack_token = fasttrack_login.get_json()['access_token']

        fasttrack_checkout = client.post(
            f'/api/v1/assets/{asset_uuid}/checkout',
            headers=get_auth_headers(fasttrack_token)
        )
        assert fasttrack_checkout.status_code == 200, \
            f"Fast-track checkout of PENDING_REVIEW failed: {fasttrack_checkout.get_json()}"

        checkout_data = fasttrack_checkout.get_json()
        assert checkout_data['is_fasttrack'] is True

        # Verify audit log
        with app.app_context():
            fasttrack_log = AuditLog.query.filter_by(
                action=AuditLog.ACTION_FASTTRACK_CHECKOUT,
                resource_id=str(asset_id)
            ).first()
            assert fasttrack_log is not None, "FASTTRACK_CHECKOUT audit event missing"


class TestFastTrackCheckoutEdgeCases:
    """
    Test edge cases for fast-track checkout functionality.
    """

    def test_expired_fasttrack_permission_blocked(
        self,
        client,
        app,
        expired_fasttrack_user,
        brand_org_for_fasttrack
    ):
        """
        Test that users with expired fast-track permission are blocked.

        Per spec edge case: "Fast-Track Expiry - Expired fast-track permission returns 403 on checkout"
        """
        # Create DRAFT asset
        create_response = client.post('/api/v1/assets', json={
            'title': 'Expired Fast-Track Test',
            'filename': 'expired_fasttrack_test.mp4',
            'file_path': '/uploads/expired_fasttrack_test.mp4',
            'organization_id': brand_org_for_fasttrack.id
        })
        asset_uuid = create_response.get_json()['uuid']

        # Login as user with expired fast-track
        login = client.post('/admin/api/login', json={
            'email': expired_fasttrack_user.email,
            'password': TEST_PASSWORD
        })
        token = login.get_json()['access_token']

        # Verify user has can_fasttrack_unapproved_assets but it's expired
        me_response = client.get('/admin/api/me', headers=get_auth_headers(token))
        user_data = me_response.get_json()
        assert user_data['can_fasttrack_unapproved_assets'] is True, \
            "User should have fast-track flag set"
        assert user_data['fasttrack_expires_at'] is not None, \
            "User should have expiry set"

        # Verify the expiry is in the past (already verified in fixture, but double-check)
        expires_at = datetime.fromisoformat(user_data['fasttrack_expires_at'].replace('Z', '+00:00'))
        assert expires_at < datetime.now(timezone.utc), \
            "Fast-track permission should be expired"

        # Try to checkout (should fail)
        checkout_response = client.post(
            f'/api/v1/assets/{asset_uuid}/checkout',
            headers=get_auth_headers(token)
        )

        # Should get 403 because fast-track has expired
        assert checkout_response.status_code == 403, \
            f"Expired fast-track should return 403, got {checkout_response.status_code}"

        error_data = checkout_response.get_json()
        assert 'expired' in error_data['error'].lower() or 'fast-track' in error_data['error'].lower(), \
            f"Error message should indicate expiry: {error_data['error']}"

    def test_fasttrack_user_with_valid_expiry_succeeds(
        self,
        client,
        app,
        fasttrack_user_with_expiry,
        brand_org_for_fasttrack
    ):
        """
        Test that users with valid (future) fast-track expiry can checkout.
        """
        # Create DRAFT asset
        create_response = client.post('/api/v1/assets', json={
            'title': 'Valid Expiry Fast-Track Test',
            'filename': 'valid_expiry_test.mp4',
            'file_path': '/uploads/valid_expiry_test.mp4',
            'organization_id': brand_org_for_fasttrack.id
        })
        asset_uuid = create_response.get_json()['uuid']

        # Login as user with valid expiry
        login = client.post('/admin/api/login', json={
            'email': fasttrack_user_with_expiry.email,
            'password': TEST_PASSWORD
        })
        token = login.get_json()['access_token']

        # Checkout should succeed
        checkout_response = client.post(
            f'/api/v1/assets/{asset_uuid}/checkout',
            headers=get_auth_headers(token)
        )

        assert checkout_response.status_code == 200, \
            f"Valid fast-track expiry should succeed: {checkout_response.get_json()}"
        assert checkout_response.get_json()['is_fasttrack'] is True

    def test_approved_asset_checkout_not_marked_fasttrack(
        self,
        client,
        app,
        regular_user,
        fasttrack_user,
        brand_org_for_fasttrack
    ):
        """
        Test that checkout of APPROVED assets is not marked as fast-track.

        Fast-track is only for DRAFT/SUBMITTED assets. APPROVED assets
        should have is_fasttrack=False even when checked out by fast-track users.
        """
        # We need to create and approve an asset
        # First create a content manager who can approve
        with app.app_context():
            approver = User(
                email='approver_for_test@skillzmedia.com',
                password_hash=TEST_PASSWORD_HASH,
                name='Test Approver',
                role=User.ROLE_CONTENT_MANAGER,
                status=User.STATUS_ACTIVE,
                can_approve_assets=True
            )
            db.session.add(approver)
            db.session.commit()
            approver_id = approver.id

        # Create asset
        create_response = client.post('/api/v1/assets', json={
            'title': 'Approved Asset Test',
            'filename': 'approved_test.mp4',
            'file_path': '/uploads/approved_test.mp4',
            'organization_id': brand_org_for_fasttrack.id
        })
        asset_uuid = create_response.get_json()['uuid']

        # Submit for review
        regular_login = client.post('/admin/api/login', json={
            'email': regular_user.email,
            'password': TEST_PASSWORD
        })
        regular_token = regular_login.get_json()['access_token']

        client.post(
            f'/api/v1/assets/{asset_uuid}/submit',
            headers=get_auth_headers(regular_token)
        )

        # Approve as the approver
        approver_login = client.post('/admin/api/login', json={
            'email': 'approver_for_test@skillzmedia.com',
            'password': TEST_PASSWORD
        })
        approver_token = approver_login.get_json()['access_token']

        approve_response = client.post(
            f'/api/v1/assets/{asset_uuid}/approve',
            headers=get_auth_headers(approver_token)
        )
        assert approve_response.status_code == 200, \
            f"Approval failed: {approve_response.get_json()}"

        # Now checkout as regular user (should work, APPROVED)
        checkout_response = client.post(
            f'/api/v1/assets/{asset_uuid}/checkout',
            headers=get_auth_headers(regular_token)
        )

        assert checkout_response.status_code == 200, \
            f"Regular checkout of APPROVED should work: {checkout_response.get_json()}"

        checkout_data = checkout_response.get_json()
        assert checkout_data['is_fasttrack'] is False, \
            "Checkout of APPROVED asset should NOT be marked as fast-track"

    def test_fasttrack_audit_log_contains_correct_details(
        self,
        client,
        app,
        fasttrack_user,
        brand_org_for_fasttrack
    ):
        """
        Test that fast-track audit log contains all required details.
        """
        import json

        # Create DRAFT asset
        create_response = client.post('/api/v1/assets', json={
            'title': 'Audit Detail Test Asset',
            'filename': 'audit_detail_test.mp4',
            'file_path': '/uploads/audit_detail_test.mp4',
            'organization_id': brand_org_for_fasttrack.id,
            'category': 'test_category'
        })
        asset_uuid = create_response.get_json()['uuid']
        asset_id = create_response.get_json()['id']

        # Login and checkout
        login = client.post('/admin/api/login', json={
            'email': fasttrack_user.email,
            'password': TEST_PASSWORD
        })
        token = login.get_json()['access_token']

        client.post(
            f'/api/v1/assets/{asset_uuid}/checkout',
            headers=get_auth_headers(token)
        )

        # Verify audit log details
        with app.app_context():
            audit_log = AuditLog.query.filter_by(
                action=AuditLog.ACTION_FASTTRACK_CHECKOUT,
                resource_id=str(asset_id)
            ).first()

            assert audit_log is not None, "FASTTRACK_CHECKOUT audit log missing"

            # Verify required fields
            assert audit_log.user_id == fasttrack_user.id
            assert audit_log.user_email == fasttrack_user.email
            assert audit_log.action == AuditLog.ACTION_FASTTRACK_CHECKOUT
            assert audit_log.resource_type == AuditLog.RESOURCE_CHECKOUT_TOKEN
            assert audit_log.resource_id == str(asset_id)

            # Verify details JSON
            if audit_log.details:
                details = json.loads(audit_log.details)
                assert details.get('asset_id') == asset_id
                assert details.get('asset_uuid') == asset_uuid
                assert details.get('is_fasttrack') is True
                assert details.get('asset_status') == ContentAsset.STATUS_DRAFT
                assert 'token_expires_at' in details


class TestFastTrackEndpointAccess:
    """
    Test the GET /api/v1/assets/fasttrack endpoint for listing fast-track assets.
    """

    def test_regular_user_blocked_from_fasttrack_endpoint(
        self,
        client,
        app,
        regular_user
    ):
        """
        Test that regular users cannot access the fast-track asset list endpoint.
        """
        # Login as regular user
        login = client.post('/admin/api/login', json={
            'email': regular_user.email,
            'password': TEST_PASSWORD
        })
        token = login.get_json()['access_token']

        # Try to access fast-track endpoint
        response = client.get(
            '/api/v1/assets/fasttrack',
            headers=get_auth_headers(token)
        )

        assert response.status_code == 403, \
            f"Regular user should get 403 on fasttrack endpoint, got {response.status_code}"

    def test_fasttrack_user_can_access_fasttrack_endpoint(
        self,
        client,
        app,
        fasttrack_user,
        brand_org_for_fasttrack
    ):
        """
        Test that fast-track users can access the fast-track asset list endpoint.
        """
        # Create some DRAFT and PENDING_REVIEW assets
        for i in range(3):
            client.post('/api/v1/assets', json={
                'title': f'Fast-Track List Test {i}',
                'filename': f'fasttrack_list_{i}.mp4',
                'file_path': f'/uploads/fasttrack_list_{i}.mp4',
                'organization_id': brand_org_for_fasttrack.id
            })

        # Login as fast-track user
        login = client.post('/admin/api/login', json={
            'email': fasttrack_user.email,
            'password': TEST_PASSWORD
        })
        token = login.get_json()['access_token']

        # Access fast-track endpoint
        response = client.get(
            '/api/v1/assets/fasttrack',
            headers=get_auth_headers(token)
        )

        assert response.status_code == 200, \
            f"Fast-track user should access fasttrack endpoint: {response.get_json()}"

        data = response.get_json()
        assert 'assets' in data
        assert 'count' in data
        assert len(data['assets']) >= 3, "Should return at least 3 DRAFT assets"

        # Verify all returned assets are DRAFT or PENDING_REVIEW
        for asset in data['assets']:
            assert asset['status'] in [ContentAsset.STATUS_DRAFT, ContentAsset.STATUS_PENDING_REVIEW], \
                f"Fast-track endpoint should only return DRAFT/PENDING_REVIEW, got {asset['status']}"
