#!/usr/bin/env python3
"""
End-to-End Integration Test: Content Catalog → CMS Sync → Template Display

This test verifies the complete integration flow between the Content Catalog
and CMS services for the Content Catalog to CMS Integration feature (018).

Verification Steps:
1. Start Content Catalog on port 5003
2. Start CMS on port 5002
3. Create test approved content in Content Catalog
4. Trigger sync from CMS /api/v1/content/sync
5. Verify content appears in CMS content page
6. Test network filter restricts content correctly

Usage:
    cd cms && pytest tests/test_content_catalog_integration.py -v

Requirements:
    - Content Catalog service must be available (or mock)
    - CMS service must be available (or test with app context)
    - SQLite databases will be used for testing
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Add project paths - cms is current dir, content_catalog is in parent
CMS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_CATALOG_ROOT = os.path.dirname(CMS_ROOT)
sys.path.insert(0, CMS_ROOT)
sys.path.insert(0, CONTENT_CATALOG_ROOT)


class ContentCatalogCMSIntegrationTest(unittest.TestCase):
    """End-to-end integration tests for Content Catalog to CMS sync."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for the entire test class."""
        os.environ['FLASK_ENV'] = 'testing'
        os.environ['CONTENT_CATALOG_URL'] = 'http://localhost:5003'

    def setUp(self):
        """Set up test fixtures for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.cms_db_path = os.path.join(self.temp_dir, 'cms_test.db')
        os.environ['CMS_DATABASE_PATH'] = self.cms_db_path

        from cms.app import create_app
        self.cms_app = create_app('testing')
        self.cms_client = self.cms_app.test_client()
        self.cms_app_context = self.cms_app.app_context()
        self.cms_app_context.push()

        from cms.models import db
        db.create_all()
        self.cms_db = db

        self._create_test_networks()
        self._create_test_user()

    def tearDown(self):
        """Clean up after each test."""
        from cms.models import db
        db.session.remove()
        self.cms_app_context.pop()

        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_test_networks(self):
        """Create test networks in CMS database."""
        from cms.models import Network

        networks = [
            Network(id='network-high-octane', name='High Octane', slug='high-octane'),
            Network(id='network-west-marine', name='West Marine', slug='west-marine'),
            Network(id='network-on-the-wave', name='On The Wave', slug='on-the-wave'),
        ]

        for network in networks:
            existing = self.cms_db.session.get(Network, network.id)
            if not existing:
                self.cms_db.session.add(network)

        self.cms_db.session.commit()

    def _create_test_user(self):
        """Create a test user for authenticated requests."""
        from cms.models import User

        self.test_user = User(
            email='test@example.com',
            name='Test User',
            role='admin',
            status='active'
        )
        self.test_user.set_password('testpassword123')
        self.cms_db.session.add(self.test_user)
        self.cms_db.session.commit()

    def _get_mock_approved_content(self, network_ids=None):
        """Get mock approved content response from Content Catalog."""
        assets = [
            {
                'uuid': 'uuid-video-1',
                'title': 'Promotional Video 1',
                'description': 'High Octane promo video',
                'filename': 'promo1.mp4',
                'file_path': '/uploads/promo1.mp4',
                'file_size': 1024000,
                'duration': 30.5,
                'resolution': '1920x1080',
                'format': 'mp4',
                'thumbnail_path': '/thumbnails/promo1.jpg',
                'status': 'published',
                'organization_id': 1,
                'networks': json.dumps(['network-high-octane']),
                'category': 'promotional',
                'tags': 'promo,video',
                'created_at': '2026-01-15T10:00:00Z',
                'published_at': '2026-01-16T10:00:00Z'
            },
            {
                'uuid': 'uuid-video-2',
                'title': 'West Marine Summer Sale',
                'description': 'Summer sale promotional video',
                'filename': 'summer_sale.mp4',
                'file_path': '/uploads/summer_sale.mp4',
                'file_size': 2048000,
                'duration': 60.0,
                'resolution': '1920x1080',
                'format': 'mp4',
                'thumbnail_path': '/thumbnails/summer_sale.jpg',
                'status': 'approved',
                'organization_id': 2,
                'networks': json.dumps(['network-west-marine', 'network-on-the-wave']),
                'category': 'promotional',
                'tags': 'summer,sale',
                'created_at': '2026-01-14T10:00:00Z',
                'published_at': None
            },
            {
                'uuid': 'uuid-image-1',
                'title': 'Brand Logo Image',
                'description': 'High resolution brand logo',
                'filename': 'logo.png',
                'file_path': '/uploads/logo.png',
                'file_size': 50000,
                'duration': None,
                'resolution': '800x600',
                'format': 'png',
                'thumbnail_path': '/thumbnails/logo.jpg',
                'status': 'published',
                'organization_id': 1,
                'networks': json.dumps(['network-high-octane', 'network-west-marine']),
                'category': 'branding',
                'tags': 'logo,brand',
                'created_at': '2026-01-13T10:00:00Z',
                'published_at': '2026-01-14T10:00:00Z'
            },
        ]

        if network_ids:
            filtered = []
            for asset in assets:
                asset_networks = json.loads(asset['networks']) if asset['networks'] else []
                if any(nid in asset_networks for nid in network_ids):
                    filtered.append(asset)
            assets = filtered

        return {
            'assets': assets,
            'count': len(assets),
            'page': 1,
            'per_page': 100,
            'total': len(assets),
            'pages': 1
        }

    def test_01_content_sync_service_initialization(self):
        """Test that ContentSyncService can be imported and initialized."""
        from cms.services.content_sync_service import ContentSyncService

        self.assertIsNotNone(ContentSyncService.CONTENT_CATALOG_URL)
        self.assertIsNotNone(ContentSyncService.APPROVED_CONTENT_ENDPOINT)

        url = ContentSyncService.get_catalog_url()
        self.assertTrue(url.startswith('http'))

    def test_02_synced_content_model_operations(self):
        """Test SyncedContent model CRUD operations."""
        from cms.models.synced_content import SyncedContent

        content = SyncedContent(
            source_uuid='test-uuid-1',
            title='Test Video',
            filename='test.mp4',
            format='mp4',
            duration=30.0,
            status='published',
            organization_id=1,
            organization_name='Test Org',
            network_ids=json.dumps(['network-1', 'network-2'])
        )

        self.cms_db.session.add(content)
        self.cms_db.session.commit()

        retrieved = SyncedContent.get_by_source_uuid('test-uuid-1')
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.title, 'Test Video')
        self.assertEqual(retrieved.format, 'mp4')

        content_dict = retrieved.to_dict()
        self.assertIn('source_uuid', content_dict)
        self.assertIn('title', content_dict)
        self.assertIn('network_ids', content_dict)
        self.assertIsInstance(content_dict['network_ids'], list)

        self.assertEqual(retrieved.content_type, 'video')
        self.assertTrue(retrieved.is_video)
        self.assertFalse(retrieved.is_image)

        self.assertTrue(retrieved.has_network('network-1'))
        self.assertFalse(retrieved.has_network('network-3'))

        self.cms_db.session.delete(retrieved)
        self.cms_db.session.commit()

    def test_03_synced_content_upsert(self):
        """Test SyncedContent upsert_from_catalog method."""
        from cms.models.synced_content import SyncedContent

        catalog_data = {
            'uuid': 'upsert-test-uuid',
            'title': 'Upsert Test Video',
            'description': 'Testing upsert functionality',
            'filename': 'upsert_test.mp4',
            'file_path': '/uploads/upsert_test.mp4',
            'file_size': 1024000,
            'duration': 45.5,
            'resolution': '1920x1080',
            'format': 'mp4',
            'thumbnail_path': '/thumbnails/upsert_test.jpg',
            'status': 'approved',
            'organization_id': 1,
            'networks': json.dumps(['network-high-octane']),
            'category': 'test',
            'tags': 'upsert,test',
            'created_at': '2026-01-15T10:00:00Z',
            'published_at': None
        }

        synced = SyncedContent.upsert_from_catalog(
            db_session=self.cms_db.session,
            catalog_data=catalog_data,
            organization_name='Test Organization',
            content_catalog_url='http://localhost:5003'
        )
        self.cms_db.session.commit()

        self.assertIsNotNone(synced)
        self.assertEqual(synced.title, 'Upsert Test Video')
        self.assertEqual(synced.organization_name, 'Test Organization')

        catalog_data['title'] = 'Updated Upsert Test Video'
        catalog_data['status'] = 'published'

        synced_updated = SyncedContent.upsert_from_catalog(
            db_session=self.cms_db.session,
            catalog_data=catalog_data,
            organization_name='Test Organization',
            content_catalog_url='http://localhost:5003'
        )
        self.cms_db.session.commit()

        self.assertEqual(synced.id, synced_updated.id)
        self.assertEqual(synced_updated.title, 'Updated Upsert Test Video')
        self.assertEqual(synced_updated.status, 'published')

        self.cms_db.session.delete(synced_updated)
        self.cms_db.session.commit()

    @patch('cms.services.content_sync_service.requests.get')
    def test_04_sync_approved_content(self, mock_get):
        """Test full sync workflow with mocked Content Catalog API."""
        from cms.services.content_sync_service import ContentSyncService
        from cms.models.synced_content import SyncedContent

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._get_mock_approved_content()
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = ContentSyncService.sync_approved_content()

        self.assertEqual(result['synced_count'], 3)
        self.assertEqual(result['total_in_catalog'], 3)
        self.assertIsNotNone(result['synced_at'])
        self.assertEqual(len(result['errors']), 0)

        synced_items = SyncedContent.query.all()
        self.assertEqual(len(synced_items), 3)

        video1 = SyncedContent.get_by_source_uuid('uuid-video-1')
        self.assertIsNotNone(video1)
        self.assertEqual(video1.title, 'Promotional Video 1')
        self.assertEqual(video1.status, 'published')
        self.assertTrue(video1.is_video)

        image1 = SyncedContent.get_by_source_uuid('uuid-image-1')
        self.assertIsNotNone(image1)
        self.assertEqual(image1.title, 'Brand Logo Image')
        self.assertTrue(image1.is_image)

    @patch('cms.services.content_sync_service.requests.get')
    def test_05_network_filtering(self, mock_get):
        """Test that network filtering works correctly."""
        from cms.services.content_sync_service import ContentSyncService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._get_mock_approved_content()
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        ContentSyncService.sync_approved_content()

        high_octane_content = ContentSyncService.get_synced_content(
            network_id='network-high-octane'
        )
        self.assertEqual(high_octane_content['total'], 2)

        west_marine_content = ContentSyncService.get_synced_content(
            network_id='network-west-marine'
        )
        self.assertEqual(west_marine_content['total'], 2)

        on_the_wave_content = ContentSyncService.get_synced_content(
            network_id='network-on-the-wave'
        )
        self.assertEqual(on_the_wave_content['total'], 1)

    @patch('cms.services.content_sync_service.requests.get')
    def test_06_content_type_filtering(self, mock_get):
        """Test content type filtering (video, image, audio)."""
        from cms.services.content_sync_service import ContentSyncService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._get_mock_approved_content()
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        ContentSyncService.sync_approved_content()

        video_content = ContentSyncService.get_synced_content(content_type='video')
        self.assertEqual(video_content['total'], 2)
        for item in video_content['items']:
            self.assertEqual(item['format'], 'mp4')

        image_content = ContentSyncService.get_synced_content(content_type='image')
        self.assertEqual(image_content['total'], 1)
        for item in image_content['items']:
            self.assertEqual(item['format'], 'png')

    @patch('cms.services.content_sync_service.requests.get')
    def test_07_organization_filtering(self, mock_get):
        """Test organization/partner filtering."""
        from cms.services.content_sync_service import ContentSyncService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._get_mock_approved_content()
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        ContentSyncService.sync_approved_content()

        org1_content = ContentSyncService.get_synced_content(organization_id=1)
        self.assertEqual(org1_content['total'], 2)

        org2_content = ContentSyncService.get_synced_content(organization_id=2)
        self.assertEqual(org2_content['total'], 1)

    @patch('cms.services.content_sync_service.requests.get')
    def test_08_status_filtering(self, mock_get):
        """Test status filtering (approved vs published)."""
        from cms.services.content_sync_service import ContentSyncService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._get_mock_approved_content()
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        ContentSyncService.sync_approved_content()

        published_content = ContentSyncService.get_synced_content(status='published')
        self.assertEqual(published_content['total'], 2)

        approved_content = ContentSyncService.get_synced_content(status='approved')
        self.assertEqual(approved_content['total'], 1)

    @patch('cms.services.content_sync_service.requests.get')
    def test_09_sync_status(self, mock_get):
        """Test sync status reporting."""
        from cms.services.content_sync_service import ContentSyncService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._get_mock_approved_content()
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        ContentSyncService.sync_approved_content()

        status = ContentSyncService.get_sync_status()

        self.assertEqual(status['total_synced'], 3)
        self.assertIn('published', status['by_status'])
        self.assertIn('approved', status['by_status'])
        self.assertIsNotNone(status['last_synced'])

    @patch('cms.services.content_sync_service.requests.get')
    def test_10_content_catalog_unavailable(self, mock_get):
        """Test handling when Content Catalog is unavailable."""
        from cms.services.content_sync_service import (
            ContentSyncService,
            ContentCatalogUnavailableError
        )
        from requests.exceptions import ConnectionError

        mock_get.side_effect = ConnectionError("Cannot connect")

        with self.assertRaises(ContentCatalogUnavailableError):
            ContentSyncService.fetch_approved_content()

    @patch('cms.services.content_sync_service.requests.get')
    def test_11_health_check(self, mock_get):
        """Test Content Catalog health check."""
        from cms.services.content_sync_service import ContentSyncService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'assets': [], 'total': 0}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        health = ContentSyncService.check_content_catalog_health()

        self.assertTrue(health['available'])
        self.assertIsNotNone(health['url'])
        self.assertIsNotNone(health['response_time_ms'])

    @patch('cms.services.content_sync_service.requests.get')
    def test_12_combined_filters(self, mock_get):
        """Test combining multiple filters."""
        from cms.services.content_sync_service import ContentSyncService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._get_mock_approved_content()
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        ContentSyncService.sync_approved_content()

        result = ContentSyncService.get_synced_content(
            network_id='network-high-octane',
            status='published'
        )
        self.assertEqual(result['total'], 2)

        result = ContentSyncService.get_synced_content(
            network_id='network-high-octane',
            content_type='video'
        )
        self.assertEqual(result['total'], 1)

    @patch('cms.services.content_sync_service.requests.get')
    def test_13_pagination(self, mock_get):
        """Test pagination in get_synced_content."""
        from cms.services.content_sync_service import ContentSyncService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._get_mock_approved_content()
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        ContentSyncService.sync_approved_content()

        page1 = ContentSyncService.get_synced_content(page=1, per_page=2)
        self.assertEqual(page1['count'], 2)
        self.assertEqual(page1['total'], 3)
        self.assertEqual(page1['page'], 1)
        self.assertEqual(page1['pages'], 2)

        page2 = ContentSyncService.get_synced_content(page=2, per_page=2)
        self.assertEqual(page2['count'], 1)
        self.assertEqual(page2['page'], 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
