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
        is_active: Whether the playlist is currently active
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
    is_active = db.Column(db.Boolean, nullable=False, default=True)
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
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'item_count': self.items.count() if self.items else 0
        }

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
        nullable=False,
        index=True
    )
    position = db.Column(db.Integer, nullable=False, default=0)
    duration_override = db.Column(db.Integer, nullable=True)  # Duration in seconds for images
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    content = db.relationship('Content', backref=db.backref('playlist_items', lazy='dynamic'))

    def to_dict(self):
        """
        Serialize the playlist item to a dictionary for API responses.

        Returns:
            Dictionary containing all playlist item fields
        """
        return {
            'id': self.id,
            'playlist_id': self.playlist_id,
            'content_id': self.content_id,
            'position': self.position,
            'duration_override': self.duration_override,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'content': self.content.to_dict() if self.content else None
        }

    def __repr__(self):
        """String representation for debugging."""
        return f'<PlaylistItem {self.id} pos={self.position}>'
