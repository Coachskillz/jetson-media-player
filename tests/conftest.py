"""
Pytest Fixtures for Central Hub Tests

Provides fixtures for Flask app, database, and mock data used across all test files.
"""

import os
import pytest
import numpy as np
import uuid
from datetime import datetime, timezone

# Set testing environment before imports
os.environ['FLASK_ENV'] = 'testing'
os.environ['TEST_DATABASE_URL'] = 'sqlite:///:memory:'


@pytest.fixture(scope='function')
def app():
    """Create application for testing with in-memory SQLite database."""
    # Override config for testing
    from central_hub.config import TestingConfig
    TestingConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

    from central_hub.app import create_app
    from central_hub.extensions import db

    app = create_app('testing')

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope='function')
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture(scope='function')
def db_session(app):
    """Create database session for testing."""
    from central_hub.extensions import db
    with app.app_context():
        yield db.session


@pytest.fixture
def mock_face_encoding():
    """Return a mock 512-byte face encoding (128 float32 values)."""
    return np.zeros(128, dtype=np.float32).tobytes()


@pytest.fixture
def mock_face_encoding_array():
    """Return a mock face encoding as numpy array."""
    return np.random.rand(128).astype(np.float32)


@pytest.fixture
def sample_ncmec_record(app, mock_face_encoding):
    """Create a sample NCMEC record for testing."""
    from central_hub.extensions import db
    from central_hub.models import NCMECRecord, NCMECStatus

    with app.app_context():
        record = NCMECRecord(
            case_id='NCMEC-2024-001',
            name='Test Child',
            age_when_missing=10,
            missing_since=datetime(2024, 1, 15).date(),
            last_known_location='Test City, State',
            face_encoding=mock_face_encoding,
            photo_path='/uploads/test.jpg',
            status=NCMECStatus.ACTIVE.value,
        )
        db.session.add(record)
        db.session.commit()
        db.session.refresh(record)
        yield record


@pytest.fixture
def sample_loyalty_member(app, mock_face_encoding):
    """Create a sample loyalty member for testing."""
    from central_hub.extensions import db
    from central_hub.models import LoyaltyMember

    network_id = uuid.uuid4()

    with app.app_context():
        member = LoyaltyMember(
            network_id=network_id,
            member_code='MEM-001',
            name='Test Member',
            email='test@example.com',
            phone='+1234567890',
            face_encoding=mock_face_encoding,
            assigned_playlist_id=1,
        )
        db.session.add(member)
        db.session.commit()
        db.session.refresh(member)
        yield member


@pytest.fixture
def sample_alert(app, sample_ncmec_record):
    """Create a sample NCMEC alert for testing."""
    from central_hub.extensions import db
    from central_hub.models import Alert, AlertType, AlertStatus

    with app.app_context():
        alert = Alert(
            alert_type=AlertType.NCMEC_MATCH.value,
            case_id=sample_ncmec_record.case_id,
            confidence=0.95,
            timestamp=datetime.now(timezone.utc),
            status=AlertStatus.NEW.value,
        )
        db.session.add(alert)
        db.session.commit()
        db.session.refresh(alert)
        yield alert


@pytest.fixture
def sample_notification_settings(app):
    """Create sample notification settings for testing."""
    from central_hub.extensions import db
    from central_hub.models import NotificationSettings, NotificationChannel

    with app.app_context():
        settings = NotificationSettings(
            name='ncmec_alert',
            channel=NotificationChannel.EMAIL.value,
            recipients={'emails': ['admin@example.com', 'alerts@example.com']},
            delay_minutes=0,
            enabled=True,
            description='NCMEC alert notifications',
        )
        db.session.add(settings)
        db.session.commit()
        db.session.refresh(settings)
        yield settings
