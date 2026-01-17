"""
Playlist database model for caching playlists from CMS.

This model tracks playlists synced from HQ and cached locally:
- Identity: playlist_id (unique from HQ), name
- Metadata: description, network_id, trigger_type, trigger_config
- Content: items (JSON array of playlist items)
- State: is_active
- Timestamps: synced_at, updated_at

Playlists are synced from HQ periodically. The local copy allows:
1. Devices to retrieve playlists when CMS is unreachable
2. Faster local playlist delivery to screens on the LAN
3. Offline resilience for the hub
"""

import json
from datetime import datetime
from models import db


class Playlist(db.Model):
    """
    Database model for cached playlist data from CMS.

    Each playlist represents a collection of content items synced
    from HQ and cached locally for serving to devices on the LAN.
    The items field stores the complete playlist item data as JSON.

    Attributes:
        id: Primary key
        playlist_id: Unique playlist identifier from HQ
        name: Playlist name
        description: Optional playlist description
        network_id: Network this playlist belongs to
        trigger_type: Trigger type (time, event, manual)
        trigger_config: JSON trigger configuration
        items: JSON array of playlist items with content references
        is_active: Whether the playlist is active
        synced_at: When playlist was last synced from HQ
        updated_at: Last modification timestamp
    """
    __tablename__ = 'playlists'

    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(256), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Organization
    network_id = db.Column(db.String(64), nullable=True, index=True)

    # Trigger configuration
    trigger_type = db.Column(db.String(32), default='manual', nullable=True)
    trigger_config = db.Column(db.Text, nullable=True)  # JSON string

    # Playlist items (stored as JSON for offline access)
    items = db.Column(db.Text, nullable=True)  # JSON array of items

    # State
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Timestamps
    synced_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """
        Serialize model to dictionary for JSON responses.

        Returns:
            dict: Complete playlist metadata including items
        """
        return {
            'id': self.id,
            'playlist_id': self.playlist_id,
            'name': self.name,
            'description': self.description,
            'network_id': self.network_id,
            'trigger_type': self.trigger_type,
            'trigger_config': self._parse_json(self.trigger_config),
            'items': self._parse_json(self.items) or [],
            'is_active': self.is_active,
            'synced_at': self.synced_at.isoformat() if self.synced_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def to_device_response(self):
        """
        Return data for device playlist endpoint.

        This is the data returned to devices when they request
        their assigned playlist.

        Returns:
            dict: Playlist data formatted for device consumption
        """
        return {
            'playlist_id': self.playlist_id,
            'name': self.name,
            'trigger_type': self.trigger_type,
            'trigger_config': self._parse_json(self.trigger_config),
            'items': self._parse_json(self.items) or [],
            'is_active': self.is_active
        }

    @staticmethod
    def _parse_json(value):
        """
        Safely parse JSON string.

        Args:
            value: JSON string or None

        Returns:
            Parsed value or None if invalid/empty
        """
        if not value:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _serialize_json(value):
        """
        Safely serialize value to JSON string.

        Args:
            value: Value to serialize

        Returns:
            JSON string or None
        """
        if value is None:
            return None
        try:
            return json.dumps(value)
        except (TypeError, ValueError):
            return None

    @property
    def is_synced(self):
        """
        Check if playlist has been synced from HQ.

        Returns:
            bool: True if synced_at is set
        """
        return bool(self.synced_at)

    @property
    def item_count(self):
        """
        Get the number of items in the playlist.

        Returns:
            int: Number of items
        """
        items = self._parse_json(self.items)
        return len(items) if items else 0

    def get_items(self):
        """
        Get parsed playlist items.

        Returns:
            list: List of playlist item dictionaries
        """
        return self._parse_json(self.items) or []

    def get_content_ids(self):
        """
        Get list of content IDs referenced by this playlist.

        Returns:
            list: List of content_id strings
        """
        items = self.get_items()
        return [item.get('content_id') for item in items if item.get('content_id')]

    def update_from_hq(self, data):
        """
        Update playlist from HQ sync data.

        Args:
            data: Dictionary of playlist data from HQ
        """
        self.name = data.get('name', self.name)
        self.description = data.get('description')
        self.network_id = data.get('network_id')
        self.trigger_type = data.get('trigger_type', 'manual')
        self.trigger_config = self._serialize_json(data.get('trigger_config'))
        self.items = self._serialize_json(data.get('items'))
        self.is_active = data.get('is_active', True)
        self.synced_at = datetime.utcnow()
        db.session.commit()

    @classmethod
    def get_by_playlist_id(cls, playlist_id):
        """
        Find playlist by HQ playlist identifier.

        Args:
            playlist_id: The playlist_id to search for

        Returns:
            Playlist or None: The playlist record if found
        """
        return cls.query.filter_by(playlist_id=playlist_id).first()

    @classmethod
    def get_all_synced(cls):
        """
        Get all playlists that have been synced from HQ.

        Returns:
            list: List of Playlist instances with sync data
        """
        return cls.query.filter(cls.synced_at.isnot(None)).all()

    @classmethod
    def get_active(cls):
        """
        Get all active playlists.

        Returns:
            list: List of active Playlist instances
        """
        return cls.query.filter_by(is_active=True).all()

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
    def create_or_update(cls, playlist_id, name, description=None,
                         network_id=None, trigger_type='manual',
                         trigger_config=None, items=None, is_active=True):
        """
        Create new playlist record or update existing one.

        Used during sync to ensure playlist record exists.

        Args:
            playlist_id: Unique identifier from HQ
            name: Playlist name
            description: Optional description
            network_id: Network ID from HQ
            trigger_type: Trigger type (time, event, manual)
            trigger_config: Trigger configuration dict
            items: List of playlist item dicts
            is_active: Whether playlist is active

        Returns:
            tuple: (Playlist instance, bool created)
        """
        playlist = cls.get_by_playlist_id(playlist_id)
        if playlist:
            # Update existing record
            playlist.name = name
            playlist.description = description
            playlist.network_id = network_id
            playlist.trigger_type = trigger_type
            playlist.trigger_config = cls._serialize_json(trigger_config)
            playlist.items = cls._serialize_json(items)
            playlist.is_active = is_active
            playlist.synced_at = datetime.utcnow()
            db.session.commit()
            return playlist, False

        # Create new record
        playlist = cls(
            playlist_id=playlist_id,
            name=name,
            description=description,
            network_id=network_id,
            trigger_type=trigger_type,
            trigger_config=cls._serialize_json(trigger_config),
            items=cls._serialize_json(items),
            is_active=is_active,
            synced_at=datetime.utcnow()
        )
        db.session.add(playlist)
        db.session.commit()
        return playlist, True

    @classmethod
    def delete_by_playlist_id(cls, playlist_id):
        """
        Delete a playlist by its HQ identifier.

        Args:
            playlist_id: The playlist_id to delete

        Returns:
            bool: True if deleted, False if not found
        """
        playlist = cls.get_by_playlist_id(playlist_id)
        if playlist:
            db.session.delete(playlist)
            db.session.commit()
            return True
        return False

    @classmethod
    def get_all_playlist_ids(cls):
        """
        Get all playlist IDs currently in the database.

        Used for sync comparison to detect deletions.

        Returns:
            set: Set of playlist_id strings
        """
        results = cls.query.with_entities(cls.playlist_id).all()
        return {r[0] for r in results}

    def __repr__(self):
        """String representation."""
        return f"<Playlist playlist_id={self.playlist_id} name='{self.name}' synced={self.is_synced}>"
