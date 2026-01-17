"""
Integration tests for CMS Playlist API endpoints.

Tests all playlist API routes:
- POST /api/v1/playlists - Create playlist
- GET /api/v1/playlists - List all playlists
- GET /api/v1/playlists/<id> - Get playlist details
- PUT /api/v1/playlists/<id> - Update playlist
- DELETE /api/v1/playlists/<id> - Delete playlist
- POST /api/v1/playlists/<id>/items - Add item to playlist
- DELETE /api/v1/playlists/<id>/items/<item_id> - Remove item from playlist
- PUT /api/v1/playlists/<id>/items/reorder - Reorder playlist items
- GET /api/v1/playlists/<id>/preview - Get playlist preview with full content details
- GET /api/v1/playlists/approved-content - List approved content for playlist builder

Each test class covers a specific operation with comprehensive
endpoint validation including success cases and error handling.
"""

from datetime import datetime, timezone, timedelta

import pytest

from cms.models import db, Content, Playlist, PlaylistItem, ContentStatus
from cms.models.playlist import LoopMode, Priority, TriggerType


# =============================================================================
# Enum Tests
# =============================================================================

class TestLoopModeEnum:
    """Tests for LoopMode enum."""

    def test_loop_mode_enum_values(self, app):
        """LoopMode enum should have correct values."""
        assert LoopMode.CONTINUOUS.value == 'continuous'
        assert LoopMode.PLAY_ONCE.value == 'play_once'
        assert LoopMode.SCHEDULED.value == 'scheduled'

    def test_loop_mode_enum_members(self, app):
        """LoopMode enum should have exactly three members."""
        members = list(LoopMode)
        assert len(members) == 3
        assert LoopMode.CONTINUOUS in members
        assert LoopMode.PLAY_ONCE in members
        assert LoopMode.SCHEDULED in members

    def test_loop_mode_enum_from_value(self, app):
        """LoopMode enum should be constructible from string value."""
        assert LoopMode('continuous') == LoopMode.CONTINUOUS
        assert LoopMode('play_once') == LoopMode.PLAY_ONCE
        assert LoopMode('scheduled') == LoopMode.SCHEDULED


class TestPriorityEnum:
    """Tests for Priority enum."""

    def test_priority_enum_values(self, app):
        """Priority enum should have correct values."""
        assert Priority.NORMAL.value == 'normal'
        assert Priority.HIGH.value == 'high'
        assert Priority.INTERRUPT.value == 'interrupt'

    def test_priority_enum_members(self, app):
        """Priority enum should have exactly three members."""
        members = list(Priority)
        assert len(members) == 3
        assert Priority.NORMAL in members
        assert Priority.HIGH in members
        assert Priority.INTERRUPT in members

    def test_priority_enum_from_value(self, app):
        """Priority enum should be constructible from string value."""
        assert Priority('normal') == Priority.NORMAL
        assert Priority('high') == Priority.HIGH
        assert Priority('interrupt') == Priority.INTERRUPT


# =============================================================================
# Playlist Model Tests
# =============================================================================

class TestPlaylistModelFields:
    """Tests for Playlist model new fields."""

    def test_playlist_default_loop_mode(self, db_session, sample_network):
        """Playlist should default to continuous loop mode."""
        playlist = Playlist(
            name='Test Playlist',
            network_id=sample_network.id
        )
        db_session.add(playlist)
        db_session.commit()

        assert playlist.loop_mode == LoopMode.CONTINUOUS.value

    def test_playlist_default_priority(self, db_session, sample_network):
        """Playlist should default to normal priority."""
        playlist = Playlist(
            name='Test Playlist',
            network_id=sample_network.id
        )
        db_session.add(playlist)
        db_session.commit()

        assert playlist.priority == Priority.NORMAL.value

    def test_playlist_loop_mode_can_be_set(self, db_session, sample_network):
        """Playlist loop_mode can be set to any valid value."""
        playlist = Playlist(
            name='Test Playlist',
            network_id=sample_network.id,
            loop_mode=LoopMode.PLAY_ONCE.value
        )
        db_session.add(playlist)
        db_session.commit()

        assert playlist.loop_mode == 'play_once'

    def test_playlist_priority_can_be_set(self, db_session, sample_network):
        """Playlist priority can be set to any valid value."""
        playlist = Playlist(
            name='Test Playlist',
            network_id=sample_network.id,
            priority=Priority.INTERRUPT.value
        )
        db_session.add(playlist)
        db_session.commit()

        assert playlist.priority == 'interrupt'

    def test_playlist_start_date_can_be_set(self, db_session, sample_network):
        """Playlist start_date can be set."""
        start = datetime.now(timezone.utc)
        playlist = Playlist(
            name='Test Playlist',
            network_id=sample_network.id,
            start_date=start
        )
        db_session.add(playlist)
        db_session.commit()

        assert playlist.start_date is not None

    def test_playlist_end_date_can_be_set(self, db_session, sample_network):
        """Playlist end_date can be set."""
        end = datetime.now(timezone.utc) + timedelta(days=30)
        playlist = Playlist(
            name='Test Playlist',
            network_id=sample_network.id,
            end_date=end
        )
        db_session.add(playlist)
        db_session.commit()

        assert playlist.end_date is not None

    def test_playlist_dates_nullable(self, db_session, sample_network):
        """Playlist dates should be nullable."""
        playlist = Playlist(
            name='Test Playlist',
            network_id=sample_network.id
        )
        db_session.add(playlist)
        db_session.commit()

        assert playlist.start_date is None
        assert playlist.end_date is None

    def test_playlist_to_dict_includes_new_fields(self, db_session, sample_network):
        """Playlist.to_dict() should include new fields."""
        start = datetime.now(timezone.utc)
        end = start + timedelta(days=30)
        playlist = Playlist(
            name='Test Playlist',
            network_id=sample_network.id,
            loop_mode=LoopMode.SCHEDULED.value,
            priority=Priority.HIGH.value,
            start_date=start,
            end_date=end
        )
        db_session.add(playlist)
        db_session.commit()

        playlist_dict = playlist.to_dict()
        assert 'loop_mode' in playlist_dict
        assert 'priority' in playlist_dict
        assert 'start_date' in playlist_dict
        assert 'end_date' in playlist_dict
        assert playlist_dict['loop_mode'] == 'scheduled'
        assert playlist_dict['priority'] == 'high'
        assert playlist_dict['start_date'] is not None
        assert playlist_dict['end_date'] is not None

    def test_playlist_fields_persist_after_refresh(self, db_session, sample_network):
        """Playlist new fields should persist across database operations."""
        playlist = Playlist(
            name='Test Playlist',
            network_id=sample_network.id,
            loop_mode=LoopMode.PLAY_ONCE.value,
            priority=Priority.INTERRUPT.value
        )
        db_session.add(playlist)
        db_session.commit()
        playlist_id = playlist.id

        # Expire and refresh from database
        db_session.expire(playlist)
        refreshed = db_session.get(Playlist, playlist_id)

        assert refreshed.loop_mode == 'play_once'
        assert refreshed.priority == 'interrupt'


# =============================================================================
# Create Playlist API Tests (POST /api/v1/playlists)
# =============================================================================

class TestPlaylistCreateAPI:
    """Tests for POST /api/v1/playlists endpoint."""

    # -------------------------------------------------------------------------
    # Successful Creation Tests
    # -------------------------------------------------------------------------

    def test_create_playlist_success(self, client, app, sample_network):
        """POST /playlists should create a new playlist."""
        response = client.post(
            '/api/v1/playlists',
            json={
                'name': 'Test Playlist',
                'network_id': sample_network.id
            }
        )

        assert response.status_code == 201
        result = response.get_json()
        assert 'id' in result
        assert result['name'] == 'Test Playlist'
        assert result['network_id'] == sample_network.id

    def test_create_playlist_with_loop_mode(self, client, app, sample_network):
        """POST /playlists should accept loop_mode field."""
        response = client.post(
            '/api/v1/playlists',
            json={
                'name': 'Test Playlist',
                'network_id': sample_network.id,
                'loop_mode': 'play_once'
            }
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['loop_mode'] == 'play_once'

    def test_create_playlist_with_priority(self, client, app, sample_network):
        """POST /playlists should accept priority field."""
        response = client.post(
            '/api/v1/playlists',
            json={
                'name': 'Test Playlist',
                'network_id': sample_network.id,
                'priority': 'high'
            }
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['priority'] == 'high'

    def test_create_playlist_with_interrupt_priority(self, client, app, sample_network):
        """POST /playlists should accept interrupt priority (for NCMEC alerts)."""
        response = client.post(
            '/api/v1/playlists',
            json={
                'name': 'NCMEC Alert Playlist',
                'network_id': sample_network.id,
                'priority': 'interrupt'
            }
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['priority'] == 'interrupt'

    def test_create_playlist_with_dates(self, client, app, sample_network):
        """POST /playlists should accept start_date and end_date fields."""
        start_date = '2024-01-15T10:00:00Z'
        end_date = '2024-12-31T23:59:59Z'

        response = client.post(
            '/api/v1/playlists',
            json={
                'name': 'Scheduled Playlist',
                'network_id': sample_network.id,
                'loop_mode': 'scheduled',
                'start_date': start_date,
                'end_date': end_date
            }
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['start_date'] is not None
        assert result['end_date'] is not None

    def test_create_playlist_defaults(self, client, app, sample_network):
        """POST /playlists should apply correct defaults for new fields."""
        response = client.post(
            '/api/v1/playlists',
            json={
                'name': 'Default Playlist',
                'network_id': sample_network.id
            }
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['loop_mode'] == 'continuous'
        assert result['priority'] == 'normal'
        assert result['start_date'] is None
        assert result['end_date'] is None

    def test_create_playlist_all_fields(self, client, app, sample_network):
        """POST /playlists should accept all new fields together."""
        response = client.post(
            '/api/v1/playlists',
            json={
                'name': 'Full Featured Playlist',
                'description': 'A playlist with all features',
                'network_id': sample_network.id,
                'trigger_type': 'time',
                'loop_mode': 'scheduled',
                'priority': 'high',
                'start_date': '2024-01-01T00:00:00Z',
                'end_date': '2024-12-31T23:59:59Z',
                'is_active': True
            }
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['loop_mode'] == 'scheduled'
        assert result['priority'] == 'high'
        assert result['trigger_type'] == 'time'

    # -------------------------------------------------------------------------
    # Validation Error Tests
    # -------------------------------------------------------------------------

    def test_create_playlist_invalid_loop_mode(self, client, app, sample_network):
        """POST /playlists should reject invalid loop_mode."""
        response = client.post(
            '/api/v1/playlists',
            json={
                'name': 'Test Playlist',
                'network_id': sample_network.id,
                'loop_mode': 'invalid_mode'
            }
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'Invalid loop_mode' in result['error']
        assert 'continuous' in result['error']
        assert 'play_once' in result['error']
        assert 'scheduled' in result['error']

    def test_create_playlist_invalid_priority(self, client, app, sample_network):
        """POST /playlists should reject invalid priority."""
        response = client.post(
            '/api/v1/playlists',
            json={
                'name': 'Test Playlist',
                'network_id': sample_network.id,
                'priority': 'invalid_priority'
            }
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'Invalid priority' in result['error']
        assert 'normal' in result['error']
        assert 'high' in result['error']
        assert 'interrupt' in result['error']

    def test_create_playlist_invalid_date_range(self, client, app, sample_network):
        """POST /playlists should reject when start_date > end_date."""
        response = client.post(
            '/api/v1/playlists',
            json={
                'name': 'Test Playlist',
                'network_id': sample_network.id,
                'start_date': '2024-12-31T00:00:00Z',
                'end_date': '2024-01-01T00:00:00Z'
            }
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'start_date must be before end_date' in result['error']

    def test_create_playlist_missing_name(self, client, app, sample_network):
        """POST /playlists should reject request without name."""
        response = client.post(
            '/api/v1/playlists',
            json={
                'network_id': sample_network.id
            }
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'name is required' in result['error']

    def test_create_playlist_no_body(self, client, app):
        """POST /playlists should reject request without body."""
        response = client.post(
            '/api/v1/playlists',
            content_type='application/json'
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'Request body is required' in result['error']


# =============================================================================
# Update Playlist API Tests (PUT /api/v1/playlists/<id>)
# =============================================================================

class TestPlaylistUpdateAPI:
    """Tests for PUT /api/v1/playlists/<id> endpoint."""

    def test_update_playlist_loop_mode(self, client, app, sample_playlist):
        """PUT /playlists/<id> should update loop_mode."""
        response = client.put(
            f'/api/v1/playlists/{sample_playlist.id}',
            json={'loop_mode': 'play_once'}
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result['loop_mode'] == 'play_once'

    def test_update_playlist_priority(self, client, app, sample_playlist):
        """PUT /playlists/<id> should update priority."""
        response = client.put(
            f'/api/v1/playlists/{sample_playlist.id}',
            json={'priority': 'high'}
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result['priority'] == 'high'

    def test_update_playlist_dates(self, client, app, sample_playlist):
        """PUT /playlists/<id> should update start_date and end_date."""
        response = client.put(
            f'/api/v1/playlists/{sample_playlist.id}',
            json={
                'start_date': '2024-06-01T00:00:00Z',
                'end_date': '2024-12-31T23:59:59Z'
            }
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result['start_date'] is not None
        assert result['end_date'] is not None

    def test_update_playlist_all_new_fields(self, client, app, sample_playlist):
        """PUT /playlists/<id> should update all new fields together."""
        response = client.put(
            f'/api/v1/playlists/{sample_playlist.id}',
            json={
                'loop_mode': 'scheduled',
                'priority': 'interrupt',
                'start_date': '2024-01-01T00:00:00Z',
                'end_date': '2024-12-31T23:59:59Z'
            }
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result['loop_mode'] == 'scheduled'
        assert result['priority'] == 'interrupt'

    def test_update_playlist_clear_dates(self, client, app, db_session, sample_network):
        """PUT /playlists/<id> should allow clearing dates."""
        # Create playlist with dates
        playlist = Playlist(
            name='Dated Playlist',
            network_id=sample_network.id,
            start_date=datetime.now(timezone.utc),
            end_date=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(playlist)
        db_session.commit()

        response = client.put(
            f'/api/v1/playlists/{playlist.id}',
            json={
                'start_date': None,
                'end_date': None
            }
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result['start_date'] is None
        assert result['end_date'] is None

    def test_update_playlist_invalid_loop_mode(self, client, app, sample_playlist):
        """PUT /playlists/<id> should reject invalid loop_mode."""
        response = client.put(
            f'/api/v1/playlists/{sample_playlist.id}',
            json={'loop_mode': 'invalid'}
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'Invalid loop_mode' in result['error']

    def test_update_playlist_invalid_priority(self, client, app, sample_playlist):
        """PUT /playlists/<id> should reject invalid priority."""
        response = client.put(
            f'/api/v1/playlists/{sample_playlist.id}',
            json={'priority': 'invalid'}
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'Invalid priority' in result['error']

    def test_update_playlist_invalid_date_range(self, client, app, sample_playlist):
        """PUT /playlists/<id> should reject when start_date > end_date."""
        response = client.put(
            f'/api/v1/playlists/{sample_playlist.id}',
            json={
                'start_date': '2024-12-31T00:00:00Z',
                'end_date': '2024-01-01T00:00:00Z'
            }
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'start_date must be before end_date' in result['error']

    def test_update_playlist_not_found(self, client, app):
        """PUT /playlists/<id> should return 404 for non-existent playlist."""
        response = client.put(
            '/api/v1/playlists/non-existent-id',
            json={'name': 'Updated'}
        )

        assert response.status_code == 404
        result = response.get_json()
        assert 'Playlist not found' in result['error']


# =============================================================================
# Playlist Preview API Tests (GET /api/v1/playlists/<id>/preview)
# =============================================================================

class TestPlaylistPreviewAPI:
    """Tests for GET /api/v1/playlists/<id>/preview endpoint."""

    def test_preview_empty_playlist(self, client, app, sample_playlist):
        """GET /playlists/<id>/preview should work for empty playlist."""
        response = client.get(f'/api/v1/playlists/{sample_playlist.id}/preview')

        assert response.status_code == 200
        result = response.get_json()
        assert result['id'] == sample_playlist.id
        assert result['name'] == sample_playlist.name
        assert result['items'] == []
        assert result['item_count'] == 0

    def test_preview_playlist_with_items(self, client, app, sample_playlist_with_items):
        """GET /playlists/<id>/preview should return items with content details."""
        response = client.get(f'/api/v1/playlists/{sample_playlist_with_items.id}/preview')

        assert response.status_code == 200
        result = response.get_json()
        assert result['item_count'] == 2
        assert len(result['items']) == 2

        # Check first item has content details
        first_item = result['items'][0]
        assert 'id' in first_item
        assert 'content_id' in first_item
        assert 'position' in first_item
        assert 'content' in first_item
        assert first_item['content'] is not None

    def test_preview_includes_effective_duration(self, client, app, sample_playlist_with_items):
        """GET /playlists/<id>/preview should include effective_duration for each item."""
        response = client.get(f'/api/v1/playlists/{sample_playlist_with_items.id}/preview')

        assert response.status_code == 200
        result = response.get_json()

        for item in result['items']:
            assert 'effective_duration' in item

    def test_preview_includes_total_duration(self, client, app, sample_playlist_with_items):
        """GET /playlists/<id>/preview should include total_duration."""
        response = client.get(f'/api/v1/playlists/{sample_playlist_with_items.id}/preview')

        assert response.status_code == 200
        result = response.get_json()
        assert 'total_duration' in result
        # Total should be video duration (60) + image duration override (10)
        assert result['total_duration'] == 70

    def test_preview_includes_content_type(self, client, app, sample_playlist_with_items):
        """GET /playlists/<id>/preview should include content_type in content."""
        response = client.get(f'/api/v1/playlists/{sample_playlist_with_items.id}/preview')

        assert response.status_code == 200
        result = response.get_json()

        for item in result['items']:
            if item['content']:
                assert 'content_type' in item['content']
                assert item['content']['content_type'] in ['video', 'image', 'audio', 'unknown']

    def test_preview_includes_new_playlist_fields(self, client, app, db_session, sample_network):
        """GET /playlists/<id>/preview should include loop_mode, priority, dates."""
        playlist = Playlist(
            name='Preview Test',
            network_id=sample_network.id,
            loop_mode=LoopMode.SCHEDULED.value,
            priority=Priority.HIGH.value,
            start_date=datetime.now(timezone.utc),
            end_date=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(playlist)
        db_session.commit()

        response = client.get(f'/api/v1/playlists/{playlist.id}/preview')

        assert response.status_code == 200
        result = response.get_json()
        assert result['loop_mode'] == 'scheduled'
        assert result['priority'] == 'high'
        assert result['start_date'] is not None
        assert result['end_date'] is not None

    def test_preview_not_found(self, client, app):
        """GET /playlists/<id>/preview should return 404 for non-existent playlist."""
        response = client.get('/api/v1/playlists/non-existent-id/preview')

        assert response.status_code == 404
        result = response.get_json()
        assert 'Playlist not found' in result['error']

    def test_preview_invalid_id_format(self, client, app):
        """GET /playlists/<id>/preview should reject overly long playlist_id."""
        long_id = 'x' * 65
        response = client.get(f'/api/v1/playlists/{long_id}/preview')

        assert response.status_code == 400
        result = response.get_json()
        assert 'Invalid playlist_id format' in result['error']

    def test_preview_handles_missing_content(self, client, app, db_session, sample_network, sample_content):
        """GET /playlists/<id>/preview should handle deleted content gracefully."""
        # Create playlist with item
        playlist = Playlist(
            name='Test Playlist',
            network_id=sample_network.id
        )
        db_session.add(playlist)
        db_session.commit()

        item = PlaylistItem(
            playlist_id=playlist.id,
            content_id=sample_content.id,
            position=0
        )
        db_session.add(item)
        db_session.commit()

        # Delete the content
        db_session.delete(sample_content)
        db_session.commit()

        response = client.get(f'/api/v1/playlists/{playlist.id}/preview')

        # Should still return 200, with content marked as missing
        # Note: The cascade delete behavior may vary - this tests graceful handling
        assert response.status_code == 200


# =============================================================================
# Approved Content API Tests (GET /api/v1/playlists/approved-content)
# =============================================================================

class TestApprovedContentAPI:
    """Tests for GET /api/v1/playlists/approved-content endpoint."""

    def test_approved_content_empty(self, client, app):
        """GET /approved-content should return empty list when no approved content."""
        response = client.get('/api/v1/playlists/approved-content')

        assert response.status_code == 200
        result = response.get_json()
        assert result['content'] == []
        assert result['count'] == 0

    def test_approved_content_only_returns_approved(self, client, app, db_session, sample_network):
        """GET /approved-content should only return content with status='approved'."""
        # Create content with different statuses
        pending = Content(
            filename='pending.mp4',
            original_name='pending.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.PENDING.value,
            network_id=sample_network.id
        )
        approved = Content(
            filename='approved.mp4',
            original_name='approved.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        rejected = Content(
            filename='rejected.mp4',
            original_name='rejected.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.REJECTED.value,
            network_id=sample_network.id
        )
        db_session.add(pending)
        db_session.add(approved)
        db_session.add(rejected)
        db_session.commit()

        response = client.get('/api/v1/playlists/approved-content')

        assert response.status_code == 200
        result = response.get_json()
        assert result['count'] == 1
        assert result['content'][0]['status'] == 'approved'
        assert result['content'][0]['original_name'] == 'approved.mp4'

    def test_approved_content_filter_by_type_video(self, client, app, db_session, sample_network):
        """GET /approved-content?type=video should filter by video type."""
        video = Content(
            filename='video.mp4',
            original_name='video.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        image = Content(
            filename='image.jpg',
            original_name='image.jpg',
            mime_type='image/jpeg',
            file_size=500,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        db_session.add(video)
        db_session.add(image)
        db_session.commit()

        response = client.get('/api/v1/playlists/approved-content?type=video')

        assert response.status_code == 200
        result = response.get_json()
        assert result['count'] == 1
        assert result['content'][0]['mime_type'].startswith('video/')

    def test_approved_content_filter_by_type_image(self, client, app, db_session, sample_network):
        """GET /approved-content?type=image should filter by image type."""
        video = Content(
            filename='video.mp4',
            original_name='video.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        image = Content(
            filename='image.jpg',
            original_name='image.jpg',
            mime_type='image/jpeg',
            file_size=500,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        db_session.add(video)
        db_session.add(image)
        db_session.commit()

        response = client.get('/api/v1/playlists/approved-content?type=image')

        assert response.status_code == 200
        result = response.get_json()
        assert result['count'] == 1
        assert result['content'][0]['mime_type'].startswith('image/')

    def test_approved_content_search(self, client, app, db_session, sample_network):
        """GET /approved-content?search=X should filter by filename."""
        content1 = Content(
            filename='holiday_video.mp4',
            original_name='Holiday Party Video.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        content2 = Content(
            filename='promo.mp4',
            original_name='Product Promotion.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        db_session.add(content1)
        db_session.add(content2)
        db_session.commit()

        response = client.get('/api/v1/playlists/approved-content?search=holiday')

        assert response.status_code == 200
        result = response.get_json()
        assert result['count'] == 1
        assert 'Holiday' in result['content'][0]['original_name']

    def test_approved_content_filter_by_network(self, client, app, db_session, sample_network):
        """GET /approved-content?network_id=X should filter by network."""
        from cms.models import Network

        other_network = Network(name='Other Network', slug='other-network')
        db_session.add(other_network)
        db_session.commit()

        content1 = Content(
            filename='content1.mp4',
            original_name='content1.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        content2 = Content(
            filename='content2.mp4',
            original_name='content2.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=other_network.id
        )
        db_session.add(content1)
        db_session.add(content2)
        db_session.commit()

        response = client.get(f'/api/v1/playlists/approved-content?network_id={sample_network.id}')

        assert response.status_code == 200
        result = response.get_json()
        assert result['count'] == 1
        assert result['content'][0]['network_id'] == sample_network.id

    def test_approved_content_includes_content_type(self, client, app, db_session, sample_network):
        """GET /approved-content should include content_type field."""
        video = Content(
            filename='video.mp4',
            original_name='video.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        db_session.add(video)
        db_session.commit()

        response = client.get('/api/v1/playlists/approved-content')

        assert response.status_code == 200
        result = response.get_json()
        assert result['count'] == 1
        assert 'content_type' in result['content'][0]
        assert result['content'][0]['content_type'] == 'video'


# =============================================================================
# Playlist List API Tests (GET /api/v1/playlists)
# =============================================================================

class TestPlaylistListAPI:
    """Tests for GET /api/v1/playlists endpoint."""

    def test_list_playlists_empty(self, client, app):
        """GET /playlists should return empty list when no playlists."""
        response = client.get('/api/v1/playlists')

        assert response.status_code == 200
        result = response.get_json()
        assert result['playlists'] == []
        assert result['count'] == 0

    def test_list_playlists_includes_new_fields(self, client, app, db_session, sample_network):
        """GET /playlists should include new fields in response."""
        playlist = Playlist(
            name='Test Playlist',
            network_id=sample_network.id,
            loop_mode=LoopMode.SCHEDULED.value,
            priority=Priority.HIGH.value
        )
        db_session.add(playlist)
        db_session.commit()

        response = client.get('/api/v1/playlists')

        assert response.status_code == 200
        result = response.get_json()
        assert result['count'] == 1
        assert result['playlists'][0]['loop_mode'] == 'scheduled'
        assert result['playlists'][0]['priority'] == 'high'


# =============================================================================
# Playlist Get API Tests (GET /api/v1/playlists/<id>)
# =============================================================================

class TestPlaylistGetAPI:
    """Tests for GET /api/v1/playlists/<id> endpoint."""

    def test_get_playlist_includes_new_fields(self, client, app, db_session, sample_network):
        """GET /playlists/<id> should include new fields."""
        playlist = Playlist(
            name='Test Playlist',
            network_id=sample_network.id,
            loop_mode=LoopMode.PLAY_ONCE.value,
            priority=Priority.INTERRUPT.value,
            start_date=datetime.now(timezone.utc),
            end_date=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(playlist)
        db_session.commit()

        response = client.get(f'/api/v1/playlists/{playlist.id}')

        assert response.status_code == 200
        result = response.get_json()
        assert result['loop_mode'] == 'play_once'
        assert result['priority'] == 'interrupt'
        assert result['start_date'] is not None
        assert result['end_date'] is not None


# =============================================================================
# Playlist Delete API Tests (DELETE /api/v1/playlists/<id>)
# =============================================================================

class TestPlaylistDeleteAPI:
    """Tests for DELETE /api/v1/playlists/<id> endpoint."""

    def test_delete_playlist_success(self, client, app, sample_playlist, db_session):
        """DELETE /playlists/<id> should delete the playlist."""
        playlist_id = sample_playlist.id

        response = client.delete(f'/api/v1/playlists/{playlist_id}')

        assert response.status_code == 200
        result = response.get_json()
        assert result['message'] == 'Playlist deleted successfully'
        assert result['id'] == playlist_id

        # Verify deleted
        deleted = db_session.get(Playlist, playlist_id)
        assert deleted is None

    def test_delete_playlist_not_found(self, client, app):
        """DELETE /playlists/<id> should return 404 for non-existent playlist."""
        response = client.delete('/api/v1/playlists/non-existent-id')

        assert response.status_code == 404


# =============================================================================
# Playlist Item API Tests (POST/DELETE /api/v1/playlists/<id>/items)
# =============================================================================

class TestPlaylistItemAPI:
    """Tests for playlist item endpoints."""

    def test_add_item_with_duration_override(self, client, app, sample_playlist, sample_image_content):
        """POST /playlists/<id>/items should accept duration_override."""
        response = client.post(
            f'/api/v1/playlists/{sample_playlist.id}/items',
            json={
                'content_id': sample_image_content.id,
                'duration_override': 15
            }
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['duration_override'] == 15

    def test_add_item_default_duration_for_image(self, client, app, sample_playlist, sample_image_content):
        """POST /playlists/<id>/items should allow images without duration_override."""
        response = client.post(
            f'/api/v1/playlists/{sample_playlist.id}/items',
            json={
                'content_id': sample_image_content.id
            }
        )

        assert response.status_code == 201
        result = response.get_json()
        # duration_override is optional
        assert 'duration_override' in result

    def test_add_item_position(self, client, app, sample_playlist, sample_content):
        """POST /playlists/<id>/items should accept position."""
        response = client.post(
            f'/api/v1/playlists/{sample_playlist.id}/items',
            json={
                'content_id': sample_content.id,
                'position': 5
            }
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['position'] == 5

    def test_remove_item(self, client, app, sample_playlist_with_items, db_session):
        """DELETE /playlists/<id>/items/<item_id> should remove item."""
        items = sample_playlist_with_items.items.all()
        item_id = items[0].id

        response = client.delete(
            f'/api/v1/playlists/{sample_playlist_with_items.id}/items/{item_id}'
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result['message'] == 'Item removed from playlist'


# =============================================================================
# Playlist Reorder API Tests (PUT /api/v1/playlists/<id>/items/reorder)
# =============================================================================

class TestPlaylistReorderAPI:
    """Tests for PUT /api/v1/playlists/<id>/items/reorder endpoint."""

    def test_reorder_items(self, client, app, sample_playlist_with_items, db_session):
        """PUT /playlists/<id>/items/reorder should reorder items."""
        items = sample_playlist_with_items.items.all()
        # Reverse order
        new_order = [items[1].id, items[0].id]

        response = client.put(
            f'/api/v1/playlists/{sample_playlist_with_items.id}/items/reorder',
            json={'item_ids': new_order}
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result['message'] == 'Playlist items reordered'
        assert len(result['items']) == 2
        assert result['items'][0]['id'] == new_order[0]
        assert result['items'][1]['id'] == new_order[1]

    def test_reorder_items_invalid_item(self, client, app, sample_playlist_with_items):
        """PUT /playlists/<id>/items/reorder should reject invalid item IDs."""
        response = client.put(
            f'/api/v1/playlists/{sample_playlist_with_items.id}/items/reorder',
            json={'item_ids': ['invalid-id-1', 'invalid-id-2']}
        )

        assert response.status_code == 404
        result = response.get_json()
        assert 'not found in playlist' in result['error']
