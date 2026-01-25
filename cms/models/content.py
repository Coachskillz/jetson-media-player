"""
Content Model for CMS Service.

Represents uploaded media content with file metadata including:
- File info: filename, original_name, mime_type, file_size
- Dimensions: width, height (for 16:9 aspect ratio preview)
- Duration: duration in seconds (for video/audio content)
- Organization: network_id for content ownership
- Status: approval status (pending/approved/rejected)
"""

import enum
from datetime import datetime, timezone
import uuid

from cms.models import db


class ContentStatus(enum.Enum):
    """Content status enum for approval workflow.

    Defines the approval status of content items:
    - PENDING: Awaiting review/approval
    - APPROVED: Approved for use in playlists
    - REJECTED: Rejected and not available for playlists
    """
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'


class Content(db.Model):
    """
    SQLAlchemy model representing uploaded media content.

    Content items are media files (images, videos, audio) that can be
    assigned to playlists and displayed on devices. The model stores
    file metadata including dimensions for 16:9 preview rendering.

    Attributes:
        id: Unique UUID identifier
        filename: Stored filename (may be sanitized/renamed from original)
        original_name: Original filename as uploaded by user
        mime_type: MIME type of the file (e.g., video/mp4, image/jpeg)
        file_size: File size in bytes
        width: Content width in pixels (for images/video)
        height: Content height in pixels (for images/video)
        duration: Duration in seconds (for video/audio content)
        status: Approval status (pending/approved/rejected)
        network_id: Foreign key reference to the owning network
        created_at: Timestamp when the content was uploaded
    """

    __tablename__ = 'content'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = db.Column(db.String(500), nullable=False)
    original_name = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    duration = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=ContentStatus.PENDING.value)
    network_id = db.Column(db.String(36), db.ForeignKey('networks.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Content Catalog integration
    # Links CMS content to a Content Catalog asset for syncing
    catalog_asset_uuid = db.Column(db.String(36), nullable=True, index=True)
    source = db.Column(db.String(20), nullable=True)  # 'upload' or 'catalog'

    # Folder organization
    folder_id = db.Column(db.String(36), db.ForeignKey('folders.id'), nullable=True, index=True)

    # Relationships
    network = db.relationship('Network', backref=db.backref('content', lazy='dynamic'))
    folder = db.relationship('Folder', backref=db.backref('content_items', lazy='dynamic'))

    def to_dict(self):
        """
        Serialize the content to a dictionary for API responses.

        Returns:
            Dictionary containing all content fields
        """
        return {
            'id': self.id,
            'filename': self.filename,
            'original_name': self.original_name,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'width': self.width,
            'height': self.height,
            'duration': self.duration,
            'status': self.status,
            'network_id': self.network_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'catalog_asset_uuid': self.catalog_asset_uuid,
            'source': self.source,
            'folder_id': self.folder_id,
            'folder_name': self.folder.name if self.folder else None,
            'folder_icon': self.folder.icon if self.folder else None,
            'folder_color': self.folder.color if self.folder else None
        }

    def to_manifest_item(self):
        """
        Return data for content manifest endpoint.

        This is the data returned in hub content manifests
        for content distribution to devices.

        Returns:
            Dictionary with essential content metadata
        """
        return {
            'id': self.id,
            'filename': self.filename,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'duration': self.duration
        }

    @property
    def is_video(self):
        """
        Check if content is a video file.

        Returns:
            bool: True if mime_type indicates video content
        """
        return self.mime_type.startswith('video/') if self.mime_type else False

    @property
    def is_image(self):
        """
        Check if content is an image file.

        Returns:
            bool: True if mime_type indicates image content
        """
        return self.mime_type.startswith('image/') if self.mime_type else False

    @property
    def is_audio(self):
        """
        Check if content is an audio file.

        Returns:
            bool: True if mime_type indicates audio content
        """
        return self.mime_type.startswith('audio/') if self.mime_type else False

    @property
    def aspect_ratio(self):
        """
        Calculate aspect ratio of the content.

        Returns:
            float or None: Width/height ratio, None if dimensions not set
        """
        if self.width and self.height:
            return self.width / self.height
        return None

    @classmethod
    def get_by_network(cls, network_id):
        """
        Get all content for a specific network.

        Args:
            network_id: The network ID to filter by

        Returns:
            list: List of Content instances for the network
        """
        return cls.query.filter_by(network_id=network_id).all()

    def __repr__(self):
        """String representation for debugging."""
        return f'<Content {self.original_name}>'
