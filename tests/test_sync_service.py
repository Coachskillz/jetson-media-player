"""Unit tests for the SyncService module.

Tests playlist and content synchronization with the local hub,
file hash verification, download handling, and background sync loop.
"""

import hashlib
import json
import os
import pytest
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest import mock

from src.player.sync_service import (
    SyncService,
    get_sync_service,
)
from src.player.config import PlayerConfig


# Sample test data
SAMPLE_REMOTE_CONFIG = {
    'playlist_version': 2,
    'updated_at': '2024-01-15T12:00:00Z',
    'default_playlist': {
        'id': 'default-001',
        'items': [
            {
                'content_id': 'content-001',
                'filename': 'video1.mp4',
                'duration': 30.0,
                'file_hash': 'abc123'
            },
            {
                'content_id': 'content-002',
                'filename': 'video2.mp4',
                'duration': 45.0,
                'file_hash': 'def456'
            }
        ]
    },
    'triggered_playlists': [
        {
            'playlist_id': 'triggered-001',
            'items': [
                {
                    'content_id': 'triggered-content-001',
                    'filename': 'triggered1.mp4',
                    'duration': 15.0,
                    'file_hash': 'ghi789'
                }
            ]
        }
    ],
    'settings': {
        'camera_enabled': True,
        'ncmec_enabled': True,
        'loyalty_enabled': False,
        'demographics_enabled': True
    }
}


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create device.json with screen_id and hub_url
        device_data = {
            'screen_id': 'screen-001',
            'hub_url': 'http://192.168.1.100:5000'
        }
        with open(Path(tmpdir) / 'device.json', 'w') as f:
            json.dump(device_data, f)

        # Create playlist.json with initial version
        playlist_data = {
            'version': 1,
            'default_playlist': {'items': []},
            'triggered_playlists': []
        }
        with open(Path(tmpdir) / 'playlist.json', 'w') as f:
            json.dump(playlist_data, f)

        # Create settings.json
        settings_data = {
            'camera_enabled': True,
            'ncmec_enabled': True
        }
        with open(Path(tmpdir) / 'settings.json', 'w') as f:
            json.dump(settings_data, f)

        yield tmpdir


@pytest.fixture
def temp_media_dir():
    """Create a temporary media directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def config(temp_config_dir):
    """Create a PlayerConfig instance for testing."""
    return PlayerConfig(config_dir=temp_config_dir)


@pytest.fixture
def sync_service(config, temp_media_dir):
    """Create a SyncService instance for testing."""
    service = SyncService(
        config=config,
        media_dir=temp_media_dir,
        sync_interval=60
    )
    yield service
    # Cleanup
    if service.is_running:
        service.stop()


@pytest.fixture
def reset_global_sync_service():
    """Reset the global sync service instance before and after tests."""
    import src.player.sync_service as ss_module
    original = ss_module._global_sync_service
    ss_module._global_sync_service = None
    yield
    ss_module._global_sync_service = original


class TestSyncServiceInit:
    """Tests for SyncService initialization."""

    def test_init_with_config(self, config, temp_media_dir):
        """Test initialization with config."""
        service = SyncService(
            config=config,
            media_dir=temp_media_dir
        )
        assert service._config is config
        assert service.media_dir == Path(temp_media_dir)

    def test_init_with_default_interval(self, config, temp_media_dir):
        """Test initialization uses default sync interval."""
        service = SyncService(
            config=config,
            media_dir=temp_media_dir
        )
        assert service.sync_interval == SyncService.DEFAULT_SYNC_INTERVAL

    def test_init_with_custom_interval(self, config, temp_media_dir):
        """Test initialization with custom sync interval."""
        service = SyncService(
            config=config,
            media_dir=temp_media_dir,
            sync_interval=120
        )
        assert service.sync_interval == 120

    def test_init_creates_media_dir(self, config):
        """Test that init creates media directory if not exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            media_path = Path(tmpdir) / "media" / "subdir"
            service = SyncService(
                config=config,
                media_dir=str(media_path)
            )
            assert media_path.exists()

    def test_init_with_callbacks(self, config, temp_media_dir):
        """Test initialization with callbacks."""
        on_sync = mock.MagicMock()
        on_content = mock.MagicMock()

        service = SyncService(
            config=config,
            media_dir=temp_media_dir,
            on_sync_complete=on_sync,
            on_content_updated=on_content
        )
        assert service._on_sync_complete is on_sync
        assert service._on_content_updated is on_content

    def test_init_stats_initialized(self, sync_service):
        """Test that statistics are initialized."""
        assert sync_service._last_sync_time is None
        assert sync_service._last_sync_success is False
        assert sync_service._consecutive_failures == 0
        assert sync_service._total_syncs == 0
        assert sync_service._total_failures == 0

    def test_init_not_running(self, sync_service):
        """Test that service is not running initially."""
        assert sync_service.is_running is False

    def test_repr(self, sync_service):
        """Test string representation."""
        repr_str = repr(sync_service)
        assert "SyncService" in repr_str
        assert "hub_url=" in repr_str


class TestSyncServiceProperties:
    """Tests for property accessors."""

    def test_hub_url_property(self, sync_service):
        """Test hub_url property."""
        assert sync_service.hub_url == 'http://192.168.1.100:5000'

    def test_screen_id_property(self, sync_service):
        """Test screen_id property."""
        assert sync_service.screen_id == 'screen-001'

    def test_is_running_property(self, sync_service):
        """Test is_running property."""
        assert sync_service.is_running is False
        sync_service._running = True
        assert sync_service.is_running is True

    def test_last_sync_time_property(self, sync_service):
        """Test last_sync_time property."""
        assert sync_service.last_sync_time is None
        test_time = datetime.now()
        sync_service._last_sync_time = test_time
        assert sync_service.last_sync_time == test_time

    def test_last_sync_success_property(self, sync_service):
        """Test last_sync_success property."""
        assert sync_service.last_sync_success is False
        sync_service._last_sync_success = True
        assert sync_service.last_sync_success is True

    def test_consecutive_failures_property(self, sync_service):
        """Test consecutive_failures property."""
        assert sync_service.consecutive_failures == 0
        sync_service._consecutive_failures = 3
        assert sync_service.consecutive_failures == 3


class TestSyncServiceLifecycle:
    """Tests for start/stop lifecycle."""

    def test_start_sets_running_flag(self, sync_service):
        """Test that start sets running flag."""
        with mock.patch.object(sync_service, 'sync_now'):
            sync_service.start()
            time.sleep(0.1)

            assert sync_service._running is True
            sync_service.stop()

    def test_start_already_running_warns(self, sync_service):
        """Test that starting again warns."""
        sync_service._running = True

        with mock.patch('src.player.sync_service.logger') as mock_logger:
            sync_service.start()
            mock_logger.warning.assert_called()

    def test_stop_clears_running_flag(self, sync_service):
        """Test that stop clears running flag."""
        sync_service._running = True
        sync_service._thread = None

        sync_service.stop()

        assert sync_service._running is False

    def test_stop_when_not_running(self, sync_service):
        """Test stop when not running does nothing."""
        sync_service._running = False
        sync_service.stop()  # Should not raise


class TestSyncServiceFetchConfig:
    """Tests for fetching screen config from hub."""

    def test_fetch_screen_config_success(self, sync_service):
        """Test successful config fetch."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_REMOTE_CONFIG

        with mock.patch('requests.get', return_value=mock_response):
            result = sync_service._fetch_screen_config()

        assert result == SAMPLE_REMOTE_CONFIG

    def test_fetch_screen_config_not_found(self, sync_service):
        """Test config fetch when screen not found."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 404

        with mock.patch('requests.get', return_value=mock_response):
            result = sync_service._fetch_screen_config()

        assert result is None

    def test_fetch_screen_config_server_error(self, sync_service):
        """Test config fetch on server error."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 500

        with mock.patch('requests.get', return_value=mock_response):
            result = sync_service._fetch_screen_config()

        assert result is None

    def test_fetch_screen_config_timeout(self, sync_service):
        """Test config fetch on timeout."""
        import requests

        with mock.patch('requests.get', side_effect=requests.Timeout):
            result = sync_service._fetch_screen_config()

        assert result is None

    def test_fetch_screen_config_request_exception(self, sync_service):
        """Test config fetch on request exception."""
        import requests

        with mock.patch('requests.get', side_effect=requests.RequestException):
            result = sync_service._fetch_screen_config()

        assert result is None

    def test_fetch_screen_config_no_screen_id(self, config, temp_media_dir):
        """Test config fetch with no screen_id configured."""
        config._device['screen_id'] = ''
        service = SyncService(config=config, media_dir=temp_media_dir)

        result = service._fetch_screen_config()

        assert result is None


class TestSyncServiceUpdatePlaylist:
    """Tests for updating local playlist."""

    def test_update_playlist_success(self, sync_service, config):
        """Test successful playlist update."""
        result = sync_service._update_playlist(SAMPLE_REMOTE_CONFIG)

        assert result is True
        assert config.playlist_version == 2

    def test_update_playlist_saves_items(self, sync_service, config):
        """Test that playlist items are saved."""
        sync_service._update_playlist(SAMPLE_REMOTE_CONFIG)

        assert config.default_playlist['id'] == 'default-001'
        assert len(config.default_playlist['items']) == 2

    def test_update_playlist_saves_triggered(self, sync_service, config):
        """Test that triggered playlists are saved."""
        sync_service._update_playlist(SAMPLE_REMOTE_CONFIG)

        assert len(config.triggered_playlists) == 1
        assert config.triggered_playlists[0]['playlist_id'] == 'triggered-001'

    def test_update_playlist_handles_exception(self, sync_service):
        """Test update playlist handles exception."""
        with mock.patch.object(sync_service._config, 'save_playlist',
                               side_effect=Exception("Save error")):
            result = sync_service._update_playlist(SAMPLE_REMOTE_CONFIG)

        assert result is False


class TestSyncServiceGetRequiredContent:
    """Tests for getting required content list."""

    def test_get_required_content_from_default(self, sync_service):
        """Test getting content from default playlist."""
        content = sync_service._get_required_content(SAMPLE_REMOTE_CONFIG)

        filenames = [c['filename'] for c in content]
        assert 'video1.mp4' in filenames
        assert 'video2.mp4' in filenames

    def test_get_required_content_from_triggered(self, sync_service):
        """Test getting content from triggered playlists."""
        content = sync_service._get_required_content(SAMPLE_REMOTE_CONFIG)

        filenames = [c['filename'] for c in content]
        assert 'triggered1.mp4' in filenames

    def test_get_required_content_no_duplicates(self, sync_service):
        """Test that duplicates are removed."""
        config_with_dupes = {
            'default_playlist': {
                'items': [
                    {'content_id': '001', 'filename': 'same.mp4'},
                    {'content_id': '002', 'filename': 'same.mp4'}  # Duplicate
                ]
            },
            'triggered_playlists': []
        }
        content = sync_service._get_required_content(config_with_dupes)

        filenames = [c['filename'] for c in content]
        assert filenames.count('same.mp4') == 1

    def test_get_required_content_empty_config(self, sync_service):
        """Test with empty config."""
        content = sync_service._get_required_content({})

        assert content == []


class TestSyncServiceVerifyFileHash:
    """Tests for file hash verification."""

    def test_verify_file_hash_correct(self, sync_service, temp_media_dir):
        """Test hash verification with correct hash."""
        test_content = b"test content for hashing"
        expected_hash = hashlib.sha256(test_content).hexdigest()

        file_path = Path(temp_media_dir) / "test.mp4"
        with open(file_path, 'wb') as f:
            f.write(test_content)

        result = sync_service._verify_file_hash(file_path, expected_hash)
        assert result is True

    def test_verify_file_hash_incorrect(self, sync_service, temp_media_dir):
        """Test hash verification with incorrect hash."""
        file_path = Path(temp_media_dir) / "test.mp4"
        with open(file_path, 'wb') as f:
            f.write(b"test content")

        result = sync_service._verify_file_hash(file_path, "wronghash")
        assert result is False

    def test_verify_file_hash_case_insensitive(self, sync_service, temp_media_dir):
        """Test hash verification is case insensitive."""
        test_content = b"test content"
        expected_hash = hashlib.sha256(test_content).hexdigest().upper()

        file_path = Path(temp_media_dir) / "test.mp4"
        with open(file_path, 'wb') as f:
            f.write(test_content)

        result = sync_service._verify_file_hash(file_path, expected_hash)
        assert result is True

    def test_verify_file_hash_nonexistent_file(self, sync_service, temp_media_dir):
        """Test hash verification with nonexistent file."""
        file_path = Path(temp_media_dir) / "nonexistent.mp4"

        result = sync_service._verify_file_hash(file_path, "somehash")
        assert result is False


class TestSyncServiceDownloadContent:
    """Tests for downloading content."""

    def test_download_content_success(self, sync_service, temp_media_dir):
        """Test successful content download."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]

        with mock.patch('requests.get', return_value=mock_response):
            result = sync_service._download_content("content-001", "test.mp4")

        assert result is True
        assert (Path(temp_media_dir) / "test.mp4").exists()

    def test_download_content_failed_status(self, sync_service):
        """Test download with failed status code."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 404

        with mock.patch('requests.get', return_value=mock_response):
            result = sync_service._download_content("content-001", "test.mp4")

        assert result is False

    def test_download_content_timeout(self, sync_service):
        """Test download timeout."""
        import requests

        with mock.patch('requests.get', side_effect=requests.Timeout):
            result = sync_service._download_content("content-001", "test.mp4")

        assert result is False

    def test_download_content_no_content_id(self, sync_service):
        """Test download with no content_id."""
        result = sync_service._download_content("", "test.mp4")
        assert result is False


class TestSyncServiceSyncContent:
    """Tests for syncing content."""

    def test_sync_content_downloads_missing(self, sync_service, temp_media_dir):
        """Test sync downloads missing files."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [b"content"]

        with mock.patch('requests.get', return_value=mock_response):
            result = sync_service._sync_content(SAMPLE_REMOTE_CONFIG)

        assert result is True

    def test_sync_content_skips_existing(self, sync_service, temp_media_dir):
        """Test sync skips existing files with correct hash."""
        # Create file with correct hash
        test_content = b"test content"
        file_hash = hashlib.sha256(test_content).hexdigest()

        file_path = Path(temp_media_dir) / "video1.mp4"
        with open(file_path, 'wb') as f:
            f.write(test_content)

        config = {
            'default_playlist': {
                'items': [
                    {'content_id': '001', 'filename': 'video1.mp4', 'file_hash': file_hash}
                ]
            },
            'triggered_playlists': []
        }

        with mock.patch('requests.get') as mock_get:
            result = sync_service._sync_content(config)

        # Should not have called get since file exists with correct hash
        assert not mock_get.called

    def test_sync_content_empty_list(self, sync_service):
        """Test sync with no content."""
        result = sync_service._sync_content({})
        assert result is False


class TestSyncServiceUpdateSettings:
    """Tests for updating settings."""

    def test_update_settings(self, sync_service, config):
        """Test updating settings from remote config."""
        sync_service._update_settings(SAMPLE_REMOTE_CONFIG)

        assert config.camera_enabled is True
        assert config.loyalty_enabled is False

    def test_update_settings_empty(self, sync_service):
        """Test update settings with no settings in config."""
        # Should not raise
        sync_service._update_settings({})

    def test_update_settings_handles_exception(self, sync_service):
        """Test update settings handles exception."""
        with mock.patch.object(sync_service._config, 'save_settings',
                               side_effect=Exception("Save error")):
            # Should not raise
            sync_service._update_settings(SAMPLE_REMOTE_CONFIG)


class TestSyncServiceSyncNow:
    """Tests for immediate sync."""

    def test_sync_now_success(self, sync_service):
        """Test successful sync_now."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_REMOTE_CONFIG

        with mock.patch('requests.get', return_value=mock_response):
            result = sync_service.sync_now()

        assert result is True
        assert sync_service.last_sync_success is True
        assert sync_service._consecutive_failures == 0

    def test_sync_now_hub_unreachable(self, sync_service):
        """Test sync_now when hub is unreachable."""
        import requests

        with mock.patch('requests.get', side_effect=requests.Timeout):
            result = sync_service.sync_now()

        assert result is False
        assert sync_service.last_sync_success is False
        assert sync_service._consecutive_failures == 1

    def test_sync_now_increments_total_syncs(self, sync_service):
        """Test sync_now increments total syncs counter."""
        import requests

        with mock.patch('requests.get', side_effect=requests.Timeout):
            sync_service.sync_now()
            sync_service.sync_now()

        assert sync_service._total_syncs == 2

    def test_sync_now_calls_callbacks(self, config, temp_media_dir):
        """Test sync_now calls callbacks."""
        on_sync = mock.MagicMock()
        on_content = mock.MagicMock()

        service = SyncService(
            config=config,
            media_dir=temp_media_dir,
            on_sync_complete=on_sync,
            on_content_updated=on_content
        )

        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_REMOTE_CONFIG

        with mock.patch('requests.get', return_value=mock_response):
            service.sync_now()

        on_sync.assert_called_once_with(True)


class TestSyncServiceRecordStats:
    """Tests for statistics recording."""

    def test_record_success(self, sync_service):
        """Test recording successful sync."""
        sync_service._consecutive_failures = 3

        sync_service._record_success()

        assert sync_service._last_sync_success is True
        assert sync_service._consecutive_failures == 0
        assert sync_service._last_sync_time is not None

    def test_record_failure(self, sync_service):
        """Test recording failed sync."""
        sync_service._record_failure()
        sync_service._record_failure()

        assert sync_service._last_sync_success is False
        assert sync_service._consecutive_failures == 2
        assert sync_service._total_failures == 2

    def test_record_success_calls_callback(self, config, temp_media_dir):
        """Test record_success calls callback."""
        on_sync = mock.MagicMock()
        service = SyncService(
            config=config,
            media_dir=temp_media_dir,
            on_sync_complete=on_sync
        )

        service._record_success()

        on_sync.assert_called_once_with(True)

    def test_record_failure_calls_callback(self, config, temp_media_dir):
        """Test record_failure calls callback."""
        on_sync = mock.MagicMock()
        service = SyncService(
            config=config,
            media_dir=temp_media_dir,
            on_sync_complete=on_sync
        )

        service._record_failure()

        on_sync.assert_called_once_with(False)


class TestSyncServiceGetStatus:
    """Tests for status reporting."""

    def test_get_status(self, sync_service):
        """Test get_status returns correct data."""
        status = sync_service.get_status()

        assert 'running' in status
        assert 'last_sync_time' in status
        assert 'last_sync_success' in status
        assert 'consecutive_failures' in status
        assert 'total_syncs' in status
        assert 'total_failures' in status
        assert 'sync_interval' in status
        assert 'hub_url' in status
        assert 'screen_id' in status
        assert 'media_dir' in status

    def test_get_status_values(self, sync_service):
        """Test get_status returns correct values."""
        sync_service._running = True
        sync_service._total_syncs = 5

        status = sync_service.get_status()

        assert status['running'] is True
        assert status['total_syncs'] == 5


class TestSyncServiceCleanup:
    """Tests for cleanup operations."""

    def test_cleanup_temp_file(self, sync_service, temp_media_dir):
        """Test cleanup_temp_file removes file."""
        temp_path = Path(temp_media_dir) / ".test.tmp"
        temp_path.touch()

        sync_service._cleanup_temp_file(temp_path)

        assert not temp_path.exists()

    def test_cleanup_temp_file_nonexistent(self, sync_service, temp_media_dir):
        """Test cleanup_temp_file handles nonexistent file."""
        temp_path = Path(temp_media_dir) / ".nonexistent.tmp"

        # Should not raise
        sync_service._cleanup_temp_file(temp_path)

    def test_cleanup_orphaned_files(self, sync_service, temp_media_dir):
        """Test cleanup_orphaned_files removes unreferenced files."""
        # Create some files
        (Path(temp_media_dir) / "video1.mp4").touch()
        (Path(temp_media_dir) / "video2.mp4").touch()
        (Path(temp_media_dir) / "orphan.mp4").touch()

        config = {
            'default_playlist': {
                'items': [
                    {'content_id': '001', 'filename': 'video1.mp4'},
                    {'content_id': '002', 'filename': 'video2.mp4'}
                ]
            },
            'triggered_playlists': []
        }

        removed = sync_service.cleanup_orphaned_files(config)

        assert 'orphan.mp4' in removed
        assert not (Path(temp_media_dir) / "orphan.mp4").exists()

    def test_cleanup_orphaned_files_keeps_hidden(self, sync_service, temp_media_dir):
        """Test cleanup_orphaned_files keeps hidden files."""
        (Path(temp_media_dir) / ".hidden_file").touch()

        removed = sync_service.cleanup_orphaned_files({'default_playlist': {'items': []}, 'triggered_playlists': []})

        assert '.hidden_file' not in removed
        assert (Path(temp_media_dir) / ".hidden_file").exists()


class TestSyncServiceDiskSpace:
    """Tests for disk space checking."""

    def test_check_disk_space(self, sync_service):
        """Test check_disk_space returns value."""
        result = sync_service.check_disk_space()

        # Should return a positive number or None
        assert result is None or result >= 0

    def test_check_disk_space_handles_error(self, sync_service):
        """Test check_disk_space handles errors."""
        with mock.patch('os.statvfs', side_effect=Exception("Error")):
            result = sync_service.check_disk_space()

        assert result is None


class TestGlobalSyncService:
    """Tests for global sync service instance."""

    def test_get_sync_service_creates_instance(
        self, config, temp_media_dir, reset_global_sync_service
    ):
        """Test that get_sync_service creates a new instance."""
        service = get_sync_service(
            config=config,
            media_dir=temp_media_dir
        )
        assert service is not None
        assert isinstance(service, SyncService)

    def test_get_sync_service_returns_same_instance(
        self, config, temp_media_dir, reset_global_sync_service
    ):
        """Test that get_sync_service returns the same instance."""
        service1 = get_sync_service(config=config, media_dir=temp_media_dir)
        service2 = get_sync_service()
        service3 = get_sync_service(media_dir='/different/path')

        assert service1 is service2
        assert service2 is service3

    def test_get_sync_service_with_callbacks(
        self, config, temp_media_dir, reset_global_sync_service
    ):
        """Test get_sync_service with callbacks."""
        on_sync = mock.MagicMock()
        on_content = mock.MagicMock()

        service = get_sync_service(
            config=config,
            media_dir=temp_media_dir,
            on_sync_complete=on_sync,
            on_content_updated=on_content
        )

        assert service._on_sync_complete is on_sync
        assert service._on_content_updated is on_content


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_sync_now_with_exception(self, sync_service):
        """Test sync_now handles unexpected exceptions."""
        with mock.patch.object(sync_service, '_fetch_screen_config',
                               side_effect=Exception("Unexpected error")):
            result = sync_service.sync_now()

        assert result is False
        assert sync_service._consecutive_failures == 1

    def test_update_playlist_empty_items(self, sync_service):
        """Test update_playlist with empty items."""
        config = {
            'playlist_version': 3,
            'default_playlist': {'items': []},
            'triggered_playlists': []
        }
        result = sync_service._update_playlist(config)

        assert result is True

    def test_download_content_cleans_temp_on_failure(self, sync_service, temp_media_dir):
        """Test that download cleans up temp file on failure."""
        import requests

        with mock.patch('requests.get', side_effect=requests.RequestException):
            sync_service._download_content("content-001", "test.mp4")

        # Temp file should not exist
        temp_path = Path(temp_media_dir) / ".test.mp4.tmp"
        assert not temp_path.exists()

    def test_sync_content_redownloads_hash_mismatch(self, sync_service, temp_media_dir):
        """Test sync re-downloads file with hash mismatch."""
        # Create file with wrong content
        file_path = Path(temp_media_dir) / "video1.mp4"
        with open(file_path, 'wb') as f:
            f.write(b"wrong content")

        config = {
            'default_playlist': {
                'items': [
                    {
                        'content_id': '001',
                        'filename': 'video1.mp4',
                        'file_hash': 'correct_hash_that_does_not_match'
                    }
                ]
            },
            'triggered_playlists': []
        }

        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [b"correct content"]

        with mock.patch('requests.get', return_value=mock_response) as mock_get:
            sync_service._sync_content(config)

        # Should have tried to download
        mock_get.assert_called()
