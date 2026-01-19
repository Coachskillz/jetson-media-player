"""
End-to-end tests for CMS importing assets from Thea Content Catalog with hash verification.

This test module verifies the complete CMS-Thea integration workflow including:
1. CMS fetches asset metadata from Thea (Content Catalog)
2. CMS downloads file from Thea
3. CMS verifies SHA256 hash matches expected checksum
4. CMS saves file to cms/uploads/trusted/ directory
5. CMS creates Content record in database

Key features tested:
- Hash verification ensures file integrity
- Proper handling of approved/published assets
- Rejection of non-approved assets
- Error handling for network failures and hash mismatches

Usage:
    cd cms && pytest tests/test_e2e_thea_checkout.py -v
"""

import hashlib
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock

import pytest
import requests

from cms.models import db, Content, ContentStatus, Network


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture(scope='function')
def test_file_content():
    """
    Create test file content with known hash for verification tests.

    Returns:
        Tuple of (content_bytes, sha256_hash_string)
    """
    content = b'Test video content for E2E Thea checkout testing - ' + os.urandom(1024)
    checksum = hashlib.sha256(content).hexdigest()
    return content, checksum


@pytest.fixture(scope='function')
def thea_approved_asset_data(test_file_content):
    """
    Create mock Thea approved asset metadata.

    Args:
        test_file_content: Tuple of (content_bytes, checksum)

    Returns:
        Dict representing Thea asset response
    """
    _, checksum = test_file_content
    return {
        'id': 1,
        'uuid': 'thea-asset-uuid-12345',
        'title': 'E2E Test Video Asset',
        'description': 'Test asset for CMS import verification',
        'filename': 'e2e_test_video.mp4',
        'file_path': '/uploads/e2e_test_video.mp4',
        'file_size': 1024 + 50,  # matches test_file_content length
        'duration': 60.5,
        'resolution': '1920x1080',
        'format': 'mp4',
        'checksum': checksum,
        'status': 'approved',
        'organization_id': 1,
        'organization_name': 'Test Brand',
        'category': 'promotional',
        'tags': 'e2e,thea,test',
        'created_at': '2026-01-15T10:00:00Z',
        'reviewed_at': '2026-01-16T10:00:00Z',
        'reviewed_by': 2
    }


@pytest.fixture(scope='function')
def thea_published_asset_data(test_file_content):
    """
    Create mock Thea published asset metadata.

    Args:
        test_file_content: Tuple of (content_bytes, checksum)

    Returns:
        Dict representing Thea published asset response
    """
    _, checksum = test_file_content
    return {
        'id': 2,
        'uuid': 'thea-published-uuid-67890',
        'title': 'Published Marketing Video',
        'description': 'Published asset for CMS import',
        'filename': 'marketing_video.mp4',
        'file_path': '/uploads/marketing_video.mp4',
        'file_size': 1024 + 50,
        'duration': 45.0,
        'resolution': '3840x2160',
        'format': 'mp4',
        'checksum': checksum,
        'status': 'published',
        'organization_id': 1,
        'organization_name': 'Test Brand',
        'category': 'marketing',
        'tags': 'marketing,video',
        'created_at': '2026-01-10T10:00:00Z',
        'reviewed_at': '2026-01-11T10:00:00Z',
        'reviewed_by': 2
    }


@pytest.fixture(scope='function')
def thea_draft_asset_data():
    """
    Create mock Thea DRAFT asset metadata (should not be checkable).

    Returns:
        Dict representing Thea draft asset response
    """
    return {
        'id': 3,
        'uuid': 'thea-draft-uuid-11111',
        'title': 'Draft Asset',
        'description': 'Draft asset that should not be importable',
        'filename': 'draft_video.mp4',
        'file_path': '/uploads/draft_video.mp4',
        'file_size': 5000,
        'duration': 30.0,
        'resolution': '1280x720',
        'format': 'mp4',
        'checksum': 'dummychecksum',
        'status': 'draft',
        'organization_id': 1,
        'category': 'draft',
        'created_at': '2026-01-17T10:00:00Z'
    }


@pytest.fixture(scope='function')
def trusted_uploads_path(app):
    """
    Get the trusted uploads path and ensure it exists.

    Args:
        app: Flask application fixture

    Returns:
        Path object for trusted uploads directory
    """
    uploads_path = app.config.get('UPLOADS_PATH')
    trusted_path = Path(uploads_path) / 'trusted'
    trusted_path.mkdir(parents=True, exist_ok=True)
    return trusted_path


# =============================================================================
# E2E Test: CMS Checkout from Thea with Hash Verification
# =============================================================================

class TestCMSTheaCheckoutE2E:
    """
    End-to-end test suite for CMS importing assets from Thea Content Catalog.

    Tests the full checkout workflow:
    1. Fetch asset metadata from Thea
    2. Validate asset status (approved/published)
    3. Download file from Thea
    4. Verify SHA256 hash matches
    5. Save to trusted uploads directory
    6. Create Content record in CMS database
    """

    @patch('cms.routes.content.requests.get')
    def test_e2e_checkout_approved_asset_with_hash_verification(
        self,
        mock_requests_get,
        client,
        app,
        db_session,
        sample_network,
        test_file_content,
        thea_approved_asset_data,
        trusted_uploads_path
    ):
        """
        E2E test: Complete checkout flow for an approved asset with hash verification.

        Steps:
        1. Mock Thea asset metadata endpoint
        2. Mock Thea download endpoint
        3. Call CMS /api/v1/thea/checkout/<id> endpoint
        4. Verify file saved to cms/uploads/trusted/
        5. Verify SHA256 hash matches expected checksum
        6. Verify Content record created in database
        """
        file_content, expected_checksum = test_file_content
        asset_uuid = thea_approved_asset_data['uuid']

        # Configure mock responses
        def mock_get_side_effect(url, *args, **kwargs):
            mock_response = MagicMock()

            if '/api/v1/assets/' in url and '/download' in url:
                # Download endpoint - return file content
                mock_response.status_code = 200
                mock_response.iter_content = lambda chunk_size: [file_content]
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
            elif '/api/v1/assets/' in url:
                # Asset metadata endpoint
                mock_response.status_code = 200
                mock_response.json.return_value = thea_approved_asset_data
            else:
                mock_response.status_code = 404
                mock_response.json.return_value = {'error': 'Not found'}

            return mock_response

        mock_requests_get.side_effect = mock_get_side_effect

        # Call CMS checkout endpoint
        response = client.post(
            f'/api/v1/thea/checkout/{asset_uuid}',
            json={'network_id': sample_network.id}
        )

        # Verify response
        assert response.status_code == 201, \
            f"Checkout failed: {response.get_json()}"

        checkout_data = response.get_json()

        # Verify response structure
        assert checkout_data['message'] == 'Asset checked out and imported successfully'
        assert checkout_data['source_asset_uuid'] == asset_uuid
        assert checkout_data['hash_verified'] is True
        assert checkout_data['hash'] == f'sha256:{expected_checksum}'

        # Verify content record created
        assert 'content' in checkout_data
        content_data = checkout_data['content']
        assert content_data['original_name'] == 'E2E Test Video Asset'
        assert content_data['status'] == ContentStatus.APPROVED.value
        assert content_data['network_id'] == sample_network.id

        # Verify file saved to trusted uploads
        content_id = content_data['id']
        content_record = db_session.get(Content, content_id)
        assert content_record is not None

        saved_file_path = trusted_uploads_path / content_record.filename
        assert saved_file_path.exists(), \
            f"File not saved to trusted uploads: {saved_file_path}"

        # Verify file content hash matches
        with open(saved_file_path, 'rb') as f:
            saved_content = f.read()
        calculated_hash = hashlib.sha256(saved_content).hexdigest()
        assert calculated_hash == expected_checksum, \
            f"Hash mismatch: expected {expected_checksum}, got {calculated_hash}"

        # Clean up
        saved_file_path.unlink()

    @patch('cms.routes.content.requests.get')
    def test_e2e_checkout_published_asset_succeeds(
        self,
        mock_requests_get,
        client,
        app,
        db_session,
        sample_network,
        test_file_content,
        thea_published_asset_data,
        trusted_uploads_path
    ):
        """
        E2E test: Published assets can be checked out successfully.
        """
        file_content, expected_checksum = test_file_content
        asset_uuid = thea_published_asset_data['uuid']

        def mock_get_side_effect(url, *args, **kwargs):
            mock_response = MagicMock()

            if '/download' in url:
                mock_response.status_code = 200
                mock_response.iter_content = lambda chunk_size: [file_content]
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
            elif '/api/v1/assets/' in url:
                mock_response.status_code = 200
                mock_response.json.return_value = thea_published_asset_data
            else:
                mock_response.status_code = 404

            return mock_response

        mock_requests_get.side_effect = mock_get_side_effect

        response = client.post(
            f'/api/v1/thea/checkout/{asset_uuid}',
            json={'network_id': sample_network.id}
        )

        assert response.status_code == 201
        checkout_data = response.get_json()
        assert checkout_data['hash_verified'] is True
        assert checkout_data['content']['original_name'] == 'Published Marketing Video'

        # Clean up saved file
        content_id = checkout_data['content']['id']
        content_record = db_session.get(Content, content_id)
        saved_file_path = trusted_uploads_path / content_record.filename
        if saved_file_path.exists():
            saved_file_path.unlink()

    @patch('cms.routes.content.requests.get')
    def test_e2e_checkout_draft_asset_rejected(
        self,
        mock_requests_get,
        client,
        app,
        thea_draft_asset_data
    ):
        """
        E2E test: DRAFT assets cannot be checked out.
        """
        asset_uuid = thea_draft_asset_data['uuid']

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = thea_draft_asset_data
        mock_requests_get.return_value = mock_response

        response = client.post(f'/api/v1/thea/checkout/{asset_uuid}')

        assert response.status_code == 400
        error_data = response.get_json()
        assert 'draft' in error_data['error'].lower() or 'approved' in error_data['error'].lower()


class TestCMSTheaCheckoutHashVerification:
    """
    Test suite for hash verification during CMS-Thea checkout.
    """

    @patch('cms.routes.content.requests.get')
    def test_hash_verification_fails_on_mismatch(
        self,
        mock_requests_get,
        client,
        app,
        db_session,
        sample_network,
        thea_approved_asset_data,
        trusted_uploads_path
    ):
        """
        E2E test: Checkout fails when downloaded file hash doesn't match expected.
        """
        # Set expected checksum in asset data
        expected_checksum = 'expected_hash_that_wont_match_12345'
        thea_approved_asset_data['checksum'] = expected_checksum

        # Create different file content that won't match
        wrong_content = b'This content has a different hash'
        asset_uuid = thea_approved_asset_data['uuid']

        def mock_get_side_effect(url, *args, **kwargs):
            mock_response = MagicMock()

            if '/download' in url:
                mock_response.status_code = 200
                mock_response.iter_content = lambda chunk_size: [wrong_content]
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
            elif '/api/v1/assets/' in url:
                mock_response.status_code = 200
                mock_response.json.return_value = thea_approved_asset_data
            else:
                mock_response.status_code = 404

            return mock_response

        mock_requests_get.side_effect = mock_get_side_effect

        response = client.post(
            f'/api/v1/thea/checkout/{asset_uuid}',
            json={'network_id': sample_network.id}
        )

        # Should fail with hash verification error
        assert response.status_code == 400, \
            f"Expected 400 for hash mismatch, got {response.status_code}"

        error_data = response.get_json()
        assert 'hash' in error_data['error'].lower()

        # Verify file was NOT saved (cleaned up after failure)
        # Check no new files in trusted path with recent creation time
        # (This is harder to verify precisely, so we verify by checking
        # that no Content record was created)
        content_count = Content.query.count()
        # Initial count should be from fixtures only
        assert content_count == 0 or all(
            c.original_name != thea_approved_asset_data['title']
            for c in Content.query.all()
        )

    @patch('cms.routes.content.requests.get')
    def test_hash_with_sha256_prefix_handled_correctly(
        self,
        mock_requests_get,
        client,
        app,
        db_session,
        sample_network,
        test_file_content,
        thea_approved_asset_data,
        trusted_uploads_path
    ):
        """
        E2E test: Checksum with sha256: prefix is handled correctly.
        """
        file_content, expected_checksum = test_file_content

        # Set checksum with sha256: prefix
        thea_approved_asset_data['checksum'] = f'sha256:{expected_checksum}'
        asset_uuid = thea_approved_asset_data['uuid']

        def mock_get_side_effect(url, *args, **kwargs):
            mock_response = MagicMock()

            if '/download' in url:
                mock_response.status_code = 200
                mock_response.iter_content = lambda chunk_size: [file_content]
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
            elif '/api/v1/assets/' in url:
                mock_response.status_code = 200
                mock_response.json.return_value = thea_approved_asset_data
            else:
                mock_response.status_code = 404

            return mock_response

        mock_requests_get.side_effect = mock_get_side_effect

        response = client.post(
            f'/api/v1/thea/checkout/{asset_uuid}',
            json={'network_id': sample_network.id}
        )

        assert response.status_code == 201
        checkout_data = response.get_json()
        assert checkout_data['hash_verified'] is True

        # Clean up
        content_id = checkout_data['content']['id']
        content_record = db_session.get(Content, content_id)
        saved_file_path = trusted_uploads_path / content_record.filename
        if saved_file_path.exists():
            saved_file_path.unlink()


class TestCMSTheaCheckoutErrorHandling:
    """
    Test suite for error handling during CMS-Thea checkout.
    """

    @patch('cms.routes.content.requests.get')
    def test_checkout_asset_not_found_returns_404(
        self,
        mock_requests_get,
        client,
        app
    ):
        """
        E2E test: Checkout returns 404 when asset doesn't exist in Thea.
        """
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {'error': 'Asset not found'}
        mock_requests_get.return_value = mock_response

        response = client.post('/api/v1/thea/checkout/non-existent-uuid')

        assert response.status_code == 404
        error_data = response.get_json()
        assert 'not found' in error_data['error'].lower()

    @patch('cms.routes.content.requests.get')
    def test_checkout_thea_unavailable_returns_503(
        self,
        mock_requests_get,
        client,
        app
    ):
        """
        E2E test: Checkout returns 503 when Thea service is unavailable.
        """
        mock_requests_get.side_effect = requests.exceptions.ConnectionError(
            "Cannot connect to Content Catalog"
        )

        response = client.post('/api/v1/thea/checkout/some-uuid')

        assert response.status_code == 503
        error_data = response.get_json()
        assert 'unavailable' in error_data['error'].lower()

    @patch('cms.routes.content.requests.get')
    def test_checkout_timeout_returns_503(
        self,
        mock_requests_get,
        client,
        app
    ):
        """
        E2E test: Checkout returns 503 when Thea request times out.
        """
        mock_requests_get.side_effect = requests.exceptions.Timeout(
            "Request timed out"
        )

        response = client.post('/api/v1/thea/checkout/some-uuid')

        assert response.status_code == 503
        error_data = response.get_json()
        assert 'unavailable' in error_data['error'].lower() or 'timed out' in error_data['message'].lower()

    @patch('cms.routes.content.requests.get')
    def test_checkout_invalid_network_id_returns_400(
        self,
        mock_requests_get,
        client,
        app,
        thea_approved_asset_data
    ):
        """
        E2E test: Checkout returns 400 when network_id is invalid.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = thea_approved_asset_data
        mock_requests_get.return_value = mock_response

        response = client.post(
            f'/api/v1/thea/checkout/{thea_approved_asset_data["uuid"]}',
            json={'network_id': 'non-existent-network-id'}
        )

        assert response.status_code == 400
        error_data = response.get_json()
        assert 'network' in error_data['error'].lower()


class TestCMSTheaCheckoutFileStorage:
    """
    Test suite for verifying file storage during checkout.
    """

    @patch('cms.routes.content.requests.get')
    def test_file_saved_to_trusted_directory(
        self,
        mock_requests_get,
        client,
        app,
        db_session,
        sample_network,
        test_file_content,
        thea_approved_asset_data,
        trusted_uploads_path
    ):
        """
        E2E test: Downloaded file is saved to cms/uploads/trusted/ directory.
        """
        file_content, expected_checksum = test_file_content
        asset_uuid = thea_approved_asset_data['uuid']

        def mock_get_side_effect(url, *args, **kwargs):
            mock_response = MagicMock()

            if '/download' in url:
                mock_response.status_code = 200
                mock_response.iter_content = lambda chunk_size: [file_content]
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
            elif '/api/v1/assets/' in url:
                mock_response.status_code = 200
                mock_response.json.return_value = thea_approved_asset_data
            else:
                mock_response.status_code = 404

            return mock_response

        mock_requests_get.side_effect = mock_get_side_effect

        response = client.post(
            f'/api/v1/thea/checkout/{asset_uuid}',
            json={'network_id': sample_network.id}
        )

        assert response.status_code == 201

        # Verify file location
        content_id = response.get_json()['content']['id']
        content_record = db_session.get(Content, content_id)

        saved_file_path = trusted_uploads_path / content_record.filename
        assert saved_file_path.exists()
        assert saved_file_path.parent.name == 'trusted'

        # Clean up
        saved_file_path.unlink()

    @patch('cms.routes.content.requests.get')
    def test_content_record_auto_approved(
        self,
        mock_requests_get,
        client,
        app,
        db_session,
        sample_network,
        test_file_content,
        thea_approved_asset_data,
        trusted_uploads_path
    ):
        """
        E2E test: Imported content is auto-approved (trusted source).
        """
        file_content, _ = test_file_content
        asset_uuid = thea_approved_asset_data['uuid']

        def mock_get_side_effect(url, *args, **kwargs):
            mock_response = MagicMock()

            if '/download' in url:
                mock_response.status_code = 200
                mock_response.iter_content = lambda chunk_size: [file_content]
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
            elif '/api/v1/assets/' in url:
                mock_response.status_code = 200
                mock_response.json.return_value = thea_approved_asset_data
            else:
                mock_response.status_code = 404

            return mock_response

        mock_requests_get.side_effect = mock_get_side_effect

        response = client.post(
            f'/api/v1/thea/checkout/{asset_uuid}',
            json={'network_id': sample_network.id}
        )

        assert response.status_code == 201

        content_id = response.get_json()['content']['id']
        content_record = db_session.get(Content, content_id)

        # Verify auto-approved status
        assert content_record.status == ContentStatus.APPROVED.value

        # Clean up
        saved_file_path = trusted_uploads_path / content_record.filename
        if saved_file_path.exists():
            saved_file_path.unlink()

    @patch('cms.routes.content.requests.get')
    def test_metadata_parsed_correctly_from_resolution(
        self,
        mock_requests_get,
        client,
        app,
        db_session,
        sample_network,
        test_file_content,
        thea_approved_asset_data,
        trusted_uploads_path
    ):
        """
        E2E test: Resolution string (e.g., '1920x1080') is parsed into width/height.
        """
        file_content, _ = test_file_content
        asset_uuid = thea_approved_asset_data['uuid']

        def mock_get_side_effect(url, *args, **kwargs):
            mock_response = MagicMock()

            if '/download' in url:
                mock_response.status_code = 200
                mock_response.iter_content = lambda chunk_size: [file_content]
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
            elif '/api/v1/assets/' in url:
                mock_response.status_code = 200
                mock_response.json.return_value = thea_approved_asset_data
            else:
                mock_response.status_code = 404

            return mock_response

        mock_requests_get.side_effect = mock_get_side_effect

        response = client.post(
            f'/api/v1/thea/checkout/{asset_uuid}',
            json={'network_id': sample_network.id}
        )

        assert response.status_code == 201

        content_id = response.get_json()['content']['id']
        content_record = db_session.get(Content, content_id)

        # Verify dimensions parsed from '1920x1080' resolution
        assert content_record.width == 1920
        assert content_record.height == 1080

        # Clean up
        saved_file_path = trusted_uploads_path / content_record.filename
        if saved_file_path.exists():
            saved_file_path.unlink()


class TestCMSTheaApprovedAssetsEndpoint:
    """
    Test suite for the approved-assets proxy endpoint.
    """

    @patch('cms.routes.content.requests.get')
    def test_list_approved_assets_success(
        self,
        mock_requests_get,
        client,
        app
    ):
        """
        E2E test: /api/v1/thea/approved-assets proxies to Thea correctly.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'assets': [
                {
                    'uuid': 'asset-1',
                    'title': 'Test Asset 1',
                    'status': 'approved'
                },
                {
                    'uuid': 'asset-2',
                    'title': 'Test Asset 2',
                    'status': 'published'
                }
            ],
            'count': 2,
            'total': 2,
            'page': 1,
            'pages': 1
        }
        mock_requests_get.return_value = mock_response

        response = client.get('/api/v1/thea/approved-assets')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 2
        assert len(data['assets']) == 2

    @patch('cms.routes.content.requests.get')
    def test_list_approved_assets_with_filters(
        self,
        mock_requests_get,
        client,
        app
    ):
        """
        E2E test: Filters are passed through to Thea.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'assets': [{'uuid': 'filtered-asset', 'status': 'approved'}],
            'count': 1,
            'total': 1,
            'page': 1,
            'pages': 1
        }
        mock_requests_get.return_value = mock_response

        response = client.get(
            '/api/v1/thea/approved-assets?organization_id=1&category=promo&format=mp4'
        )

        assert response.status_code == 200

        # Verify filters were passed in the request
        call_args = mock_requests_get.call_args
        params = call_args.kwargs.get('params', {})
        assert params.get('organization_id') == '1'
        assert params.get('category') == 'promo'
        assert params.get('format') == 'mp4'

    @patch('cms.routes.content.requests.get')
    def test_list_approved_assets_thea_unavailable(
        self,
        mock_requests_get,
        client,
        app
    ):
        """
        E2E test: Returns 503 when Thea is unavailable.
        """
        mock_requests_get.side_effect = requests.exceptions.ConnectionError()

        response = client.get('/api/v1/thea/approved-assets')

        assert response.status_code == 503
        error_data = response.get_json()
        assert 'unavailable' in error_data['error'].lower()
