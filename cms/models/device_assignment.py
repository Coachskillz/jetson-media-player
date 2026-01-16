"""
DeviceAssignment Model for CMS Service.

Represents the mapping between devices and playlists, allowing:
- Assignment of playlists to specific devices
- Priority-based playlist ordering
- Time-bounded assignments with start/end dates
"""

from datetime import datetime, timezone
import uuid

from cms.models import db


class DeviceAssignment(db.Model):
    """
    SQLAlchemy model representing a device-to-playlist assignment.

    A DeviceAssignment links a device to a playlist with additional
    scheduling and priority information. Multiple playlists can be
    assigned to a single device with different priorities and time windows.

    Attributes:
        id: Unique UUID identifier
        device_id: Foreign key reference to the assigned device
        playlist_id: Foreign key reference to the assigned playlist
        priority: Priority level for playlist ordering (higher = more important)
        start_date: Optional start date for the assignment
        end_date: Optional end date for the assignment
        created_at: Timestamp when the assignment was created
    """

    __tablename__ = 'device_assignments'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = db.Column(
        db.String(36),
        db.ForeignKey('devices.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    playlist_id = db.Column(
        db.String(36),
        db.ForeignKey('playlists.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    priority = db.Column(db.Integer, nullable=False, default=0)
    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    device = db.relationship('Device', backref=db.backref('assignments', lazy='dynamic', cascade='all, delete-orphan'))
    playlist = db.relationship('Playlist', backref=db.backref('assignments', lazy='dynamic', cascade='all, delete-orphan'))

    def to_dict(self):
        """
        Serialize the device assignment to a dictionary for API responses.

        Returns:
            Dictionary containing all device assignment fields
        """
        return {
            'id': self.id,
            'device_id': self.device_id,
            'playlist_id': self.playlist_id,
            'priority': self.priority,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def to_dict_with_relations(self):
        """
        Serialize the device assignment with related device and playlist info.

        Returns:
            Dictionary containing assignment fields with nested device and playlist
        """
        result = self.to_dict()
        result['device'] = self.device.to_dict() if self.device else None
        result['playlist'] = self.playlist.to_dict() if self.playlist else None
        return result

    def is_active(self):
        """
        Check if the assignment is currently active based on date constraints.

        Returns:
            bool: True if assignment is active (within date range or no dates set)
        """
        now = datetime.now(timezone.utc)

        # If no date constraints, always active
        if not self.start_date and not self.end_date:
            return True

        # Check start date
        if self.start_date and now < self.start_date:
            return False

        # Check end date
        if self.end_date and now > self.end_date:
            return False

        return True

    @classmethod
    def get_active_for_device(cls, device_id):
        """
        Get all currently active assignments for a device, ordered by priority.

        Args:
            device_id: The device ID to filter by

        Returns:
            list: List of active DeviceAssignment instances ordered by priority (desc)
        """
        now = datetime.now(timezone.utc)
        return cls.query.filter(
            cls.device_id == device_id,
            db.or_(cls.start_date.is_(None), cls.start_date <= now),
            db.or_(cls.end_date.is_(None), cls.end_date >= now)
        ).order_by(cls.priority.desc()).all()

    @classmethod
    def get_by_playlist(cls, playlist_id):
        """
        Get all assignments for a specific playlist.

        Args:
            playlist_id: The playlist ID to filter by

        Returns:
            list: List of DeviceAssignment instances for the playlist
        """
        return cls.query.filter_by(playlist_id=playlist_id).all()

    def __repr__(self):
        """String representation for debugging."""
        return f'<DeviceAssignment device={self.device_id} playlist={self.playlist_id} priority={self.priority}>'
