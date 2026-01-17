"""
Pytest configuration and fixtures for Content Catalog tests.

This module provides shared fixtures for testing:
- Flask application with test configuration
- In-memory SQLite database
- Test client
- Sample model instances for all Content Catalog models
- Mock services
- Helper functions for creating test data
"""

import os
import secrets
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Generator

import bcrypt
import pytest

# Add project root to path for content_catalog package imports
# The content_catalog directory is a package, so we need the parent (repo root) in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from content_catalog.app import create_app
from content_catalog.models import (
    db,
    Organization,
    User,
    UserInvitation,
    UserApprovalRequest,
    AdminSession,
    AuditLog,
    ContentAsset,
    ContentApprovalRequest,
)


# Test password constant (hashed once to save time in tests)
TEST_PASSWORD = 'TestPassword123!'
TEST_PASSWORD_HASH = bcrypt.hashpw(TEST_PASSWORD.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')


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
    temp_thumbnail_dir = os.path.join(temp_upload_dir, 'thumbnails')
    os.makedirs(temp_thumbnail_dir, exist_ok=True)

    # Create the app with test config
    application = create_app(config_name='testing')
    application.config['TESTING'] = True
    application.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    application.config['UPLOADS_PATH'] = temp_upload_dir
    application.config['THUMBNAILS_PATH'] = temp_thumbnail_dir
    application.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for tests
    application.config['MAIL_SUPPRESS_SEND'] = True  # Suppress email sending

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


# Organization Fixtures

@pytest.fixture(scope='function')
def sample_organization(db_session):
    """
    Create a sample Organization record for testing.

    Args:
        db_session: Database session fixture

    Returns:
        Organization instance
    """
    org = Organization(
        name='Test Organization',
        type='partner',
        contact_email='contact@testorg.com',
        status='active'
    )
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture(scope='function')
def sample_internal_organization(db_session):
    """
    Create a sample internal (Skillz Media) Organization for testing.

    Args:
        db_session: Database session fixture

    Returns:
        Organization instance for internal organization
    """
    org = Organization(
        name='Skillz Media',
        type='internal',
        contact_email='admin@skillzmedia.com',
        status='active'
    )
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture(scope='function')
def sample_advertiser_organization(db_session):
    """
    Create a sample advertiser Organization for testing.

    Args:
        db_session: Database session fixture

    Returns:
        Organization instance for advertiser
    """
    org = Organization(
        name='Test Advertiser Corp',
        type='advertiser',
        contact_email='ads@advertiser.com',
        status='active'
    )
    org.generate_api_key()
    db_session.add(org)
    db_session.commit()
    return org


# User Fixtures

@pytest.fixture(scope='function')
def sample_super_admin(db_session, sample_internal_organization):
    """
    Create a sample Super Admin user for testing.

    Args:
        db_session: Database session fixture
        sample_internal_organization: Internal organization fixture

    Returns:
        User instance with super_admin role
    """
    user = User(
        email='superadmin@skillzmedia.com',
        password_hash=TEST_PASSWORD_HASH,
        name='Super Admin',
        role=User.ROLE_SUPER_ADMIN,
        organization_id=sample_internal_organization.id,
        status=User.STATUS_ACTIVE
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_admin(db_session, sample_internal_organization, sample_super_admin):
    """
    Create a sample Admin user for testing.

    Args:
        db_session: Database session fixture
        sample_internal_organization: Internal organization fixture
        sample_super_admin: Super admin user who approved this admin

    Returns:
        User instance with admin role
    """
    user = User(
        email='admin@skillzmedia.com',
        password_hash=TEST_PASSWORD_HASH,
        name='Admin User',
        role=User.ROLE_ADMIN,
        organization_id=sample_internal_organization.id,
        status=User.STATUS_ACTIVE,
        approved_by=sample_super_admin.id,
        approved_at=datetime.now(timezone.utc)
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_content_manager(db_session, sample_internal_organization, sample_admin):
    """
    Create a sample Content Manager user for testing.

    Args:
        db_session: Database session fixture
        sample_internal_organization: Internal organization fixture
        sample_admin: Admin user who approved this content manager

    Returns:
        User instance with content_manager role
    """
    user = User(
        email='contentmanager@skillzmedia.com',
        password_hash=TEST_PASSWORD_HASH,
        name='Content Manager',
        role=User.ROLE_CONTENT_MANAGER,
        organization_id=sample_internal_organization.id,
        status=User.STATUS_ACTIVE,
        approved_by=sample_admin.id,
        approved_at=datetime.now(timezone.utc)
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_partner(db_session, sample_organization, sample_admin):
    """
    Create a sample Partner user for testing.

    Args:
        db_session: Database session fixture
        sample_organization: Partner organization fixture
        sample_admin: Admin user who approved this partner

    Returns:
        User instance with partner role
    """
    user = User(
        email='partner@testorg.com',
        password_hash=TEST_PASSWORD_HASH,
        name='Partner User',
        role=User.ROLE_PARTNER,
        organization_id=sample_organization.id,
        status=User.STATUS_ACTIVE,
        approved_by=sample_admin.id,
        approved_at=datetime.now(timezone.utc)
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_advertiser(db_session, sample_advertiser_organization, sample_partner):
    """
    Create a sample Advertiser user for testing.

    Args:
        db_session: Database session fixture
        sample_advertiser_organization: Advertiser organization fixture
        sample_partner: Partner user who invited this advertiser

    Returns:
        User instance with advertiser role
    """
    user = User(
        email='advertiser@advertiser.com',
        password_hash=TEST_PASSWORD_HASH,
        name='Advertiser User',
        role=User.ROLE_ADVERTISER,
        organization_id=sample_advertiser_organization.id,
        status=User.STATUS_ACTIVE,
        invited_by=sample_partner.id,
        approved_by=sample_partner.id,
        approved_at=datetime.now(timezone.utc)
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_viewer(db_session, sample_organization, sample_partner):
    """
    Create a sample Viewer user for testing.

    Args:
        db_session: Database session fixture
        sample_organization: Organization fixture
        sample_partner: Partner user who invited this viewer

    Returns:
        User instance with viewer role
    """
    user = User(
        email='viewer@testorg.com',
        password_hash=TEST_PASSWORD_HASH,
        name='Viewer User',
        role=User.ROLE_VIEWER,
        organization_id=sample_organization.id,
        status=User.STATUS_ACTIVE,
        invited_by=sample_partner.id,
        approved_by=sample_partner.id,
        approved_at=datetime.now(timezone.utc)
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def sample_pending_user(db_session, sample_organization):
    """
    Create a sample pending user awaiting approval.

    Args:
        db_session: Database session fixture
        sample_organization: Organization fixture

    Returns:
        User instance with pending status
    """
    user = User(
        email='pending@testorg.com',
        password_hash=TEST_PASSWORD_HASH,
        name='Pending User',
        role=User.ROLE_PARTNER,
        organization_id=sample_organization.id,
        status=User.STATUS_PENDING
    )
    db_session.add(user)
    db_session.commit()
    return user


# User Invitation Fixtures

@pytest.fixture(scope='function')
def sample_invitation(db_session, sample_organization, sample_admin):
    """
    Create a sample pending invitation for testing.

    Args:
        db_session: Database session fixture
        sample_organization: Organization fixture
        sample_admin: Admin user who sent the invitation

    Returns:
        UserInvitation instance
    """
    invitation = UserInvitation(
        email='newuser@testorg.com',
        role=User.ROLE_PARTNER,
        organization_id=sample_organization.id,
        invited_by=sample_admin.id,
        token=secrets.token_urlsafe(32),
        status=UserInvitation.STATUS_PENDING,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7)
    )
    db_session.add(invitation)
    db_session.commit()
    return invitation


@pytest.fixture(scope='function')
def sample_expired_invitation(db_session, sample_organization, sample_admin):
    """
    Create a sample expired invitation for testing.

    Args:
        db_session: Database session fixture
        sample_organization: Organization fixture
        sample_admin: Admin user who sent the invitation

    Returns:
        UserInvitation instance that has expired
    """
    invitation = UserInvitation(
        email='expired@testorg.com',
        role=User.ROLE_PARTNER,
        organization_id=sample_organization.id,
        invited_by=sample_admin.id,
        token=secrets.token_urlsafe(32),
        status=UserInvitation.STATUS_PENDING,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)  # Expired yesterday
    )
    db_session.add(invitation)
    db_session.commit()
    return invitation


# User Approval Request Fixtures

@pytest.fixture(scope='function')
def sample_approval_request(db_session, sample_pending_user, sample_admin):
    """
    Create a sample user approval request for testing.

    Args:
        db_session: Database session fixture
        sample_pending_user: Pending user fixture
        sample_admin: Admin who will review the request

    Returns:
        UserApprovalRequest instance
    """
    request = UserApprovalRequest(
        user_id=sample_pending_user.id,
        requested_role=User.ROLE_PARTNER,
        current_status=User.STATUS_PENDING,
        assigned_to=sample_admin.id,
        status=UserApprovalRequest.STATUS_PENDING
    )
    db_session.add(request)
    db_session.commit()
    return request


# Admin Session Fixtures

@pytest.fixture(scope='function')
def sample_session(db_session, sample_admin):
    """
    Create a sample active admin session for testing.

    Args:
        db_session: Database session fixture
        sample_admin: Admin user who owns the session

    Returns:
        AdminSession instance
    """
    session = AdminSession(
        user_id=sample_admin.id,
        token=secrets.token_urlsafe(32),
        ip_address='127.0.0.1',
        user_agent='Mozilla/5.0 (Test Browser)',
        status=AdminSession.STATUS_ACTIVE,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
    )
    db_session.add(session)
    db_session.commit()
    return session


# Audit Log Fixtures

@pytest.fixture(scope='function')
def sample_audit_log(db_session, sample_admin):
    """
    Create a sample audit log entry for testing.

    Args:
        db_session: Database session fixture
        sample_admin: Admin user who performed the action

    Returns:
        AuditLog instance
    """
    log = AuditLog(
        user_id=sample_admin.id,
        user_email=sample_admin.email,
        action=AuditLog.ACTION_USER_LOGIN,
        resource_type=AuditLog.RESOURCE_USER,
        resource_id=str(sample_admin.id),
        ip_address='127.0.0.1',
        user_agent='Mozilla/5.0 (Test Browser)'
    )
    db_session.add(log)
    db_session.commit()
    return log


# Content Asset Fixtures

@pytest.fixture(scope='function')
def sample_content_asset(db_session, sample_organization, sample_partner):
    """
    Create a sample content asset for testing.

    Args:
        db_session: Database session fixture
        sample_organization: Organization fixture
        sample_partner: Partner user who uploaded the asset

    Returns:
        ContentAsset instance
    """
    asset = ContentAsset(
        title='Test Video Asset',
        description='A test video for unit testing',
        filename='test_video_abc123.mp4',
        file_path='/uploads/test_video_abc123.mp4',
        file_size=10240000,
        duration=60.0,
        resolution='1920x1080',
        format='mp4',
        organization_id=sample_organization.id,
        uploaded_by=sample_partner.id,
        status=ContentAsset.STATUS_DRAFT,
        category='promotional',
        tags='test,video,promo'
    )
    db_session.add(asset)
    db_session.commit()
    return asset


@pytest.fixture(scope='function')
def sample_image_asset(db_session, sample_organization, sample_partner):
    """
    Create a sample image content asset for testing.

    Args:
        db_session: Database session fixture
        sample_organization: Organization fixture
        sample_partner: Partner user who uploaded the asset

    Returns:
        ContentAsset instance for an image
    """
    asset = ContentAsset(
        title='Test Image Asset',
        description='A test image for unit testing',
        filename='test_image_def456.jpg',
        file_path='/uploads/test_image_def456.jpg',
        file_size=512000,
        duration=None,
        resolution='1920x1080',
        format='jpeg',
        organization_id=sample_organization.id,
        uploaded_by=sample_partner.id,
        status=ContentAsset.STATUS_DRAFT,
        category='banner',
        tags='test,image,banner'
    )
    db_session.add(asset)
    db_session.commit()
    return asset


@pytest.fixture(scope='function')
def sample_pending_content(db_session, sample_organization, sample_partner):
    """
    Create a sample content asset pending review.

    Args:
        db_session: Database session fixture
        sample_organization: Organization fixture
        sample_partner: Partner user who uploaded the asset

    Returns:
        ContentAsset instance with pending_review status
    """
    asset = ContentAsset(
        title='Pending Review Video',
        description='A video submitted for review',
        filename='pending_video_ghi789.mp4',
        file_path='/uploads/pending_video_ghi789.mp4',
        file_size=20480000,
        duration=120.0,
        resolution='1920x1080',
        format='mp4',
        organization_id=sample_organization.id,
        uploaded_by=sample_partner.id,
        status=ContentAsset.STATUS_PENDING_REVIEW,
        category='advertisement',
        tags='pending,review'
    )
    db_session.add(asset)
    db_session.commit()
    return asset


@pytest.fixture(scope='function')
def sample_published_content(db_session, sample_organization, sample_partner, sample_content_manager):
    """
    Create a sample published content asset.

    Args:
        db_session: Database session fixture
        sample_organization: Organization fixture
        sample_partner: Partner user who uploaded the asset
        sample_content_manager: Content manager who reviewed the asset

    Returns:
        ContentAsset instance with published status
    """
    asset = ContentAsset(
        title='Published Video',
        description='A published video in the catalog',
        filename='published_video_jkl012.mp4',
        file_path='/uploads/published_video_jkl012.mp4',
        file_size=30720000,
        duration=180.0,
        resolution='1920x1080',
        format='mp4',
        organization_id=sample_organization.id,
        uploaded_by=sample_partner.id,
        status=ContentAsset.STATUS_PUBLISHED,
        reviewed_by=sample_content_manager.id,
        reviewed_at=datetime.now(timezone.utc) - timedelta(hours=2),
        published_at=datetime.now(timezone.utc) - timedelta(hours=1),
        category='featured',
        tags='published,featured'
    )
    db_session.add(asset)
    db_session.commit()
    return asset


# Content Approval Request Fixtures

@pytest.fixture(scope='function')
def sample_content_approval_request(db_session, sample_pending_content, sample_partner, sample_content_manager):
    """
    Create a sample content approval request.

    Args:
        db_session: Database session fixture
        sample_pending_content: Pending content asset
        sample_partner: Partner who requested approval
        sample_content_manager: Content manager assigned to review

    Returns:
        ContentApprovalRequest instance
    """
    request = ContentApprovalRequest(
        asset_id=sample_pending_content.id,
        requested_by=sample_partner.id,
        assigned_to=sample_content_manager.id,
        status=ContentApprovalRequest.STATUS_PENDING
    )
    db_session.add(request)
    db_session.commit()
    return request


# Complete Setup Fixtures

@pytest.fixture(scope='function')
def sample_complete_setup(db_session, sample_internal_organization, sample_organization,
                          sample_super_admin, sample_admin, sample_content_manager,
                          sample_partner, sample_content_asset):
    """
    Create a complete setup with all related entities for integration testing.

    Args:
        db_session: Database session fixture
        sample_internal_organization: Internal organization fixture
        sample_organization: Partner organization fixture
        sample_super_admin: Super admin user fixture
        sample_admin: Admin user fixture
        sample_content_manager: Content manager fixture
        sample_partner: Partner user fixture
        sample_content_asset: Content asset fixture

    Returns:
        Dictionary with all created entities
    """
    return {
        'internal_org': sample_internal_organization,
        'partner_org': sample_organization,
        'super_admin': sample_super_admin,
        'admin': sample_admin,
        'content_manager': sample_content_manager,
        'partner': sample_partner,
        'content_asset': sample_content_asset
    }


# Test Helper Functions

def create_test_organization(db_session, name='Test Organization', org_type='partner',
                             contact_email='test@org.com', status='active'):
    """
    Helper function to create an organization with custom attributes.

    Args:
        db_session: Database session
        name: Organization name
        org_type: Organization type (internal, partner, advertiser)
        contact_email: Contact email
        status: Organization status

    Returns:
        Organization instance
    """
    org = Organization(
        name=name,
        type=org_type,
        contact_email=contact_email,
        status=status
    )
    db_session.add(org)
    db_session.commit()
    return org


def create_test_user(db_session, email, name='Test User', role='partner',
                     organization_id=None, status='active', password=None):
    """
    Helper function to create a user with custom attributes.

    Args:
        db_session: Database session
        email: User email
        name: User name
        role: User role
        organization_id: Organization ID
        status: User status
        password: Plain text password (will be hashed)

    Returns:
        User instance
    """
    if password:
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=4)).decode('utf-8')
    else:
        password_hash = TEST_PASSWORD_HASH

    user = User(
        email=email,
        password_hash=password_hash,
        name=name,
        role=role,
        organization_id=organization_id,
        status=status
    )
    db_session.add(user)
    db_session.commit()
    return user


def create_test_invitation(db_session, email, role, organization_id, invited_by,
                           expires_in_days=7, status='pending'):
    """
    Helper function to create an invitation with custom attributes.

    Args:
        db_session: Database session
        email: Invitee email
        role: Role to assign
        organization_id: Organization ID
        invited_by: User ID who sent invitation
        expires_in_days: Days until expiration
        status: Invitation status

    Returns:
        UserInvitation instance
    """
    invitation = UserInvitation(
        email=email,
        role=role,
        organization_id=organization_id,
        invited_by=invited_by,
        token=secrets.token_urlsafe(32),
        status=status,
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    )
    db_session.add(invitation)
    db_session.commit()
    return invitation


def create_test_content_asset(db_session, title, filename, file_path, organization_id,
                              uploaded_by, status='draft', format='mp4', file_size=1024000):
    """
    Helper function to create a content asset with custom attributes.

    Args:
        db_session: Database session
        title: Asset title
        filename: Stored filename
        file_path: Server file path
        organization_id: Organization ID
        uploaded_by: User ID who uploaded
        status: Asset status
        format: File format
        file_size: File size in bytes

    Returns:
        ContentAsset instance
    """
    asset = ContentAsset(
        title=title,
        filename=filename,
        file_path=file_path,
        organization_id=organization_id,
        uploaded_by=uploaded_by,
        status=status,
        format=format,
        file_size=file_size
    )
    db_session.add(asset)
    db_session.commit()
    return asset


def create_test_audit_log(db_session, action, user_id=None, user_email=None,
                          resource_type=None, resource_id=None, ip_address='127.0.0.1'):
    """
    Helper function to create an audit log with custom attributes.

    Args:
        db_session: Database session
        action: Action type
        user_id: User ID who performed action
        user_email: User email
        resource_type: Type of resource affected
        resource_id: Resource ID
        ip_address: Client IP address

    Returns:
        AuditLog instance
    """
    log = AuditLog(
        action=action,
        user_id=user_id,
        user_email=user_email,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        ip_address=ip_address
    )
    db_session.add(log)
    db_session.commit()
    return log


def get_auth_headers(token):
    """
    Helper function to create authorization headers for JWT authentication.

    Args:
        token: JWT access token

    Returns:
        Dictionary with Authorization header
    """
    return {'Authorization': f'Bearer {token}'}
