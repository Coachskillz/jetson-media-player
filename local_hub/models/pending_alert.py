"""
PendingAlert database model for reliable alert forwarding queue.

CRITICAL: Alerts must NEVER be lost. This model provides a persistent
queue for alerts received from Jetson screens that need to be forwarded
to HQ. Alerts remain in the queue until HQ confirms receipt.

Key reliability guarantees:
- Alerts are stored immediately upon receipt (before forwarding attempt)
- Failed forwards are retried indefinitely every 30 seconds
- Alerts are only deleted after HQ confirmation
- Retry counter tracks forwarding attempts for monitoring

Alert types include: ncmec_match, face_match, system_error, etc.
"""

from datetime import datetime
from models import db


class PendingAlert(db.Model):
    """
    Database model for queued alerts awaiting HQ forwarding.

    This is a CRITICAL reliability component. Alerts received from
    Jetson screens are immediately persisted here, then forwarded
    to HQ asynchronously. Alerts remain until HQ confirms receipt.

    Attributes:
        id: Primary key
        screen_id: ID of screen that generated the alert
        alert_type: Type of alert (ncmec_match, face_match, system_error, etc.)
        payload: JSON string containing full alert data
        status: Queue status (pending, sending, failed)
        attempts: Number of forwarding attempts
        created_at: When alert was first received
        last_attempt_at: When last forwarding attempt was made
        next_retry_at: When next retry should be attempted
        error_message: Last error message if forwarding failed
    """
    __tablename__ = 'pending_alerts'

    id = db.Column(db.Integer, primary_key=True)
    screen_id = db.Column(db.Integer, nullable=False, index=True)
    alert_type = db.Column(db.String(64), nullable=False, index=True)

    # Alert payload - stored as JSON string
    payload = db.Column(db.Text, nullable=False)

    # Queue status tracking
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    attempts = db.Column(db.Integer, default=0, nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_attempt_at = db.Column(db.DateTime, nullable=True)
    next_retry_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Error tracking
    error_message = db.Column(db.Text, nullable=True)

    def to_dict(self):
        """
        Serialize model to dictionary for JSON responses.

        Returns:
            dict: Complete alert data including retry status
        """
        return {
            'id': self.id,
            'screen_id': self.screen_id,
            'alert_type': self.alert_type,
            'payload': self.payload,
            'status': self.status,
            'attempts': self.attempts,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_attempt_at': self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            'next_retry_at': self.next_retry_at.isoformat() if self.next_retry_at else None,
            'error_message': self.error_message
        }

    def to_hq_payload(self):
        """
        Return data formatted for HQ API forwarding.

        Returns:
            dict: Alert data in HQ API format
        """
        import json
        return {
            'alert_id': self.id,
            'screen_id': self.screen_id,
            'alert_type': self.alert_type,
            'data': json.loads(self.payload) if self.payload else {},
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def mark_sending(self):
        """
        Mark alert as currently being sent.

        Call this before attempting to forward to HQ.
        """
        self.status = 'sending'
        self.last_attempt_at = datetime.utcnow()
        self.attempts += 1
        db.session.commit()

    def mark_failed(self, error_message=None, retry_delay_seconds=30):
        """
        Mark alert as failed and schedule retry.

        Call this when HQ forwarding fails. The alert will be
        retried after retry_delay_seconds.

        Args:
            error_message: Optional error description
            retry_delay_seconds: Seconds until next retry (default 30)
        """
        from datetime import timedelta
        self.status = 'failed'
        self.error_message = error_message
        self.next_retry_at = datetime.utcnow() + timedelta(seconds=retry_delay_seconds)
        db.session.commit()

    def mark_sent(self):
        """
        Mark alert as successfully sent.

        Call this ONLY after HQ confirms receipt. This removes
        the alert from the retry queue but keeps the record.

        Note: Consider calling delete() instead if you want to
        completely remove the alert after successful forwarding.
        """
        self.status = 'sent'
        self.error_message = None
        db.session.commit()

    @property
    def is_pending(self):
        """
        Check if alert is waiting to be sent.

        Returns:
            bool: True if status is 'pending' or 'failed'
        """
        return self.status in ('pending', 'failed')

    @property
    def is_ready_for_retry(self):
        """
        Check if alert is due for a retry attempt.

        Returns:
            bool: True if pending and past next_retry_at time
        """
        if not self.is_pending:
            return False
        return datetime.utcnow() >= self.next_retry_at

    @classmethod
    def create_alert(cls, screen_id, alert_type, payload_dict):
        """
        Create a new pending alert from screen data.

        Immediately persists the alert to ensure it's never lost.

        Args:
            screen_id: ID of the source screen
            alert_type: Type of alert
            payload_dict: Alert data as dictionary

        Returns:
            PendingAlert: The created alert instance
        """
        import json
        alert = cls(
            screen_id=screen_id,
            alert_type=alert_type,
            payload=json.dumps(payload_dict) if payload_dict else '{}',
            status='pending',
            attempts=0,
            created_at=datetime.utcnow(),
            next_retry_at=datetime.utcnow()
        )
        db.session.add(alert)
        db.session.commit()
        return alert

    @classmethod
    def get_pending_alerts(cls, limit=100):
        """
        Get alerts ready for forwarding to HQ.

        Returns alerts that are pending/failed and past their
        next_retry_at time, ordered by creation time.

        Args:
            limit: Maximum number of alerts to return

        Returns:
            list: List of PendingAlert instances ready for retry
        """
        now = datetime.utcnow()
        return cls.query.filter(
            cls.status.in_(['pending', 'failed']),
            cls.next_retry_at <= now
        ).order_by(cls.created_at.asc()).limit(limit).all()

    @classmethod
    def get_all_pending(cls):
        """
        Get all alerts that haven't been successfully sent.

        Returns:
            list: List of all pending/failed PendingAlert instances
        """
        return cls.query.filter(
            cls.status.in_(['pending', 'failed'])
        ).order_by(cls.created_at.asc()).all()

    @classmethod
    def get_pending_count(cls):
        """
        Get count of alerts awaiting forwarding.

        Returns:
            int: Number of pending/failed alerts
        """
        return cls.query.filter(
            cls.status.in_(['pending', 'failed'])
        ).count()

    @classmethod
    def get_by_screen(cls, screen_id, include_sent=False):
        """
        Get alerts for a specific screen.

        Args:
            screen_id: Screen ID to filter by
            include_sent: Whether to include successfully sent alerts

        Returns:
            list: List of PendingAlert instances for the screen
        """
        query = cls.query.filter_by(screen_id=screen_id)
        if not include_sent:
            query = query.filter(cls.status.in_(['pending', 'failed']))
        return query.order_by(cls.created_at.desc()).all()

    @classmethod
    def delete_sent_alerts(cls, older_than_hours=24):
        """
        Clean up successfully sent alerts older than specified hours.

        Args:
            older_than_hours: Delete sent alerts older than this

        Returns:
            int: Number of alerts deleted
        """
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)
        result = cls.query.filter(
            cls.status == 'sent',
            cls.last_attempt_at < cutoff
        ).delete()
        db.session.commit()
        return result

    def delete(self):
        """
        Remove this alert from the queue.

        WARNING: Only call this after HQ has confirmed receipt.
        Calling this prematurely will lose the alert.
        """
        db.session.delete(self)
        db.session.commit()

    def __repr__(self):
        """String representation."""
        return f"<PendingAlert id={self.id} type={self.alert_type} status={self.status} attempts={self.attempts}>"
