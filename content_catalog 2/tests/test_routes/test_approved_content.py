"""
Integration tests for Content Catalog Approved Content API endpoint.

Tests the GET /api/v1/approvals/content/approved endpoint which returns
approved and published content assets for CMS integration.

This endpoint is critical for the CMS sync feature, enabling the CMS to
fetch approved content from the Content Catalog without direct upload access.

Test categories:
- Successful retrieval tests (authenticated users)
- Status filtering tests (only approved/published content)
- Network filtering tests
- Organization filtering tests
- Category filtering tests
- Pagination tests
- Authentication error tests
- Invalid parameter tests
"""

import json
import pytest
from datetime import datetime, timezone

from content_catalog.models import db, User, ContentAsset
from content_catalog.tests.conftest import (
    TEST_PASSWORD,
    get_auth_headers,
    create_test_content_asset,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def approved_content(db_session, sample_organization, sample_partner):
    """Create approved content asset for testing."""
    asset = ContentAsset(
        title='Approved Video',
        description='An approved video asset',
        filename='approved_video.mp4',
        file_path='/uploads/approved_video.mp4',
        file_size=10240000,
        duration=60.0,
        resolution='1920x1080',
        format='mp4',
        organization_id=sample_organization.id,
        uploaded_by=sample_partner.id,
        status=ContentAsset.STATUS_APPROVED,
        category='promotional',
        tags='approved,test',
        networks='["network-1", "network-2"]'
    )
    db_session.add(asset)
    db_session.commit()
    return asset


@pytest.fixture
def published_content(db_session, sample_organization, sample_partner, sample_content_manager):
    """Create published content asset for testing."""
    asset = ContentAsset(
        title='Published Video',
        description='A published video asset',
        filename='published_video.mp4',
        file_path='/uploads/published_video.mp4',
        file_size=20480000,
        duration=120.0,
        resolution='1920x1080',
        format='mp4',
        organization_id=sample_organization.id,
        uploaded_by=sample_partner.id,
        status=ContentAsset.STATUS_PUBLISHED,
        reviewed_by=sample_content_manager.id,
        reviewed_at=datetime.now(timezone.utc),
        published_at=datetime.now(timezone.utc),
        category='featured',
        tags='published,featured',
        networks='["network-1"]'
    )
    db_session.add(asset)
    db_session.commit()
    return asset


@pytest.fixture
def draft_content(db_session, sample_organization, sample_partner):
    """Create draft content asset for testing (should not appear in results)."""
    asset = ContentAsset(
        title='Draft Video',
        description='A draft video asset',
        filename='draft_video.mp4',
        file_path='/uploads/draft_video.mp4',
        file_size=5120000,
        duration=30.0,
        resolution='1920x1080',
        format='mp4',
        organization_id=sample_organization.id,
        uploaded_by=sample_partner.id,
        status=ContentAsset.STATUS_DRAFT,
        category='promotional',
        tags='draft'
    )
    db_session.add(asset)
    db_session.commit()
    return asset


@pytest.fixture
def pending_review_content(db_session, sample_organization, sample_partner):
    """Create pending review content asset for testing (should not appear in results)."""
    asset = ContentAsset(
        title='Pending Review Video',
        description='A video pending review',
        filename='pending_review_video.mp4',
        file_path='/uploads/pending_review_video.mp4',
        file_size=15360000,
        duration=90.0,
        resolution='1920x1080',
        format='mp4',
        organization_id=sample_organization.id,
        uploaded_by=sample_partner.id,
        status=ContentAsset.STATUS_PENDING_REVIEW,
        category='advertisement',
        tags='pending'
    )
    db_session.add(asset)
    db_session.commit()
    return asset


@pytest.fixture
def rejected_content(db_session, sample_organization, sample_partner, sample_content_manager):
    """Create rejected content asset for testing (should not appear in results)."""
    asset = ContentAsset(
        title='Rejected Video',
        description='A rejected video asset',
        filename='rejected_video.mp4',
        file_path='/uploads/rejected_video.mp4',
        file_size=8192000,
        duration=45.0,
        resolution='1920x1080',
        format='mp4',
        organization_id=sample_organization.id,
        uploaded_by=sample_partner.id,
        status=ContentAsset.STATUS_REJECTED,
        reviewed_by=sample_content_manager.id,
        reviewed_at=datetime.now(timezone.utc),
        review_notes='Does not meet quality standards',
        category='promotional',
        tags='rejected'
    )
    db_session.add(asset)
    db_session.commit()
    return asset


@pytest.fixture
def archived_content(db_session, sample_organization, sample_partner):
    """Create archived content asset for testing (should not appear in results)."""
    asset = ContentAsset(
        title='Archived Video',
        description='An archived video asset',
        filename='archived_video.mp4',
        file_path='/uploads/archived_video.mp4',
        file_size=10240000,
        duration=60.0,
        resolution='1920x1080',
        format='mp4',
        organization_id=sample_organization.id,
        uploaded_by=sample_partner.id,
        status=ContentAsset.STATUS_ARCHIVED,
        category='promotional',
        tags='archived'
    )
    db_session.add(asset)
    db_session.commit()
    return asset


# =============================================================================
# Successful Retrieval Tests
# =============================================================================

class TestApprovedContentEndpoint:
    """Tests for GET /api/v1/approvals/content/approved endpoint."""

    # -------------------------------------------------------------------------
    # Success Cases
    # -------------------------------------------------------------------------

    def test_get_approved_content_success(self, client, app, sample_admin, approved_content):
        """GET /content/approved should return approved content for authenticated user."""
        # Login to get token
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get approved content
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert 'assets' in data
        assert 'count' in data
        assert 'page' in data
        assert 'per_page' in data
        assert 'total' in data
        assert data['count'] >= 1
        assert any(a['title'] == 'Approved Video' for a in data['assets'])

    def test_get_approved_content_includes_published(self, client, app, sample_admin, published_content):
        """GET /content/approved should include published content."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get approved content
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert any(a['title'] == 'Published Video' for a in data['assets'])

    def test_get_approved_content_returns_all_fields(self, client, app, sample_admin, approved_content):
        """GET /content/approved should return all content asset fields."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get approved content
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()

        # Find the approved video
        asset = next((a for a in data['assets'] if a['title'] == 'Approved Video'), None)
        assert asset is not None

        # Verify expected fields are present
        expected_fields = [
            'id', 'uuid', 'title', 'description', 'filename', 'file_path',
            'file_size', 'duration', 'resolution', 'format', 'status',
            'organization_id', 'category', 'tags', 'networks'
        ]
        for field in expected_fields:
            assert field in asset, f"Missing field: {field}"

    def test_get_approved_content_different_roles(self, client, app, sample_super_admin, sample_admin,
                                                   sample_content_manager, sample_partner, approved_content):
        """GET /content/approved should work for different user roles."""
        users = [sample_super_admin, sample_admin, sample_content_manager, sample_partner]

        for user in users:
            # Login
            login_response = client.post('/admin/api/login', json={
                'email': user.email,
                'password': TEST_PASSWORD
            })
            token = login_response.get_json()['access_token']

            # Get approved content
            response = client.get('/api/v1/approvals/content/approved',
                                  headers=get_auth_headers(token))

            assert response.status_code == 200, f"Failed for user role: {user.role}"
            data = response.get_json()
            assert 'assets' in data


# =============================================================================
# Status Filtering Tests
# =============================================================================

class TestApprovedContentStatusFiltering:
    """Tests ensuring only approved/published content is returned."""

    def test_excludes_draft_content(self, client, app, sample_admin,
                                    approved_content, draft_content):
        """GET /content/approved should NOT return draft content."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get approved content
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()

        # Verify draft content is not in results
        titles = [a['title'] for a in data['assets']]
        assert 'Draft Video' not in titles

    def test_excludes_pending_review_content(self, client, app, sample_admin,
                                              approved_content, pending_review_content):
        """GET /content/approved should NOT return pending review content."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get approved content
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()

        # Verify pending content is not in results
        titles = [a['title'] for a in data['assets']]
        assert 'Pending Review Video' not in titles

    def test_excludes_rejected_content(self, client, app, sample_admin,
                                        approved_content, rejected_content):
        """GET /content/approved should NOT return rejected content."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get approved content
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()

        # Verify rejected content is not in results
        titles = [a['title'] for a in data['assets']]
        assert 'Rejected Video' not in titles

    def test_excludes_archived_content(self, client, app, sample_admin,
                                        approved_content, archived_content):
        """GET /content/approved should NOT return archived content."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get approved content
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()

        # Verify archived content is not in results
        titles = [a['title'] for a in data['assets']]
        assert 'Archived Video' not in titles

    def test_only_returns_approved_and_published(self, client, app, sample_admin,
                                                  approved_content, published_content,
                                                  draft_content, pending_review_content,
                                                  rejected_content, archived_content):
        """GET /content/approved should ONLY return approved and published content."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get approved content
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()

        # Verify exactly 2 items (approved + published)
        assert data['total'] == 2

        # Verify all returned content is in approved or published status
        statuses = [a['status'] for a in data['assets']]
        for status in statuses:
            assert status in [ContentAsset.STATUS_APPROVED, ContentAsset.STATUS_PUBLISHED]


# =============================================================================
# Network Filtering Tests
# =============================================================================

class TestApprovedContentNetworkFilter:
    """Tests for network_id filter parameter."""

    def test_filter_by_network_id(self, client, app, sample_admin, approved_content, published_content):
        """GET /content/approved?network_id=X should filter by network."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get content for network-2 (only approved_content has it)
        response = client.get('/api/v1/approvals/content/approved?network_id=network-2',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()

        # Only the approved content has network-2
        assert data['total'] >= 1
        titles = [a['title'] for a in data['assets']]
        assert 'Approved Video' in titles

    def test_filter_by_common_network_id(self, client, app, sample_admin, approved_content, published_content):
        """GET /content/approved?network_id=X should return all matching content."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get content for network-1 (both have it)
        response = client.get('/api/v1/approvals/content/approved?network_id=network-1',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()

        # Both approved and published have network-1
        assert data['total'] == 2

    def test_filter_by_non_existent_network(self, client, app, sample_admin, approved_content):
        """GET /content/approved?network_id=X should return empty for non-existent network."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get content for non-existent network
        response = client.get('/api/v1/approvals/content/approved?network_id=non-existent-network',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert data['total'] == 0
        assert data['count'] == 0
        assert data['assets'] == []


# =============================================================================
# Organization Filtering Tests
# =============================================================================

class TestApprovedContentOrganizationFilter:
    """Tests for organization_id filter parameter."""

    def test_filter_by_organization_id(self, client, app, sample_admin,
                                        sample_organization, approved_content):
        """GET /content/approved?organization_id=X should filter by organization."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get content for specific organization
        response = client.get(
            f'/api/v1/approvals/content/approved?organization_id={sample_organization.id}',
            headers=get_auth_headers(token)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['total'] >= 1

        # All returned content should belong to the organization
        for asset in data['assets']:
            assert asset['organization_id'] == sample_organization.id

    def test_filter_by_non_existent_organization(self, client, app, sample_admin, approved_content):
        """GET /content/approved?organization_id=X should return empty for non-existent org."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get content for non-existent organization
        response = client.get('/api/v1/approvals/content/approved?organization_id=99999',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert data['total'] == 0

    def test_invalid_organization_id_returns_error(self, client, app, sample_admin, approved_content):
        """GET /content/approved?organization_id=invalid should return 400."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get content with invalid organization_id
        response = client.get('/api/v1/approvals/content/approved?organization_id=invalid',
                              headers=get_auth_headers(token))

        assert response.status_code == 400
        data = response.get_json()
        assert 'organization_id must be an integer' in data['error']


# =============================================================================
# Category Filtering Tests
# =============================================================================

class TestApprovedContentCategoryFilter:
    """Tests for category filter parameter."""

    def test_filter_by_category(self, client, app, sample_admin, approved_content, published_content):
        """GET /content/approved?category=X should filter by category."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get content for 'promotional' category
        response = client.get('/api/v1/approvals/content/approved?category=promotional',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()

        # All returned content should have the category
        for asset in data['assets']:
            assert asset['category'] == 'promotional'

    def test_filter_by_featured_category(self, client, app, sample_admin, approved_content, published_content):
        """GET /content/approved?category=featured should only return featured content."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get content for 'featured' category
        response = client.get('/api/v1/approvals/content/approved?category=featured',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()

        # Should only include published video (which has featured category)
        for asset in data['assets']:
            assert asset['category'] == 'featured'

    def test_filter_by_non_existent_category(self, client, app, sample_admin, approved_content):
        """GET /content/approved?category=X should return empty for non-existent category."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get content for non-existent category
        response = client.get('/api/v1/approvals/content/approved?category=non-existent',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert data['total'] == 0


# =============================================================================
# Pagination Tests
# =============================================================================

class TestApprovedContentPagination:
    """Tests for pagination parameters."""

    def test_default_pagination(self, client, app, sample_admin, approved_content):
        """GET /content/approved should use default pagination (page=1, per_page=20)."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get approved content without pagination params
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert data['page'] == 1
        assert data['per_page'] == 20

    def test_custom_page_number(self, client, app, sample_admin, approved_content):
        """GET /content/approved?page=2 should return second page."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get second page
        response = client.get('/api/v1/approvals/content/approved?page=2',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert data['page'] == 2

    def test_custom_per_page(self, client, app, sample_admin, approved_content):
        """GET /content/approved?per_page=5 should limit results per page."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get with custom per_page
        response = client.get('/api/v1/approvals/content/approved?per_page=5',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert data['per_page'] == 5

    def test_max_per_page_limit(self, client, app, sample_admin, approved_content):
        """GET /content/approved?per_page=200 should cap at 100."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get with per_page exceeding max
        response = client.get('/api/v1/approvals/content/approved?per_page=200',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert data['per_page'] == 100

    def test_invalid_page_defaults_to_one(self, client, app, sample_admin, approved_content):
        """GET /content/approved?page=invalid should default to page 1."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get with invalid page
        response = client.get('/api/v1/approvals/content/approved?page=invalid',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert data['page'] == 1

    def test_negative_page_defaults_to_one(self, client, app, sample_admin, approved_content):
        """GET /content/approved?page=-1 should default to page 1."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get with negative page
        response = client.get('/api/v1/approvals/content/approved?page=-1',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert data['page'] == 1


# =============================================================================
# Combined Filter Tests
# =============================================================================

class TestApprovedContentCombinedFilters:
    """Tests for combining multiple filter parameters."""

    def test_combine_network_and_organization_filters(self, client, app, sample_admin,
                                                       sample_organization, approved_content):
        """GET /content/approved with network_id and organization_id should combine filters."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get with combined filters
        response = client.get(
            f'/api/v1/approvals/content/approved?network_id=network-1&organization_id={sample_organization.id}',
            headers=get_auth_headers(token)
        )

        assert response.status_code == 200
        data = response.get_json()

        # All returned content should match both filters
        for asset in data['assets']:
            assert asset['organization_id'] == sample_organization.id
            assert 'network-1' in asset['networks']

    def test_combine_category_and_pagination(self, client, app, sample_admin, approved_content):
        """GET /content/approved with category and pagination should work together."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get with combined filters
        response = client.get(
            '/api/v1/approvals/content/approved?category=promotional&page=1&per_page=10',
            headers=get_auth_headers(token)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['page'] == 1
        assert data['per_page'] == 10

        # All returned content should match the category
        for asset in data['assets']:
            assert asset['category'] == 'promotional'


# =============================================================================
# Authentication Error Tests
# =============================================================================

class TestApprovedContentAuthentication:
    """Tests for authentication requirements."""

    def test_no_token_returns_401(self, client, app, approved_content):
        """GET /content/approved without token should return 401."""
        response = client.get('/api/v1/approvals/content/approved')

        assert response.status_code == 401

    def test_invalid_token_returns_error(self, client, app, approved_content):
        """GET /content/approved with invalid token should return error."""
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers('invalid.token.here'))

        assert response.status_code == 422  # JWT decode error

    def test_malformed_token_returns_error(self, client, app, approved_content):
        """GET /content/approved with malformed token should return error."""
        response = client.get('/api/v1/approvals/content/approved',
                              headers={'Authorization': 'Bearer '})

        assert response.status_code in [401, 422]


# =============================================================================
# Empty Results Tests
# =============================================================================

class TestApprovedContentEmptyResults:
    """Tests for handling empty result sets."""

    def test_empty_catalog_returns_empty_list(self, client, app, sample_admin):
        """GET /content/approved with no content should return empty list."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get approved content when none exists
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert data['assets'] == []
        assert data['count'] == 0
        assert data['total'] == 0

    def test_all_non_approved_content_returns_empty(self, client, app, sample_admin,
                                                     draft_content, pending_review_content,
                                                     rejected_content, archived_content):
        """GET /content/approved with only non-approved content should return empty list."""
        # Login
        login_response = client.post('/admin/api/login', json={
            'email': sample_admin.email,
            'password': TEST_PASSWORD
        })
        token = login_response.get_json()['access_token']

        # Get approved content when only non-approved exists
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers(token))

        assert response.status_code == 200
        data = response.get_json()
        assert data['assets'] == []
        assert data['total'] == 0


# =============================================================================
# User Not Found Test
# =============================================================================

class TestApprovedContentUserNotFound:
    """Tests for handling deleted users with valid tokens."""

    def test_deleted_user_returns_404(self, client, app, db_session, sample_admin, approved_content):
        """GET /content/approved should return 404 if user is deleted after login."""
        # Login
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

        # Try to get approved content
        response = client.get('/api/v1/approvals/content/approved',
                              headers=get_auth_headers(token))

        assert response.status_code == 404
        data = response.get_json()
        assert 'User not found' in data['error']
