"""
DeviceAssignment Model for CMS Service.

Represents the mapping between devices and playlists, allowing:
- Assignment of playlists to specific devices
- Trigger-based playlist activation (demographics, face detection, etc.)
- Priority-based playlist ordering
- Time-bounded assignments with start/end dates

Supported trigger types:
- default: Always plays (fallback content)
- face_detected: Plays when any face is detected
- age_child: Plays when child is detected
- age_teen: Plays when teen is detected
- age_adult: Plays when adult is detected
- age_senior: Plays when senior is detected
- gender_male: Plays when male is detected
- gender_female: Plays when female is detected
- loyalty_recognized: Plays when loyalty member is recognized
- ncmec_alert: Plays during NCMEC alert (amber alert content)
"""

from datetime import datetime, timezone
import uuid

from cms.models import db, DateTimeUTC


# Valid trigger types for playlist assignments
TRIGGER_TYPES = [
    'default',          # Always plays (fallback content)
    'face_detected',    # Plays when any face is detected
    'age_child',        # Plays when child is detected (0-12)
    'age_teen',         # Plays when teen is detected (13-19)
    'age_adult',        # Plays when adult is detected (20-64)
    'age_senior',       # Plays when senior is detected (65+)
    'gender_male',      # Plays when male is detected
    'gender_female',    # Plays when female is detected
    'loyalty_recognized',  # Plays when loyalty member is recognized
    'ncmec_alert',      # Plays during NCMEC alert (amber alert content)
]


class DeviceAssignment(db.Model):
    """
    SQLAlchemy model representing a device-to-playlist assignment.

    A DeviceAssignment links a device to a playlist with trigger-based
    activation, scheduling, and priority information. Multiple playlists
    can be assigned to a single device with different triggers and priorities.

    Attributes:
        id: Unique UUID identifier
        device_id: Foreign key reference to the assigned device
        playlist_id: Foreign key reference to the assigned playlist
        trigger_type: Type of trigger that activates this playlist
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
    trigger_type = db.Column(db.String(50), nullable=False, default='default', index=True)
    priority = db.Column(db.Integer, nullable=False, default=0)
    is_enabled = db.Column(db.Boolean, nullable=False, default=False)  # Default OFF, except 'default' trigger
    start_date = db.Column(DateTimeUTC(), nullable=True)
    end_date = db.Column(DateTimeUTC(), nullable=True)
    created_at = db.Column(DateTimeUTC(), default=lambda: datetime.now(timezone.utc))

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
            'trigger_type': self.trigger_type,
            'priority': self.priority,
            'is_enabled': self.is_enabled,
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
        Check if the assignment is currently active based on enabled state and date constraints.

        Returns:
            bool: True if assignment is enabled and active (within date range or no dates set)
        """
        # Check if manually disabled
        if not self.is_enabled:
            return False

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
            cls.is_enabled == True,
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
