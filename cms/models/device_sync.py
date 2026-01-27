"""
Device Sync Model for CMS Service.

Tracks the synchronization status of playlists and content to individual devices.
This enables:
- Tracking which version of a playlist each device has
- Monitoring sync progress across the fleet
- Identifying devices that need updates
"""

import enum
from datetime import datetime, timezone
import uuid

from cms.models import db


class DeviceSyncStatus(enum.Enum):
    """Sync status for a specific device.

    - PENDING: Device needs this content/playlist
    - QUEUED: Sync job is queued
    - SYNCING: Currently transferring to device
    - SYNCED: Device has the latest version
    - FAILED: Sync failed, needs retry
    """
    PENDING = 'pending'
    QUEUED = 'queued'
    SYNCING = 'syncing'
    SYNCED = 'synced'
    FAILED = 'failed'


class DevicePlaylistSync(db.Model):
    """
    Tracks playlist sync status for each device.

    When a playlist is assigned to a device, this record tracks whether
    the device has received the playlist and which version it has.

    Attributes:
        id: Unique identifier
        device_id: Reference to the device
        playlist_id: Reference to the playlist
        synced_version: Version of playlist currently on device
        sync_status: Current sync state for this device
        last_sync_attempt: When sync was last attempted
        last_successful_sync: When sync last succeeded
        error_message: Error details if sync failed
    """

    __tablename__ = 'device_playlist_syncs'

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
    synced_version = db.Column(db.Integer, nullable=True)  # None if never synced
    sync_status = db.Column(db.String(20), nullable=False, default=DeviceSyncStatus.PENDING.value)
    last_sync_attempt = db.Column(db.DateTime, nullable=True)
    last_successful_sync = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    device = db.relationship('Device', backref=db.backref('playlist_syncs', lazy='dynamic', cascade='all, delete-orphan'))
    playlist = db.relationship('Playlist', backref=db.backref('device_syncs', lazy='dynamic', cascade='all, delete-orphan'))

    # Unique constraint: one sync record per device-playlist pair
    __table_args__ = (
        db.UniqueConstraint('device_id', 'playlist_id', name='uq_device_playlist_sync'),
    )

    def to_dict(self):
        """Serialize to dictionary."""
        return {
            'id': self.id,
            'device_id': self.device_id,
            'playlist_id': self.playlist_id,
            'synced_version': self.synced_version,
            'sync_status': self.sync_status,
            'last_sync_attempt': self.last_sync_attempt.isoformat() if self.last_sync_attempt else None,
            'last_successful_sync': self.last_successful_sync.isoformat() if self.last_successful_sync else None,
            'error_message': self.error_message,
            'device_name': self.device.name if self.device else None,
            'playlist_name': self.playlist.name if self.playlist else None
        }

    @property
    def is_up_to_date(self):
        """Check if device has the latest playlist version."""
        if not self.playlist or self.synced_version is None:
            return False
        return self.synced_version >= self.playlist.version

    @property
    def needs_sync(self):
        """Check if this device needs a sync for this playlist."""
        return not self.is_up_to_date or self.sync_status == DeviceSyncStatus.FAILED.value

    def mark_syncing(self):
        """Mark as currently syncing."""
        self.sync_status = DeviceSyncStatus.SYNCING.value
        self.last_sync_attempt = datetime.now(timezone.utc)
        self.error_message = None

    def mark_synced(self, version):
        """Mark as successfully synced."""
        self.sync_status = DeviceSyncStatus.SYNCED.value
        self.synced_version = version
        self.last_successful_sync = datetime.now(timezone.utc)
        self.error_message = None

    def mark_failed(self, error_message=None):
        """Mark sync as failed."""
        self.sync_status = DeviceSyncStatus.FAILED.value
        self.error_message = error_message

    def __repr__(self):
        return f'<DevicePlaylistSync device={self.device_id} playlist={self.playlist_id}>'


class ContentSyncRecord(db.Model):
    """
    Tracks content file sync status for each device.

    Content files (videos, images) need to be physically transferred to devices.
    This tracks which content files each device has.

    Attributes:
        id: Unique identifier
        device_id: Reference to the device
        content_id: Reference to the content item
        sync_status: Current sync state
        file_checksum: Checksum of synced file for verification
        synced_at: When content was synced to device
    """

    __tablename__ = 'content_sync_records'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = db.Column(
        db.String(36),
        db.ForeignKey('devices.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    content_id = db.Column(
        db.String(36),
        db.ForeignKey('content.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    sync_status = db.Column(db.String(20), nullable=False, default=DeviceSyncStatus.PENDING.value)
    file_checksum = db.Column(db.String(64), nullable=True)  # SHA256 of file on device
    synced_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    device = db.relationship('Device', backref=db.backref('content_syncs', lazy='dynamic', cascade='all, delete-orphan'))
    content = db.relationship('Content', backref=db.backref('device_syncs', lazy='dynamic', cascade='all, delete-orphan'))

    # Unique constraint
    __table_args__ = (
        db.UniqueConstraint('device_id', 'content_id', name='uq_device_content_sync'),
    )

    def to_dict(self):
        """Serialize to dictionary."""
        return {
            'id': self.id,
            'device_id': self.device_id,
            'content_id': self.content_id,
            'sync_status': self.sync_status,
            'file_checksum': self.file_checksum,
            'synced_at': self.synced_at.isoformat() if self.synced_at else None,
            'error_message': self.error_message
        }

    def __repr__(self):
        return f'<ContentSyncRecord device={self.device_id} content={self.content_id}>'
