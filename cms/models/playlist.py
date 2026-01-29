"""
Playlist Model for CMS Service.

Represents playlists with trigger support including:
- Playlist metadata: name, description, is_active
- Trigger configuration: trigger_type, trigger_config (JSON)
- Organization: network_id for playlist ownership
- Playlist items: ordered list of content items
"""

import enum
from datetime import datetime, timezone
import uuid

from cms.models import db


class TriggerType(enum.Enum):
    """Trigger type enum for playlists.

    Defines when/how a playlist should be activated:
    - TIME: Scheduled activation based on time/date
    - EVENT: Triggered by external events
    - MANUAL: Manually activated by operator
    """
    TIME = 'time'
    EVENT = 'event'
    MANUAL = 'manual'


class LoopMode(enum.Enum):
    """Loop mode enum for playlists.

    Defines how the playlist should loop:
    - CONTINUOUS: Loop forever until stopped
    - PLAY_ONCE: Play through once, then stop
    - SCHEDULED: Play only during scheduled times (start_date to end_date)
    """
    CONTINUOUS = 'continuous'
    PLAY_ONCE = 'play_once'
    SCHEDULED = 'scheduled'


class Priority(enum.Enum):
    """Priority enum for playlists.

    Defines the priority level for playlist playback:
    - NORMAL: Standard priority, plays in normal rotation
    - HIGH: High priority, plays before normal playlists
    - INTERRUPT: Interrupts current playback (for NCMEC alerts)
    """
    NORMAL = 'normal'
    HIGH = 'high'
    INTERRUPT = 'interrupt'


class SyncStatus(enum.Enum):
    """Sync status enum for playlists.

    Tracks the synchronization state of a playlist:
    - DRAFT: Playlist is being edited, not ready for sync
    - PENDING: Playlist has changes that need to be synced to devices
    - SYNCING: Sync is currently in progress
    - SYNCED: All assigned devices have the latest version
    - ERROR: Sync failed for one or more devices
    """
    DRAFT = 'draft'
    PENDING = 'pending'
    SYNCING = 'syncing'
    SYNCED = 'synced'
    ERROR = 'error'


class Playlist(db.Model):
    """
    SQLAlchemy model representing a playlist with trigger support.

    A playlist is an ordered collection of content items that can be
    assigned to devices. Playlists support different trigger types
    for controlling when and how they are activated.

    Attributes:
        id: Unique UUID identifier
        name: Human-readable playlist name
        description: Optional detailed description
        network_id: Foreign key reference to the owning network
        trigger_type: Type of trigger (time/event/manual)
        trigger_config: JSON configuration for the trigger
        loop_mode: How the playlist loops (continuous/play_once/scheduled)
        priority: Playback priority level (normal/high/interrupt)
        start_date: Optional start date for scheduled playback
        end_date: Optional end date for scheduled playback
        is_active: Whether the playlist is currently active
        sync_status: Current sync state (draft/pending/syncing/synced/error)
        version: Incremental version number for tracking changes
        last_synced_at: Timestamp of last successful sync to devices
        created_at: Timestamp when the playlist was created
        updated_at: Timestamp when the playlist was last modified
    """

    __tablename__ = 'playlists'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    network_id = db.Column(db.String(36), db.ForeignKey('networks.id'), nullable=True, index=True)
    trigger_type = db.Column(db.String(50), nullable=True, default=TriggerType.MANUAL.value)
    trigger_config = db.Column(db.Text, nullable=True)  # JSON string for trigger configuration
    loop_mode = db.Column(db.String(20), nullable=False, default=LoopMode.CONTINUOUS.value)
    priority = db.Column(db.String(20), nullable=False, default=Priority.NORMAL.value)
    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # Sync tracking fields
    sync_status = db.Column(db.String(20), nullable=False, default=SyncStatus.DRAFT.value)
    version = db.Column(db.Integer, nullable=False, default=1)
    last_synced_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    network = db.relationship('Network', backref=db.backref('playlists', lazy='dynamic'))
    items = db.relationship(
        'PlaylistItem',
        backref='playlist',
        lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='PlaylistItem.position'
    )

    def to_dict(self):
        """
        Serialize the playlist to a dictionary for API responses.

        Returns:
            Dictionary containing all playlist fields
        """
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'network_id': self.network_id,
            'trigger_type': self.trigger_type,
            'trigger_config': self.trigger_config,
            'loop_mode': self.loop_mode,
            'priority': self.priority,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'is_active': self.is_active,
            'sync_status': self.sync_status,
            'version': self.version,
            'last_synced_at': self.last_synced_at.isoformat() if self.last_synced_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'item_count': self.items.count() if self.items else 0
        }

    def mark_pending_sync(self):
        """Mark playlist as needing sync after changes are made."""
        self.sync_status = SyncStatus.PENDING.value
        self.version += 1

    def mark_syncing(self):
        """Mark playlist as currently syncing."""
        self.sync_status = SyncStatus.SYNCING.value

    def mark_synced(self):
        """Mark playlist as successfully synced to all devices."""
        self.sync_status = SyncStatus.SYNCED.value
        self.last_synced_at = datetime.now(timezone.utc)

    def mark_sync_error(self):
        """Mark playlist sync as failed."""
        self.sync_status = SyncStatus.ERROR.value

    @property
    def needs_sync(self):
        """Check if playlist has pending changes that need to be synced."""
        return self.sync_status in [SyncStatus.PENDING.value, SyncStatus.ERROR.value]

    def to_dict_with_items(self):
        """
        Serialize the playlist with all items for detailed API responses.

        Returns:
            Dictionary containing playlist fields and all items
        """
        result = self.to_dict()
        result['items'] = [item.to_dict() for item in self.items.order_by(PlaylistItem.position).all()]
        return result

    @property
    def duration(self):
        """
        Calculate total duration of all content items in the playlist.

        Returns:
            int or None: Total duration in seconds, None if no items have duration
        """
        total = 0
        for item in self.items.all():
            if item.content and item.content.duration:
                total += item.content.duration
            elif item.duration_override:
                total += item.duration_override
        return total if total > 0 else None

    @classmethod
    def get_by_network(cls, network_id):
        """
        Get all playlists for a specific network.

        Args:
            network_id: The network ID to filter by

        Returns:
            list: List of Playlist instances for the network
        """
        return cls.query.filter_by(network_id=network_id).all()

    @classmethod
    def get_active_by_network(cls, network_id):
        """
        Get all active playlists for a specific network.

        Args:
            network_id: The network ID to filter by

        Returns:
            list: List of active Playlist instances for the network
        """
        return cls.query.filter_by(network_id=network_id, is_active=True).all()

    def __repr__(self):
        """String representation for debugging."""
        return f'<Playlist {self.name}>'


class PlaylistItem(db.Model):
    """
    SQLAlchemy model representing an item in a playlist.

    Playlist items link content to playlists with ordering (position)
    and optional duration overrides for images.

    Attributes:
        id: Unique UUID identifier
        playlist_id: Foreign key reference to the parent playlist
        content_id: Foreign key reference to the content item
        position: Order position within the playlist (0-indexed)
        duration_override: Optional duration override for images (seconds)
        created_at: Timestamp when the item was added
    """

    __tablename__ = 'playlist_items'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    playlist_id = db.Column(
        db.String(36),
        db.ForeignKey('playlists.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    content_id = db.Column(
        db.String(36),
        db.ForeignKey('content.id', ondelete='CASCADE'),
        nullable=True,
        index=True
    )
    synced_content_id = db.Column(
        db.String(36),
        db.ForeignKey('synced_content.id', ondelete='CASCADE'),
        nullable=True,
        index=True
    )
    position = db.Column(db.Integer, nullable=False, default=0)
    duration_override = db.Column(db.Integer, nullable=True)  # Duration in seconds for images
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    content = db.relationship('Content', backref=db.backref('playlist_items', lazy='dynamic'))
    synced_content = db.relationship('SyncedContent', backref=db.backref('playlist_items', lazy='dynamic'))

    def to_dict(self):
        """
        Serialize the playlist item to a dictionary for API responses.

        Returns:
            Dictionary containing all playlist item fields
        """
        # Resolve content from either table
        resolved_content = None
        resolved_content_id = self.content_id or self.synced_content_id
        if self.content:
            resolved_content = self.content.to_dict()
        elif self.synced_content:
            resolved_content = self.synced_content.to_dict()

        return {
            'id': self.id,
            'playlist_id': self.playlist_id,
            'content_id': resolved_content_id,
            'synced_content_id': self.synced_content_id,
            'position': self.position,
            'duration_override': self.duration_override,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'content': resolved_content
        }

    def __repr__(self):
        """String representation for debugging."""
        return f'<PlaylistItem {self.id} pos={self.position}>'
