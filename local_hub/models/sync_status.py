"""
SyncStatus database model for tracking synchronization state with HQ.

This model tracks version information for synced resources:
- content: Media content manifest and files from HQ
- ncmec_db: NCMEC FAISS database for facial recognition
- loyalty_db: Loyalty FAISS database for member recognition

Each resource type has exactly one SyncStatus record that tracks:
- version: Current version identifier (from HQ)
- file_hash: SHA256 hash for integrity verification
- last_sync_at: When last successful sync occurred
- sync_error: Error message if last sync failed
"""

from datetime import datetime
from models import db


class SyncStatus(db.Model):
    """
    Database model for tracking sync state with HQ.

    Each record represents a syncable resource type (content, ncmec_db, loyalty_db).
    The version and file_hash are used to determine when updates are needed.

    Attributes:
        id: Primary key
        resource_type: Type of resource (content, ncmec_db, loyalty_db)
        version: Version string from HQ (e.g., "2024-01-15T10:30:00Z")
        file_hash: SHA256 hash for integrity verification
        file_size: Size of resource in bytes (for databases)
        last_sync_at: Timestamp of last successful sync
        last_attempt_at: Timestamp of last sync attempt
        sync_error: Error message if last sync failed
        updated_at: Last modification timestamp
    """
    __tablename__ = 'sync_status'

    # Valid resource types
    RESOURCE_CONTENT = 'content'
    RESOURCE_NCMEC_DB = 'ncmec_db'
    RESOURCE_LOYALTY_DB = 'loyalty_db'
    RESOURCE_PLAYLIST = 'playlist'

    VALID_RESOURCE_TYPES = [RESOURCE_CONTENT, RESOURCE_NCMEC_DB, RESOURCE_LOYALTY_DB, RESOURCE_PLAYLIST]

    id = db.Column(db.Integer, primary_key=True)
    resource_type = db.Column(db.String(32), unique=True, nullable=False, index=True)
    version = db.Column(db.String(128), nullable=True)
    file_hash = db.Column(db.String(64), nullable=True)  # SHA256 hash
    file_size = db.Column(db.Integer, nullable=True)

    # Sync tracking
    last_sync_at = db.Column(db.DateTime, nullable=True)
    last_attempt_at = db.Column(db.DateTime, nullable=True)
    sync_error = db.Column(db.Text, nullable=True)

    # Timestamps
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """
        Serialize model to dictionary for JSON responses.

        Returns:
            dict: Complete sync status information
        """
        return {
            'id': self.id,
            'resource_type': self.resource_type,
            'version': self.version,
            'file_hash': self.file_hash,
            'file_size': self.file_size,
            'last_sync_at': self.last_sync_at.isoformat() if self.last_sync_at else None,
            'last_attempt_at': self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            'sync_error': self.sync_error,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def to_version_info(self):
        """
        Return version information for API endpoints.

        This is the data returned by database version endpoints
        that screens use to check if they need to download updates.

        Returns:
            dict: Version info with hash for integrity checking
        """
        return {
            'version': self.version,
            'file_hash': self.file_hash,
            'file_size': self.file_size,
            'last_updated': self.last_sync_at.isoformat() if self.last_sync_at else None
        }

    @property
    def is_synced(self):
        """
        Check if resource has been successfully synced.

        Returns:
            bool: True if last_sync_at is set and no error
        """
        return bool(self.last_sync_at and not self.sync_error)

    @property
    def has_error(self):
        """
        Check if last sync attempt had an error.

        Returns:
            bool: True if sync_error is set
        """
        return bool(self.sync_error)

    def mark_sync_success(self, version=None, file_hash=None, file_size=None):
        """
        Update status after successful sync.

        Args:
            version: New version string from HQ
            file_hash: SHA256 hash of synced resource
            file_size: Size of resource in bytes
        """
        now = datetime.utcnow()
        if version is not None:
            self.version = version
        if file_hash is not None:
            self.file_hash = file_hash
        if file_size is not None:
            self.file_size = file_size
        self.last_sync_at = now
        self.last_attempt_at = now
        self.sync_error = None
        db.session.commit()

    def mark_sync_failure(self, error_message):
        """
        Update status after failed sync attempt.

        Args:
            error_message: Description of the sync error
        """
        self.last_attempt_at = datetime.utcnow()
        self.sync_error = error_message
        db.session.commit()

    def needs_update(self, new_version=None, new_hash=None):
        """
        Check if resource needs to be re-synced.

        Compares current version/hash with new values from HQ.

        Args:
            new_version: Version string from HQ manifest
            new_hash: SHA256 hash from HQ manifest

        Returns:
            bool: True if version differs, hash differs, or not synced
        """
        if not self.is_synced:
            return True
        if new_version is not None and self.version != new_version:
            return True
        if new_hash is not None and self.file_hash != new_hash:
            return True
        return False

    @classmethod
    def get_by_type(cls, resource_type):
        """
        Find sync status by resource type.

        Args:
            resource_type: The resource type to look up

        Returns:
            SyncStatus or None: The status record if found
        """
        return cls.query.filter_by(resource_type=resource_type).first()

    @classmethod
    def get_or_create(cls, resource_type):
        """
        Get sync status for resource type, creating if needed.

        Args:
            resource_type: One of VALID_RESOURCE_TYPES

        Returns:
            SyncStatus: The status record (existing or new)

        Raises:
            ValueError: If resource_type is not valid
        """
        if resource_type not in cls.VALID_RESOURCE_TYPES:
            raise ValueError(f"Invalid resource type: {resource_type}. "
                           f"Must be one of: {cls.VALID_RESOURCE_TYPES}")

        status = cls.get_by_type(resource_type)
        if status is None:
            status = cls(resource_type=resource_type)
            db.session.add(status)
            db.session.commit()
        return status

    @classmethod
    def get_all(cls):
        """
        Get all sync status records.

        Returns:
            list: List of all SyncStatus instances
        """
        return cls.query.all()

    @classmethod
    def get_content_status(cls):
        """
        Get sync status for content.

        Returns:
            SyncStatus: Content sync status (created if needed)
        """
        return cls.get_or_create(cls.RESOURCE_CONTENT)

    @classmethod
    def get_ncmec_db_status(cls):
        """
        Get sync status for NCMEC database.

        Returns:
            SyncStatus: NCMEC DB sync status (created if needed)
        """
        return cls.get_or_create(cls.RESOURCE_NCMEC_DB)

    @classmethod
    def get_loyalty_db_status(cls):
        """
        Get sync status for loyalty database.

        Returns:
            SyncStatus: Loyalty DB sync status (created if needed)
        """
        return cls.get_or_create(cls.RESOURCE_LOYALTY_DB)

    @classmethod
    def get_playlist_status(cls):
        """
        Get sync status for playlists.

        Returns:
            SyncStatus: Playlist sync status (created if needed)
        """
        return cls.get_or_create(cls.RESOURCE_PLAYLIST)

    def __repr__(self):
        """String representation."""
        return f"<SyncStatus resource_type={self.resource_type} version={self.version} synced={self.is_synced}>"
