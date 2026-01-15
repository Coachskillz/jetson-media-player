"""
Content database model for tracking cached media files.

This model tracks media content downloaded from HQ and cached locally:
- Identity: content_id (unique from HQ), filename
- Storage: local_path (where file is stored on disk)
- Integrity: file_hash (SHA256 for verification), file_size
- Metadata: content_type, duration_seconds
- Timestamps: cached_at, last_accessed, updated_at

Content is synced from HQ periodically. The file_hash is used to:
1. Detect when content needs to be re-downloaded (hash mismatch)
2. Verify file integrity after download
3. Allow screens to check if they have current version
"""

from datetime import datetime
from models import db


class Content(db.Model):
    """
    Database model for cached media content files.

    Each content item represents a media file downloaded from HQ
    and cached locally for serving to screens on the LAN. The
    file_hash provides integrity verification and change detection.

    Attributes:
        id: Primary key
        content_id: Unique content identifier from HQ
        filename: Original filename from HQ
        local_path: Path where file is stored locally
        file_hash: SHA256 hash for integrity verification
        file_size: File size in bytes
        content_type: Media type (video, image, audio)
        duration_seconds: Duration for video/audio content
        playlist_ids: Comma-separated list of playlists using this content
        cached_at: When content was downloaded/cached
        last_accessed: When content was last served to a screen
        updated_at: Last modification timestamp
    """
    __tablename__ = 'content'

    id = db.Column(db.Integer, primary_key=True)
    content_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    filename = db.Column(db.String(256), nullable=False)

    # Storage tracking
    local_path = db.Column(db.String(512), nullable=True)
    file_hash = db.Column(db.String(64), nullable=True)  # SHA256 hash
    file_size = db.Column(db.Integer, nullable=True)

    # Content metadata
    content_type = db.Column(db.String(32), default='video', nullable=False)
    duration_seconds = db.Column(db.Integer, nullable=True)
    playlist_ids = db.Column(db.Text, nullable=True)  # Comma-separated

    # Timestamps
    cached_at = db.Column(db.DateTime, nullable=True)
    last_accessed = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """
        Serialize model to dictionary for JSON responses.

        Returns:
            dict: Complete content metadata including hash
        """
        return {
            'id': self.id,
            'content_id': self.content_id,
            'filename': self.filename,
            'local_path': self.local_path,
            'file_hash': self.file_hash,
            'file_size': self.file_size,
            'content_type': self.content_type,
            'duration_seconds': self.duration_seconds,
            'playlist_ids': self.playlist_ids.split(',') if self.playlist_ids else [],
            'cached_at': self.cached_at.isoformat() if self.cached_at else None,
            'last_accessed': self.last_accessed.isoformat() if self.last_accessed else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def to_manifest_item(self):
        """
        Return data for content manifest endpoint.

        This is the data returned by GET /api/v1/content that
        screens use to determine which content needs downloading.

        Returns:
            dict: Manifest item with hash for integrity checking
        """
        return {
            'content_id': self.content_id,
            'filename': self.filename,
            'file_hash': self.file_hash,
            'file_size': self.file_size,
            'content_type': self.content_type,
            'duration_seconds': self.duration_seconds
        }

    @property
    def is_cached(self):
        """
        Check if content file is available locally.

        Returns:
            bool: True if local_path is set and file was cached
        """
        return bool(self.local_path and self.cached_at)

    def mark_accessed(self):
        """
        Update last_accessed timestamp when content is served.

        Call this when serving the content file to a screen.
        """
        self.last_accessed = datetime.utcnow()
        db.session.commit()

    def update_cache_info(self, local_path, file_hash, file_size):
        """
        Update caching information after downloading file.

        Args:
            local_path: Path where file is stored
            file_hash: SHA256 hash of downloaded file
            file_size: Size of file in bytes
        """
        self.local_path = local_path
        self.file_hash = file_hash
        self.file_size = file_size
        self.cached_at = datetime.utcnow()
        db.session.commit()

    def needs_update(self, new_hash):
        """
        Check if content needs to be re-downloaded.

        Compares current file_hash with new hash from HQ manifest.

        Args:
            new_hash: SHA256 hash from HQ manifest

        Returns:
            bool: True if hash differs or content not cached
        """
        if not self.is_cached:
            return True
        return self.file_hash != new_hash

    @classmethod
    def get_by_content_id(cls, content_id):
        """
        Find content by HQ content identifier.

        Args:
            content_id: The content_id to search for

        Returns:
            Content or None: The content record if found
        """
        return cls.query.filter_by(content_id=content_id).first()

    @classmethod
    def get_all_cached(cls):
        """
        Get all content items that are cached locally.

        Returns:
            list: List of Content instances with cached files
        """
        return cls.query.filter(cls.cached_at.isnot(None)).all()

    @classmethod
    def get_manifest(cls):
        """
        Get all content items for manifest endpoint.

        Returns:
            list: List of manifest item dictionaries
        """
        items = cls.query.filter(cls.cached_at.isnot(None)).all()
        return [item.to_manifest_item() for item in items]

    @classmethod
    def create_or_update(cls, content_id, filename, content_type='video',
                         duration_seconds=None, playlist_ids=None):
        """
        Create new content record or update existing one.

        Used during sync to ensure content record exists.

        Args:
            content_id: Unique identifier from HQ
            filename: Original filename
            content_type: Media type (video, image, audio)
            duration_seconds: Optional duration for video/audio
            playlist_ids: Optional list of playlist IDs

        Returns:
            tuple: (Content instance, bool created)
        """
        content = cls.get_by_content_id(content_id)
        if content:
            # Update existing record
            content.filename = filename
            content.content_type = content_type
            if duration_seconds is not None:
                content.duration_seconds = duration_seconds
            if playlist_ids is not None:
                content.playlist_ids = ','.join(playlist_ids) if isinstance(playlist_ids, list) else playlist_ids
            db.session.commit()
            return content, False

        # Create new record
        content = cls(
            content_id=content_id,
            filename=filename,
            content_type=content_type,
            duration_seconds=duration_seconds,
            playlist_ids=','.join(playlist_ids) if isinstance(playlist_ids, list) else playlist_ids
        )
        db.session.add(content)
        db.session.commit()
        return content, True

    def __repr__(self):
        """String representation."""
        return f"<Content content_id={self.content_id} cached={self.is_cached}>"
