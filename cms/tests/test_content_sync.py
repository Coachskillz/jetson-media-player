"""
Unit tests for ContentSyncService.

Tests all content sync operations:
- fetch_approved_content - API calls to Content Catalog
- sync_approved_content - Full sync workflow
- get_synced_content - Local cache query with filtering
- get_content_by_uuid - Single item retrieval
- get_organizations - Organization list retrieval
- get_sync_status - Sync statistics
- remove_archived_content - Maintenance operation
- clear_synced_content - Cache clearing
- check_content_catalog_health - Health check

Each test class covers a specific operation with comprehensive
endpoint validation including success cases and error handling.
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from cms.models import db
from cms.models.synced_content import SyncedContent
from cms.services.content_sync_service import (
    ContentSyncService,
    ContentSyncError,
    ContentCatalogUnavailableError,
)


# =============================================================================
# Test Data Fixtures
# =============================================================================

@pytest.fixture(scope='function')
def mock_catalog_response():
    """Create mock approved content response from Content Catalog."""
    return {
        'assets': [
            {
                'uuid': 'uuid-video-1',
                'title': 'Promotional Video 1',
                'description': 'High Octane promo video',
                'filename': 'promo1.mp4',
                'file_path': '/uploads/promo1.mp4',
                'file_size': 1024000,
                'duration': 30.5,
                'resolution': '1920x1080',
                'format': 'mp4',
                'thumbnail_path': '/thumbnails/promo1.jpg',
                'status': 'published',
                'organization_id': 1,
                'organization_name': 'Test Org 1',
                'networks': json.dumps(['network-high-octane']),
                'category': 'promotional',
                'tags': 'promo,video',
                'created_at': '2026-01-15T10:00:00Z',
                'published_at': '2026-01-16T10:00:00Z'
            },
            {
                'uuid': 'uuid-video-2',
                'title': 'Summer Sale Video',
                'description': 'Summer sale promotional video',
                'filename': 'summer_sale.mp4',
                'file_path': '/uploads/summer_sale.mp4',
                'file_size': 2048000,
                'duration': 60.0,
                'resolution': '1920x1080',
                'format': 'mp4',
                'thumbnail_path': '/thumbnails/summer_sale.jpg',
                'status': 'approved',
                'organization_id': 2,
                'organization_name': 'Test Org 2',
                'networks': json.dumps(['network-west-marine', 'network-on-the-wave']),
                'category': 'promotional',
                'tags': 'summer,sale',
                'created_at': '2026-01-14T10:00:00Z',
                'published_at': None
            },
            {
                'uuid': 'uuid-image-1',
                'title': 'Brand Logo Image',
                'description': 'High resolution brand logo',
                'filename': 'logo.png',
                'file_path': '/uploads/logo.png',
                'file_size': 50000,
                'duration': None,
                'resolution': '800x600',
                'format': 'png',
                'thumbnail_path': '/thumbnails/logo.jpg',
                'status': 'published',
                'organization_id': 1,
                'organization_name': 'Test Org 1',
                'networks': json.dumps(['network-high-octane', 'network-west-marine']),
                'category': 'branding',
                'tags': 'logo,brand',
                'created_at': '2026-01-13T10:00:00Z',
                'published_at': '2026-01-14T10:00:00Z'
            },
        ],
        'count': 3,
        'page': 1,
        'per_page': 100,
        'total': 3,
        'pages': 1
    }


@pytest.fixture(scope='function')
def sample_synced_content(db_session):
    """Create sample SyncedContent records for testing."""
    contents = []

    # Video content 1 - High Octane network, published
    video1 = SyncedContent(
        source_uuid='test-uuid-video-1',
        title='Test Video 1',
        filename='test_video_1.mp4',
        format='mp4',
        duration=30.0,
        status='published',
        organization_id=1,
        organization_name='Test Org 1',
        network_ids=json.dumps(['network-high-octane'])
    )
    db_session.add(video1)
    contents.append(video1)

    # Video content 2 - West Marine network, approved
    video2 = SyncedContent(
        source_uuid='test-uuid-video-2',
        title='Test Video 2',
        filename='test_video_2.mp4',
        format='mp4',
        duration=60.0,
        status='approved',
        organization_id=2,
        organization_name='Test Org 2',
        network_ids=json.dumps(['network-west-marine'])
    )
    db_session.add(video2)
    contents.append(video2)

    # Image content - Both networks, published
    image1 = SyncedContent(
        source_uuid='test-uuid-image-1',
        title='Test Image 1',
        filename='test_image_1.png',
        format='png',
        duration=None,
        status='published',
        organization_id=1,
        organization_name='Test Org 1',
        network_ids=json.dumps(['network-high-octane', 'network-west-marine'])
    )
    db_session.add(image1)
    contents.append(image1)

    # Audio content - High Octane network, published
    audio1 = SyncedContent(
        source_uuid='test-uuid-audio-1',
        title='Test Audio 1',
        filename='test_audio_1.mp3',
        format='mp3',
        duration=180.0,
        status='published',
        organization_id=1,
        organization_name='Test Org 1',
        network_ids=json.dumps(['network-high-octane'])
    )
    db_session.add(audio1)
    contents.append(audio1)

    # Archived content - should be excluded from normal queries
    archived = SyncedContent(
        source_uuid='test-uuid-archived',
        title='Archived Content',
        filename='archived.mp4',
        format='mp4',
        duration=30.0,
        status='archived',
        organization_id=1,
        organization_name='Test Org 1',
        network_ids=json.dumps(['network-high-octane'])
    )
    db_session.add(archived)
    contents.append(archived)

    db_session.commit()
    return contents


# =============================================================================
# Fetch Approved Content Tests
# =============================================================================

class TestFetchApprovedContent:
    """Tests for ContentSyncService.fetch_approved_content method."""

    @patch('cms.services.content_sync_service.requests.get')
    def test_fetch_approved_content_success(self, mock_get, app, mock_catalog_response):
        """fetch_approved_content should return content from Content Catalog API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_catalog_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with app.app_context():
            result = ContentSyncService.fetch_approved_content()

        assert 'assets' in result
        assert len(result['assets']) == 3
        assert result['total'] == 3
        mock_get.assert_called_once()

    @patch('cms.services.content_sync_service.requests.get')
    def test_fetch_approved_content_with_network_filter(self, mock_get, app, mock_catalog_response):
        """fetch_approved_content should pass network_id parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_catalog_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with app.app_context():
            ContentSyncService.fetch_approved_content(network_id='network-high-octane')

        # Verify network_id is passed in params
        call_args = mock_get.call_args
        assert call_args[1]['params']['network_id'] == 'network-high-octane'

    @patch('cms.services.content_sync_service.requests.get')
    def test_fetch_approved_content_with_organization_filter(self, mock_get, app, mock_catalog_response):
        """fetch_approved_content should pass organization_id parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_catalog_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with app.app_context():
            ContentSyncService.fetch_approved_content(organization_id=1)

        call_args = mock_get.call_args
        assert call_args[1]['params']['organization_id'] == 1

    @patch('cms.services.content_sync_service.requests.get')
    def test_fetch_approved_content_with_category_filter(self, mock_get, app, mock_catalog_response):
        """fetch_approved_content should pass category parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_catalog_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with app.app_context():
            ContentSyncService.fetch_approved_content(category='promotional')

        call_args = mock_get.call_args
        assert call_args[1]['params']['category'] == 'promotional'

    @patch('cms.services.content_sync_service.requests.get')
    def test_fetch_approved_content_with_pagination(self, mock_get, app, mock_catalog_response):
        """fetch_approved_content should pass pagination parameters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_catalog_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with app.app_context():
            ContentSyncService.fetch_approved_content(page=2, per_page=50)

        call_args = mock_get.call_args
        assert call_args[1]['params']['page'] == 2
        assert call_args[1]['params']['per_page'] == 50

    @patch('cms.services.content_sync_service.requests.get')
    def test_fetch_approved_content_enforces_max_page_size(self, mock_get, app, mock_catalog_response):
        """fetch_approved_content should limit per_page to MAX_PAGE_SIZE."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_catalog_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with app.app_context():
            ContentSyncService.fetch_approved_content(per_page=1000)

        call_args = mock_get.call_args
        assert call_args[1]['params']['per_page'] == ContentSyncService.MAX_PAGE_SIZE

    @patch('cms.services.content_sync_service.requests.get')
    def test_fetch_approved_content_connection_error(self, mock_get, app):
        """fetch_approved_content should raise ContentCatalogUnavailableError on connection failure."""
        from requests.exceptions import ConnectionError

        mock_get.side_effect = ConnectionError("Cannot connect")

        with app.app_context():
            with pytest.raises(ContentCatalogUnavailableError) as exc_info:
                ContentSyncService.fetch_approved_content()

        assert 'unavailable' in str(exc_info.value).lower()

    @patch('cms.services.content_sync_service.requests.get')
    def test_fetch_approved_content_timeout_error(self, mock_get, app):
        """fetch_approved_content should raise ContentCatalogUnavailableError on timeout."""
        from requests.exceptions import Timeout

        mock_get.side_effect = Timeout("Request timed out")

        with app.app_context():
            with pytest.raises(ContentCatalogUnavailableError) as exc_info:
                ContentSyncService.fetch_approved_content()

        assert 'timed out' in str(exc_info.value).lower()

    @patch('cms.services.content_sync_service.requests.get')
    def test_fetch_approved_content_request_error(self, mock_get, app):
        """fetch_approved_content should raise ContentSyncError on request failure."""
        from requests.exceptions import RequestException

        mock_get.side_effect = RequestException("Request failed")

        with app.app_context():
            with pytest.raises(ContentSyncError) as exc_info:
                ContentSyncService.fetch_approved_content()

        assert 'failed' in str(exc_info.value).lower()

    @patch('cms.services.content_sync_service.requests.get')
    def test_fetch_approved_content_invalid_json(self, mock_get, app):
        """fetch_approved_content should raise ContentSyncError on invalid JSON response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with app.app_context():
            with pytest.raises(ContentSyncError) as exc_info:
                ContentSyncService.fetch_approved_content()

        assert 'invalid response' in str(exc_info.value).lower()


# =============================================================================
# Sync Approved Content Tests
# =============================================================================

class TestSyncApprovedContent:
    """Tests for ContentSyncService.sync_approved_content method."""

    @patch('cms.services.content_sync_service.requests.get')
    def test_sync_approved_content_success(self, mock_get, app, db_session, mock_catalog_response):
        """sync_approved_content should create SyncedContent records."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_catalog_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with app.app_context():
            result = ContentSyncService.sync_approved_content()

            assert result['synced_count'] == 3
            assert result['created_count'] == 3
            assert result['updated_count'] == 0
            assert result['total_in_catalog'] == 3
            assert result['synced_at'] is not None
            assert len(result['errors']) == 0

            # Verify records created in database
            synced_items = SyncedContent.query.all()
            assert len(synced_items) == 3

    @patch('cms.services.content_sync_service.requests.get')
    def test_sync_approved_content_updates_existing(self, mock_get, app, db_session, mock_catalog_response):
        """sync_approved_content should update existing records."""
        # Create existing record
        with app.app_context():
            existing = SyncedContent(
                source_uuid='uuid-video-1',
                title='Old Title',
                filename='old_file.mp4',
                format='mp4',
                status='approved'
            )
            db_session.add(existing)
            db_session.commit()

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_catalog_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = ContentSyncService.sync_approved_content()

            assert result['synced_count'] == 3
            assert result['created_count'] == 2
            assert result['updated_count'] == 1

            # Verify existing record was updated
            updated = SyncedContent.get_by_source_uuid('uuid-video-1')
            assert updated.title == 'Promotional Video 1'
            assert updated.status == 'published'

    @patch('cms.services.content_sync_service.requests.get')
    def test_sync_approved_content_with_network_filter(self, mock_get, app, db_session, mock_catalog_response):
        """sync_approved_content should pass network filter to API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_catalog_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with app.app_context():
            ContentSyncService.sync_approved_content(network_id='network-high-octane')

        call_args = mock_get.call_args
        assert call_args[1]['params']['network_id'] == 'network-high-octane'

    @patch('cms.services.content_sync_service.requests.get')
    def test_sync_approved_content_handles_pagination(self, mock_get, app, db_session):
        """sync_approved_content should fetch all pages of content."""
        # First page response
        page1_response = {
            'assets': [{'uuid': 'uuid-1', 'title': 'Asset 1', 'filename': 'file1.mp4', 'status': 'published'}],
            'count': 1,
            'page': 1,
            'per_page': 1,
            'total': 2,
            'pages': 2
        }
        # Second page response
        page2_response = {
            'assets': [{'uuid': 'uuid-2', 'title': 'Asset 2', 'filename': 'file2.mp4', 'status': 'published'}],
            'count': 1,
            'page': 2,
            'per_page': 1,
            'total': 2,
            'pages': 2
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = [page1_response, page2_response]
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with app.app_context():
            result = ContentSyncService.sync_approved_content()

            assert result['synced_count'] == 2
            assert mock_get.call_count == 2

    @patch('cms.services.content_sync_service.requests.get')
    def test_sync_approved_content_propagates_unavailable_error(self, mock_get, app, db_session):
        """sync_approved_content should propagate ContentCatalogUnavailableError."""
        from requests.exceptions import ConnectionError

        mock_get.side_effect = ConnectionError("Cannot connect")

        with app.app_context():
            with pytest.raises(ContentCatalogUnavailableError):
                ContentSyncService.sync_approved_content()

    @patch('cms.services.content_sync_service.requests.get')
    def test_sync_approved_content_records_asset_errors(self, mock_get, app, db_session):
        """sync_approved_content should record errors for individual assets."""
        # Asset without required uuid field
        mock_catalog_response = {
            'assets': [
                {'title': 'Missing UUID', 'filename': 'missing.mp4'},
                {'uuid': 'valid-uuid', 'title': 'Valid Asset', 'filename': 'valid.mp4', 'status': 'published'}
            ],
            'count': 2,
            'page': 1,
            'per_page': 100,
            'total': 2,
            'pages': 1
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_catalog_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with app.app_context():
            result = ContentSyncService.sync_approved_content()

            assert result['synced_count'] == 1
            assert len(result['errors']) == 1


# =============================================================================
# Get Synced Content Tests
# =============================================================================

class TestGetSyncedContent:
    """Tests for ContentSyncService.get_synced_content method."""

    def test_get_synced_content_all(self, app, db_session, sample_synced_content):
        """get_synced_content should return all synced content."""
        with app.app_context():
            result = ContentSyncService.get_synced_content()

            assert result['total'] == 5  # Including archived
            assert result['count'] <= result['total']
            assert 'items' in result

    def test_get_synced_content_filter_by_network(self, app, db_session, sample_synced_content):
        """get_synced_content should filter by network_id."""
        with app.app_context():
            result = ContentSyncService.get_synced_content(network_id='network-high-octane')

            assert result['total'] == 4  # video1, image1, audio1, archived
            for item in result['items']:
                assert 'network-high-octane' in item['network_ids']

    def test_get_synced_content_filter_by_organization(self, app, db_session, sample_synced_content):
        """get_synced_content should filter by organization_id."""
        with app.app_context():
            result = ContentSyncService.get_synced_content(organization_id=1)

            assert result['total'] == 4  # video1, image1, audio1, archived
            for item in result['items']:
                assert item['organization_id'] == 1

    def test_get_synced_content_filter_by_status(self, app, db_session, sample_synced_content):
        """get_synced_content should filter by status."""
        with app.app_context():
            result = ContentSyncService.get_synced_content(status='published')

            assert result['total'] == 3  # video1, image1, audio1
            for item in result['items']:
                assert item['status'] == 'published'

    def test_get_synced_content_filter_by_video_type(self, app, db_session, sample_synced_content):
        """get_synced_content should filter by video content type."""
        with app.app_context():
            result = ContentSyncService.get_synced_content(content_type='video')

            assert result['total'] == 3  # video1, video2, archived
            for item in result['items']:
                assert item['format'] in ['mp4', 'webm', 'avi', 'mov', 'mkv', 'wmv', 'flv']

    def test_get_synced_content_filter_by_image_type(self, app, db_session, sample_synced_content):
        """get_synced_content should filter by image content type."""
        with app.app_context():
            result = ContentSyncService.get_synced_content(content_type='image')

            assert result['total'] == 1  # image1
            for item in result['items']:
                assert item['format'] in ['jpeg', 'jpg', 'png', 'gif', 'webp', 'svg', 'bmp']

    def test_get_synced_content_filter_by_audio_type(self, app, db_session, sample_synced_content):
        """get_synced_content should filter by audio content type."""
        with app.app_context():
            result = ContentSyncService.get_synced_content(content_type='audio')

            assert result['total'] == 1  # audio1
            for item in result['items']:
                assert item['format'] in ['mp3', 'wav', 'ogg', 'aac', 'flac', 'm4a']

    def test_get_synced_content_combined_filters(self, app, db_session, sample_synced_content):
        """get_synced_content should support combined filters."""
        with app.app_context():
            result = ContentSyncService.get_synced_content(
                network_id='network-high-octane',
                status='published',
                content_type='video'
            )

            assert result['total'] == 1  # Only video1
            assert result['items'][0]['title'] == 'Test Video 1'

    def test_get_synced_content_pagination(self, app, db_session, sample_synced_content):
        """get_synced_content should support pagination."""
        with app.app_context():
            page1 = ContentSyncService.get_synced_content(page=1, per_page=2)

            assert page1['count'] == 2
            assert page1['total'] == 5
            assert page1['page'] == 1
            assert page1['pages'] == 3

            page2 = ContentSyncService.get_synced_content(page=2, per_page=2)

            assert page2['count'] == 2
            assert page2['page'] == 2

            page3 = ContentSyncService.get_synced_content(page=3, per_page=2)

            assert page3['count'] == 1
            assert page3['page'] == 3

    def test_get_synced_content_empty_result(self, app, db_session):
        """get_synced_content should handle empty results."""
        with app.app_context():
            result = ContentSyncService.get_synced_content()

            assert result['total'] == 0
            assert result['count'] == 0
            assert result['items'] == []
            assert result['pages'] == 1


# =============================================================================
# Get Content By UUID Tests
# =============================================================================

class TestGetContentByUUID:
    """Tests for ContentSyncService.get_content_by_uuid method."""

    def test_get_content_by_uuid_found(self, app, db_session, sample_synced_content):
        """get_content_by_uuid should return content when found."""
        with app.app_context():
            result = ContentSyncService.get_content_by_uuid('test-uuid-video-1')

            assert result is not None
            assert result['source_uuid'] == 'test-uuid-video-1'
            assert result['title'] == 'Test Video 1'

    def test_get_content_by_uuid_not_found(self, app, db_session, sample_synced_content):
        """get_content_by_uuid should return None when not found."""
        with app.app_context():
            result = ContentSyncService.get_content_by_uuid('non-existent-uuid')

            assert result is None


# =============================================================================
# Get Organizations Tests
# =============================================================================

class TestGetOrganizations:
    """Tests for ContentSyncService.get_organizations method."""

    def test_get_organizations_returns_unique_list(self, app, db_session, sample_synced_content):
        """get_organizations should return unique organization list."""
        with app.app_context():
            result = ContentSyncService.get_organizations()

            assert len(result) == 2
            org_names = [org['name'] for org in result]
            assert 'Test Org 1' in org_names
            assert 'Test Org 2' in org_names

    def test_get_organizations_empty(self, app, db_session):
        """get_organizations should return empty list when no content."""
        with app.app_context():
            result = ContentSyncService.get_organizations()

            assert result == []


# =============================================================================
# Get Sync Status Tests
# =============================================================================

class TestGetSyncStatus:
    """Tests for ContentSyncService.get_sync_status method."""

    def test_get_sync_status_returns_statistics(self, app, db_session, sample_synced_content):
        """get_sync_status should return sync statistics."""
        with app.app_context():
            result = ContentSyncService.get_sync_status()

            assert result['total_synced'] == 5
            assert 'by_status' in result
            assert 'by_organization' in result
            assert 'last_synced' in result

    def test_get_sync_status_by_status(self, app, db_session, sample_synced_content):
        """get_sync_status should include status breakdown."""
        with app.app_context():
            result = ContentSyncService.get_sync_status()

            assert result['by_status']['published'] == 3
            assert result['by_status']['approved'] == 1
            assert result['by_status']['archived'] == 1

    def test_get_sync_status_by_organization(self, app, db_session, sample_synced_content):
        """get_sync_status should include organization breakdown."""
        with app.app_context():
            result = ContentSyncService.get_sync_status()

            assert result['by_organization']['Test Org 1'] == 4
            assert result['by_organization']['Test Org 2'] == 1

    def test_get_sync_status_empty(self, app, db_session):
        """get_sync_status should handle empty database."""
        with app.app_context():
            result = ContentSyncService.get_sync_status()

            assert result['total_synced'] == 0
            assert result['by_status'] == {}
            assert result['by_organization'] == {}
            assert result['last_synced'] is None


# =============================================================================
# Remove Archived Content Tests
# =============================================================================

class TestRemoveArchivedContent:
    """Tests for ContentSyncService.remove_archived_content method."""

    def test_remove_archived_content(self, app, db_session, sample_synced_content):
        """remove_archived_content should delete archived items."""
        with app.app_context():
            # Verify archived content exists
            archived_before = SyncedContent.query.filter_by(status='archived').count()
            assert archived_before == 1

            count = ContentSyncService.remove_archived_content()

            assert count == 1

            # Verify archived content is gone
            archived_after = SyncedContent.query.filter_by(status='archived').count()
            assert archived_after == 0

            # Verify other content still exists
            total_after = SyncedContent.query.count()
            assert total_after == 4

    def test_remove_archived_content_none_archived(self, app, db_session):
        """remove_archived_content should handle no archived items."""
        with app.app_context():
            # Create non-archived content
            content = SyncedContent(
                source_uuid='test-uuid',
                title='Test',
                filename='test.mp4',
                status='published'
            )
            db_session.add(content)
            db_session.commit()

            count = ContentSyncService.remove_archived_content()

            assert count == 0


# =============================================================================
# Clear Synced Content Tests
# =============================================================================

class TestClearSyncedContent:
    """Tests for ContentSyncService.clear_synced_content method."""

    def test_clear_synced_content(self, app, db_session, sample_synced_content):
        """clear_synced_content should delete all synced content."""
        with app.app_context():
            # Verify content exists
            count_before = SyncedContent.query.count()
            assert count_before == 5

            count = ContentSyncService.clear_synced_content()

            assert count == 5

            # Verify all content is gone
            count_after = SyncedContent.query.count()
            assert count_after == 0

    def test_clear_synced_content_empty(self, app, db_session):
        """clear_synced_content should handle empty database."""
        with app.app_context():
            count = ContentSyncService.clear_synced_content()

            assert count == 0


# =============================================================================
# Health Check Tests
# =============================================================================

class TestCheckContentCatalogHealth:
    """Tests for ContentSyncService.check_content_catalog_health method."""

    @patch('cms.services.content_sync_service.requests.get')
    def test_health_check_available(self, mock_get, app):
        """check_content_catalog_health should return available=True when service is up."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'assets': [], 'total': 0}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with app.app_context():
            result = ContentSyncService.check_content_catalog_health()

            assert result['available'] is True
            assert result['url'] is not None
            assert result['response_time_ms'] is not None
            assert result['error'] is None

    @patch('cms.services.content_sync_service.requests.get')
    def test_health_check_connection_error(self, mock_get, app):
        """check_content_catalog_health should return available=False on connection error."""
        from requests.exceptions import ConnectionError

        mock_get.side_effect = ConnectionError("Cannot connect")

        with app.app_context():
            result = ContentSyncService.check_content_catalog_health()

            assert result['available'] is False
            assert result['error'] is not None
            assert 'connect' in result['error'].lower()

    @patch('cms.services.content_sync_service.requests.get')
    def test_health_check_timeout(self, mock_get, app):
        """check_content_catalog_health should return available=False on timeout."""
        from requests.exceptions import Timeout

        mock_get.side_effect = Timeout("Request timed out")

        with app.app_context():
            result = ContentSyncService.check_content_catalog_health()

            assert result['available'] is False
            assert result['error'] is not None
            assert 'timed out' in result['error'].lower()

    @patch('cms.services.content_sync_service.requests.get')
    def test_health_check_request_error(self, mock_get, app):
        """check_content_catalog_health should return available=False on request error."""
        from requests.exceptions import RequestException

        mock_get.side_effect = RequestException("Request failed")

        with app.app_context():
            result = ContentSyncService.check_content_catalog_health()

            assert result['available'] is False
            assert result['error'] is not None


# =============================================================================
# Utility Method Tests
# =============================================================================

class TestUtilityMethods:
    """Tests for ContentSyncService utility methods."""

    def test_get_catalog_url(self, app):
        """get_catalog_url should return Content Catalog URL."""
        with app.app_context():
            url = ContentSyncService.get_catalog_url()

            assert url is not None
            assert url.startswith('http')

    def test_default_page_size(self):
        """DEFAULT_PAGE_SIZE should be set."""
        assert ContentSyncService.DEFAULT_PAGE_SIZE > 0
        assert ContentSyncService.DEFAULT_PAGE_SIZE <= ContentSyncService.MAX_PAGE_SIZE

    def test_timeout_settings(self):
        """Timeout settings should be configured."""
        assert ContentSyncService.REQUEST_TIMEOUT > 0
        assert ContentSyncService.CONNECT_TIMEOUT > 0
        assert ContentSyncService.CONNECT_TIMEOUT < ContentSyncService.REQUEST_TIMEOUT
