"""Unit tests for the PlaylistManager module.

Tests playlist item handling, trigger rule matching, position tracking,
gapless playback, and playlist mode switching.
"""

import os
import pytest
import tempfile
from pathlib import Path
from unittest import mock

from src.player.playlist_manager import (
    PlaylistItem,
    PlaylistMode,
    PlaylistManager,
    TriggerRule,
    TriggeredPlaylist,
    get_playlist_manager,
)
from src.player.config import PlayerConfig


# Sample test data
SAMPLE_PLAYLIST_CONFIG = {
    'default_playlist': {
        'id': 'default-001',
        'items': [
            {
                'content_id': 'content-001',
                'filename': 'video1.mp4',
                'duration': 30.0,
                'metadata': {'category': 'promo'}
            },
            {
                'content_id': 'content-002',
                'filename': 'video2.mp4',
                'duration': 45.0,
                'metadata': {'category': 'brand'}
            },
            {
                'content_id': 'content-003',
                'filename': 'video3.mp4',
                'duration': 60.0,
                'metadata': {}
            }
        ]
    },
    'triggered_playlists': [
        {
            'playlist_id': 'demo-young-male',
            'rule': {
                'type': 'demographic',
                'age_min': 18,
                'age_max': 35,
                'gender': 'male'
            },
            'items': [
                {
                    'content_id': 'triggered-001',
                    'filename': 'young_male_ad.mp4',
                    'duration': 15.0,
                    'metadata': {}
                }
            ]
        },
        {
            'playlist_id': 'demo-older-female',
            'rule': {
                'type': 'demographic',
                'age_min': 35,
                'age_max': 65,
                'gender': 'female'
            },
            'items': [
                {
                    'content_id': 'triggered-002',
                    'filename': 'older_female_ad.mp4',
                    'duration': 20.0,
                    'metadata': {}
                }
            ]
        },
        {
            'playlist_id': 'loyalty-member',
            'rule': {
                'type': 'loyalty',
                'member_id': None
            },
            'items': [
                {
                    'content_id': 'loyalty-001',
                    'filename': 'loyalty_welcome.mp4',
                    'duration': 10.0,
                    'metadata': {}
                },
                {
                    'content_id': 'loyalty-002',
                    'filename': 'loyalty_offer.mp4',
                    'duration': 15.0,
                    'metadata': {}
                }
            ]
        }
    ],
    'version': 1,
    'updated_at': '2024-01-15T12:00:00Z'
}


@pytest.fixture
def temp_media_dir():
    """Create a temporary media directory with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some test media files
        for filename in ['video1.mp4', 'video2.mp4', 'video3.mp4',
                         'young_male_ad.mp4', 'older_female_ad.mp4',
                         'loyalty_welcome.mp4', 'loyalty_offer.mp4']:
            filepath = Path(tmpdir) / filename
            filepath.touch()
        yield tmpdir


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory with playlist config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        import json
        # Write playlist.json
        playlist_path = Path(tmpdir) / 'playlist.json'
        with open(playlist_path, 'w') as f:
            json.dump(SAMPLE_PLAYLIST_CONFIG, f)
        yield tmpdir


@pytest.fixture
def config(temp_config_dir):
    """Create a PlayerConfig instance with test configuration."""
    return PlayerConfig(config_dir=temp_config_dir)


@pytest.fixture
def playlist_manager(config, temp_media_dir):
    """Create a PlaylistManager instance for testing."""
    manager = PlaylistManager(config=config, media_dir=temp_media_dir)
    manager.load_from_config()
    return manager


@pytest.fixture
def reset_global_playlist_manager():
    """Reset the global playlist manager instance before and after tests."""
    import src.player.playlist_manager as pm_module
    original = pm_module._global_playlist_manager
    pm_module._global_playlist_manager = None
    yield
    pm_module._global_playlist_manager = original


class TestPlaylistItem:
    """Tests for PlaylistItem dataclass."""

    def test_create_playlist_item(self):
        """Test creating a playlist item."""
        item = PlaylistItem(
            content_id='test-001',
            filename='test.mp4',
            duration=30.0,
            metadata={'category': 'test'}
        )
        assert item.content_id == 'test-001'
        assert item.filename == 'test.mp4'
        assert item.duration == 30.0
        assert item.metadata == {'category': 'test'}

    def test_playlist_item_default_metadata(self):
        """Test playlist item with default empty metadata."""
        item = PlaylistItem(
            content_id='test-001',
            filename='test.mp4',
            duration=30.0
        )
        assert item.metadata == {}

    def test_get_uri(self, temp_media_dir):
        """Test generating file URI."""
        item = PlaylistItem(
            content_id='test-001',
            filename='video1.mp4',
            duration=30.0
        )
        media_dir = Path(temp_media_dir)
        uri = item.get_uri(media_dir)
        assert uri == f"file://{media_dir}/video1.mp4"

    def test_file_exists_true(self, temp_media_dir):
        """Test file_exists returns True for existing file."""
        item = PlaylistItem(
            content_id='test-001',
            filename='video1.mp4',
            duration=30.0
        )
        assert item.file_exists(Path(temp_media_dir)) is True

    def test_file_exists_false(self, temp_media_dir):
        """Test file_exists returns False for missing file."""
        item = PlaylistItem(
            content_id='test-001',
            filename='nonexistent.mp4',
            duration=30.0
        )
        assert item.file_exists(Path(temp_media_dir)) is False


class TestTriggerRule:
    """Tests for TriggerRule matching logic."""

    def test_demographic_rule_matches_exact(self):
        """Test demographic rule matching exact criteria."""
        rule = TriggerRule(
            rule_type='demographic',
            age_min=25,
            age_max=35,
            gender='male'
        )
        trigger_data = {
            'type': 'demographic',
            'age': 30,
            'gender': 'male',
            'confidence': 0.9
        }
        assert rule.matches(trigger_data) is True

    def test_demographic_rule_age_too_young(self):
        """Test demographic rule rejects age below minimum."""
        rule = TriggerRule(
            rule_type='demographic',
            age_min=25,
            age_max=35,
            gender='male'
        )
        trigger_data = {
            'type': 'demographic',
            'age': 20,
            'gender': 'male'
        }
        assert rule.matches(trigger_data) is False

    def test_demographic_rule_age_too_old(self):
        """Test demographic rule rejects age above maximum."""
        rule = TriggerRule(
            rule_type='demographic',
            age_min=25,
            age_max=35,
            gender='male'
        )
        trigger_data = {
            'type': 'demographic',
            'age': 40,
            'gender': 'male'
        }
        assert rule.matches(trigger_data) is False

    def test_demographic_rule_wrong_gender(self):
        """Test demographic rule rejects wrong gender."""
        rule = TriggerRule(
            rule_type='demographic',
            age_min=25,
            age_max=35,
            gender='male'
        )
        trigger_data = {
            'type': 'demographic',
            'age': 30,
            'gender': 'female'
        }
        assert rule.matches(trigger_data) is False

    def test_demographic_rule_any_gender(self):
        """Test demographic rule with gender='any' matches all genders."""
        rule = TriggerRule(
            rule_type='demographic',
            age_min=25,
            age_max=35,
            gender='any'
        )
        assert rule.matches({'type': 'demographic', 'age': 30, 'gender': 'male'}) is True
        assert rule.matches({'type': 'demographic', 'age': 30, 'gender': 'female'}) is True

    def test_demographic_rule_no_age_constraint(self):
        """Test demographic rule without age constraints."""
        rule = TriggerRule(
            rule_type='demographic',
            age_min=None,
            age_max=None,
            gender='male'
        )
        trigger_data = {
            'type': 'demographic',
            'age': 75,
            'gender': 'male'
        }
        assert rule.matches(trigger_data) is True

    def test_demographic_rule_wrong_type(self):
        """Test demographic rule rejects non-demographic triggers."""
        rule = TriggerRule(
            rule_type='demographic',
            age_min=25,
            age_max=35,
            gender='male'
        )
        trigger_data = {
            'type': 'loyalty',
            'member_id': 'member-001'
        }
        assert rule.matches(trigger_data) is False

    def test_loyalty_rule_matches_any_member(self):
        """Test loyalty rule with member_id=None matches any member."""
        rule = TriggerRule(
            rule_type='loyalty',
            member_id=None
        )
        trigger_data = {
            'type': 'loyalty',
            'member_id': 'member-12345'
        }
        assert rule.matches(trigger_data) is True

    def test_loyalty_rule_matches_specific_member(self):
        """Test loyalty rule matching specific member ID."""
        rule = TriggerRule(
            rule_type='loyalty',
            member_id='member-vip-001'
        )
        trigger_data = {
            'type': 'loyalty',
            'member_id': 'member-vip-001'
        }
        assert rule.matches(trigger_data) is True

    def test_loyalty_rule_rejects_wrong_member(self):
        """Test loyalty rule rejects non-matching member ID."""
        rule = TriggerRule(
            rule_type='loyalty',
            member_id='member-vip-001'
        )
        trigger_data = {
            'type': 'loyalty',
            'member_id': 'member-regular-002'
        }
        assert rule.matches(trigger_data) is False

    def test_loyalty_rule_rejects_missing_member_id(self):
        """Test loyalty rule with member_id=None rejects triggers without member_id."""
        rule = TriggerRule(
            rule_type='loyalty',
            member_id=None
        )
        trigger_data = {
            'type': 'loyalty',
            'member_id': None  # No member ID
        }
        assert rule.matches(trigger_data) is False


class TestTriggeredPlaylist:
    """Tests for TriggeredPlaylist class."""

    def test_triggered_playlist_matches_trigger(self):
        """Test triggered playlist matching."""
        rule = TriggerRule(
            rule_type='demographic',
            age_min=25,
            age_max=35,
            gender='male'
        )
        playlist = TriggeredPlaylist(
            playlist_id='demo-001',
            rule=rule,
            items=[]
        )
        trigger_data = {
            'type': 'demographic',
            'age': 30,
            'gender': 'male'
        }
        assert playlist.matches_trigger(trigger_data) is True

    def test_triggered_playlist_no_match(self):
        """Test triggered playlist non-matching."""
        rule = TriggerRule(
            rule_type='demographic',
            age_min=25,
            age_max=35,
            gender='male'
        )
        playlist = TriggeredPlaylist(
            playlist_id='demo-001',
            rule=rule,
            items=[]
        )
        trigger_data = {
            'type': 'demographic',
            'age': 50,
            'gender': 'female'
        }
        assert playlist.matches_trigger(trigger_data) is False


class TestPlaylistManagerInit:
    """Tests for PlaylistManager initialization."""

    def test_init_with_config(self, config, temp_media_dir):
        """Test initialization with config."""
        manager = PlaylistManager(config=config, media_dir=temp_media_dir)
        assert manager._config is config
        assert manager.media_dir == Path(temp_media_dir)

    def test_init_default_mode(self, config, temp_media_dir):
        """Test initialization starts in default mode."""
        manager = PlaylistManager(config=config, media_dir=temp_media_dir)
        assert manager.mode == PlaylistMode.DEFAULT
        assert manager.is_triggered is False

    def test_init_empty_playlists(self, config, temp_media_dir):
        """Test initialization with empty playlists."""
        manager = PlaylistManager(config=config, media_dir=temp_media_dir)
        assert manager.default_playlist_length == 0
        assert manager.current_item is None

    def test_repr(self, playlist_manager):
        """Test string representation."""
        repr_str = repr(playlist_manager)
        assert 'PlaylistManager' in repr_str
        assert 'mode=default' in repr_str


class TestPlaylistManagerLoadFromConfig:
    """Tests for loading playlists from config."""

    def test_load_from_config_success(self, playlist_manager):
        """Test loading playlists from config."""
        assert playlist_manager.default_playlist_length == 3
        assert len(playlist_manager._triggered_playlists) == 3

    def test_load_from_config_items(self, playlist_manager):
        """Test loaded playlist items have correct data."""
        items = playlist_manager._default_items
        assert items[0].content_id == 'content-001'
        assert items[0].filename == 'video1.mp4'
        assert items[0].duration == 30.0

    def test_load_from_config_triggered_rules(self, playlist_manager):
        """Test triggered playlist rules are loaded correctly."""
        triggered = playlist_manager._triggered_playlists[0]
        assert triggered.playlist_id == 'demo-young-male'
        assert triggered.rule.rule_type == 'demographic'
        assert triggered.rule.age_min == 18
        assert triggered.rule.age_max == 35
        assert triggered.rule.gender == 'male'


class TestPlaylistManagerPlayback:
    """Tests for playlist playback functionality."""

    def test_get_first_uri(self, playlist_manager, temp_media_dir):
        """Test getting first URI for initial playback."""
        uri = playlist_manager.get_first_uri()
        assert uri == f"file://{temp_media_dir}/video1.mp4"
        assert playlist_manager.current_filename == 'video1.mp4'

    def test_get_first_uri_empty_playlist(self, config, temp_media_dir):
        """Test get_first_uri with empty playlist returns None."""
        manager = PlaylistManager(config=config, media_dir=temp_media_dir)
        # Don't load config, keep empty
        uri = manager.get_first_uri()
        assert uri is None

    def test_get_next_uri_sequential(self, playlist_manager, temp_media_dir):
        """Test sequential playback through playlist."""
        # Start playback
        uri1 = playlist_manager.get_first_uri()
        assert 'video1.mp4' in uri1

        # Get subsequent URIs
        uri2 = playlist_manager.get_next_uri()
        assert 'video2.mp4' in uri2

        uri3 = playlist_manager.get_next_uri()
        assert 'video3.mp4' in uri3

    def test_get_next_uri_loops(self, playlist_manager, temp_media_dir):
        """Test playlist loops back to beginning."""
        # Play through all items
        playlist_manager.get_first_uri()  # video1
        playlist_manager.get_next_uri()   # video2
        playlist_manager.get_next_uri()   # video3

        # Should loop back
        uri = playlist_manager.get_next_uri()
        assert 'video1.mp4' in uri

    def test_position_tracking(self, playlist_manager):
        """Test position tracking through playlist."""
        playlist_manager.get_first_uri()
        assert playlist_manager.default_position == 0

        playlist_manager.get_next_uri()
        assert playlist_manager.default_position == 1

        playlist_manager.get_next_uri()
        assert playlist_manager.default_position == 2


class TestPlaylistManagerTriggers:
    """Tests for trigger handling."""

    def test_handle_demographic_trigger(self, playlist_manager):
        """Test handling demographic trigger."""
        trigger_data = {
            'type': 'demographic',
            'age': 25,
            'gender': 'male',
            'confidence': 0.95
        }
        result = playlist_manager.handle_trigger(trigger_data)
        assert result is True
        assert playlist_manager.is_triggered is True
        assert playlist_manager.triggered_playlist_id == 'demo-young-male'
        assert playlist_manager.mode == PlaylistMode.TRIGGERED

    def test_handle_loyalty_trigger(self, playlist_manager):
        """Test handling loyalty trigger."""
        trigger_data = {
            'type': 'loyalty',
            'member_id': 'member-12345'
        }
        result = playlist_manager.handle_trigger(trigger_data)
        assert result is True
        assert playlist_manager.is_triggered is True
        assert playlist_manager.triggered_playlist_id == 'loyalty-member'

    def test_handle_trigger_no_match(self, playlist_manager):
        """Test trigger with no matching playlist."""
        trigger_data = {
            'type': 'demographic',
            'age': 80,
            'gender': 'male'
        }
        result = playlist_manager.handle_trigger(trigger_data)
        assert result is False
        assert playlist_manager.is_triggered is False
        assert playlist_manager.mode == PlaylistMode.DEFAULT

    def test_handle_ncmec_alert_ignored(self, playlist_manager):
        """Test NCMEC alerts are logged but don't change playlist."""
        trigger_data = {
            'type': 'ncmec_alert',
            'case_id': 'case-001',
            'alert_data': {}
        }
        result = playlist_manager.handle_trigger(trigger_data)
        assert result is False
        assert playlist_manager.is_triggered is False

    def test_triggered_playlist_playback(self, playlist_manager, temp_media_dir):
        """Test playback during triggered playlist."""
        # Start default playback
        playlist_manager.get_first_uri()

        # Trigger a playlist
        playlist_manager.handle_trigger({
            'type': 'loyalty',
            'member_id': 'member-001'
        })

        # Next URI should be from triggered playlist
        uri = playlist_manager.get_next_uri()
        assert 'loyalty_welcome.mp4' in uri

    def test_return_to_default_after_triggered(self, playlist_manager, temp_media_dir):
        """Test returning to default playlist after triggered playlist completes."""
        # Start default playback
        playlist_manager.get_first_uri()

        # Trigger loyalty playlist (2 items)
        playlist_manager.handle_trigger({
            'type': 'loyalty',
            'member_id': 'member-001'
        })

        # Play through triggered playlist
        uri1 = playlist_manager.get_next_uri()  # loyalty_welcome.mp4
        assert 'loyalty_welcome.mp4' in uri1

        uri2 = playlist_manager.get_next_uri()  # loyalty_offer.mp4
        assert 'loyalty_offer.mp4' in uri2

        # Next should return to default playlist
        uri3 = playlist_manager.get_next_uri()
        assert playlist_manager.mode == PlaylistMode.DEFAULT
        # Should continue where default left off
        assert 'video2.mp4' in uri3 or 'video1.mp4' in uri3


class TestPlaylistManagerCallbacks:
    """Tests for playlist change callbacks."""

    def test_callback_on_trigger_activation(self, config, temp_media_dir):
        """Test callback is called when triggered playlist activates."""
        callback_called = []

        def on_change(manager):
            callback_called.append(manager.mode.value)

        manager = PlaylistManager(
            config=config,
            media_dir=temp_media_dir,
            on_playlist_changed=on_change
        )
        manager.load_from_config()

        manager.handle_trigger({
            'type': 'demographic',
            'age': 25,
            'gender': 'male'
        })

        assert 'triggered' in callback_called

    def test_callback_on_return_to_default(self, config, temp_media_dir):
        """Test callback is called when returning to default playlist."""
        callback_called = []

        def on_change(manager):
            callback_called.append(manager.mode.value)

        manager = PlaylistManager(
            config=config,
            media_dir=temp_media_dir,
            on_playlist_changed=on_change
        )
        manager.load_from_config()

        # Trigger short playlist (demo-young-male has 1 item)
        manager.handle_trigger({
            'type': 'demographic',
            'age': 25,
            'gender': 'male'
        })

        # Play the triggered item
        manager.get_next_uri()
        # Trigger end - should return to default
        manager.get_next_uri()

        assert 'triggered' in callback_called
        assert 'default' in callback_called


class TestPlaylistManagerMissingFiles:
    """Tests for handling missing media files."""

    def test_skip_missing_file(self, config):
        """Test skipping missing files during playback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Only create video2.mp4 and video3.mp4
            (Path(tmpdir) / 'video2.mp4').touch()
            (Path(tmpdir) / 'video3.mp4').touch()

            manager = PlaylistManager(config=config, media_dir=tmpdir)
            manager.load_from_config()

            # First URI should skip video1.mp4 and return video2.mp4
            uri = manager.get_first_uri()
            assert uri is not None
            assert 'video2.mp4' in uri

    def test_all_files_missing_returns_none(self, config):
        """Test returns None when all files are missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # No media files created
            manager = PlaylistManager(config=config, media_dir=tmpdir)
            manager.load_from_config()

            uri = manager.get_first_uri()
            assert uri is None


class TestPlaylistManagerProperties:
    """Tests for playlist manager properties."""

    def test_current_item_property(self, playlist_manager):
        """Test current_item property."""
        assert playlist_manager.current_item is None

        playlist_manager.get_first_uri()
        assert playlist_manager.current_item is not None
        assert playlist_manager.current_item.content_id == 'content-001'

    def test_current_filename_property(self, playlist_manager):
        """Test current_filename property."""
        assert playlist_manager.current_filename is None

        playlist_manager.get_first_uri()
        assert playlist_manager.current_filename == 'video1.mp4'

    def test_triggered_playlist_id_property(self, playlist_manager):
        """Test triggered_playlist_id property."""
        assert playlist_manager.triggered_playlist_id is None

        playlist_manager.handle_trigger({
            'type': 'demographic',
            'age': 25,
            'gender': 'male'
        })
        assert playlist_manager.triggered_playlist_id == 'demo-young-male'


class TestPlaylistManagerInfo:
    """Tests for playlist info reporting."""

    def test_get_playlist_info(self, playlist_manager):
        """Test get_playlist_info returns correct data."""
        playlist_manager.get_first_uri()

        info = playlist_manager.get_playlist_info()
        assert info['mode'] == 'default'
        assert info['default_items'] == 3
        assert info['default_position'] == 0
        assert info['current_filename'] == 'video1.mp4'
        assert info['is_triggered'] is False
        assert info['triggered_playlist_id'] is None
        assert info['triggered_playlists_count'] == 3

    def test_get_playlist_info_triggered_mode(self, playlist_manager):
        """Test playlist info during triggered mode."""
        playlist_manager.handle_trigger({
            'type': 'demographic',
            'age': 25,
            'gender': 'male'
        })

        info = playlist_manager.get_playlist_info()
        assert info['mode'] == 'triggered'
        assert info['is_triggered'] is True
        assert info['triggered_playlist_id'] == 'demo-young-male'


class TestPlaylistManagerManagement:
    """Tests for playlist management functions."""

    def test_set_default_items(self, config, temp_media_dir):
        """Test setting default items directly."""
        manager = PlaylistManager(config=config, media_dir=temp_media_dir)

        items = [
            PlaylistItem('test-001', 'video1.mp4', 30.0),
            PlaylistItem('test-002', 'video2.mp4', 45.0)
        ]
        manager.set_default_items(items)

        assert manager.default_playlist_length == 2

    def test_set_triggered_playlists(self, config, temp_media_dir):
        """Test setting triggered playlists directly."""
        manager = PlaylistManager(config=config, media_dir=temp_media_dir)

        rule = TriggerRule(rule_type='demographic', age_min=20, age_max=30)
        playlist = TriggeredPlaylist(
            playlist_id='test-triggered',
            rule=rule,
            items=[PlaylistItem('test-001', 'test.mp4', 15.0)]
        )
        manager.set_triggered_playlists([playlist])

        assert len(manager._triggered_playlists) == 1

    def test_reset_position(self, playlist_manager):
        """Test resetting playlist position."""
        # Advance position
        playlist_manager.get_first_uri()
        playlist_manager.get_next_uri()
        playlist_manager.get_next_uri()

        # Reset
        playlist_manager.reset_position()

        assert playlist_manager._default_index == 0
        assert playlist_manager._triggered_index == 0
        assert playlist_manager.current_item is None


class TestPlaylistManagerReload:
    """Tests for playlist reloading."""

    def test_reload_updates_playlists(self, playlist_manager, temp_config_dir):
        """Test reload picks up config changes."""
        import json

        # Modify config file
        playlist_path = Path(temp_config_dir) / 'playlist.json'
        with open(playlist_path, 'r') as f:
            config_data = json.load(f)

        # Add a new item
        config_data['default_playlist']['items'].append({
            'content_id': 'content-004',
            'filename': 'video4.mp4',
            'duration': 20.0,
            'metadata': {}
        })

        with open(playlist_path, 'w') as f:
            json.dump(config_data, f)

        # Reload
        result = playlist_manager.reload()
        assert result is True
        assert playlist_manager.default_playlist_length == 4


class TestGlobalPlaylistManager:
    """Tests for global playlist manager instance."""

    def test_get_playlist_manager_creates_instance(
        self, config, temp_media_dir, reset_global_playlist_manager
    ):
        """Test that get_playlist_manager creates a new instance."""
        manager = get_playlist_manager(
            config=config,
            media_dir=temp_media_dir
        )
        assert manager is not None
        assert isinstance(manager, PlaylistManager)

    def test_get_playlist_manager_returns_same_instance(
        self, config, temp_media_dir, reset_global_playlist_manager
    ):
        """Test that get_playlist_manager returns the same instance."""
        manager1 = get_playlist_manager(config=config, media_dir=temp_media_dir)
        manager2 = get_playlist_manager()
        manager3 = get_playlist_manager(media_dir='/different/path')

        assert manager1 is manager2
        assert manager2 is manager3

    def test_global_manager_singleton_pattern(
        self, config, temp_media_dir, reset_global_playlist_manager
    ):
        """Test global manager follows singleton pattern."""
        manager1 = get_playlist_manager(config=config, media_dir=temp_media_dir)
        manager1.load_from_config()
        manager1.get_first_uri()

        manager2 = get_playlist_manager()
        assert manager2.current_filename == 'video1.mp4'


class TestPlaylistModeEnum:
    """Tests for PlaylistMode enum."""

    def test_playlist_mode_values(self):
        """Test PlaylistMode enum values."""
        assert PlaylistMode.DEFAULT.value == 'default'
        assert PlaylistMode.TRIGGERED.value == 'triggered'

    def test_playlist_mode_comparison(self):
        """Test PlaylistMode enum comparison."""
        assert PlaylistMode.DEFAULT != PlaylistMode.TRIGGERED
        assert PlaylistMode.DEFAULT == PlaylistMode.DEFAULT


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_trigger_data(self, playlist_manager):
        """Test handling empty trigger data."""
        result = playlist_manager.handle_trigger({})
        assert result is False

    def test_trigger_missing_type(self, playlist_manager):
        """Test trigger data without type field."""
        result = playlist_manager.handle_trigger({'age': 30, 'gender': 'male'})
        assert result is False

    def test_get_next_uri_without_starting(self, playlist_manager):
        """Test get_next_uri before get_first_uri."""
        uri = playlist_manager.get_next_uri()
        assert uri is not None
        # Should return first item

    def test_multiple_triggers_in_sequence(self, playlist_manager):
        """Test handling multiple triggers."""
        # First trigger
        playlist_manager.handle_trigger({
            'type': 'demographic',
            'age': 25,
            'gender': 'male'
        })
        assert playlist_manager.triggered_playlist_id == 'demo-young-male'

        # Second trigger should switch to new playlist
        playlist_manager.handle_trigger({
            'type': 'loyalty',
            'member_id': 'member-001'
        })
        assert playlist_manager.triggered_playlist_id == 'loyalty-member'

    def test_demographic_trigger_boundary_ages(self, playlist_manager):
        """Test demographic triggers at age boundaries."""
        # Exactly at age_min (18)
        result = playlist_manager.handle_trigger({
            'type': 'demographic',
            'age': 18,
            'gender': 'male'
        })
        assert result is True

        playlist_manager._switch_to_default()

        # Exactly at age_max (35)
        result = playlist_manager.handle_trigger({
            'type': 'demographic',
            'age': 35,
            'gender': 'male'
        })
        assert result is True

    def test_load_from_empty_config(self, temp_media_dir):
        """Test loading from config with empty playlists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import json
            # Write empty playlist.json
            playlist_path = Path(tmpdir) / 'playlist.json'
            with open(playlist_path, 'w') as f:
                json.dump({}, f)

            config = PlayerConfig(config_dir=tmpdir)
            manager = PlaylistManager(config=config, media_dir=temp_media_dir)
            result = manager.load_from_config()

            assert result is True
            assert manager.default_playlist_length == 0
            assert len(manager._triggered_playlists) == 0
