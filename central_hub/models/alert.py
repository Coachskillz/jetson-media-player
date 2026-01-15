"""
Alert Models

SQLAlchemy models for alert management and notification logging.
Handles NCMEC and Loyalty match alerts from distributed screens
with status workflow tracking and notification delivery logging.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from central_hub.extensions import db


class AlertStatus(enum.Enum):
    """Status workflow enum for alerts.

    Workflow: new → reviewed → escalated/resolved/false_positive
    """
    NEW = 'new'
    REVIEWED = 'reviewed'
    ESCALATED = 'escalated'
    RESOLVED = 'resolved'
    FALSE_POSITIVE = 'false_positive'


class AlertType(enum.Enum):
    """Type enum for alerts."""
    NCMEC_MATCH = 'ncmec_match'
    LOYALTY_MATCH = 'loyalty_match'


class NotificationType(enum.Enum):
    """Channel type enum for notifications."""
    EMAIL = 'email'
    SMS = 'sms'


class NotificationStatus(enum.Enum):
    """Delivery status enum for notifications."""
    SENT = 'sent'
    FAILED = 'failed'


class Alert(db.Model):
    """Alert record for face recognition matches from distributed screens.

    Stores match alerts triggered by NCMEC or Loyalty face recognition
    on edge devices, with status workflow for review and resolution.
    """
    __tablename__ = 'alerts'

    # Primary key - UUID for global uniqueness
    id = db.Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # Network/location context (optional for some alert types)
    network_id = db.Column(UUID(as_uuid=True), index=True)
    store_id = db.Column(UUID(as_uuid=True), index=True)
    screen_id = db.Column(UUID(as_uuid=True), index=True)

    # Alert type (ncmec_match/loyalty_match)
    alert_type = db.Column(
        db.String(20),
        nullable=False,
        index=True
    )

    # Match reference - depends on alert type
    case_id = db.Column(db.String(50), index=True)  # For NCMEC matches
    member_id = db.Column(UUID(as_uuid=True), index=True)  # For loyalty matches

    # Match confidence score (0.0 to 1.0)
    confidence = db.Column(db.Float, nullable=False)

    # Captured image from screen (filesystem path)
    captured_image_path = db.Column(db.String(500))

    # Detection timestamp (when detected on screen)
    timestamp = db.Column(
        db.DateTime(timezone=True),
        nullable=False
    )

    # Receipt timestamp (when received by central hub)
    received_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Status workflow
    status = db.Column(
        db.String(20),
        default=AlertStatus.NEW.value,
        nullable=False,
        index=True
    )

    # Review information
    reviewed_by = db.Column(db.String(255))
    reviewed_at = db.Column(db.DateTime(timezone=True))
    notes = db.Column(db.Text)

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "alert_type IN ('ncmec_match', 'loyalty_match')",
            name='check_alert_type'
        ),
        CheckConstraint(
            "status IN ('new', 'reviewed', 'escalated', 'resolved', 'false_positive')",
            name='check_alert_status'
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name='check_confidence_range'
        ),
    )

    # Relationship to notification logs
    notification_logs = db.relationship(
        'AlertNotificationLog',
        backref='alert',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<Alert {self.id}: {self.alert_type} ({self.status})>'

    def to_dict(self):
        """Convert alert to dictionary for JSON serialization."""
        return {
            'id': str(self.id),
            'network_id': str(self.network_id) if self.network_id else None,
            'store_id': str(self.store_id) if self.store_id else None,
            'screen_id': str(self.screen_id) if self.screen_id else None,
            'alert_type': self.alert_type,
            'case_id': self.case_id,
            'member_id': str(self.member_id) if self.member_id else None,
            'confidence': self.confidence,
            'captured_image_path': self.captured_image_path,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'received_at': self.received_at.isoformat() if self.received_at else None,
            'status': self.status,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'notes': self.notes,
        }


class AlertNotificationLog(db.Model):
    """Log of notification attempts for alerts.

    Tracks all email and SMS notification delivery attempts
    with status and error information for auditing and debugging.
    """
    __tablename__ = 'alert_notification_logs'

    # Primary key - UUID
    id = db.Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # Alert reference
    alert_id = db.Column(
        UUID(as_uuid=True),
        ForeignKey('alerts.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )

    # Notification details
    notification_type = db.Column(
        db.String(10),
        nullable=False
    )
    recipient = db.Column(db.String(255), nullable=False)

    # Delivery tracking
    sent_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    status = db.Column(
        db.String(10),
        nullable=False
    )
    error_message = db.Column(db.Text)

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "notification_type IN ('email', 'sms')",
            name='check_notification_type'
        ),
        CheckConstraint(
            "status IN ('sent', 'failed')",
            name='check_notification_status'
        ),
    )

    def __repr__(self):
        return f'<AlertNotificationLog {self.id}: {self.notification_type} to {self.recipient} ({self.status})>'

    def to_dict(self):
        """Convert notification log to dictionary for JSON serialization."""
        return {
            'id': str(self.id),
            'alert_id': str(self.alert_id),
            'notification_type': self.notification_type,
            'recipient': self.recipient,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'status': self.status,
            'error_message': self.error_message,
        }
