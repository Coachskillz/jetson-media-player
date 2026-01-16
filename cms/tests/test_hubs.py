"""
Integration tests for CMS Hubs API endpoints.

Tests all hub API routes:
- POST /api/v1/hubs/register - Hub registration
- GET /api/v1/hubs - List all hubs
- GET /api/v1/hubs/<hub_id> - Get specific hub
- GET /api/v1/hubs/<hub_id>/content-manifest - Get content manifest for hub

Each test class covers a specific operation with comprehensive
endpoint validation including success cases and error handling.
"""

import pytest

from cms.models import db, Hub, Network, Content


# =============================================================================
# Hub Registration API Tests (POST /api/v1/hubs/register)
# =============================================================================

class TestHubRegistrationAPI:
    """Tests for POST /api/v1/hubs/register endpoint."""

    # -------------------------------------------------------------------------
    # Success Cases
    # -------------------------------------------------------------------------

    def test_register_hub_success(self, client, app, sample_network):
        """POST /hubs/register should create a new hub."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'WM',
            'name': 'West Marine Hub',
            'network_id': sample_network.id
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['code'] == 'WM'
        assert data['name'] == 'West Marine Hub'
        assert data['network_id'] == sample_network.id
        assert data['status'] == 'pending'
        assert 'id' in data
        assert 'created_at' in data

    def test_register_hub_with_location(self, client, app, sample_network):
        """POST /hubs/register should accept optional location field."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'HON',
            'name': 'Honolulu Hub',
            'network_id': sample_network.id,
            'location': '123 Beach Blvd, Honolulu, HI'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['code'] == 'HON'
        assert data['name'] == 'Honolulu Hub'

    def test_register_hub_two_letter_code(self, client, app, sample_network):
        """POST /hubs/register should accept 2-letter codes."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'AB',
            'name': 'Two Letter Hub',
            'network_id': sample_network.id
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['code'] == 'AB'

    def test_register_hub_three_letter_code(self, client, app, sample_network):
        """POST /hubs/register should accept 3-letter codes."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'ABC',
            'name': 'Three Letter Hub',
            'network_id': sample_network.id
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['code'] == 'ABC'

    def test_register_hub_four_letter_code(self, client, app, sample_network):
        """POST /hubs/register should accept 4-letter codes."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'ABCD',
            'name': 'Four Letter Hub',
            'network_id': sample_network.id
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['code'] == 'ABCD'

    # -------------------------------------------------------------------------
    # Duplicate Hub Tests
    # -------------------------------------------------------------------------

    def test_register_duplicate_hub_code(self, client, app, sample_hub):
        """POST /hubs/register should reject duplicate hub code."""
        response = client.post('/api/v1/hubs/register', json={
            'code': sample_hub.code,
            'name': 'Different Hub Name',
            'network_id': sample_hub.network_id
        })

        assert response.status_code == 409
        data = response.get_json()
        assert 'already exists' in data['error']

    # -------------------------------------------------------------------------
    # Validation Error Tests
    # -------------------------------------------------------------------------

    def test_register_hub_empty_body(self, client, app):
        """POST /hubs/register should reject empty body."""
        response = client.post('/api/v1/hubs/register',
                               data='',
                               content_type='application/json')

        assert response.status_code == 400
        data = response.get_json()
        assert 'Request body is required' in data['error']

    def test_register_hub_missing_code(self, client, app, sample_network):
        """POST /hubs/register should reject missing code."""
        response = client.post('/api/v1/hubs/register', json={
            'name': 'Test Hub',
            'network_id': sample_network.id
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'code is required' in data['error']

    def test_register_hub_missing_name(self, client, app, sample_network):
        """POST /hubs/register should reject missing name."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'MN',
            'network_id': sample_network.id
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'name is required' in data['error']

    def test_register_hub_missing_network_id(self, client, app):
        """POST /hubs/register should reject missing network_id."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'NN',
            'name': 'No Network Hub'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'network_id is required' in data['error']

    def test_register_hub_invalid_network_id(self, client, app):
        """POST /hubs/register should reject non-existent network_id."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'IN',
            'name': 'Invalid Network Hub',
            'network_id': 'non-existent-network-id'
        })

        assert response.status_code == 404
        data = response.get_json()
        assert 'not found' in data['error']

    def test_register_hub_code_lowercase(self, client, app, sample_network):
        """POST /hubs/register should reject lowercase code."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'wm',
            'name': 'Lowercase Hub',
            'network_id': sample_network.id
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'uppercase letters' in data['error']

    def test_register_hub_code_mixed_case(self, client, app, sample_network):
        """POST /hubs/register should reject mixed case code."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'Wm',
            'name': 'Mixed Case Hub',
            'network_id': sample_network.id
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'uppercase letters' in data['error']

    def test_register_hub_code_with_numbers(self, client, app, sample_network):
        """POST /hubs/register should reject code with numbers."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'W1',
            'name': 'Number Hub',
            'network_id': sample_network.id
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'uppercase letters' in data['error']

    def test_register_hub_code_one_letter(self, client, app, sample_network):
        """POST /hubs/register should reject single letter code."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'W',
            'name': 'Single Letter Hub',
            'network_id': sample_network.id
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'uppercase letters' in data['error']

    def test_register_hub_code_five_letters(self, client, app, sample_network):
        """POST /hubs/register should reject code longer than 4 letters."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'ABCDE',
            'name': 'Five Letter Hub',
            'network_id': sample_network.id
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'uppercase letters' in data['error']

    def test_register_hub_name_too_long(self, client, app, sample_network):
        """POST /hubs/register should reject name > 200 chars."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'LN',
            'name': 'x' * 201,
            'network_id': sample_network.id
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'max 200 characters' in data['error']

    def test_register_hub_location_too_long(self, client, app, sample_network):
        """POST /hubs/register should reject location > 500 chars."""
        response = client.post('/api/v1/hubs/register', json={
            'code': 'LL',
            'name': 'Long Location Hub',
            'network_id': sample_network.id,
            'location': 'x' * 501
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'max 500 characters' in data['error']


# =============================================================================
# Hub List API Tests (GET /api/v1/hubs)
# =============================================================================

class TestHubListAPI:
    """Tests for GET /api/v1/hubs endpoint."""

    def test_list_hubs_empty(self, client, app):
        """GET /hubs should return empty list when no hubs."""
        response = client.get('/api/v1/hubs')

        assert response.status_code == 200
        data = response.get_json()
        assert data['hubs'] == []
        assert data['count'] == 0

    def test_list_hubs_all(self, client, app, db_session, sample_network):
        """GET /hubs should return all hubs."""
        # Create multiple hubs
        hub1 = Hub(code='AA', name='Hub AA', network_id=sample_network.id, status='active')
        hub2 = Hub(code='BB', name='Hub BB', network_id=sample_network.id, status='pending')
        hub3 = Hub(code='CC', name='Hub CC', network_id=sample_network.id, status='active')
        db_session.add_all([hub1, hub2, hub3])
        db_session.commit()

        response = client.get('/api/v1/hubs')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 3

    def test_list_hubs_filter_by_status(self, client, app, db_session, sample_network):
        """GET /hubs?status=X should filter by status."""
        # Create hubs with different statuses
        hub1 = Hub(code='SA', name='Hub SA', network_id=sample_network.id, status='active')
        hub2 = Hub(code='SP', name='Hub SP', network_id=sample_network.id, status='pending')
        hub3 = Hub(code='SI', name='Hub SI', network_id=sample_network.id, status='inactive')
        db_session.add_all([hub1, hub2, hub3])
        db_session.commit()

        response = client.get('/api/v1/hubs?status=active')

        assert response.status_code == 200
        data = response.get_json()
        assert all(h['status'] == 'active' for h in data['hubs'])

    def test_list_hubs_filter_by_network(self, client, app, db_session):
        """GET /hubs?network_id=X should filter by network."""
        # Create two networks
        network1 = Network(name='Network One', slug='network-one')
        network2 = Network(name='Network Two', slug='network-two')
        db_session.add_all([network1, network2])
        db_session.commit()

        # Create hubs in different networks
        hub1 = Hub(code='NA', name='Hub NA', network_id=network1.id, status='active')
        hub2 = Hub(code='NB', name='Hub NB', network_id=network1.id, status='active')
        hub3 = Hub(code='NC', name='Hub NC', network_id=network2.id, status='active')
        db_session.add_all([hub1, hub2, hub3])
        db_session.commit()

        response = client.get(f'/api/v1/hubs?network_id={network1.id}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 2
        assert all(h['network_id'] == network1.id for h in data['hubs'])

    def test_list_hubs_combined_filters(self, client, app, db_session, sample_network):
        """GET /hubs should support multiple filters."""
        # Create hubs with various combinations
        hub1 = Hub(code='CA', name='Hub CA', network_id=sample_network.id, status='active')
        hub2 = Hub(code='CP', name='Hub CP', network_id=sample_network.id, status='pending')
        db_session.add_all([hub1, hub2])
        db_session.commit()

        response = client.get(
            f'/api/v1/hubs?status=active&network_id={sample_network.id}'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert all(
            h['status'] == 'active' and h['network_id'] == sample_network.id
            for h in data['hubs']
        )


# =============================================================================
# Hub Get API Tests (GET /api/v1/hubs/<hub_id>)
# =============================================================================

class TestHubGetAPI:
    """Tests for GET /api/v1/hubs/<hub_id> endpoint."""

    def test_get_hub_by_uuid(self, client, app, sample_hub):
        """GET /hubs/<hub_id> should return hub by UUID."""
        response = client.get(f'/api/v1/hubs/{sample_hub.id}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == sample_hub.id
        assert data['code'] == sample_hub.code
        assert data['name'] == sample_hub.name

    def test_get_hub_by_code(self, client, app, sample_hub):
        """GET /hubs/<hub_id> should return hub by code."""
        response = client.get(f'/api/v1/hubs/{sample_hub.code}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == sample_hub.id
        assert data['code'] == sample_hub.code

    def test_get_hub_not_found(self, client, app):
        """GET /hubs/<hub_id> should return 404 for non-existent hub."""
        response = client.get('/api/v1/hubs/non-existent-hub-id')

        assert response.status_code == 404
        data = response.get_json()
        assert 'Hub not found' in data['error']


# =============================================================================
# Hub Content Manifest API Tests (GET /api/v1/hubs/<hub_id>/content-manifest)
# =============================================================================

class TestHubContentManifestAPI:
    """Tests for GET /api/v1/hubs/<hub_id>/content-manifest endpoint."""

    def test_get_manifest_empty(self, client, app, sample_hub):
        """GET /hubs/<hub_id>/content-manifest should return empty manifest."""
        response = client.get(f'/api/v1/hubs/{sample_hub.id}/content-manifest')

        assert response.status_code == 200
        data = response.get_json()
        assert data['hub_id'] == sample_hub.id
        assert data['hub_code'] == sample_hub.code
        assert data['network_id'] == sample_hub.network_id
        assert data['manifest_version'] == 1
        assert data['content'] == []
        assert data['count'] == 0

    def test_get_manifest_by_uuid(self, client, app, sample_hub):
        """GET /hubs/<hub_id>/content-manifest should work with UUID."""
        response = client.get(f'/api/v1/hubs/{sample_hub.id}/content-manifest')

        assert response.status_code == 200
        data = response.get_json()
        assert data['hub_id'] == sample_hub.id

    def test_get_manifest_by_code(self, client, app, sample_hub):
        """GET /hubs/<hub_id>/content-manifest should work with code."""
        response = client.get(f'/api/v1/hubs/{sample_hub.code}/content-manifest')

        assert response.status_code == 200
        data = response.get_json()
        assert data['hub_code'] == sample_hub.code

    def test_get_manifest_with_content(self, client, app, sample_hub, sample_content):
        """GET /hubs/<hub_id>/content-manifest should include network content."""
        response = client.get(f'/api/v1/hubs/{sample_hub.id}/content-manifest')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1
        assert len(data['content']) == 1

        content_item = data['content'][0]
        assert content_item['id'] == sample_content.id
        assert content_item['filename'] == sample_content.filename
        assert content_item['mime_type'] == sample_content.mime_type
        assert content_item['file_size'] == sample_content.file_size
        assert f'/api/v1/content/{sample_content.id}/download' in content_item['url']

    def test_get_manifest_with_multiple_content(self, client, app, db_session, sample_hub, sample_network):
        """GET /hubs/<hub_id>/content-manifest should include all network content."""
        # Create additional content
        content1 = Content(
            filename='video1_abc123.mp4',
            original_name='video1.mp4',
            mime_type='video/mp4',
            file_size=5000000,
            network_id=sample_network.id
        )
        content2 = Content(
            filename='image1_def456.jpg',
            original_name='image1.jpg',
            mime_type='image/jpeg',
            file_size=200000,
            network_id=sample_network.id
        )
        content3 = Content(
            filename='video2_ghi789.mp4',
            original_name='video2.mp4',
            mime_type='video/mp4',
            file_size=8000000,
            network_id=sample_network.id
        )
        db_session.add_all([content1, content2, content3])
        db_session.commit()

        response = client.get(f'/api/v1/hubs/{sample_hub.id}/content-manifest')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 3
        assert len(data['content']) == 3

        # Verify all content items have required fields
        for item in data['content']:
            assert 'id' in item
            assert 'filename' in item
            assert 'mime_type' in item
            assert 'file_size' in item
            assert 'url' in item

    def test_get_manifest_excludes_other_network_content(self, client, app, db_session, sample_hub, sample_network):
        """GET /hubs/<hub_id>/content-manifest should only include hub's network content."""
        # Create another network with content
        other_network = Network(name='Other Network', slug='other-network')
        db_session.add(other_network)
        db_session.commit()

        # Create content in both networks
        network_content = Content(
            filename='network_content_abc.mp4',
            original_name='network_content.mp4',
            mime_type='video/mp4',
            file_size=5000000,
            network_id=sample_network.id
        )
        other_content = Content(
            filename='other_content_def.mp4',
            original_name='other_content.mp4',
            mime_type='video/mp4',
            file_size=5000000,
            network_id=other_network.id
        )
        db_session.add_all([network_content, other_content])
        db_session.commit()

        response = client.get(f'/api/v1/hubs/{sample_hub.id}/content-manifest')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1

        # Verify only hub's network content is included
        assert data['content'][0]['id'] == network_content.id

    def test_get_manifest_not_found(self, client, app):
        """GET /hubs/<hub_id>/content-manifest should return 404 for non-existent hub."""
        response = client.get('/api/v1/hubs/non-existent-hub-id/content-manifest')

        assert response.status_code == 404
        data = response.get_json()
        assert 'Hub not found' in data['error']

    def test_get_manifest_content_has_download_url(self, client, app, sample_hub, sample_content):
        """GET /hubs/<hub_id>/content-manifest content items should have download URLs."""
        response = client.get(f'/api/v1/hubs/{sample_hub.id}/content-manifest')

        assert response.status_code == 200
        data = response.get_json()

        for content_item in data['content']:
            assert 'url' in content_item
            assert content_item['url'].startswith('/api/v1/content/')
            assert content_item['url'].endswith('/download')
