"""
PlaybackLog Model for CMS Service.

Tracks content playback events from devices for analytics and reporting.
"""

from datetime import datetime, timezone
import uuid

from cms.models import db, DateTimeUTC


class PlaybackLog(db.Model):
    """
    SQLAlchemy model representing a content playback event.

    Playback logs are sent in batches (every 5 minutes) from devices
    to record what content played, when, and for how long.

    Attributes:
        id: Unique auto-increment identifier
        device_id: Device identifier (e.g., SKZ-H-WM-0001)
        hub_id: Hub identifier if device connects through a hub
        network_id: Network identifier (e.g., west_marine, high_octane)
        store_name: Human-readable store name
        location: Screen location within the store
        content_filename: Name of the video/content file played
        started_at: When playback started
        ended_at: When playback ended (nullable)
        duration_seconds: How long the content played
        created_at: When the log was recorded in CMS
    """

    __tablename__ = 'playback_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    device_id = db.Column(db.String(100), index=True, nullable=False)
    hub_id = db.Column(db.String(100), nullable=True)
    network_id = db.Column(db.String(100), nullable=True, index=True)
    store_name = db.Column(db.String(200), nullable=True)
    location = db.Column(db.String(200), nullable=True)
    content_filename = db.Column(db.String(500), nullable=False)
    started_at = db.Column(DateTimeUTC(), index=True, nullable=False)
    ended_at = db.Column(DateTimeUTC(), nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    created_at = db.Column(DateTimeUTC(), default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        """Serialize the playback log to a dictionary for API responses."""
        return {
            'id': self.id,
            'device_id': self.device_id,
            'hub_id': self.hub_id,
            'network_id': self.network_id,
            'store_name': self.store_name,
            'location': self.location,
            'content_filename': self.content_filename,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'duration_seconds': self.duration_seconds,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<PlaybackLog {self.device_id} - {self.content_filename}>'
