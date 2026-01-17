"""
Tests for playlist sync functionality in SyncService.

Tests the playlist synchronization functionality to ensure:
- Playlist manifest is fetched correctly from HQ
- Playlist comparison detects new/updated/deleted playlists
- Full sync creates, updates, and deletes playlists correctly
- Error handling works properly for various failure scenarios
- Sync status is tracked correctly
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from models import db
from models.playlist import Playlist
from models.sync_status import SyncStatus
from models.hub_config import HubConfig
from services import SyncError, HQConnectionError, HQTimeoutError
from services.sync_service import SyncService


# =============================================================================
# Playlist Manifest Fetch Tests
# =============================================================================

class TestFetchPlaylistManifest:
    """Tests for fetch_playlist_manifest() method."""

    def test_fetch_manifest_success(self, app, db_session):
        """fetch_playlist_manifest() should return playlist list on success."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {'playlist_id': 'pl-001', 'name': 'Morning Playlist', 'items': []},
                {'playlist_id': 'pl-002', 'name': 'Evening Playlist', 'items': []},
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.fetch_playlist_manifest('hub-123')

        assert len(result) == 2
        assert result[0]['playlist_id'] == 'pl-001'
        assert result[1]['playlist_id'] == 'pl-002'
        mock_hq_client.get_playlists.assert_called_once_with('hub-123')

    def test_fetch_manifest_empty_response(self, app, db_session):
        """fetch_playlist_manifest() should handle empty playlist list."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {'playlists': []}
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.fetch_playlist_manifest('hub-123')

        assert result == []

    def test_fetch_manifest_list_format(self, app, db_session):
        """fetch_playlist_manifest() should handle direct list response format."""
        mock_hq_client = MagicMock()
        # Some APIs return list directly
        mock_hq_client.get_playlists.return_value = [
            {'playlist_id': 'pl-001', 'name': 'Test Playlist'},
        ]
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.fetch_playlist_manifest('hub-123')

        assert len(result) == 1
        assert result[0]['playlist_id'] == 'pl-001'

    def test_fetch_manifest_connection_error(self, app, db_session):
        """fetch_playlist_manifest() should raise SyncError on connection failure."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.side_effect = HQConnectionError("Connection refused")
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)

        with pytest.raises(SyncError) as exc_info:
            sync_service.fetch_playlist_manifest('hub-123')

        assert 'playlist manifest' in str(exc_info.value).lower()

    def test_fetch_manifest_timeout_error(self, app, db_session):
        """fetch_playlist_manifest() should raise SyncError on timeout."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.side_effect = HQTimeoutError("Request timed out")
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)

        with pytest.raises(SyncError) as exc_info:
            sync_service.fetch_playlist_manifest('hub-123')

        assert 'playlist manifest' in str(exc_info.value).lower()


# =============================================================================
# Playlist Comparison Tests
# =============================================================================

class TestComparePlaylists:
    """Tests for compare_playlists() method."""

    def test_compare_all_new_playlists(self, app, db_session):
        """compare_playlists() should identify all new playlists when local is empty."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)

        hq_playlists = [
            {'playlist_id': 'pl-001', 'name': 'Playlist 1'},
            {'playlist_id': 'pl-002', 'name': 'Playlist 2'},
        ]
        local_ids = set()

        to_create, to_update, to_delete = sync_service.compare_playlists(
            hq_playlists, local_ids
        )

        assert len(to_create) == 2
        assert len(to_update) == 0
        assert len(to_delete) == 0

    def test_compare_all_existing_playlists(self, app, db_session):
        """compare_playlists() should identify all existing playlists for update."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)

        hq_playlists = [
            {'playlist_id': 'pl-001', 'name': 'Playlist 1'},
            {'playlist_id': 'pl-002', 'name': 'Playlist 2'},
        ]
        local_ids = {'pl-001', 'pl-002'}

        to_create, to_update, to_delete = sync_service.compare_playlists(
            hq_playlists, local_ids
        )

        assert len(to_create) == 0
        assert len(to_update) == 2
        assert len(to_delete) == 0

    def test_compare_orphaned_playlists(self, app, db_session):
        """compare_playlists() should identify orphaned local playlists."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)

        hq_playlists = [
            {'playlist_id': 'pl-001', 'name': 'Playlist 1'},
        ]
        local_ids = {'pl-001', 'pl-002', 'pl-003'}

        to_create, to_update, to_delete = sync_service.compare_playlists(
            hq_playlists, local_ids
        )

        assert len(to_create) == 0
        assert len(to_update) == 1
        assert len(to_delete) == 2
        assert 'pl-002' in to_delete
        assert 'pl-003' in to_delete

    def test_compare_mixed_actions(self, app, db_session):
        """compare_playlists() should handle mixed create/update/delete."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)

        hq_playlists = [
            {'playlist_id': 'pl-001', 'name': 'Existing'},
            {'playlist_id': 'pl-003', 'name': 'New'},
        ]
        local_ids = {'pl-001', 'pl-002'}  # pl-002 is orphaned

        to_create, to_update, to_delete = sync_service.compare_playlists(
            hq_playlists, local_ids
        )

        assert len(to_create) == 1  # pl-003
        assert len(to_update) == 1  # pl-001
        assert len(to_delete) == 1  # pl-002

    def test_compare_handles_id_field_variations(self, app, db_session):
        """compare_playlists() should handle 'id' field as well as 'playlist_id'."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)

        hq_playlists = [
            {'id': 'pl-001', 'name': 'Playlist with id field'},
        ]
        local_ids = set()

        to_create, to_update, to_delete = sync_service.compare_playlists(
            hq_playlists, local_ids
        )

        assert len(to_create) == 1
        assert to_create[0]['id'] == 'pl-001'

    def test_compare_empty_manifest(self, app, db_session):
        """compare_playlists() should handle empty HQ manifest."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)

        hq_playlists = []
        local_ids = {'pl-001'}

        to_create, to_update, to_delete = sync_service.compare_playlists(
            hq_playlists, local_ids
        )

        assert len(to_create) == 0
        assert len(to_update) == 0
        # Empty manifest means local should be marked for deletion
        assert len(to_delete) == 1


# =============================================================================
# Full Playlist Sync Tests
# =============================================================================

class TestSyncPlaylists:
    """Tests for sync_playlists() method - full sync operations."""

    def test_sync_hub_not_registered(self, app, db_session):
        """sync_playlists() should skip sync when hub is not registered."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        # Ensure hub is not registered
        hub_config = HubConfig.get_instance()
        hub_config.hub_id = None
        hub_config.hub_token = None
        db_session.commit()

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.sync_playlists()

        assert result['created'] == 0
        assert result['updated'] == 0
        assert result['deleted'] == 0
        assert 'not registered' in result['errors'][0].lower()

    def test_sync_creates_new_playlists(self, app, db_session, sample_hub_config):
        """sync_playlists() should create new playlists from HQ manifest."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {
                    'playlist_id': 'pl-new-001',
                    'name': 'New Playlist',
                    'description': 'Test description',
                    'items': [{'content_id': 'content-001', 'duration': 30}],
                    'is_active': True,
                },
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.sync_playlists()

        assert result['created'] == 1
        assert result['updated'] == 0
        assert result['deleted'] == 0
        assert result['success'] is True

        # Verify playlist was created
        playlist = Playlist.get_by_playlist_id('pl-new-001')
        assert playlist is not None
        assert playlist.name == 'New Playlist'
        assert playlist.description == 'Test description'

    def test_sync_updates_existing_playlists(self, app, db_session, sample_hub_config):
        """sync_playlists() should update existing playlists."""
        # Create existing playlist
        Playlist.create_or_update(
            playlist_id='pl-existing',
            name='Old Name',
            items=[],
        )

        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {
                    'playlist_id': 'pl-existing',
                    'name': 'Updated Name',
                    'items': [{'content_id': 'content-001'}],
                    'is_active': True,
                },
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.sync_playlists()

        assert result['created'] == 0
        assert result['updated'] == 1
        assert result['deleted'] == 0
        assert result['success'] is True

        # Verify playlist was updated
        playlist = Playlist.get_by_playlist_id('pl-existing')
        assert playlist.name == 'Updated Name'

    def test_sync_deletes_orphaned_playlists(self, app, db_session, sample_hub_config):
        """sync_playlists() should delete orphaned playlists."""
        # Create playlist that will be orphaned
        Playlist.create_or_update(
            playlist_id='pl-orphan',
            name='Orphan Playlist',
            items=[],
        )

        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {
                    'playlist_id': 'pl-new',
                    'name': 'New Playlist',
                    'items': [],
                },
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.sync_playlists()

        assert result['created'] == 1
        assert result['updated'] == 0
        assert result['deleted'] == 1
        assert result['success'] is True

        # Verify orphan was deleted
        assert Playlist.get_by_playlist_id('pl-orphan') is None

    def test_sync_preserves_local_on_empty_manifest(self, app, db_session, sample_hub_config):
        """sync_playlists() should preserve local playlists when HQ returns empty manifest."""
        # Create local playlist
        Playlist.create_or_update(
            playlist_id='pl-local',
            name='Local Playlist',
            items=[],
        )

        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {'playlists': []}
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.sync_playlists()

        # Local playlists should be preserved
        assert result['deleted'] == 0
        assert result['success'] is True
        assert Playlist.get_by_playlist_id('pl-local') is not None

    def test_sync_handles_mixed_operations(self, app, db_session, sample_hub_config):
        """sync_playlists() should handle mixed create/update/delete."""
        # Create existing playlists
        Playlist.create_or_update(playlist_id='pl-keep', name='Keep', items=[])
        Playlist.create_or_update(playlist_id='pl-delete', name='Delete', items=[])

        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {'playlist_id': 'pl-keep', 'name': 'Updated Keep', 'items': []},
                {'playlist_id': 'pl-new', 'name': 'Brand New', 'items': []},
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.sync_playlists()

        assert result['created'] == 1  # pl-new
        assert result['updated'] == 1  # pl-keep
        assert result['deleted'] == 1  # pl-delete
        assert result['success'] is True

    def test_sync_connection_error(self, app, db_session, sample_hub_config):
        """sync_playlists() should raise SyncError on connection failure."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.side_effect = HQConnectionError("Network down")
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)

        with pytest.raises(SyncError) as exc_info:
            sync_service.sync_playlists()

        assert 'sync failed' in str(exc_info.value).lower()

    def test_sync_partial_failure(self, app, db_session, sample_hub_config):
        """sync_playlists() should continue on partial failures and report errors."""
        # Create a playlist that we can try to delete
        Playlist.create_or_update(playlist_id='pl-keep', name='Keep', items=[])

        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {'playlist_id': 'pl-good', 'name': 'Good Playlist', 'items': []},
                {'playlist_id': 'pl-keep', 'name': 'Updated', 'items': []},
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)

        # Mock Playlist.create_or_update to fail for one specific playlist
        original_create_or_update = Playlist.create_or_update

        def mock_create_or_update(*args, **kwargs):
            if kwargs.get('playlist_id') == 'pl-good':
                raise Exception("Database error")
            return original_create_or_update(*args, **kwargs)

        with patch.object(Playlist, 'create_or_update', side_effect=mock_create_or_update):
            result = sync_service.sync_playlists()

        # Partial success
        assert result['updated'] == 1  # pl-keep succeeded
        assert len(result['errors']) >= 1
        assert result['success'] is False


# =============================================================================
# Sync Status Tests
# =============================================================================

class TestGetPlaylistSyncStatus:
    """Tests for get_playlist_sync_status() method."""

    def test_status_empty(self, app, db_session):
        """get_playlist_sync_status() should handle empty playlist state."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        status = sync_service.get_playlist_sync_status()

        assert status['playlist_count'] == 0
        assert status['active_playlist_count'] == 0

    def test_status_with_playlists(self, app, db_session):
        """get_playlist_sync_status() should return correct playlist counts."""
        # Create some playlists
        Playlist.create_or_update(
            playlist_id='pl-active-1',
            name='Active 1',
            items=[],
            is_active=True,
        )
        Playlist.create_or_update(
            playlist_id='pl-active-2',
            name='Active 2',
            items=[],
            is_active=True,
        )
        Playlist.create_or_update(
            playlist_id='pl-inactive',
            name='Inactive',
            items=[],
            is_active=False,
        )

        mock_hq_client = MagicMock()
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        status = sync_service.get_playlist_sync_status()

        assert status['playlist_count'] == 3
        assert status['active_playlist_count'] == 2

    def test_status_includes_sync_info(self, app, db_session, sample_hub_config):
        """get_playlist_sync_status() should include last sync time."""
        # Trigger a successful sync first
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {'playlist_id': 'pl-001', 'name': 'Test', 'items': []},
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        sync_service.sync_playlists()

        status = sync_service.get_playlist_sync_status()

        assert 'last_sync' in status


# =============================================================================
# Playlist Model Interaction Tests
# =============================================================================

class TestPlaylistModelInteraction:
    """Tests for Playlist model interactions during sync."""

    def test_playlist_items_stored_as_json(self, app, db_session, sample_hub_config):
        """Playlist items should be stored and retrieved correctly as JSON."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {
                    'playlist_id': 'pl-items',
                    'name': 'Playlist with Items',
                    'items': [
                        {'content_id': 'c-001', 'duration': 30, 'order': 1},
                        {'content_id': 'c-002', 'duration': 60, 'order': 2},
                    ],
                },
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        sync_service.sync_playlists()

        playlist = Playlist.get_by_playlist_id('pl-items')
        items = playlist.get_items()

        assert len(items) == 2
        assert items[0]['content_id'] == 'c-001'
        assert items[1]['duration'] == 60

    def test_playlist_trigger_config_stored(self, app, db_session, sample_hub_config):
        """Playlist trigger configuration should be stored correctly."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {
                    'playlist_id': 'pl-trigger',
                    'name': 'Scheduled Playlist',
                    'trigger_type': 'time',
                    'trigger_config': {
                        'start_time': '09:00',
                        'end_time': '17:00',
                        'days': ['monday', 'tuesday'],
                    },
                    'items': [],
                },
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        sync_service.sync_playlists()

        playlist = Playlist.get_by_playlist_id('pl-trigger')
        assert playlist.trigger_type == 'time'

        data = playlist.to_dict()
        assert data['trigger_config']['start_time'] == '09:00'

    def test_synced_at_timestamp_updated(self, app, db_session, sample_hub_config):
        """Playlist synced_at timestamp should be updated on sync."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {'playlist_id': 'pl-sync', 'name': 'Synced', 'items': []},
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        sync_service.sync_playlists()

        playlist = Playlist.get_by_playlist_id('pl-sync')
        assert playlist.synced_at is not None
        assert playlist.is_synced is True


# =============================================================================
# Edge Cases and Error Handling Tests
# =============================================================================

class TestPlaylistSyncEdgeCases:
    """Tests for edge cases and error handling in playlist sync."""

    def test_handles_playlist_without_id(self, app, db_session, sample_hub_config):
        """sync_playlists() should skip playlists without valid ID."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {'name': 'No ID Playlist', 'items': []},  # Missing playlist_id
                {'playlist_id': 'pl-valid', 'name': 'Valid', 'items': []},
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.sync_playlists()

        # Only the valid playlist should be created
        assert result['created'] == 1
        assert Playlist.get_by_playlist_id('pl-valid') is not None

    def test_handles_null_items(self, app, db_session, sample_hub_config):
        """sync_playlists() should handle null items field."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {'playlist_id': 'pl-null', 'name': 'Null Items', 'items': None},
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.sync_playlists()

        assert result['created'] == 1
        playlist = Playlist.get_by_playlist_id('pl-null')
        assert playlist.get_items() == []

    def test_handles_missing_optional_fields(self, app, db_session, sample_hub_config):
        """sync_playlists() should handle missing optional fields."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {
                    'playlist_id': 'pl-minimal',
                    'name': 'Minimal',
                    # No description, network_id, trigger_type, etc.
                },
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.sync_playlists()

        assert result['created'] == 1
        playlist = Playlist.get_by_playlist_id('pl-minimal')
        assert playlist.name == 'Minimal'
        assert playlist.description is None
        assert playlist.trigger_type == 'manual'  # Default

    def test_sync_result_timestamps(self, app, db_session, sample_hub_config):
        """sync_playlists() should include started_at and completed_at timestamps."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {'playlists': []}
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        result = sync_service.sync_playlists()

        assert 'started_at' in result
        assert 'completed_at' in result
        assert result['completed_at'] is not None

    def test_sync_status_updated_on_success(self, app, db_session, sample_hub_config):
        """sync_playlists() should update SyncStatus on successful sync."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.return_value = {
            'playlists': [
                {'playlist_id': 'pl-001', 'name': 'Test', 'items': []},
            ]
        }
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)
        sync_service.sync_playlists()

        sync_status = SyncStatus.get_playlist_status()
        assert sync_status.last_sync is not None
        assert sync_status.error_message is None

    def test_sync_status_updated_on_failure(self, app, db_session, sample_hub_config):
        """sync_playlists() should update SyncStatus with error on failure."""
        mock_hq_client = MagicMock()
        mock_hq_client.get_playlists.side_effect = HQConnectionError("Failed")
        mock_config = MagicMock()
        mock_config.content_path = '/tmp/content'
        mock_config.databases_path = '/tmp/databases'

        sync_service = SyncService(mock_hq_client, mock_config)

        with pytest.raises(SyncError):
            sync_service.sync_playlists()

        sync_status = SyncStatus.get_playlist_status()
        assert sync_status.error_message is not None
