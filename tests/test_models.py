"""
Test Model Serialization

Tests all model to_dict() serialization methods to ensure proper JSON output.
"""

import os
import uuid
import pytest
from datetime import datetime, timezone, date

# Set testing environment
os.environ['FLASK_ENV'] = 'testing'


class TestNCMECRecordSerialization:
    """Tests for NCMECRecord model serialization."""

    def test_ncmec_record_to_dict(self, app, mock_face_encoding):
        """Test NCMECRecord serializes correctly."""
        from central_hub.extensions import db
        from central_hub.models import NCMECRecord, NCMECStatus

        with app.app_context():
            record = NCMECRecord(
                case_id='SERIAL-001',
                name='John Doe',
                age_when_missing=12,
                missing_since=date(2024, 1, 15),
                last_known_location='Test City, CA',
                face_encoding=mock_face_encoding,
                photo_path='/uploads/photo.jpg',
                status=NCMECStatus.ACTIVE.value,
            )
            db.session.add(record)
            db.session.commit()
            db.session.refresh(record)

            # Serialize to dict
            data = record.to_dict()

            # Verify all expected fields
            assert 'id' in data
            assert data['case_id'] == 'SERIAL-001'
            assert data['name'] == 'John Doe'
            assert data['age_when_missing'] == 12
            assert data['missing_since'] == '2024-01-15'
            assert data['last_known_location'] == 'Test City, CA'
            assert data['photo_path'] == '/uploads/photo.jpg'
            assert data['status'] == 'active'
            assert 'created_at' in data
            assert 'updated_at' in data

            # Verify face_encoding is NOT included (binary data)
            assert 'face_encoding' not in data

            # Verify ID is a string (not UUID object)
            assert isinstance(data['id'], str)


class TestNCMECDatabaseVersionSerialization:
    """Tests for NCMECDatabaseVersion model serialization."""

    def test_ncmec_database_version_to_dict(self, app):
        """Test NCMECDatabaseVersion serializes correctly."""
        from central_hub.extensions import db
        from central_hub.models import NCMECDatabaseVersion

        with app.app_context():
            version = NCMECDatabaseVersion(
                version=1,
                record_count=100,
                file_hash='abc123def456',
                file_path='/databases/ncmec_v1.faiss',
            )
            db.session.add(version)
            db.session.commit()
            db.session.refresh(version)

            data = version.to_dict()

            assert 'id' in data
            assert data['version'] == 1
            assert data['record_count'] == 100
            assert data['file_hash'] == 'abc123def456'
            assert data['file_path'] == '/databases/ncmec_v1.faiss'
            assert 'created_at' in data

            # Verify ID is a string
            assert isinstance(data['id'], str)


class TestLoyaltyMemberSerialization:
    """Tests for LoyaltyMember model serialization."""

    def test_loyalty_member_to_dict(self, app, mock_face_encoding):
        """Test LoyaltyMember serializes correctly."""
        from central_hub.extensions import db
        from central_hub.models import LoyaltyMember

        network_id = uuid.uuid4()
        store_id = uuid.uuid4()

        with app.app_context():
            member = LoyaltyMember(
                network_id=network_id,
                member_code='LOYAL-001',
                name='Jane Smith',
                email='jane@example.com',
                phone='+1234567890',
                face_encoding=mock_face_encoding,
                photo_path='/uploads/member.jpg',
                assigned_playlist_id=5,
                last_seen_at=datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
                last_seen_store_id=store_id,
            )
            db.session.add(member)
            db.session.commit()
            db.session.refresh(member)

            data = member.to_dict()

            assert 'id' in data
            assert data['network_id'] == str(network_id)
            assert data['member_code'] == 'LOYAL-001'
            assert data['name'] == 'Jane Smith'
            assert data['email'] == 'jane@example.com'
            assert data['phone'] == '+1234567890'
            assert data['assigned_playlist_id'] == 5
            assert data['last_seen_store_id'] == str(store_id)
            assert 'enrolled_at' in data
            assert 'last_seen_at' in data

            # Verify face_encoding is NOT included
            assert 'face_encoding' not in data


class TestAlertSerialization:
    """Tests for Alert model serialization."""

    def test_alert_to_dict(self, app):
        """Test Alert serializes correctly."""
        from central_hub.extensions import db
        from central_hub.models import Alert, AlertType, AlertStatus

        network_id = uuid.uuid4()
        store_id = uuid.uuid4()
        screen_id = uuid.uuid4()

        with app.app_context():
            alert = Alert(
                network_id=network_id,
                store_id=store_id,
                screen_id=screen_id,
                alert_type=AlertType.NCMEC_MATCH.value,
                case_id='ALERT-001',
                confidence=0.95,
                captured_image_path='/captures/image.jpg',
                timestamp=datetime(2024, 6, 15, 14, 30, 0, tzinfo=timezone.utc),
                status=AlertStatus.NEW.value,
            )
            db.session.add(alert)
            db.session.commit()
            db.session.refresh(alert)

            data = alert.to_dict()

            assert 'id' in data
            assert data['network_id'] == str(network_id)
            assert data['store_id'] == str(store_id)
            assert data['screen_id'] == str(screen_id)
            assert data['alert_type'] == 'ncmec_match'
            assert data['case_id'] == 'ALERT-001'
            assert data['confidence'] == 0.95
            assert data['captured_image_path'] == '/captures/image.jpg'
            assert data['status'] == 'new'
            assert 'timestamp' in data
            assert 'received_at' in data

    def test_alert_to_dict_with_review(self, app):
        """Test Alert with review info serializes correctly."""
        from central_hub.extensions import db
        from central_hub.models import Alert, AlertType, AlertStatus

        with app.app_context():
            alert = Alert(
                alert_type=AlertType.NCMEC_MATCH.value,
                case_id='REVIEW-001',
                confidence=0.92,
                timestamp=datetime.now(timezone.utc),
                status=AlertStatus.REVIEWED.value,
                reviewed_by='admin@example.com',
                reviewed_at=datetime.now(timezone.utc),
                notes='Confirmed match, authorities notified.',
            )
            db.session.add(alert)
            db.session.commit()
            db.session.refresh(alert)

            data = alert.to_dict()

            assert data['status'] == 'reviewed'
            assert data['reviewed_by'] == 'admin@example.com'
            assert data['reviewed_at'] is not None
            assert data['notes'] == 'Confirmed match, authorities notified.'


class TestAlertNotificationLogSerialization:
    """Tests for AlertNotificationLog model serialization."""

    def test_alert_notification_log_to_dict(self, app):
        """Test AlertNotificationLog serializes correctly."""
        from central_hub.extensions import db
        from central_hub.models import (
            Alert, AlertNotificationLog, AlertType, NotificationStatus
        )

        with app.app_context():
            # Create parent alert first
            alert = Alert(
                alert_type=AlertType.NCMEC_MATCH.value,
                case_id='LOG-001',
                confidence=0.95,
                timestamp=datetime.now(timezone.utc),
            )
            db.session.add(alert)
            db.session.commit()

            # Create notification log
            log = AlertNotificationLog(
                alert_id=alert.id,
                notification_type='email',
                recipient='admin@example.com',
                status=NotificationStatus.SENT.value,
            )
            db.session.add(log)
            db.session.commit()
            db.session.refresh(log)

            data = log.to_dict()

            assert 'id' in data
            assert data['alert_id'] == str(alert.id)
            assert data['notification_type'] == 'email'
            assert data['recipient'] == 'admin@example.com'
            assert data['status'] == 'sent'
            assert 'sent_at' in data
            assert data['error_message'] is None

    def test_alert_notification_log_failed_to_dict(self, app):
        """Test failed AlertNotificationLog includes error message."""
        from central_hub.extensions import db
        from central_hub.models import (
            Alert, AlertNotificationLog, AlertType, NotificationStatus
        )

        with app.app_context():
            alert = Alert(
                alert_type=AlertType.NCMEC_MATCH.value,
                case_id='FAIL-001',
                confidence=0.95,
                timestamp=datetime.now(timezone.utc),
            )
            db.session.add(alert)
            db.session.commit()

            log = AlertNotificationLog(
                alert_id=alert.id,
                notification_type='sms',
                recipient='+1234567890',
                status=NotificationStatus.FAILED.value,
                error_message='Invalid phone number format',
            )
            db.session.add(log)
            db.session.commit()
            db.session.refresh(log)

            data = log.to_dict()

            assert data['status'] == 'failed'
            assert data['error_message'] == 'Invalid phone number format'


class TestNotificationSettingsSerialization:
    """Tests for NotificationSettings model serialization."""

    def test_notification_settings_to_dict(self, app):
        """Test NotificationSettings serializes correctly."""
        from central_hub.extensions import db
        from central_hub.models import NotificationSettings, NotificationChannel

        with app.app_context():
            settings = NotificationSettings(
                name='ncmec_alert',
                channel=NotificationChannel.EMAIL.value,
                recipients={
                    'emails': ['admin@example.com', 'security@example.com'],
                },
                delay_minutes=0,
                enabled=True,
                description='Critical NCMEC alert notifications',
            )
            db.session.add(settings)
            db.session.commit()
            db.session.refresh(settings)

            data = settings.to_dict()

            assert 'id' in data
            assert data['name'] == 'ncmec_alert'
            assert data['channel'] == 'email'
            assert data['recipients'] == {
                'emails': ['admin@example.com', 'security@example.com']
            }
            assert data['delay_minutes'] == 0
            assert data['enabled'] is True
            assert data['description'] == 'Critical NCMEC alert notifications'
            assert 'created_at' in data
            assert 'updated_at' in data

    def test_notification_settings_sms_channel(self, app):
        """Test SMS notification settings serialization."""
        from central_hub.extensions import db
        from central_hub.models import NotificationSettings, NotificationChannel

        with app.app_context():
            settings = NotificationSettings(
                name='hub_offline_sms',
                channel=NotificationChannel.SMS.value,
                recipients={
                    'phones': ['+1234567890', '+0987654321'],
                },
                delay_minutes=5,
                enabled=True,
            )
            db.session.add(settings)
            db.session.commit()
            db.session.refresh(settings)

            data = settings.to_dict()

            assert data['channel'] == 'sms'
            assert 'phones' in data['recipients']
            assert data['delay_minutes'] == 5


class TestModelNullFields:
    """Tests for handling null/optional fields in serialization."""

    def test_ncmec_record_null_optional_fields(self, app, mock_face_encoding):
        """Test NCMECRecord with null optional fields."""
        from central_hub.extensions import db
        from central_hub.models import NCMECRecord

        with app.app_context():
            record = NCMECRecord(
                case_id='NULL-001',
                name='Test Person',
                face_encoding=mock_face_encoding,
                # All optional fields left as None
            )
            db.session.add(record)
            db.session.commit()
            db.session.refresh(record)

            data = record.to_dict()

            assert data['age_when_missing'] is None
            assert data['missing_since'] is None
            assert data['last_known_location'] is None
            assert data['photo_path'] is None

    def test_alert_null_optional_fields(self, app):
        """Test Alert with null optional fields."""
        from central_hub.extensions import db
        from central_hub.models import Alert, AlertType

        with app.app_context():
            alert = Alert(
                alert_type=AlertType.NCMEC_MATCH.value,
                case_id='NULL-ALERT',
                confidence=0.9,
                timestamp=datetime.now(timezone.utc),
                # All optional fields left as None
            )
            db.session.add(alert)
            db.session.commit()
            db.session.refresh(alert)

            data = alert.to_dict()

            assert data['network_id'] is None
            assert data['store_id'] is None
            assert data['screen_id'] is None
            assert data['reviewed_by'] is None
            assert data['reviewed_at'] is None
            assert data['notes'] is None
