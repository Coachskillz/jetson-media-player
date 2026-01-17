"""
Unit tests for SyncedContent model.

Tests all SyncedContent model methods and properties:
- Model creation with required and optional fields
- to_dict serialization method
- to_content_card method for UI display
- content_type property (video, image, audio, other)
- is_video, is_image, is_audio type detection properties
- is_published, is_approved status properties
- Network ID list management (get/set/has)
- Class query methods (get_by_source_uuid, get_by_network, etc.)
- upsert_from_catalog for sync operations
"""

import json
from datetime import datetime, timezone, timedelta

import pytest

from cms.models import db
from cms.models.synced_content import SyncedContent


# =============================================================================
# Model Creation Tests
# =============================================================================

class TestSyncedContentCreation:
    """Tests for SyncedContent model creation."""

    def test_create_synced_content_required_fields(self, db_session):
        """SyncedContent should be created with required fields."""
        content = SyncedContent(
            source_uuid='test-source-uuid-001',
            title='Test Content',
            filename='test.mp4'
        )
        db_session.add(content)
        db_session.commit()

        assert content.id is not None
        assert content.source_uuid == 'test-source-uuid-001'
        assert content.title == 'Test Content'
        assert content.filename == 'test.mp4'
        assert content.status == SyncedContent.STATUS_APPROVED  # Default status
        assert content.synced_at is not None

    def test_create_synced_content_all_fields(self, db_session):
        """SyncedContent should accept all optional fields."""
        now = datetime.now(timezone.utc)
        content = SyncedContent(
            source_uuid='test-source-uuid-002',
            title='Full Test Content',
            description='A comprehensive test content description',
            filename='full_test.mp4',
            file_path='/uploads/full_test.mp4',
            file_size=2048000,
            duration=120.5,
            resolution='1920x1080',
            format='mp4',
            thumbnail_url='/thumbnails/full_test.jpg',
            category='promotional',
            tags='test,promo,video',
            status=SyncedContent.STATUS_PUBLISHED,
            organization_id=1,
            organization_name='Test Organization',
            network_ids='["network-1", "network-2"]',
            content_catalog_url='http://catalog.example.com',
            synced_at=now,
            created_at=now - timedelta(days=1),
            published_at=now
        )
        db_session.add(content)
        db_session.commit()

        assert content.description == 'A comprehensive test content description'
        assert content.file_path == '/uploads/full_test.mp4'
        assert content.file_size == 2048000
        assert content.duration == 120.5
        assert content.resolution == '1920x1080'
        assert content.format == 'mp4'
        assert content.thumbnail_url == '/thumbnails/full_test.jpg'
        assert content.category == 'promotional'
        assert content.tags == 'test,promo,video'
        assert content.status == SyncedContent.STATUS_PUBLISHED
        assert content.organization_id == 1
        assert content.organization_name == 'Test Organization'
        assert content.network_ids == '["network-1", "network-2"]'
        assert content.content_catalog_url == 'http://catalog.example.com'

    def test_source_uuid_must_be_unique(self, db_session):
        """SyncedContent source_uuid must be unique."""
        content1 = SyncedContent(
            source_uuid='unique-test-uuid',
            title='Content 1',
            filename='content1.mp4'
        )
        db_session.add(content1)
        db_session.commit()

        content2 = SyncedContent(
            source_uuid='unique-test-uuid',
            title='Content 2',
            filename='content2.mp4'
        )
        db_session.add(content2)

        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()

    def test_synced_content_id_is_uuid(self, db_session):
        """SyncedContent id should be a valid UUID string."""
        content = SyncedContent(
            source_uuid='test-uuid-for-id',
            title='ID Test',
            filename='id_test.mp4'
        )
        db_session.add(content)
        db_session.commit()

        assert len(content.id) == 36  # UUID format: 8-4-4-4-12

    def test_repr_method(self, db_session):
        """__repr__ should return readable string representation."""
        content = SyncedContent(
            source_uuid='repr-test-uuid',
            title='Repr Test Title',
            filename='repr.mp4'
        )
        db_session.add(content)
        db_session.commit()

        repr_str = repr(content)
        assert 'SyncedContent' in repr_str
        assert 'Repr Test Title' in repr_str


# =============================================================================
# Status Constants Tests
# =============================================================================

class TestStatusConstants:
    """Tests for SyncedContent status constants."""

    def test_status_constants_defined(self):
        """Status constants should be defined."""
        assert SyncedContent.STATUS_APPROVED == 'approved'
        assert SyncedContent.STATUS_PUBLISHED == 'published'
        assert SyncedContent.STATUS_ARCHIVED == 'archived'

    def test_valid_statuses_list(self):
        """VALID_STATUSES should contain all status constants."""
        assert SyncedContent.STATUS_APPROVED in SyncedContent.VALID_STATUSES
        assert SyncedContent.STATUS_PUBLISHED in SyncedContent.VALID_STATUSES
        assert SyncedContent.STATUS_ARCHIVED in SyncedContent.VALID_STATUSES
        assert len(SyncedContent.VALID_STATUSES) == 3


# =============================================================================
# Serialization Tests
# =============================================================================

class TestSyncedContentSerialization:
    """Tests for SyncedContent serialization methods."""

    def test_to_dict_basic(self, db_session):
        """to_dict should serialize all fields."""
        content = SyncedContent(
            source_uuid='dict-test-uuid',
            title='Dict Test',
            filename='dict_test.mp4',
            format='mp4'
        )
        db_session.add(content)
        db_session.commit()

        result = content.to_dict()

        assert result['id'] == content.id
        assert result['source_uuid'] == 'dict-test-uuid'
        assert result['title'] == 'Dict Test'
        assert result['filename'] == 'dict_test.mp4'
        assert result['format'] == 'mp4'
        assert 'synced_at' in result

    def test_to_dict_with_all_fields(self, db_session):
        """to_dict should include all fields when populated."""
        now = datetime.now(timezone.utc)
        content = SyncedContent(
            source_uuid='full-dict-uuid',
            title='Full Dict Test',
            description='Test description',
            filename='full.mp4',
            file_path='/uploads/full.mp4',
            file_size=1024000,
            duration=60.0,
            resolution='1280x720',
            format='mp4',
            thumbnail_url='/thumbs/full.jpg',
            category='test',
            tags='tag1,tag2',
            status='published',
            organization_id=1,
            organization_name='Test Org',
            network_ids='["net-1", "net-2"]',
            content_catalog_url='http://catalog.test',
            synced_at=now,
            created_at=now - timedelta(days=1),
            published_at=now
        )
        db_session.add(content)
        db_session.commit()

        result = content.to_dict()

        assert result['description'] == 'Test description'
        assert result['file_path'] == '/uploads/full.mp4'
        assert result['file_size'] == 1024000
        assert result['duration'] == 60.0
        assert result['resolution'] == '1280x720'
        assert result['thumbnail_url'] == '/thumbs/full.jpg'
        assert result['category'] == 'test'
        assert result['tags'] == 'tag1,tag2'
        assert result['status'] == 'published'
        assert result['organization_id'] == 1
        assert result['organization_name'] == 'Test Org'
        assert result['network_ids'] == ['net-1', 'net-2']
        assert result['content_catalog_url'] == 'http://catalog.test'
        assert result['synced_at'] is not None
        assert result['created_at'] is not None
        assert result['published_at'] is not None

    def test_to_dict_timestamps_iso_format(self, db_session):
        """to_dict should format timestamps as ISO strings."""
        now = datetime.now(timezone.utc)
        content = SyncedContent(
            source_uuid='timestamp-dict-uuid',
            title='Timestamp Test',
            filename='timestamp.mp4',
            synced_at=now,
            created_at=now,
            published_at=now
        )
        db_session.add(content)
        db_session.commit()

        result = content.to_dict()

        # Verify timestamps are ISO formatted strings
        assert isinstance(result['synced_at'], str)
        assert isinstance(result['created_at'], str)
        assert isinstance(result['published_at'], str)

    def test_to_dict_null_timestamps(self, db_session):
        """to_dict should handle null timestamps."""
        content = SyncedContent(
            source_uuid='null-timestamp-uuid',
            title='Null Timestamp Test',
            filename='null.mp4',
            created_at=None,
            published_at=None
        )
        db_session.add(content)
        db_session.commit()

        result = content.to_dict()

        assert result['created_at'] is None
        assert result['published_at'] is None

    def test_to_content_card(self, db_session):
        """to_content_card should return display-friendly subset."""
        content = SyncedContent(
            source_uuid='card-test-uuid',
            title='Card Test Content',
            description='Long description not needed for card',
            filename='card_test.mp4',
            duration=45.0,
            format='mp4',
            thumbnail_url='/thumbs/card.jpg',
            status='published',
            organization_name='Card Org'
        )
        db_session.add(content)
        db_session.commit()

        result = content.to_content_card()

        assert 'id' in result
        assert 'source_uuid' in result
        assert result['title'] == 'Card Test Content'
        assert result['filename'] == 'card_test.mp4'
        assert result['duration'] == 45.0
        assert result['format'] == 'mp4'
        assert result['thumbnail_url'] == '/thumbs/card.jpg'
        assert result['status'] == 'published'
        assert result['organization_name'] == 'Card Org'
        assert result['content_type'] == 'video'

        # Should NOT include full details
        assert 'description' not in result
        assert 'file_path' not in result
        assert 'file_size' not in result


# =============================================================================
# Content Type Detection Tests
# =============================================================================

class TestContentTypeDetection:
    """Tests for content type detection properties."""

    def test_content_type_video(self, db_session):
        """content_type should return 'video' for video formats."""
        video_formats = ['mp4', 'webm', 'avi', 'mov', 'mkv', 'wmv', 'flv']

        for fmt in video_formats:
            content = SyncedContent(
                source_uuid=f'video-format-{fmt}',
                title=f'Video {fmt}',
                filename=f'test.{fmt}',
                format=fmt
            )
            db_session.add(content)
            db_session.commit()

            assert content.content_type == 'video', f"Failed for format: {fmt}"
            assert content.is_video is True
            assert content.is_image is False
            assert content.is_audio is False

            db_session.delete(content)
            db_session.commit()

    def test_content_type_image(self, db_session):
        """content_type should return 'image' for image formats."""
        image_formats = ['jpeg', 'jpg', 'png', 'gif', 'webp', 'svg', 'bmp']

        for fmt in image_formats:
            content = SyncedContent(
                source_uuid=f'image-format-{fmt}',
                title=f'Image {fmt}',
                filename=f'test.{fmt}',
                format=fmt
            )
            db_session.add(content)
            db_session.commit()

            assert content.content_type == 'image', f"Failed for format: {fmt}"
            assert content.is_video is False
            assert content.is_image is True
            assert content.is_audio is False

            db_session.delete(content)
            db_session.commit()

    def test_content_type_audio(self, db_session):
        """content_type should return 'audio' for audio formats."""
        audio_formats = ['mp3', 'wav', 'ogg', 'aac', 'flac', 'm4a']

        for fmt in audio_formats:
            content = SyncedContent(
                source_uuid=f'audio-format-{fmt}',
                title=f'Audio {fmt}',
                filename=f'test.{fmt}',
                format=fmt
            )
            db_session.add(content)
            db_session.commit()

            assert content.content_type == 'audio', f"Failed for format: {fmt}"
            assert content.is_video is False
            assert content.is_image is False
            assert content.is_audio is True

            db_session.delete(content)
            db_session.commit()

    def test_content_type_other(self, db_session):
        """content_type should return 'other' for unknown formats."""
        content = SyncedContent(
            source_uuid='other-format-uuid',
            title='Other Format',
            filename='test.pdf',
            format='pdf'
        )
        db_session.add(content)
        db_session.commit()

        assert content.content_type == 'other'
        assert content.is_video is False
        assert content.is_image is False
        assert content.is_audio is False

    def test_content_type_null_format(self, db_session):
        """content_type should return 'other' when format is None."""
        content = SyncedContent(
            source_uuid='null-format-uuid',
            title='No Format',
            filename='test.mp4',
            format=None
        )
        db_session.add(content)
        db_session.commit()

        assert content.content_type == 'other'
        assert content.is_video is False
        assert content.is_image is False
        assert content.is_audio is False

    def test_content_type_case_insensitive(self, db_session):
        """Format detection should be case insensitive."""
        content = SyncedContent(
            source_uuid='case-test-uuid',
            title='Case Test',
            filename='TEST.MP4',
            format='MP4'
        )
        db_session.add(content)
        db_session.commit()

        assert content.is_video is True
        assert content.content_type == 'video'


# =============================================================================
# Status Property Tests
# =============================================================================

class TestStatusProperties:
    """Tests for status checking properties."""

    def test_is_published_true(self, db_session):
        """is_published should return True for published status."""
        content = SyncedContent(
            source_uuid='published-status-uuid',
            title='Published',
            filename='published.mp4',
            status=SyncedContent.STATUS_PUBLISHED
        )
        db_session.add(content)
        db_session.commit()

        assert content.is_published is True
        assert content.is_approved is False

    def test_is_approved_true(self, db_session):
        """is_approved should return True for approved status."""
        content = SyncedContent(
            source_uuid='approved-status-uuid',
            title='Approved',
            filename='approved.mp4',
            status=SyncedContent.STATUS_APPROVED
        )
        db_session.add(content)
        db_session.commit()

        assert content.is_approved is True
        assert content.is_published is False

    def test_archived_status(self, db_session):
        """Archived content should not be published or approved."""
        content = SyncedContent(
            source_uuid='archived-status-uuid',
            title='Archived',
            filename='archived.mp4',
            status=SyncedContent.STATUS_ARCHIVED
        )
        db_session.add(content)
        db_session.commit()

        assert content.is_published is False
        assert content.is_approved is False


# =============================================================================
# Network ID Management Tests
# =============================================================================

class TestNetworkIdManagement:
    """Tests for network ID list management methods."""

    def test_get_network_ids_list_basic(self, db_session):
        """get_network_ids_list should parse JSON string to list."""
        content = SyncedContent(
            source_uuid='network-list-uuid',
            title='Network List Test',
            filename='networks.mp4',
            network_ids='["network-1", "network-2", "network-3"]'
        )
        db_session.add(content)
        db_session.commit()

        result = content.get_network_ids_list()

        assert isinstance(result, list)
        assert len(result) == 3
        assert 'network-1' in result
        assert 'network-2' in result
        assert 'network-3' in result

    def test_get_network_ids_list_empty_string(self, db_session):
        """get_network_ids_list should return empty list for empty string."""
        content = SyncedContent(
            source_uuid='empty-network-uuid',
            title='Empty Network Test',
            filename='empty.mp4',
            network_ids=''
        )
        db_session.add(content)
        db_session.commit()

        result = content.get_network_ids_list()

        assert result == []

    def test_get_network_ids_list_null(self, db_session):
        """get_network_ids_list should return empty list for None."""
        content = SyncedContent(
            source_uuid='null-network-uuid',
            title='Null Network Test',
            filename='null.mp4',
            network_ids=None
        )
        db_session.add(content)
        db_session.commit()

        result = content.get_network_ids_list()

        assert result == []

    def test_get_network_ids_list_invalid_json(self, db_session):
        """get_network_ids_list should return empty list for invalid JSON."""
        content = SyncedContent(
            source_uuid='invalid-json-uuid',
            title='Invalid JSON Test',
            filename='invalid.mp4',
            network_ids='not valid json'
        )
        db_session.add(content)
        db_session.commit()

        result = content.get_network_ids_list()

        assert result == []

    def test_set_network_ids_list(self, db_session):
        """set_network_ids_list should serialize list to JSON string."""
        content = SyncedContent(
            source_uuid='set-network-uuid',
            title='Set Network Test',
            filename='set.mp4'
        )
        db_session.add(content)

        content.set_network_ids_list(['net-a', 'net-b'])
        db_session.commit()

        assert content.network_ids == '["net-a", "net-b"]'

        # Verify round-trip
        result = content.get_network_ids_list()
        assert result == ['net-a', 'net-b']

    def test_set_network_ids_list_empty(self, db_session):
        """set_network_ids_list should set None for empty list."""
        content = SyncedContent(
            source_uuid='set-empty-uuid',
            title='Set Empty Test',
            filename='set_empty.mp4',
            network_ids='["existing"]'
        )
        db_session.add(content)

        content.set_network_ids_list([])
        db_session.commit()

        assert content.network_ids is None

    def test_set_network_ids_list_none(self, db_session):
        """set_network_ids_list should set None for None input."""
        content = SyncedContent(
            source_uuid='set-none-uuid',
            title='Set None Test',
            filename='set_none.mp4',
            network_ids='["existing"]'
        )
        db_session.add(content)

        content.set_network_ids_list(None)
        db_session.commit()

        assert content.network_ids is None

    def test_has_network_true(self, db_session):
        """has_network should return True when network exists."""
        content = SyncedContent(
            source_uuid='has-network-uuid',
            title='Has Network Test',
            filename='has.mp4',
            network_ids='["network-alpha", "network-beta"]'
        )
        db_session.add(content)
        db_session.commit()

        assert content.has_network('network-alpha') is True
        assert content.has_network('network-beta') is True

    def test_has_network_false(self, db_session):
        """has_network should return False when network doesn't exist."""
        content = SyncedContent(
            source_uuid='no-network-uuid',
            title='No Network Test',
            filename='no.mp4',
            network_ids='["network-alpha"]'
        )
        db_session.add(content)
        db_session.commit()

        assert content.has_network('network-gamma') is False

    def test_has_network_empty(self, db_session):
        """has_network should return False when no networks assigned."""
        content = SyncedContent(
            source_uuid='empty-has-uuid',
            title='Empty Has Test',
            filename='empty_has.mp4',
            network_ids=None
        )
        db_session.add(content)
        db_session.commit()

        assert content.has_network('any-network') is False


# =============================================================================
# Class Query Method Tests
# =============================================================================

class TestClassQueryMethods:
    """Tests for SyncedContent class query methods."""

    @pytest.fixture
    def multiple_synced_content(self, db_session):
        """Create multiple SyncedContent records for query tests."""
        contents = []

        # Content 1: Org 1, Network A, Published
        c1 = SyncedContent(
            source_uuid='query-uuid-1',
            title='Query Content 1',
            filename='query1.mp4',
            format='mp4',
            status='published',
            organization_id=1,
            organization_name='Org One',
            network_ids='["network-a"]'
        )
        db_session.add(c1)
        contents.append(c1)

        # Content 2: Org 1, Network A & B, Approved
        c2 = SyncedContent(
            source_uuid='query-uuid-2',
            title='Query Content 2',
            filename='query2.mp4',
            format='mp4',
            status='approved',
            organization_id=1,
            organization_name='Org One',
            network_ids='["network-a", "network-b"]'
        )
        db_session.add(c2)
        contents.append(c2)

        # Content 3: Org 2, Network B, Published
        c3 = SyncedContent(
            source_uuid='query-uuid-3',
            title='Query Content 3',
            filename='query3.png',
            format='png',
            status='published',
            organization_id=2,
            organization_name='Org Two',
            network_ids='["network-b"]'
        )
        db_session.add(c3)
        contents.append(c3)

        # Content 4: Org 2, No Network, Archived
        c4 = SyncedContent(
            source_uuid='query-uuid-4',
            title='Query Content 4',
            filename='query4.mp3',
            format='mp3',
            status='archived',
            organization_id=2,
            organization_name='Org Two',
            network_ids=None
        )
        db_session.add(c4)
        contents.append(c4)

        db_session.commit()
        return contents

    def test_get_by_source_uuid_found(self, db_session, multiple_synced_content):
        """get_by_source_uuid should return content when found."""
        result = SyncedContent.get_by_source_uuid('query-uuid-2')

        assert result is not None
        assert result.title == 'Query Content 2'

    def test_get_by_source_uuid_not_found(self, db_session, multiple_synced_content):
        """get_by_source_uuid should return None when not found."""
        result = SyncedContent.get_by_source_uuid('non-existent-uuid')

        assert result is None

    def test_get_by_network(self, db_session, multiple_synced_content):
        """get_by_network should return content for the network."""
        result = SyncedContent.get_by_network('network-a')

        assert len(result) == 2
        titles = [c.title for c in result]
        assert 'Query Content 1' in titles
        assert 'Query Content 2' in titles

    def test_get_by_network_empty(self, db_session, multiple_synced_content):
        """get_by_network should return empty list for unknown network."""
        result = SyncedContent.get_by_network('network-z')

        assert result == []

    def test_get_by_organization(self, db_session, multiple_synced_content):
        """get_by_organization should return content for the organization."""
        result = SyncedContent.get_by_organization(1)

        assert len(result) == 2
        for content in result:
            assert content.organization_id == 1

    def test_get_by_organization_empty(self, db_session, multiple_synced_content):
        """get_by_organization should return empty list for unknown org."""
        result = SyncedContent.get_by_organization(999)

        assert result == []

    def test_get_by_status_published(self, db_session, multiple_synced_content):
        """get_by_status should return content with specified status."""
        result = SyncedContent.get_by_status('published')

        assert len(result) == 2
        for content in result:
            assert content.status == 'published'

    def test_get_by_status_approved(self, db_session, multiple_synced_content):
        """get_by_status should return approved content."""
        result = SyncedContent.get_by_status('approved')

        assert len(result) == 1
        assert result[0].status == 'approved'

    def test_get_by_status_archived(self, db_session, multiple_synced_content):
        """get_by_status should return archived content."""
        result = SyncedContent.get_by_status('archived')

        assert len(result) == 1
        assert result[0].status == 'archived'

    def test_get_all_organizations(self, db_session, multiple_synced_content):
        """get_all_organizations should return unique organizations."""
        result = SyncedContent.get_all_organizations()

        assert len(result) == 2
        org_names = [org['name'] for org in result]
        assert 'Org One' in org_names
        assert 'Org Two' in org_names

    def test_get_all_organizations_empty(self, db_session):
        """get_all_organizations should return empty list when no content."""
        result = SyncedContent.get_all_organizations()

        assert result == []


# =============================================================================
# Upsert from Catalog Tests
# =============================================================================

class TestUpsertFromCatalog:
    """Tests for SyncedContent.upsert_from_catalog method."""

    def test_upsert_creates_new_record(self, db_session):
        """upsert_from_catalog should create new record when not exists."""
        catalog_data = {
            'uuid': 'new-catalog-uuid',
            'title': 'New Catalog Content',
            'description': 'Content from catalog',
            'filename': 'catalog.mp4',
            'file_path': '/uploads/catalog.mp4',
            'file_size': 5000000,
            'duration': 90.0,
            'resolution': '1920x1080',
            'format': 'mp4',
            'thumbnail_path': '/thumbs/catalog.jpg',
            'category': 'promotional',
            'tags': 'new,catalog',
            'status': 'published',
            'organization_id': 1,
            'networks': '["network-x"]',
            'created_at': '2026-01-15T10:00:00Z',
            'published_at': '2026-01-16T10:00:00Z'
        }

        result = SyncedContent.upsert_from_catalog(
            db_session,
            catalog_data,
            organization_name='Test Org',
            content_catalog_url='http://catalog.test'
        )
        db_session.commit()

        assert result is not None
        assert result.source_uuid == 'new-catalog-uuid'
        assert result.title == 'New Catalog Content'
        assert result.description == 'Content from catalog'
        assert result.filename == 'catalog.mp4'
        assert result.file_path == '/uploads/catalog.mp4'
        assert result.file_size == 5000000
        assert result.duration == 90.0
        assert result.resolution == '1920x1080'
        assert result.format == 'mp4'
        assert result.thumbnail_url == '/thumbs/catalog.jpg'
        assert result.category == 'promotional'
        assert result.tags == 'new,catalog'
        assert result.status == 'published'
        assert result.organization_id == 1
        assert result.organization_name == 'Test Org'
        assert result.network_ids == '["network-x"]'
        assert result.content_catalog_url == 'http://catalog.test'
        assert result.created_at is not None
        assert result.published_at is not None
        assert result.synced_at is not None

    def test_upsert_updates_existing_record(self, db_session):
        """upsert_from_catalog should update existing record."""
        # Create existing record
        existing = SyncedContent(
            source_uuid='existing-uuid',
            title='Old Title',
            filename='old.mp4',
            status='approved'
        )
        db_session.add(existing)
        db_session.commit()

        # Upsert with new data
        catalog_data = {
            'uuid': 'existing-uuid',
            'title': 'Updated Title',
            'filename': 'updated.mp4',
            'status': 'published'
        }

        result = SyncedContent.upsert_from_catalog(
            db_session,
            catalog_data,
            organization_name='Updated Org'
        )
        db_session.commit()

        # Should be same record
        assert result.id == existing.id
        assert result.title == 'Updated Title'
        assert result.filename == 'updated.mp4'
        assert result.status == 'published'
        assert result.organization_name == 'Updated Org'

    def test_upsert_missing_uuid_raises_error(self, db_session):
        """upsert_from_catalog should raise ValueError without uuid."""
        catalog_data = {
            'title': 'No UUID Content',
            'filename': 'no_uuid.mp4'
        }

        with pytest.raises(ValueError) as exc_info:
            SyncedContent.upsert_from_catalog(db_session, catalog_data)

        assert 'uuid' in str(exc_info.value).lower()

    def test_upsert_handles_default_values(self, db_session):
        """upsert_from_catalog should handle missing optional fields."""
        catalog_data = {
            'uuid': 'minimal-uuid'
        }

        result = SyncedContent.upsert_from_catalog(db_session, catalog_data)
        db_session.commit()

        assert result.source_uuid == 'minimal-uuid'
        assert result.title == 'Untitled'
        assert result.filename == 'unknown'
        assert result.status == SyncedContent.STATUS_APPROVED

    def test_upsert_parses_iso_timestamps(self, db_session):
        """upsert_from_catalog should parse ISO format timestamps."""
        catalog_data = {
            'uuid': 'timestamp-uuid',
            'title': 'Timestamp Test',
            'filename': 'ts.mp4',
            'created_at': '2026-01-15T10:30:00+00:00',
            'published_at': '2026-01-16T14:45:00Z'
        }

        result = SyncedContent.upsert_from_catalog(db_session, catalog_data)
        db_session.commit()

        assert result.created_at is not None
        assert result.published_at is not None
        assert result.created_at.year == 2026
        assert result.created_at.month == 1
        assert result.created_at.day == 15

    def test_upsert_handles_invalid_timestamp(self, db_session):
        """upsert_from_catalog should handle invalid timestamps gracefully."""
        catalog_data = {
            'uuid': 'bad-timestamp-uuid',
            'title': 'Bad Timestamp',
            'filename': 'bad_ts.mp4',
            'created_at': 'not-a-valid-timestamp',
            'published_at': '12345'
        }

        result = SyncedContent.upsert_from_catalog(db_session, catalog_data)
        db_session.commit()

        assert result.created_at is None
        assert result.published_at is None

    def test_upsert_handles_null_timestamps(self, db_session):
        """upsert_from_catalog should handle null timestamps."""
        catalog_data = {
            'uuid': 'null-ts-uuid',
            'title': 'Null Timestamp',
            'filename': 'null_ts.mp4',
            'created_at': None,
            'published_at': None
        }

        result = SyncedContent.upsert_from_catalog(db_session, catalog_data)
        db_session.commit()

        # Should not raise error, timestamps remain None/default
        assert result is not None


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_long_title_handling(self, db_session):
        """SyncedContent should handle long titles (up to 500 chars)."""
        long_title = 'A' * 500
        content = SyncedContent(
            source_uuid='long-title-uuid',
            title=long_title,
            filename='long.mp4'
        )
        db_session.add(content)
        db_session.commit()

        assert len(content.title) == 500

    def test_long_filename_handling(self, db_session):
        """SyncedContent should handle long filenames (up to 500 chars)."""
        long_filename = 'f' * 496 + '.mp4'
        content = SyncedContent(
            source_uuid='long-filename-uuid',
            title='Long Filename Test',
            filename=long_filename
        )
        db_session.add(content)
        db_session.commit()

        assert len(content.filename) == 500

    def test_unicode_content(self, db_session):
        """SyncedContent should handle unicode characters."""
        content = SyncedContent(
            source_uuid='unicode-uuid',
            title='Unicode Test: \u4e2d\u6587 \u0420\u0443\u0441\u0441\u043a\u0438\u0439 \u1f600',
            description='Description with emoji \u1f389 and symbols \u00a9 \u00ae',
            filename='unicode_test.mp4',
            tags='\u6807\u7b7e,\u0442\u0435\u0433\u0438'
        )
        db_session.add(content)
        db_session.commit()

        assert '\u4e2d\u6587' in content.title
        assert '\u1f389' in content.description
        assert '\u6807\u7b7e' in content.tags

    def test_special_characters_in_network_ids(self, db_session):
        """Network IDs should handle special characters properly."""
        content = SyncedContent(
            source_uuid='special-network-uuid',
            title='Special Network Test',
            filename='special.mp4'
        )
        db_session.add(content)

        special_ids = ['network-with-dash', 'network_with_underscore', 'network.with.dots']
        content.set_network_ids_list(special_ids)
        db_session.commit()

        result = content.get_network_ids_list()
        assert result == special_ids

    def test_empty_description(self, db_session):
        """SyncedContent should handle empty description."""
        content = SyncedContent(
            source_uuid='empty-desc-uuid',
            title='Empty Description',
            filename='empty_desc.mp4',
            description=''
        )
        db_session.add(content)
        db_session.commit()

        assert content.description == ''

        result = content.to_dict()
        assert result['description'] == ''
