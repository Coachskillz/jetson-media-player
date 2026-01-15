"""
Unit tests for Local Hub database models.

Tests all 5 models:
- HubConfig: Hub registration and identity
- Screen: Jetson screens connected to hub
- Content: Cached media content
- PendingAlert: Alert forwarding queue
- SyncStatus: Sync state tracking
"""

import json
from datetime import datetime, timedelta

import pytest

from models import db, HubConfig, Screen, Content, PendingAlert, SyncStatus


# =============================================================================
# HubConfig Model Tests
# =============================================================================

class TestHubConfig:
    """Tests for HubConfig model."""

    def test_get_instance_creates_singleton(self, app, db_session):
        """get_instance() should create a single HubConfig if none exists."""
        config = HubConfig.get_instance()
        assert config is not None
        assert config.id is not None

        # Second call should return the same instance
        config2 = HubConfig.get_instance()
        assert config2.id == config.id

    def test_to_dict_excludes_token(self, app, db_session):
        """to_dict() should exclude hub_token for security."""
        config = HubConfig.get_instance()
        config.hub_id = 'test-hub-id'
        config.hub_token = 'secret-token'
        config.network_id = 'network-123'
        config.store_id = 'store-456'
        db_session.commit()

        result = config.to_dict()

        assert 'hub_id' in result
        assert result['hub_id'] == 'test-hub-id'
        assert result['network_id'] == 'network-123'
        assert result['store_id'] == 'store-456'
        assert 'hub_token' not in result

    def test_is_registered_requires_hub_id_and_token(self, app, db_session):
        """is_registered should return True only if both hub_id and hub_token are set."""
        config = HubConfig.get_instance()

        # Initially not registered
        assert config.is_registered is False

        # Only hub_id - not registered
        config.hub_id = 'test-id'
        db_session.commit()
        assert config.is_registered is False

        # Both set - registered
        config.hub_token = 'test-token'
        db_session.commit()
        assert config.is_registered is True

    def test_update_registration(self, app, db_session):
        """update_registration() should update all fields and set registered_at."""
        config = HubConfig.update_registration(
            hub_id='new-hub-id',
            hub_token='new-token',
            network_id='network-999',
            store_id='store-999'
        )

        assert config.hub_id == 'new-hub-id'
        assert config.hub_token == 'new-token'
        assert config.network_id == 'network-999'
        assert config.store_id == 'store-999'
        assert config.registered_at is not None
        assert config.is_registered is True

    def test_to_dict_handles_none_dates(self, app, db_session):
        """to_dict() should handle None dates gracefully."""
        config = HubConfig.get_instance()
        result = config.to_dict()

        assert result['registered_at'] is None
        # updated_at may be set by default

    def test_repr(self, app, db_session):
        """__repr__ should include hub_id and registration status."""
        config = HubConfig.get_instance()
        config.hub_id = 'test-123'
        db_session.commit()

        repr_str = repr(config)
        assert 'HubConfig' in repr_str
        assert 'test-123' in repr_str


# =============================================================================
# Screen Model Tests
# =============================================================================

class TestScreen:
    """Tests for Screen model."""

    def test_create_screen(self, app, db_session):
        """Should create a screen with required fields."""
        screen = Screen(
            hardware_id='hw-test-001',
            name='Test Screen',
            status='online'
        )
        db_session.add(screen)
        db_session.commit()

        assert screen.id is not None
        assert screen.hardware_id == 'hw-test-001'
        assert screen.status == 'online'
        assert screen.created_at is not None

    def test_to_dict(self, app, db_session):
        """to_dict() should serialize all fields."""
        screen = Screen(
            hardware_id='hw-test-002',
            name='Test Screen 2',
            status='online',
            camera_enabled=True,
            loyalty_enabled=False,
            ncmec_enabled=True,
            current_playlist_id='playlist-123'
        )
        db_session.add(screen)
        db_session.commit()

        result = screen.to_dict()

        assert result['hardware_id'] == 'hw-test-002'
        assert result['name'] == 'Test Screen 2'
        assert result['status'] == 'online'
        assert result['camera_enabled'] is True
        assert result['loyalty_enabled'] is False
        assert result['ncmec_enabled'] is True
        assert result['current_playlist_id'] == 'playlist-123'

    def test_to_config_dict(self, app, db_session):
        """to_config_dict() should return configuration data for screens."""
        screen = Screen(
            hardware_id='hw-test-003',
            camera_enabled=True,
            ncmec_enabled=True,
            ncmec_db_version='v1.2.3',
            current_playlist_id='playlist-456'
        )
        db_session.add(screen)
        db_session.commit()

        config = screen.to_config_dict()

        assert config['screen_id'] == screen.id
        assert config['playlist_id'] == 'playlist-456'
        assert config['camera_enabled'] is True
        assert config['ncmec_enabled'] is True
        assert config['ncmec_db_version'] == 'v1.2.3'

    def test_update_heartbeat(self, app, db_session):
        """update_heartbeat() should update timestamp and set status to online."""
        screen = Screen(
            hardware_id='hw-test-004',
            status='offline'
        )
        db_session.add(screen)
        db_session.commit()

        old_heartbeat = screen.last_heartbeat
        screen.update_heartbeat()

        assert screen.status == 'online'
        assert screen.last_heartbeat >= old_heartbeat

    def test_is_online_property(self, app, db_session):
        """is_online should return True only when status is 'online'."""
        screen = Screen(hardware_id='hw-test-005', status='offline')
        db_session.add(screen)
        db_session.commit()

        assert screen.is_online is False

        screen.status = 'online'
        assert screen.is_online is True

    def test_get_by_hardware_id(self, app, db_session):
        """get_by_hardware_id() should find screen by hardware_id."""
        screen = Screen(hardware_id='hw-unique-001', name='Unique Screen')
        db_session.add(screen)
        db_session.commit()

        found = Screen.get_by_hardware_id('hw-unique-001')
        assert found is not None
        assert found.name == 'Unique Screen'

        not_found = Screen.get_by_hardware_id('nonexistent')
        assert not_found is None

    def test_register_creates_new_screen(self, app, db_session):
        """register() should create a new screen if hardware_id doesn't exist."""
        screen, created = Screen.register('hw-new-001', name='New Screen')

        assert created is True
        assert screen.hardware_id == 'hw-new-001'
        assert screen.name == 'New Screen'
        assert screen.status == 'online'

    def test_register_updates_existing_screen(self, app, db_session):
        """register() should update heartbeat for existing screen."""
        # Create existing screen
        existing = Screen(hardware_id='hw-existing-001', status='offline')
        db_session.add(existing)
        db_session.commit()

        # Register again
        screen, created = Screen.register('hw-existing-001')

        assert created is False
        assert screen.id == existing.id
        assert screen.status == 'online'  # Updated by heartbeat

    def test_register_updates_name_if_not_set(self, app, db_session):
        """register() should set name if existing screen has no name."""
        # Create existing screen without name
        existing = Screen(hardware_id='hw-noname-001')
        db_session.add(existing)
        db_session.commit()

        # Register with name
        screen, created = Screen.register('hw-noname-001', name='New Name')

        assert created is False
        assert screen.name == 'New Name'

    def test_get_all_online(self, app, db_session):
        """get_all_online() should return only screens with status='online'."""
        screen1 = Screen(hardware_id='hw-online-1', status='online')
        screen2 = Screen(hardware_id='hw-offline-1', status='offline')
        screen3 = Screen(hardware_id='hw-online-2', status='online')
        db_session.add_all([screen1, screen2, screen3])
        db_session.commit()

        online = Screen.get_all_online()
        assert len(online) == 2
        assert all(s.status == 'online' for s in online)

    def test_get_all_offline(self, app, db_session):
        """get_all_offline() should return only screens with status='offline'."""
        screen1 = Screen(hardware_id='hw-on-1', status='online')
        screen2 = Screen(hardware_id='hw-off-1', status='offline')
        db_session.add_all([screen1, screen2])
        db_session.commit()

        offline = Screen.get_all_offline()
        assert len(offline) == 1
        assert offline[0].status == 'offline'

    def test_repr(self, app, db_session):
        """__repr__ should include id, hardware_id, and status."""
        screen = Screen(hardware_id='hw-repr-001', status='online')
        db_session.add(screen)
        db_session.commit()

        repr_str = repr(screen)
        assert 'Screen' in repr_str
        assert 'hw-repr-001' in repr_str
        assert 'online' in repr_str


# =============================================================================
# Content Model Tests
# =============================================================================

class TestContent:
    """Tests for Content model."""

    def test_create_content(self, app, db_session):
        """Should create content with required fields."""
        content = Content(
            content_id='content-001',
            filename='video.mp4',
            content_type='video'
        )
        db_session.add(content)
        db_session.commit()

        assert content.id is not None
        assert content.content_id == 'content-001'
        assert content.filename == 'video.mp4'

    def test_to_dict(self, app, db_session):
        """to_dict() should serialize all fields."""
        content = Content(
            content_id='content-002',
            filename='image.jpg',
            local_path='/storage/image.jpg',
            file_hash='abc123',
            file_size=1024,
            content_type='image',
            duration_seconds=None,
            playlist_ids='p1,p2,p3'
        )
        content.cached_at = datetime.utcnow()
        db_session.add(content)
        db_session.commit()

        result = content.to_dict()

        assert result['content_id'] == 'content-002'
        assert result['filename'] == 'image.jpg'
        assert result['file_hash'] == 'abc123'
        assert result['playlist_ids'] == ['p1', 'p2', 'p3']

    def test_to_dict_playlist_ids_empty(self, app, db_session):
        """to_dict() should return empty list when playlist_ids is None."""
        content = Content(content_id='content-003', filename='test.mp4')
        db_session.add(content)
        db_session.commit()

        result = content.to_dict()
        assert result['playlist_ids'] == []

    def test_to_manifest_item(self, app, db_session):
        """to_manifest_item() should return manifest data."""
        content = Content(
            content_id='content-004',
            filename='manifest.mp4',
            file_hash='xyz789',
            file_size=2048,
            content_type='video',
            duration_seconds=120
        )
        db_session.add(content)
        db_session.commit()

        item = content.to_manifest_item()

        assert item['content_id'] == 'content-004'
        assert item['file_hash'] == 'xyz789'
        assert item['file_size'] == 2048
        assert item['duration_seconds'] == 120

    def test_is_cached_property(self, app, db_session):
        """is_cached should return True when local_path and cached_at are set."""
        content = Content(content_id='content-005', filename='test.mp4')
        db_session.add(content)
        db_session.commit()

        assert content.is_cached is False

        content.local_path = '/storage/test.mp4'
        assert content.is_cached is False

        content.cached_at = datetime.utcnow()
        assert content.is_cached is True

    def test_mark_accessed(self, app, db_session):
        """mark_accessed() should update last_accessed timestamp."""
        content = Content(content_id='content-006', filename='test.mp4')
        db_session.add(content)
        db_session.commit()

        assert content.last_accessed is None

        content.mark_accessed()
        assert content.last_accessed is not None

    def test_update_cache_info(self, app, db_session):
        """update_cache_info() should set caching fields."""
        content = Content(content_id='content-007', filename='test.mp4')
        db_session.add(content)
        db_session.commit()

        content.update_cache_info(
            local_path='/storage/cached.mp4',
            file_hash='cache-hash-123',
            file_size=4096
        )

        assert content.local_path == '/storage/cached.mp4'
        assert content.file_hash == 'cache-hash-123'
        assert content.file_size == 4096
        assert content.cached_at is not None

    def test_needs_update(self, app, db_session):
        """needs_update() should compare hashes."""
        content = Content(content_id='content-008', filename='test.mp4')
        db_session.add(content)
        db_session.commit()

        # Not cached - needs update
        assert content.needs_update('any-hash') is True

        # Cache the content
        content.update_cache_info('/path', 'hash-v1', 1024)

        # Same hash - no update needed
        assert content.needs_update('hash-v1') is False

        # Different hash - needs update
        assert content.needs_update('hash-v2') is True

    def test_get_by_content_id(self, app, db_session):
        """get_by_content_id() should find content by content_id."""
        content = Content(content_id='unique-content-001', filename='unique.mp4')
        db_session.add(content)
        db_session.commit()

        found = Content.get_by_content_id('unique-content-001')
        assert found is not None
        assert found.filename == 'unique.mp4'

        not_found = Content.get_by_content_id('nonexistent')
        assert not_found is None

    def test_get_all_cached(self, app, db_session):
        """get_all_cached() should return only cached content."""
        content1 = Content(content_id='cached-001', filename='a.mp4')
        content1.cached_at = datetime.utcnow()
        content2 = Content(content_id='uncached-001', filename='b.mp4')
        content3 = Content(content_id='cached-002', filename='c.mp4')
        content3.cached_at = datetime.utcnow()

        db_session.add_all([content1, content2, content3])
        db_session.commit()

        cached = Content.get_all_cached()
        assert len(cached) == 2

    def test_get_manifest(self, app, db_session):
        """get_manifest() should return manifest items for cached content."""
        content1 = Content(content_id='manifest-001', filename='a.mp4', file_hash='h1')
        content1.cached_at = datetime.utcnow()
        content2 = Content(content_id='manifest-002', filename='b.mp4', file_hash='h2')
        # content2 not cached

        db_session.add_all([content1, content2])
        db_session.commit()

        manifest = Content.get_manifest()
        assert len(manifest) == 1
        assert manifest[0]['content_id'] == 'manifest-001'

    def test_create_or_update_creates_new(self, app, db_session):
        """create_or_update() should create new content."""
        content, created = Content.create_or_update(
            content_id='new-content-001',
            filename='new.mp4',
            content_type='video',
            duration_seconds=60,
            playlist_ids=['p1', 'p2']
        )

        assert created is True
        assert content.content_id == 'new-content-001'
        assert content.duration_seconds == 60
        assert content.playlist_ids == 'p1,p2'

    def test_create_or_update_updates_existing(self, app, db_session):
        """create_or_update() should update existing content."""
        # Create existing
        existing = Content(content_id='existing-001', filename='old.mp4')
        db_session.add(existing)
        db_session.commit()

        # Update it
        content, created = Content.create_or_update(
            content_id='existing-001',
            filename='updated.mp4',
            content_type='image',
            duration_seconds=30
        )

        assert created is False
        assert content.id == existing.id
        assert content.filename == 'updated.mp4'
        assert content.duration_seconds == 30

    def test_repr(self, app, db_session):
        """__repr__ should include content_id and cached status."""
        content = Content(content_id='repr-001', filename='test.mp4')
        db_session.add(content)
        db_session.commit()

        repr_str = repr(content)
        assert 'Content' in repr_str
        assert 'repr-001' in repr_str


# =============================================================================
# PendingAlert Model Tests
# =============================================================================

class TestPendingAlert:
    """Tests for PendingAlert model."""

    def test_create_alert_classmethod(self, app, db_session):
        """create_alert() should create and persist alert."""
        alert = PendingAlert.create_alert(
            screen_id=1,
            alert_type='ncmec_match',
            payload_dict={'match_id': 'test-123', 'confidence': 0.95}
        )

        assert alert.id is not None
        assert alert.screen_id == 1
        assert alert.alert_type == 'ncmec_match'
        assert alert.status == 'pending'
        assert alert.attempts == 0
        assert 'match_id' in alert.payload

    def test_to_dict(self, app, db_session):
        """to_dict() should serialize all fields."""
        alert = PendingAlert.create_alert(
            screen_id=2,
            alert_type='face_match',
            payload_dict={'data': 'test'}
        )

        result = alert.to_dict()

        assert result['screen_id'] == 2
        assert result['alert_type'] == 'face_match'
        assert result['status'] == 'pending'
        assert result['attempts'] == 0
        assert 'created_at' in result

    def test_to_hq_payload(self, app, db_session):
        """to_hq_payload() should format for HQ API."""
        alert = PendingAlert.create_alert(
            screen_id=3,
            alert_type='system_error',
            payload_dict={'error': 'test error'}
        )

        payload = alert.to_hq_payload()

        assert payload['alert_id'] == alert.id
        assert payload['screen_id'] == 3
        assert payload['alert_type'] == 'system_error'
        assert payload['data'] == {'error': 'test error'}

    def test_mark_sending(self, app, db_session):
        """mark_sending() should update status and increment attempts."""
        alert = PendingAlert.create_alert(
            screen_id=4,
            alert_type='test',
            payload_dict={}
        )

        alert.mark_sending()

        assert alert.status == 'sending'
        assert alert.attempts == 1
        assert alert.last_attempt_at is not None

    def test_mark_failed(self, app, db_session):
        """mark_failed() should set error and schedule retry."""
        alert = PendingAlert.create_alert(
            screen_id=5,
            alert_type='test',
            payload_dict={}
        )

        original_retry = alert.next_retry_at
        alert.mark_failed(error_message='Connection refused', retry_delay_seconds=60)

        assert alert.status == 'failed'
        assert alert.error_message == 'Connection refused'
        assert alert.next_retry_at > original_retry

    def test_mark_sent(self, app, db_session):
        """mark_sent() should set status to sent and clear error."""
        alert = PendingAlert.create_alert(
            screen_id=6,
            alert_type='test',
            payload_dict={}
        )
        alert.mark_failed(error_message='Previous error')

        alert.mark_sent()

        assert alert.status == 'sent'
        assert alert.error_message is None

    def test_is_pending_property(self, app, db_session):
        """is_pending should return True for pending/failed status."""
        alert = PendingAlert.create_alert(
            screen_id=7,
            alert_type='test',
            payload_dict={}
        )

        assert alert.is_pending is True

        alert.mark_sent()
        assert alert.is_pending is False

        # Failed is also pending
        alert.status = 'failed'
        db_session.commit()
        assert alert.is_pending is True

    def test_is_ready_for_retry(self, app, db_session):
        """is_ready_for_retry should check time and status."""
        alert = PendingAlert.create_alert(
            screen_id=8,
            alert_type='test',
            payload_dict={}
        )

        # Default next_retry_at is now, so it should be ready
        assert alert.is_ready_for_retry is True

        # Set retry time in future
        alert.next_retry_at = datetime.utcnow() + timedelta(hours=1)
        db_session.commit()
        assert alert.is_ready_for_retry is False

        # Sent alerts are not ready for retry
        alert.status = 'sent'
        db_session.commit()
        assert alert.is_ready_for_retry is False

    def test_get_pending_alerts(self, app, db_session):
        """get_pending_alerts() should return alerts ready for retry."""
        # Create ready alert
        alert1 = PendingAlert.create_alert(screen_id=9, alert_type='test', payload_dict={})

        # Create alert with future retry
        alert2 = PendingAlert.create_alert(screen_id=10, alert_type='test', payload_dict={})
        alert2.next_retry_at = datetime.utcnow() + timedelta(hours=1)
        db_session.commit()

        # Create sent alert
        alert3 = PendingAlert.create_alert(screen_id=11, alert_type='test', payload_dict={})
        alert3.mark_sent()

        pending = PendingAlert.get_pending_alerts()

        # Only alert1 should be returned
        assert len(pending) == 1
        assert pending[0].id == alert1.id

    def test_get_all_pending(self, app, db_session):
        """get_all_pending() should return all unsent alerts."""
        alert1 = PendingAlert.create_alert(screen_id=12, alert_type='test', payload_dict={})
        alert2 = PendingAlert.create_alert(screen_id=13, alert_type='test', payload_dict={})
        alert2.mark_failed(error_message='Failed')

        alert3 = PendingAlert.create_alert(screen_id=14, alert_type='test', payload_dict={})
        alert3.mark_sent()

        pending = PendingAlert.get_all_pending()
        assert len(pending) == 2

    def test_get_pending_count(self, app, db_session):
        """get_pending_count() should return count of pending alerts."""
        PendingAlert.create_alert(screen_id=15, alert_type='test', payload_dict={})
        PendingAlert.create_alert(screen_id=16, alert_type='test', payload_dict={})

        sent = PendingAlert.create_alert(screen_id=17, alert_type='test', payload_dict={})
        sent.mark_sent()

        count = PendingAlert.get_pending_count()
        assert count == 2

    def test_get_by_screen(self, app, db_session):
        """get_by_screen() should filter by screen_id."""
        PendingAlert.create_alert(screen_id=18, alert_type='test', payload_dict={})
        PendingAlert.create_alert(screen_id=18, alert_type='test', payload_dict={})
        PendingAlert.create_alert(screen_id=19, alert_type='test', payload_dict={})

        screen_18_alerts = PendingAlert.get_by_screen(18)
        assert len(screen_18_alerts) == 2

        screen_19_alerts = PendingAlert.get_by_screen(19)
        assert len(screen_19_alerts) == 1

    def test_get_by_screen_include_sent(self, app, db_session):
        """get_by_screen() with include_sent should include sent alerts."""
        alert1 = PendingAlert.create_alert(screen_id=20, alert_type='test', payload_dict={})
        alert2 = PendingAlert.create_alert(screen_id=20, alert_type='test', payload_dict={})
        alert2.mark_sent()

        # Without include_sent
        alerts = PendingAlert.get_by_screen(20, include_sent=False)
        assert len(alerts) == 1

        # With include_sent
        alerts = PendingAlert.get_by_screen(20, include_sent=True)
        assert len(alerts) == 2

    def test_delete_sent_alerts(self, app, db_session):
        """delete_sent_alerts() should remove old sent alerts."""
        # Create sent alert with old timestamp
        old_alert = PendingAlert.create_alert(screen_id=21, alert_type='test', payload_dict={})
        old_alert.mark_sent()
        old_alert.last_attempt_at = datetime.utcnow() - timedelta(hours=48)
        db_session.commit()

        # Create recent sent alert
        recent_alert = PendingAlert.create_alert(screen_id=22, alert_type='test', payload_dict={})
        recent_alert.mark_sent()

        # Delete old alerts (older than 24 hours)
        deleted = PendingAlert.delete_sent_alerts(older_than_hours=24)

        assert deleted == 1
        assert PendingAlert.query.get(old_alert.id) is None
        assert PendingAlert.query.get(recent_alert.id) is not None

    def test_delete(self, app, db_session):
        """delete() should remove the alert from database."""
        alert = PendingAlert.create_alert(screen_id=23, alert_type='test', payload_dict={})
        alert_id = alert.id

        alert.delete()

        assert PendingAlert.query.get(alert_id) is None

    def test_repr(self, app, db_session):
        """__repr__ should include key fields."""
        alert = PendingAlert.create_alert(
            screen_id=24,
            alert_type='ncmec_match',
            payload_dict={}
        )

        repr_str = repr(alert)
        assert 'PendingAlert' in repr_str
        assert 'ncmec_match' in repr_str


# =============================================================================
# SyncStatus Model Tests
# =============================================================================

class TestSyncStatus:
    """Tests for SyncStatus model."""

    def test_valid_resource_types(self, app, db_session):
        """Should have correct valid resource types defined."""
        assert SyncStatus.RESOURCE_CONTENT == 'content'
        assert SyncStatus.RESOURCE_NCMEC_DB == 'ncmec_db'
        assert SyncStatus.RESOURCE_LOYALTY_DB == 'loyalty_db'
        assert len(SyncStatus.VALID_RESOURCE_TYPES) == 3

    def test_get_or_create_creates_new(self, app, db_session):
        """get_or_create() should create new status for valid type."""
        status = SyncStatus.get_or_create('content')

        assert status is not None
        assert status.id is not None
        assert status.resource_type == 'content'

    def test_get_or_create_returns_existing(self, app, db_session):
        """get_or_create() should return existing status."""
        status1 = SyncStatus.get_or_create('content')
        status2 = SyncStatus.get_or_create('content')

        assert status1.id == status2.id

    def test_get_or_create_invalid_type(self, app, db_session):
        """get_or_create() should raise for invalid resource type."""
        with pytest.raises(ValueError) as exc_info:
            SyncStatus.get_or_create('invalid_type')

        assert 'Invalid resource type' in str(exc_info.value)

    def test_to_dict(self, app, db_session):
        """to_dict() should serialize all fields."""
        status = SyncStatus.get_or_create('content')
        status.version = 'v1.0.0'
        status.file_hash = 'abc123'
        status.file_size = 1024
        db_session.commit()

        result = status.to_dict()

        assert result['resource_type'] == 'content'
        assert result['version'] == 'v1.0.0'
        assert result['file_hash'] == 'abc123'
        assert result['file_size'] == 1024

    def test_to_version_info(self, app, db_session):
        """to_version_info() should return version data."""
        status = SyncStatus.get_or_create('ncmec_db')
        status.version = 'v2.0.0'
        status.file_hash = 'xyz789'
        status.file_size = 2048
        status.last_sync_at = datetime.utcnow()
        db_session.commit()

        info = status.to_version_info()

        assert info['version'] == 'v2.0.0'
        assert info['file_hash'] == 'xyz789'
        assert info['file_size'] == 2048
        assert info['last_updated'] is not None

    def test_is_synced_property(self, app, db_session):
        """is_synced should check last_sync_at and sync_error."""
        status = SyncStatus.get_or_create('content')

        # Not synced initially
        assert status.is_synced is False

        # Synced after marking success
        status.mark_sync_success(version='v1')
        assert status.is_synced is True

        # Not synced if error
        status.sync_error = 'Some error'
        db_session.commit()
        assert status.is_synced is False

    def test_has_error_property(self, app, db_session):
        """has_error should check sync_error field."""
        status = SyncStatus.get_or_create('content')

        assert status.has_error is False

        status.sync_error = 'Connection failed'
        db_session.commit()
        assert status.has_error is True

    def test_mark_sync_success(self, app, db_session):
        """mark_sync_success() should update all fields."""
        status = SyncStatus.get_or_create('content')
        status.sync_error = 'Previous error'
        db_session.commit()

        status.mark_sync_success(
            version='v3.0.0',
            file_hash='success-hash',
            file_size=4096
        )

        assert status.version == 'v3.0.0'
        assert status.file_hash == 'success-hash'
        assert status.file_size == 4096
        assert status.last_sync_at is not None
        assert status.last_attempt_at is not None
        assert status.sync_error is None

    def test_mark_sync_failure(self, app, db_session):
        """mark_sync_failure() should set error and update timestamp."""
        status = SyncStatus.get_or_create('content')

        status.mark_sync_failure('Network timeout')

        assert status.sync_error == 'Network timeout'
        assert status.last_attempt_at is not None

    def test_needs_update(self, app, db_session):
        """needs_update() should compare version and hash."""
        status = SyncStatus.get_or_create('content')

        # Not synced - needs update
        assert status.needs_update(new_version='v1') is True

        # Sync it
        status.mark_sync_success(version='v1', file_hash='hash1')

        # Same version/hash - no update
        assert status.needs_update(new_version='v1') is False
        assert status.needs_update(new_hash='hash1') is False

        # Different version - needs update
        assert status.needs_update(new_version='v2') is True

        # Different hash - needs update
        assert status.needs_update(new_hash='hash2') is True

    def test_get_by_type(self, app, db_session):
        """get_by_type() should find status by resource_type."""
        SyncStatus.get_or_create('content')

        found = SyncStatus.get_by_type('content')
        assert found is not None
        assert found.resource_type == 'content'

        not_found = SyncStatus.get_by_type('nonexistent')
        assert not_found is None

    def test_get_all(self, app, db_session):
        """get_all() should return all status records."""
        SyncStatus.get_or_create('content')
        SyncStatus.get_or_create('ncmec_db')

        all_status = SyncStatus.get_all()
        assert len(all_status) == 2

    def test_get_content_status(self, app, db_session):
        """get_content_status() should return content sync status."""
        status = SyncStatus.get_content_status()

        assert status.resource_type == 'content'

    def test_get_ncmec_db_status(self, app, db_session):
        """get_ncmec_db_status() should return NCMEC DB sync status."""
        status = SyncStatus.get_ncmec_db_status()

        assert status.resource_type == 'ncmec_db'

    def test_get_loyalty_db_status(self, app, db_session):
        """get_loyalty_db_status() should return loyalty DB sync status."""
        status = SyncStatus.get_loyalty_db_status()

        assert status.resource_type == 'loyalty_db'

    def test_repr(self, app, db_session):
        """__repr__ should include key fields."""
        status = SyncStatus.get_or_create('content')
        status.version = 'v1'
        db_session.commit()

        repr_str = repr(status)
        assert 'SyncStatus' in repr_str
        assert 'content' in repr_str
