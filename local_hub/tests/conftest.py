"""
Pytest configuration and fixtures for Local Hub tests.

This module provides shared fixtures for testing:
- Flask application with test configuration
- In-memory SQLite database
- Test client
- Sample model instances
- Mock services
"""

import json
import os
import sys
import tempfile
from datetime import datetime
from typing import Generator

import pytest

# Add local_hub to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from config import reset_config
from models import db, HubConfig, Screen, Content, PendingAlert, SyncStatus


@pytest.fixture(scope='function')
def temp_config_file():
    """
    Create a temporary config file for testing.

    Yields:
        Path to temporary config file
    """
    config_data = {
        'hq_url': 'https://test-hub.skillzmedia.com',
        'network_slug': 'test-network',
        'sync_interval_minutes': 1,
        'heartbeat_interval_seconds': 10,
        'alert_retry_interval_seconds': 5,
        'storage_path': tempfile.mkdtemp(),
        'log_path': tempfile.mkdtemp(),
        'port': 5001
    }

    # Create temp config file
    fd, config_path = tempfile.mkstemp(suffix='.json')
    with os.fdopen(fd, 'w') as f:
        json.dump(config_data, f)

    yield config_path

    # Cleanup
    os.unlink(config_path)


@pytest.fixture(scope='function')
def app(temp_config_file):
    """
    Create a Flask application configured for testing.

    This fixture provides an isolated Flask app with:
    - In-memory SQLite database
    - Testing mode enabled
    - Scheduler disabled
    - Clean database tables

    Yields:
        Flask application instance
    """
    # Reset global config before creating app
    reset_config()

    # Create the app with test config
    application = create_app(config_path=temp_config_file)
    application.config['TESTING'] = True
    application.config['SCHEDULER_ENABLED'] = False

    # Create all tables in test database
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()

    # Reset config after test
    reset_config()


@pytest.fixture(scope='function')
def client(app):
    """
    Create a test client for the Flask application.

    Args:
        app: Flask application fixture

    Yields:
        Flask test client
    """
    return app.test_client()


@pytest.fixture(scope='function')
def db_session(app):
    """
    Provide a database session for testing.

    This fixture ensures clean database state for each test.

    Args:
        app: Flask application fixture

    Yields:
        SQLAlchemy session
    """
    with app.app_context():
        yield db.session


@pytest.fixture(scope='function')
def sample_hub_config(db_session):
    """
    Create a sample HubConfig record for testing.

    Args:
        db_session: Database session fixture

    Returns:
        HubConfig instance
    """
    config = HubConfig.get_instance()
    config.update_registration(
        hub_id='test-hub-123',
        hub_token='test-token-abc',
        network_id='test-network-456',
        store_id='test-store-789'
    )
    return config


@pytest.fixture(scope='function')
def sample_screen(db_session):
    """
    Create a sample Screen record for testing.

    Args:
        db_session: Database session fixture

    Returns:
        Screen instance
    """
    screen = Screen(
        hardware_id='test-hw-001',
        name='Test Screen 1',
        status='online',
        camera_enabled=True,
        facial_recognition_enabled=False,
        playlist_version=1
    )
    db_session.add(screen)
    db_session.commit()
    return screen


@pytest.fixture(scope='function')
def sample_content(db_session):
    """
    Create a sample Content record for testing.

    Args:
        db_session: Database session fixture

    Returns:
        Content instance
    """
    content = Content(
        content_id='content-001',
        filename='test_video.mp4',
        file_hash='abc123def456',
        file_size=1024000,
        content_type='video/mp4',
        local_path='/var/skillz-hub/storage/content/test_video.mp4'
    )
    db_session.add(content)
    db_session.commit()
    return content


@pytest.fixture(scope='function')
def sample_pending_alert(db_session):
    """
    Create a sample PendingAlert record for testing.

    Args:
        db_session: Database session fixture

    Returns:
        PendingAlert instance
    """
    alert = PendingAlert(
        alert_type='face_match',
        screen_id=1,
        payload={'match_id': 'test-match-001', 'confidence': 0.95},
        attempts=0
    )
    db_session.add(alert)
    db_session.commit()
    return alert


@pytest.fixture(scope='function')
def sample_sync_status(db_session):
    """
    Create a sample SyncStatus record for testing.

    Args:
        db_session: Database session fixture

    Returns:
        SyncStatus instance
    """
    sync_status = SyncStatus(
        sync_type='content',
        version='v1.0.0',
        file_hash='xyz789abc123',
        last_sync=datetime.utcnow()
    )
    db_session.add(sync_status)
    db_session.commit()
    return sync_status


@pytest.fixture(scope='function')
def multiple_screens(db_session):
    """
    Create multiple Screen records for testing.

    Args:
        db_session: Database session fixture

    Returns:
        List of Screen instances
    """
    screens = []
    for i in range(3):
        screen = Screen(
            hardware_id=f'test-hw-{i:03d}',
            name=f'Test Screen {i}',
            status='online' if i % 2 == 0 else 'offline',
            camera_enabled=i % 2 == 0,
            facial_recognition_enabled=False,
            playlist_version=i
        )
        db_session.add(screen)
        screens.append(screen)
    db_session.commit()
    return screens


@pytest.fixture(scope='function')
def mock_hq_responses():
    """
    Provide mock responses for HQ API calls.

    Returns:
        Dictionary of mock responses keyed by endpoint
    """
    return {
        '/api/v1/hub/register': {
            'hub_id': 'mock-hub-123',
            'hub_token': 'mock-token-xyz',
            'network_id': 'mock-network-456',
            'store_id': 'mock-store-789'
        },
        '/api/v1/hub/heartbeat': {
            'status': 'ok',
            'server_time': datetime.utcnow().isoformat()
        },
        '/api/v1/content/manifest': {
            'version': 'v2.0.0',
            'content': [
                {
                    'content_id': 'content-001',
                    'filename': 'video1.mp4',
                    'file_hash': 'hash001',
                    'file_size': 1000000,
                    'content_type': 'video/mp4',
                    'download_url': 'https://cdn.example.com/video1.mp4'
                }
            ]
        },
        '/api/v1/alerts': {
            'status': 'received',
            'alert_id': 'alert-001'
        }
    }


class MockResponse:
    """Mock HTTP response for testing HTTP clients."""

    def __init__(self, json_data, status_code=200, text=''):
        self.json_data = json_data
        self.status_code = status_code
        self.text = text or json.dumps(json_data)
        self.ok = 200 <= status_code < 300

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if not self.ok:
            from requests import HTTPError
            raise HTTPError(f'{self.status_code} Error')


@pytest.fixture(scope='function')
def mock_response_factory():
    """
    Factory fixture for creating mock HTTP responses.

    Returns:
        Function that creates MockResponse instances
    """
    def _create_response(json_data, status_code=200, text=''):
        return MockResponse(json_data, status_code, text)
    return _create_response
