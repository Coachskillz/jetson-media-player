"""
Integration tests for Local Hub API endpoints.

Tests all API routes:
- /api/v1/screens/* - Screen management
- /api/v1/content/* - Content distribution
- /api/v1/databases/* - Database distribution
- /api/v1/alerts/* - Alert ingestion

Each test class covers a specific blueprint with comprehensive
endpoint validation.
"""

import json
import os
import tempfile
from datetime import datetime

import pytest

from models import db, Screen, Content, PendingAlert, SyncStatus


# =============================================================================
# Screens API Tests (/api/v1/screens)
# =============================================================================

class TestScreensAPI:
    """Tests for /api/v1/screens endpoints."""

    # -------------------------------------------------------------------------
    # POST /screens/register
    # -------------------------------------------------------------------------

    def test_register_screen_success(self, client, app):
        """POST /screens/register should create a new screen."""
        response = client.post('/api/v1/screens/register', json={
            'hardware_id': 'hw-test-001',
            'name': 'Test Screen 1'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['success'] is True
        assert data['created'] is True
        assert data['message'] == 'Screen registered'
        assert data['screen']['hardware_id'] == 'hw-test-001'
        assert data['screen']['name'] == 'Test Screen 1'

    def test_register_existing_screen(self, client, app, sample_screen):
        """POST /screens/register should return existing screen."""
        response = client.post('/api/v1/screens/register', json={
            'hardware_id': sample_screen.hardware_id
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['created'] is False
        assert data['message'] == 'Screen already registered'
        assert data['screen']['id'] == sample_screen.id

    def test_register_screen_missing_hardware_id(self, client, app):
        """POST /screens/register should reject missing hardware_id."""
        response = client.post('/api/v1/screens/register', json={
            'name': 'Test Screen'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'hardware_id is required' in data['error']

    def test_register_screen_empty_body(self, client, app):
        """POST /screens/register should reject empty body."""
        response = client.post('/api/v1/screens/register',
                               data='',
                               content_type='application/json')

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'Request body is required' in data['error']

    def test_register_screen_invalid_hardware_id_type(self, client, app):
        """POST /screens/register should reject non-string hardware_id."""
        response = client.post('/api/v1/screens/register', json={
            'hardware_id': 12345
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'hardware_id must be a string' in data['error']

    def test_register_screen_hardware_id_too_long(self, client, app):
        """POST /screens/register should reject hardware_id > 64 chars."""
        response = client.post('/api/v1/screens/register', json={
            'hardware_id': 'x' * 65
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'max 64 characters' in data['error']

    def test_register_screen_name_too_long(self, client, app):
        """POST /screens/register should reject name > 128 chars."""
        response = client.post('/api/v1/screens/register', json={
            'hardware_id': 'hw-test-002',
            'name': 'x' * 129
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'name must be a string with max 128 characters' in data['error']

    # -------------------------------------------------------------------------
    # GET /screens/{id}/config
    # -------------------------------------------------------------------------

    def test_get_screen_config_success(self, client, app, sample_screen):
        """GET /screens/{id}/config should return configuration."""
        response = client.get(f'/api/v1/screens/{sample_screen.id}/config')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['config']['screen_id'] == sample_screen.id
        assert 'camera_enabled' in data['config']
        assert 'ncmec_enabled' in data['config']

    def test_get_screen_config_not_found(self, client, app):
        """GET /screens/{id}/config should return 404 for non-existent screen."""
        response = client.get('/api/v1/screens/99999/config')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'Screen not found' in data['error']

    # -------------------------------------------------------------------------
    # POST /screens/{id}/heartbeat
    # -------------------------------------------------------------------------

    def test_screen_heartbeat_success(self, client, app, sample_screen):
        """POST /screens/{id}/heartbeat should acknowledge heartbeat."""
        response = client.post(f'/api/v1/screens/{sample_screen.id}/heartbeat')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['message'] == 'Heartbeat received'
        assert 'timestamp' in data

    def test_screen_heartbeat_not_found(self, client, app):
        """POST /screens/{id}/heartbeat should return 404 for non-existent screen."""
        response = client.post('/api/v1/screens/99999/heartbeat')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'Screen not found' in data['error']

    def test_screen_heartbeat_updates_status(self, client, app, db_session):
        """POST /screens/{id}/heartbeat should set status to online."""
        # Create an offline screen
        screen = Screen(hardware_id='hw-offline-test', status='offline')
        db_session.add(screen)
        db_session.commit()

        # Send heartbeat
        response = client.post(f'/api/v1/screens/{screen.id}/heartbeat')

        assert response.status_code == 200
        # Verify screen is now online
        db_session.refresh(screen)
        assert screen.status == 'online'

    # -------------------------------------------------------------------------
    # GET /screens
    # -------------------------------------------------------------------------

    def test_list_screens_empty(self, client, app):
        """GET /screens should return empty list when no screens."""
        response = client.get('/api/v1/screens')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['screens'] == []
        assert data['count'] == 0

    def test_list_screens_all(self, client, app, multiple_screens):
        """GET /screens should return all screens."""
        response = client.get('/api/v1/screens')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['count'] == 3

    def test_list_screens_filter_online(self, client, app, multiple_screens):
        """GET /screens?status=online should return only online screens."""
        response = client.get('/api/v1/screens?status=online')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        # multiple_screens fixture creates screens where i%2==0 are online
        assert all(s['status'] == 'online' for s in data['screens'])

    def test_list_screens_filter_offline(self, client, app, multiple_screens):
        """GET /screens?status=offline should return only offline screens."""
        response = client.get('/api/v1/screens?status=offline')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert all(s['status'] == 'offline' for s in data['screens'])


# =============================================================================
# Content API Tests (/api/v1/content)
# =============================================================================

class TestContentAPI:
    """Tests for /api/v1/content endpoints."""

    # -------------------------------------------------------------------------
    # GET /content (manifest)
    # -------------------------------------------------------------------------

    def test_get_manifest_empty(self, client, app):
        """GET /content should return empty manifest when no content."""
        response = client.get('/api/v1/content')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['content'] == []
        assert data['count'] == 0

    def test_get_manifest_with_cached_content(self, client, app, db_session):
        """GET /content should return manifest with cached content."""
        # Create cached content
        content = Content(
            content_id='manifest-test-001',
            filename='test_video.mp4',
            file_hash='abc123',
            file_size=1024,
            content_type='video'
        )
        content.cached_at = datetime.utcnow()
        db_session.add(content)
        db_session.commit()

        response = client.get('/api/v1/content')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['count'] == 1
        assert data['content'][0]['content_id'] == 'manifest-test-001'
        assert data['content'][0]['file_hash'] == 'abc123'

    def test_get_manifest_excludes_uncached(self, client, app, db_session):
        """GET /content should exclude uncached content from manifest."""
        # Create uncached content
        content = Content(
            content_id='uncached-001',
            filename='uncached.mp4',
            content_type='video'
        )
        db_session.add(content)
        db_session.commit()

        response = client.get('/api/v1/content')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 0

    # -------------------------------------------------------------------------
    # GET /content/{content_id}
    # -------------------------------------------------------------------------

    def test_get_content_info_success(self, client, app, db_session):
        """GET /content/{content_id} should return content info."""
        content = Content(
            content_id='info-test-001',
            filename='test.mp4',
            file_hash='hash123',
            file_size=2048,
            content_type='video'
        )
        db_session.add(content)
        db_session.commit()

        response = client.get('/api/v1/content/info-test-001')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['content']['content_id'] == 'info-test-001'
        assert data['content']['file_hash'] == 'hash123'
        assert data['content']['cached'] is False

    def test_get_content_info_not_found(self, client, app):
        """GET /content/{content_id} should return 404 for non-existent content."""
        response = client.get('/api/v1/content/nonexistent-content')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'Content not found' in data['error']

    def test_get_content_info_invalid_id_format(self, client, app):
        """GET /content/{content_id} should reject overly long content_id."""
        response = client.get(f'/api/v1/content/{"x" * 65}')

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'Invalid content_id format' in data['error']

    # -------------------------------------------------------------------------
    # GET /content/{content_id}/download
    # -------------------------------------------------------------------------

    def test_download_content_not_found(self, client, app):
        """GET /content/{content_id}/download should return 404 for missing content."""
        response = client.get('/api/v1/content/nonexistent/download')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'Content not found' in data['error']

    def test_download_content_not_cached(self, client, app, db_session):
        """GET /content/{content_id}/download should return 404 for uncached content."""
        content = Content(
            content_id='uncached-download-test',
            filename='test.mp4',
            content_type='video'
        )
        db_session.add(content)
        db_session.commit()

        response = client.get('/api/v1/content/uncached-download-test/download')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'Content not cached locally' in data['error']

    def test_download_content_file_missing_on_disk(self, client, app, db_session):
        """GET /content/{content_id}/download should return 404 if file missing."""
        content = Content(
            content_id='missing-file-test',
            filename='test.mp4',
            local_path='/nonexistent/path/test.mp4',
            content_type='video'
        )
        content.cached_at = datetime.utcnow()
        db_session.add(content)
        db_session.commit()

        response = client.get('/api/v1/content/missing-file-test/download')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'Content file not found on disk' in data['error']

    def test_download_content_success(self, client, app, db_session):
        """GET /content/{content_id}/download should stream file successfully."""
        # Create a temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write('test content data')
            temp_path = f.name

        try:
            content = Content(
                content_id='download-success-test',
                filename='test.txt',
                local_path=temp_path,
                content_type='video'
            )
            content.cached_at = datetime.utcnow()
            db_session.add(content)
            db_session.commit()

            response = client.get('/api/v1/content/download-success-test/download')

            assert response.status_code == 200
            assert response.data == b'test content data'
        finally:
            os.unlink(temp_path)

    def test_download_content_invalid_id_format(self, client, app):
        """GET /content/{content_id}/download should reject overly long content_id."""
        response = client.get(f'/api/v1/content/{"x" * 65}/download')

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'Invalid content_id format' in data['error']


# =============================================================================
# Databases API Tests (/api/v1/databases)
# =============================================================================

class TestDatabasesAPI:
    """Tests for /api/v1/databases endpoints."""

    # -------------------------------------------------------------------------
    # GET /databases
    # -------------------------------------------------------------------------

    def test_list_databases_empty(self, client, app):
        """GET /databases should return database statuses even when not synced."""
        response = client.get('/api/v1/databases')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['count'] == 2
        # Verify both database types are listed
        types = [db['type'] for db in data['databases']]
        assert 'ncmec_db' in types
        assert 'loyalty_db' in types

    def test_list_databases_with_synced(self, client, app, db_session):
        """GET /databases should show synced databases as available."""
        # Create synced NCMEC status
        status = SyncStatus.get_or_create('ncmec_db')
        status.mark_sync_success(
            version='v1.0.0',
            file_hash='abc123',
            file_size=1024
        )

        response = client.get('/api/v1/databases')

        assert response.status_code == 200
        data = response.get_json()

        ncmec_db = next(db for db in data['databases'] if db['type'] == 'ncmec_db')
        assert ncmec_db['available'] is True
        assert ncmec_db['version'] == 'v1.0.0'
        assert ncmec_db['file_hash'] == 'abc123'

    # -------------------------------------------------------------------------
    # GET /databases/ncmec/version
    # -------------------------------------------------------------------------

    def test_ncmec_version_not_available(self, client, app):
        """GET /databases/ncmec/version should return 404 when not synced."""
        response = client.get('/api/v1/databases/ncmec/version')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'NCMEC database not available' in data['error']

    def test_ncmec_version_success(self, client, app, db_session):
        """GET /databases/ncmec/version should return version info."""
        status = SyncStatus.get_or_create('ncmec_db')
        status.mark_sync_success(
            version='v2.0.0',
            file_hash='xyz789',
            file_size=2048
        )

        response = client.get('/api/v1/databases/ncmec/version')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['version'] == 'v2.0.0'
        assert data['file_hash'] == 'xyz789'
        assert data['file_size'] == 2048

    # -------------------------------------------------------------------------
    # GET /databases/ncmec/download
    # -------------------------------------------------------------------------

    def test_ncmec_download_not_available(self, client, app):
        """GET /databases/ncmec/download should return 404 when not synced."""
        response = client.get('/api/v1/databases/ncmec/download')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'NCMEC database not available' in data['error']

    def test_ncmec_download_file_missing(self, client, app, db_session):
        """GET /databases/ncmec/download should return 404 when file missing."""
        status = SyncStatus.get_or_create('ncmec_db')
        status.mark_sync_success(version='v1.0.0')

        # Configure app to use a temp directory (file won't exist)
        with tempfile.TemporaryDirectory() as tmpdir:
            app.config['DATABASES_PATH'] = tmpdir
            response = client.get('/api/v1/databases/ncmec/download')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'file not found on disk' in data['error']

    def test_ncmec_download_success(self, client, app, db_session):
        """GET /databases/ncmec/download should stream file successfully."""
        status = SyncStatus.get_or_create('ncmec_db')
        status.mark_sync_success(version='v1.0.0')

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create the ncmec.faiss file
            faiss_path = os.path.join(tmpdir, 'ncmec.faiss')
            with open(faiss_path, 'wb') as f:
                f.write(b'fake faiss data')

            app.config['DATABASES_PATH'] = tmpdir
            response = client.get('/api/v1/databases/ncmec/download')

        assert response.status_code == 200
        assert response.data == b'fake faiss data'

    # -------------------------------------------------------------------------
    # GET /databases/loyalty/version
    # -------------------------------------------------------------------------

    def test_loyalty_version_not_available(self, client, app):
        """GET /databases/loyalty/version should return 404 when not synced."""
        response = client.get('/api/v1/databases/loyalty/version')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'Loyalty database not available' in data['error']

    def test_loyalty_version_success(self, client, app, db_session):
        """GET /databases/loyalty/version should return version info."""
        status = SyncStatus.get_or_create('loyalty_db')
        status.mark_sync_success(
            version='v3.0.0',
            file_hash='loyalty-hash',
            file_size=4096
        )

        response = client.get('/api/v1/databases/loyalty/version')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['version'] == 'v3.0.0'
        assert data['file_hash'] == 'loyalty-hash'

    # -------------------------------------------------------------------------
    # GET /databases/loyalty/download
    # -------------------------------------------------------------------------

    def test_loyalty_download_not_available(self, client, app):
        """GET /databases/loyalty/download should return 404 when not synced."""
        response = client.get('/api/v1/databases/loyalty/download')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'Loyalty database not available' in data['error']

    def test_loyalty_download_success(self, client, app, db_session):
        """GET /databases/loyalty/download should stream file successfully."""
        status = SyncStatus.get_or_create('loyalty_db')
        status.mark_sync_success(version='v1.0.0')

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create the loyalty.faiss file
            faiss_path = os.path.join(tmpdir, 'loyalty.faiss')
            with open(faiss_path, 'wb') as f:
                f.write(b'loyalty faiss data')

            app.config['DATABASES_PATH'] = tmpdir
            response = client.get('/api/v1/databases/loyalty/download')

        assert response.status_code == 200
        assert response.data == b'loyalty faiss data'


# =============================================================================
# Alerts API Tests (/api/v1/alerts)
# =============================================================================

class TestAlertsAPI:
    """Tests for /api/v1/alerts endpoints."""

    # -------------------------------------------------------------------------
    # POST /alerts
    # -------------------------------------------------------------------------

    def test_ingest_alert_success(self, client, app, sample_screen):
        """POST /alerts should create and queue alert."""
        response = client.post('/api/v1/alerts', json={
            'screen_id': sample_screen.id,
            'alert_type': 'ncmec_match',
            'data': {
                'match_confidence': 0.95,
                'person_id': 'person-123'
            }
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['success'] is True
        assert data['message'] == 'Alert received and queued'
        assert 'alert_id' in data

    def test_ingest_alert_missing_body(self, client, app):
        """POST /alerts should reject empty body."""
        response = client.post('/api/v1/alerts',
                               data='',
                               content_type='application/json')

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'Request body is required' in data['error']

    def test_ingest_alert_missing_screen_id(self, client, app):
        """POST /alerts should reject missing screen_id."""
        response = client.post('/api/v1/alerts', json={
            'alert_type': 'test'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'screen_id is required' in data['error']

    def test_ingest_alert_invalid_screen_id(self, client, app):
        """POST /alerts should reject invalid screen_id type."""
        response = client.post('/api/v1/alerts', json={
            'screen_id': 'not-an-int',
            'alert_type': 'test'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'screen_id must be a positive integer' in data['error']

    def test_ingest_alert_screen_not_found(self, client, app):
        """POST /alerts should reject non-existent screen."""
        response = client.post('/api/v1/alerts', json={
            'screen_id': 99999,
            'alert_type': 'test'
        })

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'Screen not found' in data['error']

    def test_ingest_alert_missing_alert_type(self, client, app, sample_screen):
        """POST /alerts should reject missing alert_type."""
        response = client.post('/api/v1/alerts', json={
            'screen_id': sample_screen.id
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'alert_type is required' in data['error']

    def test_ingest_alert_invalid_alert_type(self, client, app, sample_screen):
        """POST /alerts should reject invalid alert_type."""
        response = client.post('/api/v1/alerts', json={
            'screen_id': sample_screen.id,
            'alert_type': 'invalid_type'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'alert_type must be one of' in data['error']

    def test_ingest_alert_all_valid_types(self, client, app, sample_screen):
        """POST /alerts should accept all valid alert types."""
        valid_types = [
            'ncmec_match', 'face_match', 'loyalty_match',
            'system_error', 'hardware_error', 'connectivity',
            'camera_error', 'storage_warning', 'test'
        ]

        for alert_type in valid_types:
            response = client.post('/api/v1/alerts', json={
                'screen_id': sample_screen.id,
                'alert_type': alert_type
            })
            assert response.status_code == 201, f'Failed for {alert_type}'

    def test_ingest_alert_invalid_data_type(self, client, app, sample_screen):
        """POST /alerts should reject non-object data."""
        response = client.post('/api/v1/alerts', json={
            'screen_id': sample_screen.id,
            'alert_type': 'test',
            'data': 'not-an-object'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'data must be an object' in data['error']

    def test_ingest_alert_type_too_long(self, client, app, sample_screen):
        """POST /alerts should reject overly long alert_type."""
        response = client.post('/api/v1/alerts', json={
            'screen_id': sample_screen.id,
            'alert_type': 'x' * 65
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'max 64 characters' in data['error']

    # -------------------------------------------------------------------------
    # GET /alerts
    # -------------------------------------------------------------------------

    def test_list_alerts_empty(self, client, app):
        """GET /alerts should return empty list when no alerts."""
        response = client.get('/api/v1/alerts')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['alerts'] == []
        assert data['count'] == 0

    def test_list_alerts_with_alerts(self, client, app, sample_screen, db_session):
        """GET /alerts should return pending alerts."""
        # Create some alerts
        PendingAlert.create_alert(
            screen_id=sample_screen.id,
            alert_type='test',
            payload_dict={'key': 'value1'}
        )
        PendingAlert.create_alert(
            screen_id=sample_screen.id,
            alert_type='ncmec_match',
            payload_dict={'key': 'value2'}
        )

        response = client.get('/api/v1/alerts')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['count'] == 2

    def test_list_alerts_filter_by_screen(self, client, app, db_session):
        """GET /alerts?screen_id=X should filter by screen."""
        # Create two screens
        screen1 = Screen(hardware_id='hw-alert-filter-1', status='online')
        screen2 = Screen(hardware_id='hw-alert-filter-2', status='online')
        db_session.add_all([screen1, screen2])
        db_session.commit()

        # Create alerts for both screens
        PendingAlert.create_alert(screen_id=screen1.id, alert_type='test', payload_dict={})
        PendingAlert.create_alert(screen_id=screen1.id, alert_type='test', payload_dict={})
        PendingAlert.create_alert(screen_id=screen2.id, alert_type='test', payload_dict={})

        response = client.get(f'/api/v1/alerts?screen_id={screen1.id}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 2
        assert all(a['screen_id'] == screen1.id for a in data['alerts'])

    def test_list_alerts_filter_by_status(self, client, app, sample_screen, db_session):
        """GET /alerts?status=X should filter by status."""
        alert1 = PendingAlert.create_alert(
            screen_id=sample_screen.id,
            alert_type='test',
            payload_dict={}
        )
        alert2 = PendingAlert.create_alert(
            screen_id=sample_screen.id,
            alert_type='test',
            payload_dict={}
        )
        alert2.mark_failed(error_message='Test failure')

        response = client.get('/api/v1/alerts?status=failed')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1
        assert data['alerts'][0]['status'] == 'failed'

    def test_list_alerts_excludes_sent(self, client, app, sample_screen, db_session):
        """GET /alerts should exclude sent alerts."""
        alert1 = PendingAlert.create_alert(
            screen_id=sample_screen.id,
            alert_type='test',
            payload_dict={}
        )
        alert2 = PendingAlert.create_alert(
            screen_id=sample_screen.id,
            alert_type='test',
            payload_dict={}
        )
        alert2.mark_sent()

        response = client.get('/api/v1/alerts')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1

    # -------------------------------------------------------------------------
    # GET /alerts/count
    # -------------------------------------------------------------------------

    def test_get_pending_count_empty(self, client, app):
        """GET /alerts/count should return 0 when no alerts."""
        response = client.get('/api/v1/alerts/count')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['pending_count'] == 0

    def test_get_pending_count_with_alerts(self, client, app, sample_screen, db_session):
        """GET /alerts/count should return correct count."""
        PendingAlert.create_alert(screen_id=sample_screen.id, alert_type='test', payload_dict={})
        PendingAlert.create_alert(screen_id=sample_screen.id, alert_type='test', payload_dict={})
        sent_alert = PendingAlert.create_alert(
            screen_id=sample_screen.id, alert_type='test', payload_dict={})
        sent_alert.mark_sent()

        response = client.get('/api/v1/alerts/count')

        assert response.status_code == 200
        data = response.get_json()
        assert data['pending_count'] == 2  # Excludes sent alert

    # -------------------------------------------------------------------------
    # GET /alerts/{alert_id}
    # -------------------------------------------------------------------------

    def test_get_alert_success(self, client, app, sample_screen, db_session):
        """GET /alerts/{alert_id} should return alert details."""
        alert = PendingAlert.create_alert(
            screen_id=sample_screen.id,
            alert_type='ncmec_match',
            payload_dict={'match_id': 'test-match'}
        )

        response = client.get(f'/api/v1/alerts/{alert.id}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['alert']['id'] == alert.id
        assert data['alert']['alert_type'] == 'ncmec_match'

    def test_get_alert_not_found(self, client, app):
        """GET /alerts/{alert_id} should return 404 for non-existent alert."""
        response = client.get('/api/v1/alerts/99999')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'Alert not found' in data['error']
