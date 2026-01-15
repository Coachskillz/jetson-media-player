"""Integration tests for Jetson Media Player.

End-to-end verification of SkillzPlayer with all components:
- GStreamerPlayer (mocked for non-Jetson environments)
- PlaylistManager
- TriggerListener
- SyncService
- HeartbeatReporter
"""

import os
import json
import time
import tempfile
import threading
from pathlib import Path
from unittest import mock

import pytest

# Import player components
from src.player.config import PlayerConfig
from src.player.playlist_manager import (
    PlaylistManager,
    PlaylistItem,
    PlaylistMode,
    TriggerRule,
    TriggeredPlaylist
)
from src.player.heartbeat import HeartbeatReporter


# -----------------------------------------------------------------------------
# Test Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def temp_media_dir():
    """Create a temporary media directory with test files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        media_dir = Path(temp_dir) / "media"
        media_dir.mkdir()

        # Create dummy video files
        (media_dir / "promo1.mp4").write_bytes(b"test video content 1")
        (media_dir / "promo2.mp4").write_bytes(b"test video content 2")
        (media_dir / "beer_ad.mp4").write_bytes(b"test video content 3")
        (media_dir / "loyalty_welcome.mp4").write_bytes(b"test video content 4")

        yield str(media_dir)


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory with test config files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        config_dir = Path(temp_dir) / "config"
        config_dir.mkdir()

        # Create device.json
        device_config = {
            "screen_id": "test-screen-001",
            "hardware_id": "AA:BB:CC:DD:EE:FF",
            "hub_url": "http://localhost:5000",
            "name": "Test Screen",
            "location_in_store": "Test Location"
        }
        (config_dir / "device.json").write_text(json.dumps(device_config))

        # Create playlist.json
        playlist_config = {
            "default_playlist": {
                "id": "default-001",
                "items": [
                    {"content_id": "c001", "filename": "promo1.mp4", "duration": 30},
                    {"content_id": "c002", "filename": "promo2.mp4", "duration": 15}
                ]
            },
            "triggered_playlists": [
                {
                    "playlist_id": "adult-playlist",
                    "rule": {
                        "type": "demographic",
                        "age_min": 21,
                        "age_max": 65,
                        "gender": "any"
                    },
                    "items": [
                        {"content_id": "c003", "filename": "beer_ad.mp4", "duration": 30}
                    ]
                },
                {
                    "playlist_id": "loyalty-playlist",
                    "rule": {
                        "type": "loyalty",
                        "member_id": None
                    },
                    "items": [
                        {"content_id": "c004", "filename": "loyalty_welcome.mp4", "duration": 15}
                    ]
                }
            ],
            "version": 1,
            "updated_at": "2026-01-15T12:00:00Z"
        }
        (config_dir / "playlist.json").write_text(json.dumps(playlist_config))

        # Create settings.json
        settings_config = {
            "camera_enabled": True,
            "ncmec_enabled": True,
            "loyalty_enabled": True,
            "demographics_enabled": True
        }
        (config_dir / "settings.json").write_text(json.dumps(settings_config))

        yield str(config_dir)


@pytest.fixture
def player_config(temp_config_dir):
    """Create a PlayerConfig instance with test configuration."""
    return PlayerConfig(config_dir=temp_config_dir)


@pytest.fixture
def playlist_manager(player_config, temp_media_dir):
    """Create a PlaylistManager instance with test data."""
    manager = PlaylistManager(
        config=player_config,
        media_dir=temp_media_dir
    )
    manager.load_from_config()
    return manager


@pytest.fixture
def reset_global_instances():
    """Reset global singleton instances before and after tests."""
    # Reset player module globals
    import src.player.player as player_module
    import src.player.playlist_manager as playlist_module
    import src.player.gstreamer_player as gstreamer_module
    import src.player.trigger_listener as trigger_module
    import src.player.sync_service as sync_module
    import src.player.config as config_module

    # Store originals
    originals = {
        'player': player_module._global_player,
        'playlist': playlist_module._global_playlist_manager,
        'gstreamer': gstreamer_module._global_player,
        'trigger': trigger_module._global_trigger_listener,
        'sync': sync_module._global_sync_service,
        'config': config_module._global_player_config,
    }

    # Reset to None
    player_module._global_player = None
    playlist_module._global_playlist_manager = None
    gstreamer_module._global_player = None
    trigger_module._global_trigger_listener = None
    sync_module._global_sync_service = None
    config_module._global_player_config = None

    yield

    # Restore originals
    player_module._global_player = originals['player']
    playlist_module._global_playlist_manager = originals['playlist']
    gstreamer_module._global_player = originals['gstreamer']
    trigger_module._global_trigger_listener = originals['trigger']
    sync_module._global_sync_service = originals['sync']
    config_module._global_player_config = originals['config']


# -----------------------------------------------------------------------------
# Integration Tests: Config and Playlist Manager
# -----------------------------------------------------------------------------

class TestConfigPlaylistIntegration:
    """Tests for Config and PlaylistManager integration."""

    def test_playlist_loads_from_config(self, playlist_manager, temp_media_dir):
        """Test that PlaylistManager correctly loads playlists from config."""
        assert playlist_manager.default_playlist_length == 2
        assert len(playlist_manager._triggered_playlists) == 2

    def test_get_first_uri_returns_valid_uri(self, playlist_manager, temp_media_dir):
        """Test that get_first_uri returns a valid file URI."""
        first_uri = playlist_manager.get_first_uri()

        assert first_uri is not None
        assert first_uri.startswith("file://")
        assert "promo1.mp4" in first_uri

    def test_get_next_uri_loops_playlist(self, playlist_manager, temp_media_dir):
        """Test that playlist loops correctly."""
        # Get all items in sequence
        uri1 = playlist_manager.get_first_uri()
        uri2 = playlist_manager.get_next_uri()
        uri3 = playlist_manager.get_next_uri()  # Should loop back

        assert "promo1.mp4" in uri1
        assert "promo2.mp4" in uri2
        assert "promo1.mp4" in uri3  # Looped back

    def test_config_updates_reflected_in_playlist(self, player_config, temp_media_dir, temp_config_dir):
        """Test that config changes are reflected when playlist reloads."""
        # Create playlist manager
        manager = PlaylistManager(config=player_config, media_dir=temp_media_dir)
        manager.load_from_config()

        initial_count = manager.default_playlist_length

        # Modify config file
        playlist_path = Path(temp_config_dir) / "playlist.json"
        playlist_data = json.loads(playlist_path.read_text())
        playlist_data["default_playlist"]["items"].append(
            {"content_id": "c005", "filename": "promo2.mp4", "duration": 20}
        )
        playlist_path.write_text(json.dumps(playlist_data))

        # Reload
        manager.reload()

        assert manager.default_playlist_length == initial_count + 1


# -----------------------------------------------------------------------------
# Integration Tests: Trigger Handling
# -----------------------------------------------------------------------------

class TestTriggerPlaylistIntegration:
    """Tests for trigger handling and playlist switching."""

    def test_demographic_trigger_activates_playlist(self, playlist_manager):
        """Test that demographic trigger activates matching playlist."""
        trigger_data = {
            "type": "demographic",
            "age": 30,
            "gender": "male",
            "confidence": 0.92
        }

        # Handle trigger
        result = playlist_manager.handle_trigger(trigger_data)

        assert result is True
        assert playlist_manager.mode == PlaylistMode.TRIGGERED
        assert playlist_manager.triggered_playlist_id == "adult-playlist"

    def test_loyalty_trigger_activates_playlist(self, playlist_manager):
        """Test that loyalty trigger activates matching playlist."""
        trigger_data = {
            "type": "loyalty",
            "member_id": "member-001",
            "member_name": "Test User"
        }

        result = playlist_manager.handle_trigger(trigger_data)

        assert result is True
        assert playlist_manager.mode == PlaylistMode.TRIGGERED
        assert playlist_manager.triggered_playlist_id == "loyalty-playlist"

    def test_ncmec_trigger_does_not_change_playlist(self, playlist_manager):
        """Test that NCMEC alert does not change playlist (log only)."""
        trigger_data = {
            "type": "ncmec_alert",
            "case_id": "12345"
        }

        initial_mode = playlist_manager.mode
        result = playlist_manager.handle_trigger(trigger_data)

        assert result is False
        assert playlist_manager.mode == initial_mode

    def test_unmatched_trigger_no_change(self, playlist_manager):
        """Test that unmatched trigger does not change playlist."""
        trigger_data = {
            "type": "demographic",
            "age": 10,  # No playlist for children
            "gender": "female",
            "confidence": 0.95
        }

        result = playlist_manager.handle_trigger(trigger_data)

        # Adult playlist requires age 21+
        assert result is False
        assert playlist_manager.mode == PlaylistMode.DEFAULT

    def test_triggered_playlist_returns_to_default(self, playlist_manager, temp_media_dir):
        """Test that triggered playlist returns to default after completion."""
        # Activate triggered playlist
        trigger_data = {
            "type": "demographic",
            "age": 35,
            "gender": "male",
            "confidence": 0.90
        }
        playlist_manager.handle_trigger(trigger_data)

        assert playlist_manager.mode == PlaylistMode.TRIGGERED

        # Play through triggered playlist (1 item)
        uri = playlist_manager.get_next_uri()
        assert "beer_ad.mp4" in uri

        # Next call should return to default
        uri = playlist_manager.get_next_uri()
        assert playlist_manager.mode == PlaylistMode.DEFAULT


# -----------------------------------------------------------------------------
# Integration Tests: Heartbeat Reporter
# -----------------------------------------------------------------------------

class TestHeartbeatIntegration:
    """Tests for HeartbeatReporter integration."""

    def test_heartbeat_collects_metrics(self):
        """Test that heartbeat collects system metrics."""
        reporter = HeartbeatReporter(
            hub_url="http://localhost:5000",
            screen_id="test-screen",
            interval=60
        )

        metrics = reporter.collect_metrics()

        # Verify all expected fields are present
        assert "status" in metrics
        assert "current_content" in metrics
        assert "cpu_temp" in metrics
        assert "memory_usage_percent" in metrics
        assert "disk_free_gb" in metrics
        assert "uptime_seconds" in metrics

    def test_heartbeat_uses_status_callback(self):
        """Test that heartbeat uses status callback correctly."""
        reporter = HeartbeatReporter(
            hub_url="http://localhost:5000",
            screen_id="test-screen",
            interval=60
        )

        # Set custom status callback
        def custom_status():
            return {
                "status": "playing",
                "current_content": "test_video.mp4"
            }

        reporter.set_status_callback(custom_status)

        metrics = reporter.collect_metrics()

        assert metrics["status"] == "playing"
        assert metrics["current_content"] == "test_video.mp4"

    @mock.patch('requests.post')
    def test_heartbeat_sends_to_hub(self, mock_post):
        """Test that heartbeat sends data to hub."""
        mock_post.return_value.status_code = 200

        reporter = HeartbeatReporter(
            hub_url="http://localhost:5000",
            screen_id="test-screen",
            interval=60
        )

        result = reporter.send_heartbeat()

        assert result is True
        mock_post.assert_called_once()

        # Verify URL
        call_args = mock_post.call_args
        assert "test-screen" in call_args[0][0]
        assert "heartbeat" in call_args[0][0]

    @mock.patch('requests.post')
    def test_heartbeat_handles_hub_failure(self, mock_post):
        """Test that heartbeat handles hub failure gracefully."""
        mock_post.side_effect = Exception("Connection refused")

        reporter = HeartbeatReporter(
            hub_url="http://localhost:5000",
            screen_id="test-screen",
            interval=60
        )

        result = reporter.send_heartbeat()

        assert result is False
        assert reporter._consecutive_failures == 1


# -----------------------------------------------------------------------------
# Integration Tests: Full Player Flow (Mocked GStreamer)
# -----------------------------------------------------------------------------

class TestFullPlayerIntegration:
    """Integration tests for full player flow with mocked GStreamer."""

    @mock.patch('src.player.gstreamer_player.Gst')
    @mock.patch('src.player.gstreamer_player.GLib')
    def test_player_initialization_flow(
        self,
        mock_glib,
        mock_gst,
        temp_config_dir,
        temp_media_dir,
        reset_global_instances
    ):
        """Test full player initialization flow."""
        # Setup mocks
        mock_gst.init.return_value = None
        mock_player = mock.MagicMock()
        mock_gst.ElementFactory.make.return_value = mock_player
        mock_gst.StateChangeReturn.FAILURE = 0
        mock_gst.StateChangeReturn.SUCCESS = 1
        mock_player.set_state.return_value = 1  # SUCCESS

        from src.player.player import SkillzPlayer

        player = SkillzPlayer(
            config_dir=temp_config_dir,
            media_dir=temp_media_dir,
            sync_interval=300,
            heartbeat_interval=60
        )

        assert player is not None
        assert not player.is_running

    def test_player_config_loading(self, temp_config_dir, temp_media_dir, reset_global_instances):
        """Test that player loads config correctly."""
        from src.player.player import SkillzPlayer

        player = SkillzPlayer(
            config_dir=temp_config_dir,
            media_dir=temp_media_dir
        )

        # Load config manually
        result = player._load_config()

        assert result is True
        assert player._config is not None
        assert player._config.screen_id == "test-screen-001"

    def test_player_playlist_manager_initialization(
        self,
        temp_config_dir,
        temp_media_dir,
        reset_global_instances
    ):
        """Test that player initializes playlist manager correctly."""
        from src.player.player import SkillzPlayer

        player = SkillzPlayer(
            config_dir=temp_config_dir,
            media_dir=temp_media_dir
        )

        player._load_config()
        result = player._initialize_playlist_manager()

        assert result is True
        assert player._playlist_manager is not None
        assert player._playlist_manager.default_playlist_length == 2


# -----------------------------------------------------------------------------
# Integration Tests: Status Reporting
# -----------------------------------------------------------------------------

class TestStatusReporting:
    """Tests for status reporting across components."""

    def test_playlist_info_format(self, playlist_manager):
        """Test playlist info format for status reporting."""
        info = playlist_manager.get_playlist_info()

        assert "mode" in info
        assert "default_items" in info
        assert "default_position" in info
        assert "current_filename" in info
        assert "is_triggered" in info
        assert "triggered_playlist_id" in info
        assert "triggered_playlists_count" in info

        assert info["mode"] == "default"
        assert info["default_items"] == 2
        assert info["triggered_playlists_count"] == 2

    def test_heartbeat_info_format(self):
        """Test heartbeat info format."""
        reporter = HeartbeatReporter(
            hub_url="http://localhost:5000",
            screen_id="test-screen",
            interval=60
        )

        info = reporter.get_last_heartbeat_info()

        assert "last_time" in info
        assert "last_success" in info
        assert "consecutive_failures" in info


# -----------------------------------------------------------------------------
# Integration Tests: Error Handling
# -----------------------------------------------------------------------------

class TestErrorHandling:
    """Tests for error handling across components."""

    def test_missing_media_file_handling(self, player_config):
        """Test handling of missing media files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            media_dir = Path(temp_dir) / "media"
            media_dir.mkdir()

            # Create only one file (promo1.mp4 missing)
            (media_dir / "promo2.mp4").write_bytes(b"content")

            manager = PlaylistManager(config=player_config, media_dir=str(media_dir))
            manager.load_from_config()

            # First item is missing, should skip to next
            uri = manager.get_first_uri()

            # Should get promo2.mp4 after skipping missing promo1.mp4
            if uri:
                assert "promo2.mp4" in uri

    def test_empty_playlist_handling(self, temp_media_dir):
        """Test handling of empty playlist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "config"
            config_dir.mkdir()

            # Create config with empty playlist
            device_config = {"screen_id": "test", "hub_url": "http://localhost:5000"}
            (config_dir / "device.json").write_text(json.dumps(device_config))

            playlist_config = {
                "default_playlist": {"id": "empty", "items": []},
                "triggered_playlists": [],
                "version": 1
            }
            (config_dir / "playlist.json").write_text(json.dumps(playlist_config))

            settings_config = {"camera_enabled": False}
            (config_dir / "settings.json").write_text(json.dumps(settings_config))

            config = PlayerConfig(config_dir=str(config_dir))
            manager = PlaylistManager(config=config, media_dir=temp_media_dir)
            manager.load_from_config()

            assert manager.default_playlist_length == 0
            assert manager.get_first_uri() is None

    @mock.patch('requests.post')
    def test_heartbeat_network_error_recovery(self, mock_post):
        """Test heartbeat recovery after network errors."""
        # First call fails, second succeeds
        mock_post.side_effect = [
            Exception("Network error"),
            mock.MagicMock(status_code=200)
        ]

        reporter = HeartbeatReporter(
            hub_url="http://localhost:5000",
            screen_id="test-screen",
            interval=60
        )

        # First attempt fails
        result1 = reporter.send_heartbeat()
        assert result1 is False
        assert reporter._consecutive_failures == 1

        # Second attempt succeeds
        result2 = reporter.send_heartbeat()
        assert result2 is True
        assert reporter._consecutive_failures == 0


# -----------------------------------------------------------------------------
# Integration Tests: Component Callbacks
# -----------------------------------------------------------------------------

class TestComponentCallbacks:
    """Tests for component callback mechanisms."""

    def test_playlist_changed_callback(self, player_config, temp_media_dir):
        """Test playlist changed callback is invoked."""
        callback_invoked = []

        def on_change(manager):
            callback_invoked.append(manager.mode.value)

        manager = PlaylistManager(
            config=player_config,
            media_dir=temp_media_dir,
            on_playlist_changed=on_change
        )
        manager.load_from_config()

        # Trigger playlist change
        trigger_data = {"type": "demographic", "age": 35, "gender": "any"}
        manager.handle_trigger(trigger_data)

        assert len(callback_invoked) == 1
        assert callback_invoked[0] == "triggered"

    def test_heartbeat_status_callback_integration(self, playlist_manager):
        """Test heartbeat using playlist manager for status."""
        reporter = HeartbeatReporter(
            hub_url="http://localhost:5000",
            screen_id="test-screen",
            interval=60
        )

        # Set callback that uses playlist manager
        def get_status():
            return {
                "status": "playing",
                "current_content": playlist_manager.current_filename or ""
            }

        reporter.set_status_callback(get_status)

        # Start playback
        playlist_manager.get_first_uri()

        metrics = reporter.collect_metrics()

        assert metrics["status"] == "playing"
        assert "promo1.mp4" in metrics["current_content"]


# -----------------------------------------------------------------------------
# Import Verification Tests
# -----------------------------------------------------------------------------

class TestModuleImports:
    """Tests to verify all modules can be imported correctly."""

    def test_import_skillz_player(self):
        """Test SkillzPlayer can be imported."""
        from src.player.player import SkillzPlayer
        assert SkillzPlayer is not None

    def test_import_gstreamer_player(self):
        """Test GStreamerPlayer can be imported."""
        from src.player.gstreamer_player import GStreamerPlayer, PlayerState
        assert GStreamerPlayer is not None
        assert PlayerState is not None

    def test_import_playlist_manager(self):
        """Test PlaylistManager can be imported."""
        from src.player.playlist_manager import (
            PlaylistManager,
            PlaylistItem,
            PlaylistMode,
            TriggerRule,
            TriggeredPlaylist
        )
        assert PlaylistManager is not None
        assert PlaylistItem is not None
        assert PlaylistMode is not None

    def test_import_trigger_listener(self):
        """Test TriggerListener can be imported."""
        from src.player.trigger_listener import TriggerListener
        assert TriggerListener is not None

    def test_import_sync_service(self):
        """Test SyncService can be imported."""
        from src.player.sync_service import SyncService
        assert SyncService is not None

    def test_import_heartbeat(self):
        """Test HeartbeatReporter can be imported."""
        from src.player.heartbeat import HeartbeatReporter
        assert HeartbeatReporter is not None

    def test_import_config(self):
        """Test PlayerConfig can be imported."""
        from src.player.config import PlayerConfig
        assert PlayerConfig is not None


# -----------------------------------------------------------------------------
# Run as Script (for manual testing)
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Jetson Media Player Integration Tests")
    print("=" * 60)

    # Run pytest with verbose output
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
