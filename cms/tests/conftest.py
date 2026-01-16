"""
Pytest configuration and fixtures for CMS tests.

This module provides shared fixtures for testing:
- Flask application with test configuration
- In-memory SQLite database
- Test client
- Sample model instances for all CMS models
- Mock services
"""

import os
import sys
import tempfile
from datetime import datetime, timezone
from typing import Generator

import pytest

# Add project root to path for cms package imports
# The cms directory is a package, so we need the parent (repo root) in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cms.app import create_app
from cms.models import (
    db,
    Network,
    Hub,
    Device,
    Content,
    Playlist,
    PlaylistItem,
    DeviceAssignment,
)


@pytest.fixture(scope='function')
def app():
    """
    Create a Flask application configured for testing.

    This fixture provides an isolated Flask app with:
    - In-memory SQLite database
    - Testing mode enabled
    - Clean database tables

    Yields:
        Flask application instance
    """
    # Create temp directory for uploads during tests
    temp_upload_dir = tempfile.mkdtemp()

    # Create the app with test config
    application = create_app(config_name='testing')
    application.config['TESTING'] = True
    application.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    application.config['UPLOADS_PATH'] = temp_upload_dir

    # Create all tables in test database
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


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
def sample_network(db_session):
    """
    Create a sample Network record for testing.

    Args:
        db_session: Database session fixture

    Returns:
        Network instance
    """
    network = Network(
        name='Test Network',
        slug='test-network'
    )
    db_session.add(network)
    db_session.commit()
    return network


@pytest.fixture(scope='function')
def sample_hub(db_session, sample_network):
    """
    Create a sample Hub record for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key

    Returns:
        Hub instance
    """
    hub = Hub(
        code='TST',
        name='Test Hub',
        network_id=sample_network.id,
        status='active'
    )
    db_session.add(hub)
    db_session.commit()
    return hub


@pytest.fixture(scope='function')
def sample_device_direct(db_session, sample_network):
    """
    Create a sample Device in direct mode for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key

    Returns:
        Device instance configured in direct mode
    """
    device = Device(
        device_id='SKZ-D-0001',
        hardware_id='test-hw-direct-001',
        mode='direct',
        name='Test Direct Device 1',
        status='active',
        network_id=sample_network.id,
        last_seen=datetime.now(timezone.utc)
    )
    db_session.add(device)
    db_session.commit()
    return device


@pytest.fixture(scope='function')
def sample_device_hub(db_session, sample_network, sample_hub):
    """
    Create a sample Device in hub mode for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key
        sample_hub: Hub fixture for foreign key

    Returns:
        Device instance configured in hub mode
    """
    device = Device(
        device_id=f'SKZ-H-{sample_hub.code}-0001',
        hardware_id='test-hw-hub-001',
        mode='hub',
        hub_id=sample_hub.id,
        name='Test Hub Device 1',
        status='active',
        network_id=sample_network.id,
        last_seen=datetime.now(timezone.utc)
    )
    db_session.add(device)
    db_session.commit()
    return device


@pytest.fixture(scope='function')
def sample_content(db_session, sample_network):
    """
    Create a sample Content record for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key

    Returns:
        Content instance
    """
    content = Content(
        filename='test_video_abc123.mp4',
        original_name='test_video.mp4',
        mime_type='video/mp4',
        file_size=10240000,
        width=1920,
        height=1080,
        duration=60,
        network_id=sample_network.id
    )
    db_session.add(content)
    db_session.commit()
    return content


@pytest.fixture(scope='function')
def sample_image_content(db_session, sample_network):
    """
    Create a sample image Content record for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key

    Returns:
        Content instance for an image
    """
    content = Content(
        filename='test_image_def456.jpg',
        original_name='test_image.jpg',
        mime_type='image/jpeg',
        file_size=512000,
        width=1920,
        height=1080,
        duration=None,
        network_id=sample_network.id
    )
    db_session.add(content)
    db_session.commit()
    return content


@pytest.fixture(scope='function')
def sample_playlist(db_session, sample_network):
    """
    Create a sample Playlist record for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key

    Returns:
        Playlist instance
    """
    playlist = Playlist(
        name='Test Playlist',
        description='A test playlist for unit testing',
        network_id=sample_network.id,
        trigger_type='manual',
        trigger_config=None,
        is_active=True
    )
    db_session.add(playlist)
    db_session.commit()
    return playlist


@pytest.fixture(scope='function')
def sample_playlist_with_items(db_session, sample_network, sample_content, sample_image_content):
    """
    Create a sample Playlist with items for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key
        sample_content: Video content fixture
        sample_image_content: Image content fixture

    Returns:
        Playlist instance with items
    """
    playlist = Playlist(
        name='Test Playlist with Items',
        description='A test playlist with content items',
        network_id=sample_network.id,
        trigger_type='time',
        trigger_config='{"schedule": "daily", "time": "09:00"}',
        is_active=True
    )
    db_session.add(playlist)
    db_session.commit()

    # Add playlist items
    item1 = PlaylistItem(
        playlist_id=playlist.id,
        content_id=sample_content.id,
        position=0,
        duration_override=None
    )
    item2 = PlaylistItem(
        playlist_id=playlist.id,
        content_id=sample_image_content.id,
        position=1,
        duration_override=10  # 10 seconds for image
    )
    db_session.add(item1)
    db_session.add(item2)
    db_session.commit()

    return playlist


@pytest.fixture(scope='function')
def sample_device_assignment(db_session, sample_device_direct, sample_playlist):
    """
    Create a sample DeviceAssignment record for testing.

    Args:
        db_session: Database session fixture
        sample_device_direct: Device fixture
        sample_playlist: Playlist fixture

    Returns:
        DeviceAssignment instance
    """
    assignment = DeviceAssignment(
        device_id=sample_device_direct.id,
        playlist_id=sample_playlist.id,
        priority=1,
        start_date=None,
        end_date=None
    )
    db_session.add(assignment)
    db_session.commit()
    return assignment


@pytest.fixture(scope='function')
def sample_complete_setup(db_session, sample_network, sample_hub, sample_device_direct,
                          sample_device_hub, sample_content, sample_playlist):
    """
    Create a complete setup with all related entities for integration testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture
        sample_hub: Hub fixture
        sample_device_direct: Direct device fixture
        sample_device_hub: Hub device fixture
        sample_content: Content fixture
        sample_playlist: Playlist fixture

    Returns:
        Dictionary with all created entities
    """
    # Create playlist item linking content to playlist
    playlist_item = PlaylistItem(
        playlist_id=sample_playlist.id,
        content_id=sample_content.id,
        position=0
    )
    db_session.add(playlist_item)

    # Create device assignments for both devices
    assignment_direct = DeviceAssignment(
        device_id=sample_device_direct.id,
        playlist_id=sample_playlist.id,
        priority=1
    )
    assignment_hub = DeviceAssignment(
        device_id=sample_device_hub.id,
        playlist_id=sample_playlist.id,
        priority=1
    )
    db_session.add(assignment_direct)
    db_session.add(assignment_hub)
    db_session.commit()

    return {
        'network': sample_network,
        'hub': sample_hub,
        'device_direct': sample_device_direct,
        'device_hub': sample_device_hub,
        'content': sample_content,
        'playlist': sample_playlist,
        'playlist_item': playlist_item,
        'assignment_direct': assignment_direct,
        'assignment_hub': assignment_hub
    }


# Test helper functions

def create_test_network(db_session, name='Test Network', slug='test-network'):
    """
    Helper function to create a network with custom attributes.

    Args:
        db_session: Database session
        name: Network name
        slug: Network slug

    Returns:
        Network instance
    """
    network = Network(name=name, slug=slug)
    db_session.add(network)
    db_session.commit()
    return network


def create_test_hub(db_session, network_id, code='TST', name='Test Hub', status='active'):
    """
    Helper function to create a hub with custom attributes.

    Args:
        db_session: Database session
        network_id: Parent network ID
        code: Hub code
        name: Hub name
        status: Hub status

    Returns:
        Hub instance
    """
    hub = Hub(
        code=code,
        name=name,
        network_id=network_id,
        status=status
    )
    db_session.add(hub)
    db_session.commit()
    return hub


def create_test_device(db_session, device_id, hardware_id, mode='direct',
                       hub_id=None, network_id=None, name=None, status='pending'):
    """
    Helper function to create a device with custom attributes.

    Args:
        db_session: Database session
        device_id: Device ID (SKZ-D-XXXX or SKZ-H-CODE-XXXX format)
        hardware_id: Hardware identifier
        mode: Device mode ('direct' or 'hub')
        hub_id: Parent hub ID (for hub mode)
        network_id: Network ID
        name: Device name
        status: Device status

    Returns:
        Device instance
    """
    device = Device(
        device_id=device_id,
        hardware_id=hardware_id,
        mode=mode,
        hub_id=hub_id,
        network_id=network_id,
        name=name,
        status=status
    )
    db_session.add(device)
    db_session.commit()
    return device


def create_test_content(db_session, filename, original_name, mime_type,
                        file_size, network_id=None, width=None, height=None, duration=None):
    """
    Helper function to create content with custom attributes.

    Args:
        db_session: Database session
        filename: Stored filename
        original_name: Original filename
        mime_type: MIME type
        file_size: File size in bytes
        network_id: Network ID
        width: Content width
        height: Content height
        duration: Duration in seconds

    Returns:
        Content instance
    """
    content = Content(
        filename=filename,
        original_name=original_name,
        mime_type=mime_type,
        file_size=file_size,
        network_id=network_id,
        width=width,
        height=height,
        duration=duration
    )
    db_session.add(content)
    db_session.commit()
    return content


def create_test_playlist(db_session, name, network_id=None, description=None,
                         trigger_type='manual', trigger_config=None, is_active=True):
    """
    Helper function to create a playlist with custom attributes.

    Args:
        db_session: Database session
        name: Playlist name
        network_id: Network ID
        description: Playlist description
        trigger_type: Trigger type
        trigger_config: Trigger configuration JSON
        is_active: Whether playlist is active

    Returns:
        Playlist instance
    """
    playlist = Playlist(
        name=name,
        description=description,
        network_id=network_id,
        trigger_type=trigger_type,
        trigger_config=trigger_config,
        is_active=is_active
    )
    db_session.add(playlist)
    db_session.commit()
    return playlist
