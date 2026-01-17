"""
HeartbeatQueue database model for offline heartbeat resilience.

CRITICAL: Device heartbeats must be preserved when CMS is unreachable.
This model provides a persistent queue for heartbeats collected from
local devices that need to be forwarded to CMS. Heartbeats remain in
the queue until CMS confirms receipt.

Key reliability guarantees:
- Heartbeats are stored immediately upon receipt (before forwarding attempt)
- Failed forwards are retried with exponential backoff
- Heartbeats are only deleted after CMS confirmation
- Retry counter tracks forwarding attempts for monitoring

The queue supports batched forwarding to reduce network overhead.
"""

from datetime import datetime
from models import db


class HeartbeatQueue(db.Model):
    """
    Database model for queued heartbeats awaiting CMS forwarding.

    This is a CRITICAL reliability component. Heartbeats received from
    local devices are immediately persisted here, then forwarded to CMS
    asynchronously. Heartbeats remain until CMS confirms receipt.

    Attributes:
        id: Primary key
        device_id: ID of device that generated the heartbeat
        device_type: Type of device (screen, sensor, etc.)
        payload: JSON string containing full heartbeat data
        status: Queue status (pending, sending, failed, sent)
        attempts: Number of forwarding attempts
        created_at: When heartbeat was first received
        last_attempt_at: When last forwarding attempt was made
        next_retry_at: When next retry should be attempted
        error_message: Last error message if forwarding failed
    """
    __tablename__ = 'heartbeat_queue'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(64), nullable=False, index=True)
    device_type = db.Column(db.String(32), nullable=False, default='screen')

    # Heartbeat payload - stored as JSON string
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
            dict: Complete heartbeat data including retry status
        """
        return {
            'id': self.id,
            'device_id': self.device_id,
            'device_type': self.device_type,
            'payload': self.payload,
            'status': self.status,
            'attempts': self.attempts,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_attempt_at': self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            'next_retry_at': self.next_retry_at.isoformat() if self.next_retry_at else None,
            'error_message': self.error_message
        }

    def to_cms_payload(self):
        """
        Return data formatted for CMS API forwarding.

        Returns:
            dict: Heartbeat data in CMS API format
        """
        import json
        return {
            'queue_id': self.id,
            'device_id': self.device_id,
            'device_type': self.device_type,
            'data': json.loads(self.payload) if self.payload else {},
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def mark_sending(self):
        """
        Mark heartbeat as currently being sent.

        Call this before attempting to forward to CMS.
        """
        self.status = 'sending'
        self.last_attempt_at = datetime.utcnow()
        self.attempts += 1
        db.session.commit()

    def mark_failed(self, error_message=None, retry_delay_seconds=30):
        """
        Mark heartbeat as failed and schedule retry.

        Call this when CMS forwarding fails. The heartbeat will be
        retried after retry_delay_seconds. Uses exponential backoff
        based on attempt count.

        Args:
            error_message: Optional error description
            retry_delay_seconds: Base seconds until next retry (default 30)
        """
        from datetime import timedelta
        self.status = 'failed'
        self.error_message = error_message
        # Exponential backoff: 30s, 60s, 120s, 240s, max 300s
        backoff = min(retry_delay_seconds * (2 ** (self.attempts - 1)), 300)
        self.next_retry_at = datetime.utcnow() + timedelta(seconds=backoff)
        db.session.commit()

    def mark_sent(self):
        """
        Mark heartbeat as successfully sent.

        Call this ONLY after CMS confirms receipt. This removes
        the heartbeat from the retry queue but keeps the record.

        Note: Consider calling delete() instead if you want to
        completely remove the heartbeat after successful forwarding.
        """
        self.status = 'sent'
        self.error_message = None
        db.session.commit()

    @property
    def is_pending(self):
        """
        Check if heartbeat is waiting to be sent.

        Returns:
            bool: True if status is 'pending' or 'failed'
        """
        return self.status in ('pending', 'failed')

    @property
    def is_ready_for_retry(self):
        """
        Check if heartbeat is due for a retry attempt.

        Returns:
            bool: True if pending and past next_retry_at time
        """
        if not self.is_pending:
            return False
        return datetime.utcnow() >= self.next_retry_at

    @classmethod
    def enqueue(cls, device_id, payload_dict, device_type='screen'):
        """
        Create a new queued heartbeat from device data.

        Immediately persists the heartbeat to ensure it's never lost.

        Args:
            device_id: ID of the source device
            payload_dict: Heartbeat data as dictionary
            device_type: Type of device (default 'screen')

        Returns:
            HeartbeatQueue: The created heartbeat instance
        """
        import json
        heartbeat = cls(
            device_id=str(device_id),
            device_type=device_type,
            payload=json.dumps(payload_dict) if payload_dict else '{}',
            status='pending',
            attempts=0,
            created_at=datetime.utcnow(),
            next_retry_at=datetime.utcnow()
        )
        db.session.add(heartbeat)
        db.session.commit()
        return heartbeat

    @classmethod
    def get_pending(cls, limit=100):
        """
        Get heartbeats ready for forwarding to CMS.

        Returns heartbeats that are pending/failed and past their
        next_retry_at time, ordered by creation time (FIFO).

        Args:
            limit: Maximum number of heartbeats to return

        Returns:
            list: List of HeartbeatQueue instances ready for retry
        """
        now = datetime.utcnow()
        return cls.query.filter(
            cls.status.in_(['pending', 'failed']),
            cls.next_retry_at <= now
        ).order_by(cls.created_at.asc()).limit(limit).all()

    @classmethod
    def get_all_pending(cls):
        """
        Get all heartbeats that haven't been successfully sent.

        Returns:
            list: List of all pending/failed HeartbeatQueue instances
        """
        return cls.query.filter(
            cls.status.in_(['pending', 'failed'])
        ).order_by(cls.created_at.asc()).all()

    @classmethod
    def get_pending_count(cls):
        """
        Get count of heartbeats awaiting forwarding.

        Returns:
            int: Number of pending/failed heartbeats
        """
        return cls.query.filter(
            cls.status.in_(['pending', 'failed'])
        ).count()

    @classmethod
    def get_batch_for_cms(cls, limit=50):
        """
        Get a batch of heartbeats formatted for CMS API.

        Returns heartbeat payloads ready to be sent as a batch
        to the CMS heartbeats endpoint.

        Args:
            limit: Maximum number of heartbeats in batch

        Returns:
            tuple: (list of queue entries, list of CMS payloads)
        """
        entries = cls.get_pending(limit=limit)
        payloads = [entry.to_cms_payload() for entry in entries]
        return entries, payloads

    @classmethod
    def get_by_device(cls, device_id, include_sent=False):
        """
        Get heartbeats for a specific device.

        Args:
            device_id: Device ID to filter by
            include_sent: Whether to include successfully sent heartbeats

        Returns:
            list: List of HeartbeatQueue instances for the device
        """
        query = cls.query.filter_by(device_id=str(device_id))
        if not include_sent:
            query = query.filter(cls.status.in_(['pending', 'failed']))
        return query.order_by(cls.created_at.desc()).all()

    @classmethod
    def delete_sent(cls, older_than_hours=24):
        """
        Clean up successfully sent heartbeats older than specified hours.

        Args:
            older_than_hours: Delete sent heartbeats older than this

        Returns:
            int: Number of heartbeats deleted
        """
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)
        result = cls.query.filter(
            cls.status == 'sent',
            cls.last_attempt_at < cutoff
        ).delete()
        db.session.commit()
        return result

    @classmethod
    def enforce_max_queue_size(cls, max_size=1000):
        """
        Enforce maximum queue size by removing oldest entries.

        This prevents unbounded queue growth during extended
        offline periods. Removes oldest pending entries if
        queue exceeds max_size.

        Args:
            max_size: Maximum number of pending entries to keep

        Returns:
            int: Number of entries removed
        """
        pending_count = cls.get_pending_count()
        if pending_count <= max_size:
            return 0

        # Get IDs of oldest entries to remove
        excess = pending_count - max_size
        oldest = cls.query.filter(
            cls.status.in_(['pending', 'failed'])
        ).order_by(cls.created_at.asc()).limit(excess).all()

        for entry in oldest:
            db.session.delete(entry)

        db.session.commit()
        return len(oldest)

    def delete(self):
        """
        Remove this heartbeat from the queue.

        WARNING: Only call this after CMS has confirmed receipt.
        Calling this prematurely will lose the heartbeat data.
        """
        db.session.delete(self)
        db.session.commit()

    def __repr__(self):
        """String representation."""
        return f"<HeartbeatQueue id={self.id} device={self.device_id} status={self.status} attempts={self.attempts}>"
