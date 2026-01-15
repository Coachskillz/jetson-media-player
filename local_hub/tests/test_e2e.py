"""
End-to-end tests for Local Hub complete workflows.

These tests verify the complete user journey through the Local Hub API:
1. Hub starts successfully (via Flask test client)
2. Screen registration flow
3. Screen configuration retrieval
4. Screen heartbeat submission
5. Alert submission and queuing
6. Content manifest retrieval

Each test class covers a complete E2E flow that a Jetson screen
would perform when interacting with the Local Hub.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

from models import db, Screen, Content, PendingAlert, SyncStatus


# =============================================================================
# Complete Screen Lifecycle E2E Tests
# =============================================================================

class TestScreenLifecycleE2E:
    """
    End-to-end tests for the complete screen lifecycle.

    Verification Flow:
    1. Start local hub on port 5000 (simulated via test client)
    2. POST /api/v1/screens/register with hardware_id
    3. GET /api/v1/screens/{id}/config returns valid config
    4. POST /api/v1/screens/{id}/heartbeat returns ack
    """

    def test_complete_screen_registration_flow(self, client, app):
        """
        E2E: Complete screen registration to heartbeat flow.

        Steps:
        1. Register a new screen with hardware_id
        2. Verify screen was created with correct attributes
        3. Get screen configuration
        4. Send heartbeat
        5. Verify heartbeat updated screen status
        """
        # Step 1: Register screen
        register_response = client.post('/api/v1/screens/register', json={
            'hardware_id': 'e2e-test-screen-001',
            'name': 'E2E Test Screen'
        })

        assert register_response.status_code == 201, \
            f"Registration failed: {register_response.get_json()}"
        register_data = register_response.get_json()
        assert register_data['success'] is True
        assert register_data['created'] is True

        screen_id = register_data['screen']['id']
        assert screen_id is not None
        assert register_data['screen']['hardware_id'] == 'e2e-test-screen-001'
        assert register_data['screen']['name'] == 'E2E Test Screen'

        # Step 2: Get screen configuration
        config_response = client.get(f'/api/v1/screens/{screen_id}/config')

        assert config_response.status_code == 200, \
            f"Config retrieval failed: {config_response.get_json()}"
        config_data = config_response.get_json()
        assert config_data['success'] is True
        assert config_data['config']['screen_id'] == screen_id

        # Verify config contains expected fields
        config = config_data['config']
        assert 'camera_enabled' in config
        assert 'ncmec_enabled' in config
        assert 'loyalty_enabled' in config
        assert 'ncmec_db_version' in config
        assert 'loyalty_db_version' in config

        # Step 3: Send heartbeat
        heartbeat_response = client.post(f'/api/v1/screens/{screen_id}/heartbeat')

        assert heartbeat_response.status_code == 200, \
            f"Heartbeat failed: {heartbeat_response.get_json()}"
        heartbeat_data = heartbeat_response.get_json()
        assert heartbeat_data['success'] is True
        assert heartbeat_data['message'] == 'Heartbeat received'
        assert 'timestamp' in heartbeat_data

        # Step 4: Verify screen status is online
        with app.app_context():
            screen = db.session.get(Screen, screen_id)
            assert screen is not None
            assert screen.status == 'online'
            assert screen.last_heartbeat is not None

    def test_screen_reregistration_returns_existing(self, client, app):
        """
        E2E: Re-registering same screen returns existing record.

        Verifies idempotent registration behavior.
        """
        # First registration
        response1 = client.post('/api/v1/screens/register', json={
            'hardware_id': 'e2e-idempotent-001',
            'name': 'First Name'
        })
        assert response1.status_code == 201
        first_id = response1.get_json()['screen']['id']

        # Second registration with same hardware_id
        response2 = client.post('/api/v1/screens/register', json={
            'hardware_id': 'e2e-idempotent-001',
            'name': 'Different Name'
        })

        assert response2.status_code == 200
        data = response2.get_json()
        assert data['created'] is False
        assert data['message'] == 'Screen already registered'
        assert data['screen']['id'] == first_id

    def test_multiple_screens_independent_configs(self, client, app):
        """
        E2E: Multiple screens can register and get independent configs.
        """
        screens = []
        for i in range(3):
            response = client.post('/api/v1/screens/register', json={
                'hardware_id': f'e2e-multi-{i:03d}',
                'name': f'Multi Screen {i}'
            })
            assert response.status_code == 201
            screens.append(response.get_json()['screen'])

        # Each screen should have independent config
        for screen in screens:
            config_response = client.get(f'/api/v1/screens/{screen["id"]}/config')
            assert config_response.status_code == 200
            config = config_response.get_json()['config']
            assert config['screen_id'] == screen['id']


# =============================================================================
# Alert Submission E2E Tests
# =============================================================================

class TestAlertSubmissionE2E:
    """
    End-to-end tests for alert submission and queuing.

    Verification Flow:
    5. POST /api/v1/alerts queues alert successfully
    """

    def test_complete_alert_submission_flow(self, client, app, sample_screen):
        """
        E2E: Submit alert and verify it's queued.

        Steps:
        1. Submit alert for registered screen
        2. Verify alert is queued
        3. Check alert appears in listing
        """
        # Step 1: Submit alert
        alert_response = client.post('/api/v1/alerts', json={
            'screen_id': sample_screen.id,
            'alert_type': 'ncmec_match',
            'data': {
                'match_confidence': 0.97,
                'person_id': 'person-e2e-001',
                'image_path': '/captures/test.jpg'
            }
        })

        assert alert_response.status_code == 201, \
            f"Alert submission failed: {alert_response.get_json()}"
        alert_data = alert_response.get_json()
        assert alert_data['success'] is True
        assert alert_data['message'] == 'Alert received and queued'
        assert 'alert_id' in alert_data

        alert_id = alert_data['alert_id']

        # Step 2: Verify alert exists in database
        with app.app_context():
            alert = db.session.get(PendingAlert, alert_id)
            assert alert is not None
            assert alert.screen_id == sample_screen.id
            assert alert.alert_type == 'ncmec_match'
            assert alert.status == 'pending'
            assert alert.attempts == 0

        # Step 3: Verify alert appears in listing
        list_response = client.get('/api/v1/alerts')
        assert list_response.status_code == 200
        list_data = list_response.get_json()
        assert list_data['count'] >= 1

        alert_ids = [a['id'] for a in list_data['alerts']]
        assert alert_id in alert_ids

    def test_alert_submission_all_types(self, client, app, sample_screen):
        """
        E2E: All valid alert types can be submitted.
        """
        valid_types = [
            'ncmec_match',
            'face_match',
            'loyalty_match',
            'system_error',
            'hardware_error',
            'connectivity',
            'camera_error',
            'storage_warning',
            'test'
        ]

        alert_ids = []
        for alert_type in valid_types:
            response = client.post('/api/v1/alerts', json={
                'screen_id': sample_screen.id,
                'alert_type': alert_type,
                'data': {'test_key': f'test_value_{alert_type}'}
            })

            assert response.status_code == 201, \
                f"Failed for type {alert_type}: {response.get_json()}"
            alert_ids.append(response.get_json()['alert_id'])

        # Verify all alerts are pending
        count_response = client.get('/api/v1/alerts/count')
        assert count_response.status_code == 200
        assert count_response.get_json()['pending_count'] == len(valid_types)

    def test_alert_persistence_reliability(self, client, app, sample_screen):
        """
        E2E: Verify CRITICAL requirement - alerts are never lost.

        Tests that alerts remain in queue until explicitly marked sent.
        """
        # Create multiple alerts
        for i in range(5):
            response = client.post('/api/v1/alerts', json={
                'screen_id': sample_screen.id,
                'alert_type': 'test',
                'data': {'batch_id': i}
            })
            assert response.status_code == 201

        # Verify all 5 alerts are pending
        count_response = client.get('/api/v1/alerts/count')
        assert count_response.get_json()['pending_count'] == 5

        # Get individual alert and verify it has correct status
        list_response = client.get('/api/v1/alerts')
        alerts = list_response.get_json()['alerts']

        for alert in alerts:
            assert alert['status'] in ['pending', 'failed', 'sending']
            # Alerts should never be auto-deleted
            detail_response = client.get(f'/api/v1/alerts/{alert["id"]}')
            assert detail_response.status_code == 200


# =============================================================================
# Content Manifest E2E Tests
# =============================================================================

class TestContentManifestE2E:
    """
    End-to-end tests for content manifest retrieval.

    Verification Flow:
    6. GET /api/v1/content returns manifest
    """

    def test_content_manifest_retrieval(self, client, app):
        """
        E2E: Content manifest returns cached content list.
        """
        # Initially empty
        response = client.get('/api/v1/content')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'content' in data
        assert 'count' in data
        assert isinstance(data['content'], list)

    def test_content_manifest_with_cached_items(self, client, app, db_session):
        """
        E2E: Content manifest includes cached content with hashes.
        """
        # Create cached content
        content1 = Content(
            content_id='e2e-content-001',
            filename='promo_video.mp4',
            file_hash='sha256-e2e-hash-001',
            file_size=10240000,
            content_type='video/mp4',
            local_path='/var/skillz-hub/storage/content/promo_video.mp4'
        )
        content1.cached_at = datetime.utcnow()

        content2 = Content(
            content_id='e2e-content-002',
            filename='banner.png',
            file_hash='sha256-e2e-hash-002',
            file_size=512000,
            content_type='image/png',
            local_path='/var/skillz-hub/storage/content/banner.png'
        )
        content2.cached_at = datetime.utcnow()

        db_session.add_all([content1, content2])
        db_session.commit()

        # Get manifest
        response = client.get('/api/v1/content')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 2

        # Verify manifest items have required fields
        for item in data['content']:
            assert 'content_id' in item
            assert 'filename' in item
            assert 'file_hash' in item
            assert 'file_size' in item
            assert 'content_type' in item

    def test_content_manifest_excludes_uncached(self, client, app, db_session):
        """
        E2E: Uncached content doesn't appear in manifest.
        """
        # Create one cached and one uncached
        cached = Content(
            content_id='e2e-cached-001',
            filename='cached.mp4',
            file_hash='hash-cached',
            content_type='video'
        )
        cached.cached_at = datetime.utcnow()

        uncached = Content(
            content_id='e2e-uncached-001',
            filename='uncached.mp4',
            content_type='video'
        )
        # No cached_at set

        db_session.add_all([cached, uncached])
        db_session.commit()

        response = client.get('/api/v1/content')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1
        assert data['content'][0]['content_id'] == 'e2e-cached-001'


# =============================================================================
# Database Availability E2E Tests
# =============================================================================

class TestDatabaseAvailabilityE2E:
    """
    End-to-end tests for database version checking.
    """

    def test_database_status_listing(self, client, app):
        """
        E2E: Database listing shows all database types.
        """
        response = client.get('/api/v1/databases')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['count'] == 2

        db_types = [db['type'] for db in data['databases']]
        assert 'ncmec_db' in db_types
        assert 'loyalty_db' in db_types

    def test_database_version_check_flow(self, client, app, db_session):
        """
        E2E: Screen can check database versions and determine if update needed.
        """
        # Set up synced NCMEC database
        ncmec_status = SyncStatus.get_or_create('ncmec_db')
        ncmec_status.mark_sync_success(
            version='v2025.01.15',
            file_hash='sha256-ncmec-hash',
            file_size=50000000
        )

        # Set up synced Loyalty database
        loyalty_status = SyncStatus.get_or_create('loyalty_db')
        loyalty_status.mark_sync_success(
            version='v2025.01.10',
            file_hash='sha256-loyalty-hash',
            file_size=25000000
        )

        # Check NCMEC version
        ncmec_response = client.get('/api/v1/databases/ncmec/version')
        assert ncmec_response.status_code == 200
        ncmec_data = ncmec_response.get_json()
        assert ncmec_data['version'] == 'v2025.01.15'
        assert ncmec_data['file_hash'] == 'sha256-ncmec-hash'

        # Check Loyalty version
        loyalty_response = client.get('/api/v1/databases/loyalty/version')
        assert loyalty_response.status_code == 200
        loyalty_data = loyalty_response.get_json()
        assert loyalty_data['version'] == 'v2025.01.10'
        assert loyalty_data['file_hash'] == 'sha256-loyalty-hash'


# =============================================================================
# Complete Integration Flow E2E Tests
# =============================================================================

class TestCompleteIntegrationE2E:
    """
    End-to-end tests combining all verification steps in sequence.

    This test class verifies the complete flow a Jetson screen
    would perform when connecting to the Local Hub.
    """

    def test_complete_jetson_screen_flow(self, client, app, db_session):
        """
        E2E: Complete Jetson screen integration flow.

        Verification Steps:
        1. Start local hub on port 5000 (via test client)
        2. POST /api/v1/screens/register with hardware_id
        3. GET /api/v1/screens/{id}/config returns valid config
        4. POST /api/v1/screens/{id}/heartbeat returns ack
        5. POST /api/v1/alerts queues alert successfully
        6. GET /api/v1/content returns manifest
        """
        # Step 1: Hub is started (implicit via test client)

        # Step 2: Register screen
        register_response = client.post('/api/v1/screens/register', json={
            'hardware_id': 'jetson-complete-e2e-001',
            'name': 'Complete E2E Test Screen'
        })
        assert register_response.status_code == 201
        screen_data = register_response.get_json()
        screen_id = screen_data['screen']['id']

        # Step 3: Get configuration
        config_response = client.get(f'/api/v1/screens/{screen_id}/config')
        assert config_response.status_code == 200
        config = config_response.get_json()['config']
        assert config['screen_id'] == screen_id

        # Step 4: Send heartbeat
        heartbeat_response = client.post(f'/api/v1/screens/{screen_id}/heartbeat')
        assert heartbeat_response.status_code == 200
        assert heartbeat_response.get_json()['success'] is True

        # Step 5: Submit alert
        alert_response = client.post('/api/v1/alerts', json={
            'screen_id': screen_id,
            'alert_type': 'ncmec_match',
            'data': {
                'match_confidence': 0.98,
                'person_id': 'complete-e2e-person',
                'timestamp': datetime.utcnow().isoformat()
            }
        })
        assert alert_response.status_code == 201
        assert 'alert_id' in alert_response.get_json()

        # Step 6: Get content manifest
        manifest_response = client.get('/api/v1/content')
        assert manifest_response.status_code == 200
        manifest = manifest_response.get_json()
        assert 'content' in manifest
        assert 'count' in manifest

        # All verification steps passed

    def test_multiple_screens_parallel_operations(self, client, app, db_session):
        """
        E2E: Multiple screens operating simultaneously.

        Verifies the hub can handle multiple concurrent screen registrations,
        heartbeats, and alerts without data corruption.
        """
        num_screens = 5
        screens = []

        # Register multiple screens
        for i in range(num_screens):
            response = client.post('/api/v1/screens/register', json={
                'hardware_id': f'parallel-e2e-{i:03d}',
                'name': f'Parallel Screen {i}'
            })
            assert response.status_code == 201
            screens.append(response.get_json()['screen'])

        # All screens send heartbeats
        for screen in screens:
            response = client.post(f'/api/v1/screens/{screen["id"]}/heartbeat')
            assert response.status_code == 200

        # All screens submit alerts
        for screen in screens:
            response = client.post('/api/v1/alerts', json={
                'screen_id': screen['id'],
                'alert_type': 'test',
                'data': {'screen_name': screen['name']}
            })
            assert response.status_code == 201

        # Verify all screens are online
        list_response = client.get('/api/v1/screens?status=online')
        assert list_response.status_code == 200
        assert list_response.get_json()['count'] == num_screens

        # Verify all alerts queued
        alerts_response = client.get('/api/v1/alerts/count')
        assert alerts_response.status_code == 200
        assert alerts_response.get_json()['pending_count'] == num_screens


# =============================================================================
# Health and Status E2E Tests
# =============================================================================

class TestHealthStatusE2E:
    """
    End-to-end tests for hub health and status endpoints.
    """

    def test_health_endpoint(self, client, app):
        """
        E2E: Health endpoint returns hub status.
        """
        response = client.get('/health')

        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'healthy'

    def test_screens_list_reflects_status(self, client, app, db_session):
        """
        E2E: Screen listing accurately reflects current status.
        """
        # Create screens with different statuses
        online_screen = Screen(
            hardware_id='status-online',
            name='Online Screen',
            status='online',
            last_heartbeat=datetime.utcnow()
        )
        offline_screen = Screen(
            hardware_id='status-offline',
            name='Offline Screen',
            status='offline',
            last_heartbeat=datetime.utcnow() - timedelta(minutes=5)
        )

        db_session.add_all([online_screen, offline_screen])
        db_session.commit()

        # Verify listing shows correct counts
        all_response = client.get('/api/v1/screens')
        assert all_response.get_json()['count'] == 2

        online_response = client.get('/api/v1/screens?status=online')
        assert online_response.get_json()['count'] == 1

        offline_response = client.get('/api/v1/screens?status=offline')
        assert offline_response.get_json()['count'] == 1
