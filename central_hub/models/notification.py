"""
Notification Settings Models

SQLAlchemy models for notification configuration and settings.
Stores channel preferences, recipients, and notification delays
for alert delivery.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from central_hub.extensions import db


class NotificationChannel(enum.Enum):
    """Channel enum for notification delivery methods."""
    EMAIL = 'email'
    SMS = 'sms'
    WEBHOOK = 'webhook'


class NotificationSettings(db.Model):
    """Configuration settings for notification delivery.

    Stores notification channel preferences, recipient lists,
    and delivery timing configuration for alerts.
    """
    __tablename__ = 'notification_settings'

    # Primary key - UUID for global uniqueness
    id = db.Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # Setting name/identifier
    name = db.Column(
        db.String(100),
        unique=True,
        nullable=False,
        index=True
    )

    # Notification channel (email/sms/webhook)
    channel = db.Column(
        db.String(20),
        nullable=False,
        index=True
    )

    # Recipients configuration (JSONB for flexible structure)
    # Example: {"emails": ["admin@example.com"], "phones": ["+1234567890"]}
    recipients = db.Column(
        JSONB,
        nullable=False,
        default=dict
    )

    # Delay in minutes before sending notification
    delay_minutes = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    # Whether this notification setting is active
    enabled = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    # Optional description
    description = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "channel IN ('email', 'sms', 'webhook')",
            name='check_notification_channel'
        ),
        CheckConstraint(
            "delay_minutes >= 0",
            name='check_delay_minutes_non_negative'
        ),
    )

    def __repr__(self):
        return f'<NotificationSettings {self.name}: {self.channel}>'

    def to_dict(self):
        """Convert settings to dictionary for JSON serialization."""
        return {
            'id': str(self.id),
            'name': self.name,
            'channel': self.channel,
            'recipients': self.recipients,
            'delay_minutes': self.delay_minutes,
            'enabled': self.enabled,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
