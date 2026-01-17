"""
Integration tests for CMS Content API endpoints.

Tests all content API routes:
- POST /api/v1/content/upload - Upload content file with metadata
- POST /api/v1/content - Alternative upload endpoint
- GET /api/v1/content - List all content
- GET /api/v1/content/<id> - Get content metadata
- GET /api/v1/content/<id>/download - Download content file
- DELETE /api/v1/content/<id> - Delete content

Each test class covers a specific operation with comprehensive
endpoint validation including success cases and error handling.
"""

import io
import os
import tempfile
from pathlib import Path

import pytest

from cms.models import db, Content, Network


# =============================================================================
# Content Upload API Tests (POST /api/v1/content/upload)
# =============================================================================

class TestContentUploadAPI:
    """Tests for POST /api/v1/content/upload endpoint."""

    # -------------------------------------------------------------------------
    # Successful Upload Tests
    # -------------------------------------------------------------------------

    def test_upload_content_success(self, client, app):
        """POST /content/upload should create content from file upload."""
        data = {
            'file': (io.BytesIO(b'test video content'), 'test_video.mp4')
        }
        response = client.post(
            '/api/v1/content/upload',
            data=data,
            content_type='multipart/form-data'
        )

        assert response.status_code == 201
        result = response.get_json()
        assert 'id' in result
        assert result['original_name'] == 'test_video.mp4'
        assert result['mime_type'] == 'video/mp4'
        assert result['file_size'] > 0
        assert 'filename' in result
        assert 'created_at' in result

    def test_upload_content_via_post_route(self, client, app):
        """POST /content should also accept file uploads."""
        data = {
            'file': (io.BytesIO(b'test image content'), 'test_image.jpg')
        }
        response = client.post(
            '/api/v1/content',
            data=data,
            content_type='multipart/form-data'
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['original_name'] == 'test_image.jpg'
        assert result['mime_type'] == 'image/jpeg'

    def test_upload_content_with_network_id(self, client, app, sample_network):
        """POST /content/upload should accept optional network_id."""
        data = {
            'file': (io.BytesIO(b'test video content'), 'network_video.mp4'),
            'network_id': sample_network.id
        }
        response = client.post(
            '/api/v1/content/upload',
            data=data,
            content_type='multipart/form-data'
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['network_id'] == sample_network.id

    def test_upload_content_with_dimensions(self, client, app):
        """POST /content/upload should accept optional width and height."""
        data = {
            'file': (io.BytesIO(b'test video content'), 'sized_video.mp4'),
            'width': '1920',
            'height': '1080'
        }
        response = client.post(
            '/api/v1/content/upload',
            data=data,
            content_type='multipart/form-data'
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['width'] == 1920
        assert result['height'] == 1080

    def test_upload_content_with_duration(self, client, app):
        """POST /content/upload should accept optional duration."""
        data = {
            'file': (io.BytesIO(b'test video content'), 'timed_video.mp4'),
            'duration': '120'
        }
        response = client.post(
            '/api/v1/content/upload',
            data=data,
            content_type='multipart/form-data'
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['duration'] == 120

    def test_upload_content_generates_unique_filename(self, client, app):
        """POST /content/upload should generate unique filename for storage."""
        data = {
            'file': (io.BytesIO(b'test content'), 'original.mp4')
        }
        response = client.post(
            '/api/v1/content/upload',
            data=data,
            content_type='multipart/form-data'
        )

        assert response.status_code == 201
        result = response.get_json()
        # Stored filename should be UUID-based, not the original
        assert result['filename'] != 'original.mp4'
        assert result['filename'].endswith('.mp4')
        assert result['original_name'] == 'original.mp4'

    def test_upload_content_image_types(self, client, app):
        """POST /content/upload should handle various image types."""
        image_types = [
            ('test.jpg', 'image/jpeg'),
            ('test.jpeg', 'image/jpeg'),
            ('test.png', 'image/png'),
            ('test.gif', 'image/gif'),
            ('test.webp', 'image/webp'),
        ]

        for filename, expected_mime in image_types:
            data = {
                'file': (io.BytesIO(b'test image content'), filename)
            }
            response = client.post(
                '/api/v1/content/upload',
                data=data,
                content_type='multipart/form-data'
            )

            assert response.status_code == 201, f"Failed for {filename}"
            result = response.get_json()
            assert result['mime_type'] == expected_mime, f"Wrong MIME type for {filename}"

    def test_upload_content_video_types(self, client, app):
        """POST /content/upload should handle various video types."""
        video_types = [
            ('test.mp4', 'video/mp4'),
            ('test.avi', 'video/x-msvideo'),
            ('test.mov', 'video/quicktime'),
            ('test.mkv', 'video/x-matroska'),
            ('test.webm', 'video/webm'),
        ]

        for filename, expected_mime in video_types:
            data = {
                'file': (io.BytesIO(b'test video content'), filename)
            }
            response = client.post(
                '/api/v1/content/upload',
                data=data,
                content_type='multipart/form-data'
            )

            assert response.status_code == 201, f"Failed for {filename}"
            result = response.get_json()
            assert result['mime_type'] == expected_mime, f"Wrong MIME type for {filename}"

    # -------------------------------------------------------------------------
    # Upload Validation Error Tests
    # -------------------------------------------------------------------------

    def test_upload_content_no_file(self, client, app):
        """POST /content/upload should reject request without file."""
        response = client.post(
            '/api/v1/content/upload',
            data={},
            content_type='multipart/form-data'
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'No file provided' in result['error']

    def test_upload_content_empty_filename(self, client, app):
        """POST /content/upload should reject file with empty filename."""
        data = {
            'file': (io.BytesIO(b'test content'), '')
        }
        response = client.post(
            '/api/v1/content/upload',
            data=data,
            content_type='multipart/form-data'
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'No file selected' in result['error']

    def test_upload_content_disallowed_file_type(self, client, app):
        """POST /content/upload should reject disallowed file types."""
        data = {
            'file': (io.BytesIO(b'test content'), 'malware.exe')
        }
        response = client.post(
            '/api/v1/content/upload',
            data=data,
            content_type='multipart/form-data'
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'File type not allowed' in result['error']

    def test_upload_content_invalid_network_id(self, client, app):
        """POST /content/upload should reject invalid network_id."""
        data = {
            'file': (io.BytesIO(b'test content'), 'test.mp4'),
            'network_id': 'non-existent-network-id'
        }
        response = client.post(
            '/api/v1/content/upload',
            data=data,
            content_type='multipart/form-data'
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'not found' in result['error']

    def test_upload_content_invalid_dimensions_ignored(self, client, app):
        """POST /content/upload should handle invalid dimension values gracefully."""
        data = {
            'file': (io.BytesIO(b'test content'), 'test.mp4'),
            'width': 'invalid',
            'height': 'not-a-number'
        }
        response = client.post(
            '/api/v1/content/upload',
            data=data,
            content_type='multipart/form-data'
        )

        # Should succeed, with invalid values set to None
        assert response.status_code == 201
        result = response.get_json()
        assert result['width'] is None
        assert result['height'] is None


# =============================================================================
# Content List API Tests (GET /api/v1/content)
# =============================================================================

class TestContentListAPI:
    """Tests for GET /api/v1/content endpoint."""

    def test_list_content_empty(self, client, app):
        """GET /content should return empty list when no content."""
        response = client.get('/api/v1/content')

        assert response.status_code == 200
        data = response.get_json()
        assert data['content'] == []
        assert data['count'] == 0

    def test_list_content_all(self, client, app, sample_content, sample_image_content):
        """GET /content should return all content items."""
        response = client.get('/api/v1/content')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 2
        content_ids = [c['id'] for c in data['content']]
        assert sample_content.id in content_ids
        assert sample_image_content.id in content_ids

    def test_list_content_filter_by_network(self, client, app, sample_content, sample_network):
        """GET /content?network_id=X should filter by network."""
        response = client.get(f'/api/v1/content?network_id={sample_network.id}')

        assert response.status_code == 200
        data = response.get_json()
        assert all(c['network_id'] == sample_network.id for c in data['content'])

    def test_list_content_filter_by_type_video(self, client, app, sample_content, sample_image_content):
        """GET /content?type=video should return only video content."""
        response = client.get('/api/v1/content?type=video')

        assert response.status_code == 200
        data = response.get_json()
        assert all(c['mime_type'].startswith('video/') for c in data['content'])

    def test_list_content_filter_by_type_image(self, client, app, sample_content, sample_image_content):
        """GET /content?type=image should return only image content."""
        response = client.get('/api/v1/content?type=image')

        assert response.status_code == 200
        data = response.get_json()
        assert all(c['mime_type'].startswith('image/') for c in data['content'])

    def test_list_content_ordered_by_created_at(self, client, app, db_session, sample_network):
        """GET /content should return content ordered by created_at descending."""
        # Create multiple content items
        from cms.tests.conftest import create_test_content

        content1 = create_test_content(
            db_session,
            filename='first.mp4',
            original_name='first.mp4',
            mime_type='video/mp4',
            file_size=1000,
            network_id=sample_network.id
        )
        content2 = create_test_content(
            db_session,
            filename='second.mp4',
            original_name='second.mp4',
            mime_type='video/mp4',
            file_size=2000,
            network_id=sample_network.id
        )

        response = client.get('/api/v1/content')

        assert response.status_code == 200
        data = response.get_json()
        # Most recent should be first (second.mp4)
        assert data['content'][0]['id'] == content2.id


# =============================================================================
# Content Retrieval API Tests (GET /api/v1/content/<id>)
# =============================================================================

class TestContentRetrievalAPI:
    """Tests for GET /api/v1/content/<id> endpoint."""

    def test_get_content_success(self, client, app, sample_content):
        """GET /content/<id> should return content metadata."""
        response = client.get(f'/api/v1/content/{sample_content.id}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == sample_content.id
        assert data['filename'] == sample_content.filename
        assert data['original_name'] == sample_content.original_name
        assert data['mime_type'] == sample_content.mime_type
        assert data['file_size'] == sample_content.file_size
        assert data['width'] == sample_content.width
        assert data['height'] == sample_content.height
        assert data['duration'] == sample_content.duration

    def test_get_content_not_found(self, client, app):
        """GET /content/<id> should return 404 for non-existent content."""
        response = client.get('/api/v1/content/non-existent-content-id')

        assert response.status_code == 404
        data = response.get_json()
        assert 'Content not found' in data['error']

    def test_get_content_invalid_id_format(self, client, app):
        """GET /content/<id> should reject overly long content_id."""
        # ID longer than 64 characters
        long_id = 'x' * 65
        response = client.get(f'/api/v1/content/{long_id}')

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid content_id format' in data['error']


# =============================================================================
# Content Download API Tests (GET /api/v1/content/<id>/download)
# =============================================================================

class TestContentDownloadAPI:
    """Tests for GET /api/v1/content/<id>/download endpoint."""

    def test_download_content_success(self, client, app, db_session, sample_network):
        """GET /content/<id>/download should stream the file."""
        # Create content with an actual file
        uploads_path = app.config.get('UPLOADS_PATH')

        # Create a test file
        test_filename = 'test-download-file.mp4'
        test_content = b'test file content for download'
        file_path = Path(uploads_path) / test_filename
        file_path.write_bytes(test_content)

        # Create content record
        content = Content(
            filename=test_filename,
            original_name='download_test.mp4',
            mime_type='video/mp4',
            file_size=len(test_content),
            network_id=sample_network.id
        )
        db_session.add(content)
        db_session.commit()

        response = client.get(f'/api/v1/content/{content.id}/download')

        assert response.status_code == 200
        assert response.data == test_content
        assert response.content_type == 'video/mp4'
        # Check attachment header
        assert 'download_test.mp4' in response.headers.get('Content-Disposition', '')

    def test_download_content_not_found(self, client, app):
        """GET /content/<id>/download should return 404 for non-existent content."""
        response = client.get('/api/v1/content/non-existent-id/download')

        assert response.status_code == 404
        data = response.get_json()
        assert 'Content not found' in data['error']

    def test_download_content_file_missing(self, client, app, sample_content):
        """GET /content/<id>/download should return 404 if file is missing from disk."""
        # sample_content has no actual file on disk
        response = client.get(f'/api/v1/content/{sample_content.id}/download')

        assert response.status_code == 404
        data = response.get_json()
        assert 'file not found' in data['error'].lower()

    def test_download_content_invalid_id_format(self, client, app):
        """GET /content/<id>/download should reject overly long content_id."""
        long_id = 'x' * 65
        response = client.get(f'/api/v1/content/{long_id}/download')

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid content_id format' in data['error']


# =============================================================================
# Content Delete API Tests (DELETE /api/v1/content/<id>)
# =============================================================================

class TestContentDeleteAPI:
    """Tests for DELETE /api/v1/content/<id> endpoint."""

    def test_delete_content_success(self, client, app, db_session, sample_network):
        """DELETE /content/<id> should delete content and file."""
        # Create content with an actual file
        uploads_path = app.config.get('UPLOADS_PATH')

        # Create a test file
        test_filename = 'test-delete-file.mp4'
        test_content = b'test file content to delete'
        file_path = Path(uploads_path) / test_filename
        file_path.write_bytes(test_content)

        # Create content record
        content = Content(
            filename=test_filename,
            original_name='delete_test.mp4',
            mime_type='video/mp4',
            file_size=len(test_content),
            network_id=sample_network.id
        )
        db_session.add(content)
        db_session.commit()
        content_id = content.id

        response = client.delete(f'/api/v1/content/{content_id}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Content deleted successfully'
        assert data['id'] == content_id

        # Verify content is deleted from database
        deleted_content = db_session.get(Content, content_id)
        assert deleted_content is None

        # Verify file is deleted from disk
        assert not file_path.exists()

    def test_delete_content_not_found(self, client, app):
        """DELETE /content/<id> should return 404 for non-existent content."""
        response = client.delete('/api/v1/content/non-existent-id')

        assert response.status_code == 404
        data = response.get_json()
        assert 'Content not found' in data['error']

    def test_delete_content_removes_record_even_if_file_missing(self, client, app, sample_content, db_session):
        """DELETE /content/<id> should delete record even if file doesn't exist."""
        content_id = sample_content.id

        response = client.delete(f'/api/v1/content/{content_id}')

        # Should still succeed (file just wasn't there)
        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Content deleted successfully'

        # Verify content is deleted from database
        deleted_content = db_session.get(Content, content_id)
        assert deleted_content is None

    def test_delete_content_invalid_id_format(self, client, app):
        """DELETE /content/<id> should reject overly long content_id."""
        long_id = 'x' * 65
        response = client.delete(f'/api/v1/content/{long_id}')

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid content_id format' in data['error']


# =============================================================================
# Content Upload and Retrieval Integration Tests
# =============================================================================

class TestContentUploadRetrievalIntegration:
    """Integration tests for upload followed by retrieval operations."""

    def test_upload_then_retrieve_metadata(self, client, app):
        """Uploaded content should be retrievable by ID."""
        # Upload content
        upload_data = {
            'file': (io.BytesIO(b'integration test content'), 'integration.mp4'),
            'width': '1920',
            'height': '1080',
            'duration': '60'
        }
        upload_response = client.post(
            '/api/v1/content/upload',
            data=upload_data,
            content_type='multipart/form-data'
        )
        assert upload_response.status_code == 201
        uploaded = upload_response.get_json()

        # Retrieve by ID
        get_response = client.get(f'/api/v1/content/{uploaded["id"]}')
        assert get_response.status_code == 200
        retrieved = get_response.get_json()

        # Verify data matches
        assert retrieved['id'] == uploaded['id']
        assert retrieved['original_name'] == 'integration.mp4'
        assert retrieved['width'] == 1920
        assert retrieved['height'] == 1080
        assert retrieved['duration'] == 60

    def test_upload_then_list(self, client, app):
        """Uploaded content should appear in list."""
        # Upload content
        upload_data = {
            'file': (io.BytesIO(b'list test content'), 'list_test.mp4')
        }
        upload_response = client.post(
            '/api/v1/content/upload',
            data=upload_data,
            content_type='multipart/form-data'
        )
        assert upload_response.status_code == 201
        uploaded = upload_response.get_json()

        # List all content
        list_response = client.get('/api/v1/content')
        assert list_response.status_code == 200
        content_list = list_response.get_json()

        # Verify uploaded content appears in list
        content_ids = [c['id'] for c in content_list['content']]
        assert uploaded['id'] in content_ids

    def test_upload_then_download(self, client, app):
        """Uploaded content should be downloadable."""
        test_content = b'downloadable content bytes'

        # Upload content
        upload_data = {
            'file': (io.BytesIO(test_content), 'downloadable.mp4')
        }
        upload_response = client.post(
            '/api/v1/content/upload',
            data=upload_data,
            content_type='multipart/form-data'
        )
        assert upload_response.status_code == 201
        uploaded = upload_response.get_json()

        # Download content
        download_response = client.get(f'/api/v1/content/{uploaded["id"]}/download')
        assert download_response.status_code == 200
        assert download_response.data == test_content

    def test_upload_then_delete(self, client, app, db_session):
        """Uploaded content should be deletable."""
        # Upload content
        upload_data = {
            'file': (io.BytesIO(b'deletable content'), 'deletable.mp4')
        }
        upload_response = client.post(
            '/api/v1/content/upload',
            data=upload_data,
            content_type='multipart/form-data'
        )
        assert upload_response.status_code == 201
        uploaded = upload_response.get_json()

        # Delete content
        delete_response = client.delete(f'/api/v1/content/{uploaded["id"]}')
        assert delete_response.status_code == 200

        # Verify content is gone
        get_response = client.get(f'/api/v1/content/{uploaded["id"]}')
        assert get_response.status_code == 404

    def test_full_content_lifecycle(self, client, app, sample_network, db_session):
        """Test complete content lifecycle: upload, read, list, download, delete."""
        test_content = b'complete lifecycle test content'

        # 1. Upload
        upload_data = {
            'file': (io.BytesIO(test_content), 'lifecycle.mp4'),
            'network_id': sample_network.id,
            'width': '1280',
            'height': '720',
            'duration': '30'
        }
        upload_response = client.post(
            '/api/v1/content/upload',
            data=upload_data,
            content_type='multipart/form-data'
        )
        assert upload_response.status_code == 201
        content_id = upload_response.get_json()['id']

        # 2. Read metadata
        get_response = client.get(f'/api/v1/content/{content_id}')
        assert get_response.status_code == 200
        metadata = get_response.get_json()
        assert metadata['network_id'] == sample_network.id
        assert metadata['width'] == 1280

        # 3. List and verify presence
        list_response = client.get(f'/api/v1/content?network_id={sample_network.id}')
        assert list_response.status_code == 200
        content_ids = [c['id'] for c in list_response.get_json()['content']]
        assert content_id in content_ids

        # 4. Download
        download_response = client.get(f'/api/v1/content/{content_id}/download')
        assert download_response.status_code == 200
        assert download_response.data == test_content

        # 5. Delete
        delete_response = client.delete(f'/api/v1/content/{content_id}')
        assert delete_response.status_code == 200

        # 6. Verify gone
        verify_response = client.get(f'/api/v1/content/{content_id}')
        assert verify_response.status_code == 404


# =============================================================================
# Content Status and ContentStatus Enum Tests
# =============================================================================

class TestContentStatusEnum:
    """Tests for ContentStatus enum."""

    def test_status_enum_values(self, app):
        """ContentStatus enum should have correct values."""
        from cms.models import ContentStatus

        assert ContentStatus.PENDING.value == 'pending'
        assert ContentStatus.APPROVED.value == 'approved'
        assert ContentStatus.REJECTED.value == 'rejected'

    def test_status_enum_members(self, app):
        """ContentStatus enum should have exactly three members."""
        from cms.models import ContentStatus

        members = list(ContentStatus)
        assert len(members) == 3
        assert ContentStatus.PENDING in members
        assert ContentStatus.APPROVED in members
        assert ContentStatus.REJECTED in members

    def test_status_enum_from_value(self, app):
        """ContentStatus enum should be constructible from string value."""
        from cms.models import ContentStatus

        assert ContentStatus('pending') == ContentStatus.PENDING
        assert ContentStatus('approved') == ContentStatus.APPROVED
        assert ContentStatus('rejected') == ContentStatus.REJECTED


class TestContentModelStatus:
    """Tests for Content model status field."""

    def test_content_status_default_value(self, db_session, sample_network):
        """Content should default to pending status when created."""
        from cms.models import Content, ContentStatus

        content = Content(
            filename='test_default_status.mp4',
            original_name='test.mp4',
            mime_type='video/mp4',
            file_size=1000,
            network_id=sample_network.id
        )
        db_session.add(content)
        db_session.commit()

        assert content.status == ContentStatus.PENDING.value

    def test_content_status_in_to_dict(self, db_session, sample_network):
        """Content.to_dict() should include status field."""
        from cms.models import Content, ContentStatus

        content = Content(
            filename='test_dict_status.mp4',
            original_name='test.mp4',
            mime_type='video/mp4',
            file_size=1000,
            network_id=sample_network.id
        )
        db_session.add(content)
        db_session.commit()

        content_dict = content.to_dict()
        assert 'status' in content_dict
        assert content_dict['status'] == ContentStatus.PENDING.value

    def test_content_status_can_be_set_approved(self, db_session, sample_network):
        """Content status can be set to approved."""
        from cms.models import Content, ContentStatus

        content = Content(
            filename='test_approved_status.mp4',
            original_name='test.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        db_session.add(content)
        db_session.commit()

        assert content.status == ContentStatus.APPROVED.value
        assert content.to_dict()['status'] == 'approved'

    def test_content_status_can_be_set_rejected(self, db_session, sample_network):
        """Content status can be set to rejected."""
        from cms.models import Content, ContentStatus

        content = Content(
            filename='test_rejected_status.mp4',
            original_name='test.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.REJECTED.value,
            network_id=sample_network.id
        )
        db_session.add(content)
        db_session.commit()

        assert content.status == ContentStatus.REJECTED.value
        assert content.to_dict()['status'] == 'rejected'

    def test_content_status_persists_after_refresh(self, db_session, sample_network):
        """Content status should persist across database operations."""
        from cms.models import Content, ContentStatus

        content = Content(
            filename='test_persist_status.mp4',
            original_name='test.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        db_session.add(content)
        db_session.commit()
        content_id = content.id

        # Expire and refresh from database
        db_session.expire(content)
        refreshed_content = db_session.get(Content, content_id)

        assert refreshed_content.status == ContentStatus.APPROVED.value


class TestContentStatusAPI:
    """Tests for content status API endpoints."""

    # -------------------------------------------------------------------------
    # Status Update Endpoint Tests (PUT /api/v1/content/<id>/status)
    # -------------------------------------------------------------------------

    def test_update_status_to_approved(self, client, app, sample_content):
        """PUT /content/<id>/status should update status to approved."""
        response = client.put(
            f'/api/v1/content/{sample_content.id}/status',
            json={'status': 'approved'}
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result['status'] == 'approved'
        assert result['id'] == sample_content.id

    def test_update_status_to_rejected(self, client, app, sample_content):
        """PUT /content/<id>/status should update status to rejected."""
        response = client.put(
            f'/api/v1/content/{sample_content.id}/status',
            json={'status': 'rejected'}
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result['status'] == 'rejected'

    def test_update_status_to_pending(self, client, app, db_session, sample_network):
        """PUT /content/<id>/status should update status back to pending."""
        from cms.models import Content, ContentStatus

        # Create approved content
        content = Content(
            filename='approved_content.mp4',
            original_name='approved.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        db_session.add(content)
        db_session.commit()

        response = client.put(
            f'/api/v1/content/{content.id}/status',
            json={'status': 'pending'}
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result['status'] == 'pending'

    def test_update_status_invalid_value(self, client, app, sample_content):
        """PUT /content/<id>/status should reject invalid status values."""
        response = client.put(
            f'/api/v1/content/{sample_content.id}/status',
            json={'status': 'invalid_status'}
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'Invalid status' in result['error']
        assert 'pending' in result['error']
        assert 'approved' in result['error']
        assert 'rejected' in result['error']

    def test_update_status_missing_status_field(self, client, app, sample_content):
        """PUT /content/<id>/status should reject request without status field."""
        response = client.put(
            f'/api/v1/content/{sample_content.id}/status',
            json={}
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'status is required' in result['error']

    def test_update_status_no_body(self, client, app, sample_content):
        """PUT /content/<id>/status should reject request without body."""
        response = client.put(
            f'/api/v1/content/{sample_content.id}/status',
            content_type='application/json'
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'Request body is required' in result['error']

    def test_update_status_not_found(self, client, app):
        """PUT /content/<id>/status should return 404 for non-existent content."""
        response = client.put(
            '/api/v1/content/non-existent-id/status',
            json={'status': 'approved'}
        )

        assert response.status_code == 404
        result = response.get_json()
        assert 'Content not found' in result['error']

    def test_update_status_invalid_id_format(self, client, app):
        """PUT /content/<id>/status should reject overly long content_id."""
        long_id = 'x' * 65
        response = client.put(
            f'/api/v1/content/{long_id}/status',
            json={'status': 'approved'}
        )

        assert response.status_code == 400
        result = response.get_json()
        assert 'Invalid content_id format' in result['error']

    # -------------------------------------------------------------------------
    # Status Filter Tests (GET /api/v1/content?status=X)
    # -------------------------------------------------------------------------

    def test_list_content_filter_by_status_pending(self, client, app, db_session, sample_network):
        """GET /content?status=pending should filter by pending status."""
        from cms.models import Content, ContentStatus

        # Create content with different statuses
        pending_content = Content(
            filename='pending.mp4',
            original_name='pending.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.PENDING.value,
            network_id=sample_network.id
        )
        approved_content = Content(
            filename='approved.mp4',
            original_name='approved.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        db_session.add(pending_content)
        db_session.add(approved_content)
        db_session.commit()

        response = client.get('/api/v1/content?status=pending')

        assert response.status_code == 200
        data = response.get_json()
        assert all(c['status'] == 'pending' for c in data['content'])

    def test_list_content_filter_by_status_approved(self, client, app, db_session, sample_network):
        """GET /content?status=approved should filter by approved status."""
        from cms.models import Content, ContentStatus

        # Create content with different statuses
        pending_content = Content(
            filename='pending2.mp4',
            original_name='pending.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.PENDING.value,
            network_id=sample_network.id
        )
        approved_content = Content(
            filename='approved2.mp4',
            original_name='approved.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        db_session.add(pending_content)
        db_session.add(approved_content)
        db_session.commit()

        response = client.get('/api/v1/content?status=approved')

        assert response.status_code == 200
        data = response.get_json()
        assert all(c['status'] == 'approved' for c in data['content'])

    def test_list_content_filter_by_status_rejected(self, client, app, db_session, sample_network):
        """GET /content?status=rejected should filter by rejected status."""
        from cms.models import Content, ContentStatus

        # Create content with different statuses
        rejected_content = Content(
            filename='rejected.mp4',
            original_name='rejected.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.REJECTED.value,
            network_id=sample_network.id
        )
        approved_content = Content(
            filename='approved3.mp4',
            original_name='approved.mp4',
            mime_type='video/mp4',
            file_size=1000,
            status=ContentStatus.APPROVED.value,
            network_id=sample_network.id
        )
        db_session.add(rejected_content)
        db_session.add(approved_content)
        db_session.commit()

        response = client.get('/api/v1/content?status=rejected')

        assert response.status_code == 200
        data = response.get_json()
        assert all(c['status'] == 'rejected' for c in data['content'])

    def test_list_content_filter_by_status_invalid(self, client, app):
        """GET /content?status=invalid should return 400 with error."""
        response = client.get('/api/v1/content?status=invalid_status')

        assert response.status_code == 400
        result = response.get_json()
        assert 'Invalid status' in result['error']

    # -------------------------------------------------------------------------
    # Status in Response Tests
    # -------------------------------------------------------------------------

    def test_upload_content_has_default_pending_status(self, client, app):
        """POST /content/upload should create content with pending status."""
        data = {
            'file': (io.BytesIO(b'test content'), 'test_status.mp4')
        }
        response = client.post(
            '/api/v1/content/upload',
            data=data,
            content_type='multipart/form-data'
        )

        assert response.status_code == 201
        result = response.get_json()
        assert result['status'] == 'pending'

    def test_get_content_includes_status(self, client, app, sample_content):
        """GET /content/<id> should include status in response."""
        response = client.get(f'/api/v1/content/{sample_content.id}')

        assert response.status_code == 200
        result = response.get_json()
        assert 'status' in result

    def test_list_content_items_include_status(self, client, app, sample_content):
        """GET /content should include status in each content item."""
        response = client.get('/api/v1/content')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] > 0
        for content in data['content']:
            assert 'status' in content
