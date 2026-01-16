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
    User,
    UserSession,
    UserInvitation,
    AuditLog,
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


# =============================================================================
# User Authentication Fixtures
# =============================================================================


@pytest.fixture(scope='function')
def sample_super_admin(db_session):
    """
    Create a sample super admin user for testing.

    Args:
        db_session: Database session fixture

    Returns:
        User instance with super_admin role
    """
    user = User(
        email='superadmin@test.com',
        name='Test Super Admin',
        role='super_admin',
        status='active',
        network_id=None  # Super admins have access to all networks
    )
    user.set_password('TestPassword123!')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_admin(db_session, sample_network):
    """
    Create a sample admin user for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key

    Returns:
        User instance with admin role
    """
    user = User(
        email='admin@test.com',
        name='Test Admin',
        role='admin',
        status='active',
        network_id=sample_network.id
    )
    user.set_password('TestPassword123!')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_content_manager(db_session, sample_network):
    """
    Create a sample content manager user for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key

    Returns:
        User instance with content_manager role
    """
    user = User(
        email='content_manager@test.com',
        name='Test Content Manager',
        role='content_manager',
        status='active',
        network_id=sample_network.id
    )
    user.set_password('TestPassword123!')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_viewer(db_session, sample_network):
    """
    Create a sample viewer user for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key

    Returns:
        User instance with viewer role
    """
    user = User(
        email='viewer@test.com',
        name='Test Viewer',
        role='viewer',
        status='active',
        network_id=sample_network.id
    )
    user.set_password('TestPassword123!')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_pending_user(db_session, sample_network, sample_admin):
    """
    Create a sample pending user (awaiting approval) for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key
        sample_admin: Admin user who invited this user

    Returns:
        User instance with pending status
    """
    user = User(
        email='pending@test.com',
        name='Test Pending User',
        role='content_manager',
        status='pending',
        network_id=sample_network.id,
        invited_by=sample_admin.id
    )
    user.set_password('TestPassword123!')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_suspended_user(db_session, sample_network, sample_admin):
    """
    Create a sample suspended user for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key
        sample_admin: Admin user who suspended this user

    Returns:
        User instance with suspended status
    """
    user = User(
        email='suspended@test.com',
        name='Test Suspended User',
        role='content_manager',
        status='suspended',
        network_id=sample_network.id,
        suspended_by=sample_admin.id,
        suspended_at=datetime.now(timezone.utc),
        suspended_reason='Test suspension'
    )
    user.set_password('TestPassword123!')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_user_session(db_session, sample_admin):
    """
    Create a sample user session for testing.

    Args:
        db_session: Database session fixture
        sample_admin: User fixture for foreign key

    Returns:
        UserSession instance
    """
    session = UserSession.create_session(
        user_id=sample_admin.id,
        ip_address='127.0.0.1',
        user_agent='Test User Agent',
        device_info='Test Device',
        remember_me=False
    )
    db_session.add(session)
    db_session.commit()
    return session


@pytest.fixture(scope='function')
def sample_user_session_remember_me(db_session, sample_admin):
    """
    Create a sample user session with "remember me" enabled for testing.

    Args:
        db_session: Database session fixture
        sample_admin: User fixture for foreign key

    Returns:
        UserSession instance with extended expiration
    """
    session = UserSession.create_session(
        user_id=sample_admin.id,
        ip_address='192.168.1.1',
        user_agent='Test User Agent - Remember Me',
        device_info='Test Device - Remember Me',
        remember_me=True
    )
    db_session.add(session)
    db_session.commit()
    return session


@pytest.fixture(scope='function')
def sample_user_invitation(db_session, sample_network, sample_admin):
    """
    Create a sample user invitation for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key
        sample_admin: Admin user who created the invitation

    Returns:
        UserInvitation instance
    """
    from datetime import timedelta
    invitation = UserInvitation(
        email='invited@test.com',
        role='content_manager',
        network_id=sample_network.id,
        invited_by=sample_admin.id,
        status='pending',
        expires_at=datetime.now(timezone.utc) + timedelta(days=7)
    )
    db_session.add(invitation)
    db_session.commit()
    return invitation


@pytest.fixture(scope='function')
def sample_expired_invitation(db_session, sample_network, sample_admin):
    """
    Create a sample expired user invitation for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key
        sample_admin: Admin user who created the invitation

    Returns:
        UserInvitation instance that has expired
    """
    from datetime import timedelta
    invitation = UserInvitation(
        email='expired@test.com',
        role='content_manager',
        network_id=sample_network.id,
        invited_by=sample_admin.id,
        status='pending',
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)  # Expired yesterday
    )
    db_session.add(invitation)
    db_session.commit()
    return invitation


@pytest.fixture(scope='function')
def sample_audit_log(db_session, sample_admin):
    """
    Create a sample audit log entry for testing.

    Args:
        db_session: Database session fixture
        sample_admin: User who performed the action

    Returns:
        AuditLog instance
    """
    import json
    audit_log = AuditLog(
        user_id=sample_admin.id,
        user_email=sample_admin.email,
        user_name=sample_admin.name,
        user_role=sample_admin.role,
        action='user.login',
        action_category='auth',
        resource_type=None,
        resource_id=None,
        resource_name=None,
        details=json.dumps({'method': 'password'}),
        ip_address='127.0.0.1',
        user_agent='Test User Agent',
        session_id=None
    )
    db_session.add(audit_log)
    db_session.commit()
    return audit_log


@pytest.fixture(scope='function')
def sample_audit_log_user_action(db_session, sample_admin, sample_content_manager):
    """
    Create a sample audit log entry for a user management action.

    Args:
        db_session: Database session fixture
        sample_admin: User who performed the action
        sample_content_manager: User who was the target of the action

    Returns:
        AuditLog instance for a user management action
    """
    import json
    audit_log = AuditLog(
        user_id=sample_admin.id,
        user_email=sample_admin.email,
        user_name=sample_admin.name,
        user_role=sample_admin.role,
        action='user.update',
        action_category='users',
        resource_type='user',
        resource_id=sample_content_manager.id,
        resource_name=sample_content_manager.email,
        details=json.dumps({
            'before': {'name': 'Old Name'},
            'after': {'name': sample_content_manager.name}
        }),
        ip_address='127.0.0.1',
        user_agent='Test User Agent',
        session_id=None
    )
    db_session.add(audit_log)
    db_session.commit()
    return audit_log


@pytest.fixture(scope='function')
def sample_user_with_must_change_password(db_session, sample_network):
    """
    Create a sample user who must change their password on login.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key

    Returns:
        User instance with must_change_password=True
    """
    user = User(
        email='must_change@test.com',
        name='Test Must Change Password',
        role='content_manager',
        status='active',
        network_id=sample_network.id,
        must_change_password=True
    )
    user.set_password('TempPassword123!')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_locked_user(db_session, sample_network):
    """
    Create a sample user who is locked due to failed login attempts.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for foreign key

    Returns:
        User instance with locked_until set
    """
    from datetime import timedelta
    user = User(
        email='locked@test.com',
        name='Test Locked User',
        role='content_manager',
        status='active',
        network_id=sample_network.id,
        failed_login_attempts=5,
        locked_until=datetime.now(timezone.utc) + timedelta(minutes=15)
    )
    user.set_password('TestPassword123!')
    db_session.add(user)
    db_session.commit()
    return user


# =============================================================================
# User Authentication Helper Functions
# =============================================================================


def create_test_user(db_session, email, name, role, status='active',
                     network_id=None, password='TestPassword123!',
                     must_change_password=False):
    """
    Helper function to create a user with custom attributes.

    Args:
        db_session: Database session
        email: User email address
        name: User's display name
        role: User role ('super_admin', 'admin', 'content_manager', 'viewer')
        status: Account status (default: 'active')
        network_id: Network ID (optional)
        password: Password to set (default: 'TestPassword123!')
        must_change_password: Whether user must change password on login

    Returns:
        User instance
    """
    user = User(
        email=email,
        name=name,
        role=role,
        status=status,
        network_id=network_id,
        must_change_password=must_change_password
    )
    user.set_password(password)
    db_session.add(user)
    db_session.commit()
    return user


def create_test_session(db_session, user_id, ip_address='127.0.0.1',
                        user_agent='Test Agent', remember_me=False):
    """
    Helper function to create a user session with custom attributes.

    Args:
        db_session: Database session
        user_id: ID of the user to create session for
        ip_address: Client IP address
        user_agent: Client user agent string
        remember_me: Whether to extend session duration

    Returns:
        UserSession instance
    """
    session = UserSession.create_session(
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        remember_me=remember_me
    )
    db_session.add(session)
    db_session.commit()
    return session


def create_test_invitation(db_session, email, role, invited_by,
                           network_id=None, status='pending', days_valid=7):
    """
    Helper function to create a user invitation with custom attributes.

    Args:
        db_session: Database session
        email: Email address for the invitation
        role: Role to assign to the invited user
        invited_by: ID of the user who created the invitation
        network_id: Network ID (optional)
        status: Invitation status (default: 'pending')
        days_valid: Number of days until expiration (default: 7)

    Returns:
        UserInvitation instance
    """
    from datetime import timedelta
    invitation = UserInvitation(
        email=email,
        role=role,
        network_id=network_id,
        invited_by=invited_by,
        status=status,
        expires_at=datetime.now(timezone.utc) + timedelta(days=days_valid)
    )
    db_session.add(invitation)
    db_session.commit()
    return invitation


def create_test_audit_log(db_session, user_id, user_email, action,
                          action_category, user_name=None, user_role=None,
                          resource_type=None, resource_id=None, resource_name=None,
                          details=None, ip_address='127.0.0.1', user_agent='Test Agent',
                          session_id=None):
    """
    Helper function to create an audit log entry with custom attributes.

    Args:
        db_session: Database session
        user_id: ID of the user who performed the action
        user_email: Email of the user
        action: Action performed (e.g., 'user.login', 'user.create')
        action_category: Category of action ('auth', 'users', etc.)
        user_name: Name of the user (optional)
        user_role: Role of the user (optional)
        resource_type: Type of affected resource (optional)
        resource_id: ID of affected resource (optional)
        resource_name: Name of affected resource (optional)
        details: JSON string with additional details (optional)
        ip_address: Client IP address
        user_agent: Client user agent string
        session_id: Session ID (optional)

    Returns:
        AuditLog instance
    """
    audit_log = AuditLog(
        user_id=user_id,
        user_email=user_email,
        user_name=user_name,
        user_role=user_role,
        action=action,
        action_category=action_category,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent,
        session_id=session_id
    )
    db_session.add(audit_log)
    db_session.commit()
    return audit_log
