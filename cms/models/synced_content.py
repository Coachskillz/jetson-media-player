"""
Synced Content Model for CMS Service.

Represents content assets synced from the Content Catalog service.
This model caches approved/published content from the Content Catalog
for display in the CMS content page without requiring direct upload.

Key features:
- Caches content metadata from Content Catalog API
- Stores source tracking (uuid, organization, last sync time)
- Supports network filtering for multi-tenant content isolation
- Read-only from CMS perspective (content managed in Content Catalog)
"""

from datetime import datetime, timezone
import json
import uuid

from cms.models import db


class SyncedContent(db.Model):
    """
    SQLAlchemy model representing content synced from Content Catalog.

    Synced content items are cached copies of approved/published content
    from the Content Catalog service. The CMS fetches and stores metadata
    locally to enable display and filtering without requiring the Content
    Catalog to be available for every page load.

    Status Values (from Content Catalog):
        - 'approved': Content approved but not yet published
        - 'published': Content published and available in catalog
        - 'archived': Content archived (should be removed from sync)

    Attributes:
        id: Unique UUID identifier (internal CMS ID)
        source_uuid: UUID from Content Catalog (for deduplication)
        title: Human-readable title for the content
        description: Optional description of the content
        filename: Original filename of the content
        file_path: Path to content file in Content Catalog storage
        file_size: File size in bytes
        duration: Duration in seconds (for video/audio content)
        resolution: Video/image resolution (e.g., "1920x1080")
        format: File format/codec (e.g., "mp4", "jpeg")
        thumbnail_url: URL or path to thumbnail image
        category: Content category for filtering
        tags: Comma-separated tags for categorization
        status: Current approval status from Content Catalog
        organization_id: Source organization ID from Content Catalog
        organization_name: Cached organization name for display
        network_ids: JSON string of network IDs for distribution filtering
        content_catalog_url: Base URL of Content Catalog for file access
        synced_at: Timestamp of last sync from Content Catalog
        created_at: Original creation timestamp from Content Catalog
        published_at: When content was published in Content Catalog
    """

    __tablename__ = 'synced_content'

    # Status constants (subset from Content Catalog - only synced statuses)
    STATUS_APPROVED = 'approved'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED = 'archived'

    VALID_STATUSES = [
        STATUS_APPROVED,
        STATUS_PUBLISHED,
        STATUS_ARCHIVED
    ]

    # Primary key (CMS internal)
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Source tracking from Content Catalog
    source_uuid = db.Column(db.String(36), unique=True, nullable=False, index=True)
    source_id = db.Column(db.Integer, nullable=True)  # Integer ID from Content Catalog for download URL

    # Content metadata
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # File information
    filename = db.Column(db.String(500), nullable=False)
    local_filename = db.Column(db.String(500), nullable=True)  # Local CMS copy filename
    file_path = db.Column(db.String(1000), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    duration = db.Column(db.Float, nullable=True)
    resolution = db.Column(db.String(50), nullable=True)
    format = db.Column(db.String(50), nullable=True)
    thumbnail_url = db.Column(db.String(1000), nullable=True)

    # Categorization
    category = db.Column(db.String(100), nullable=True)
    tags = db.Column(db.Text, nullable=True)

    # Workflow status (from Content Catalog)
    status = db.Column(db.String(50), default=STATUS_APPROVED, nullable=False, index=True)

    # Source organization
    organization_id = db.Column(db.Integer, nullable=True, index=True)
    organization_name = db.Column(db.String(255), nullable=True)

    # Network filtering (JSON string of network IDs)
    network_ids = db.Column(db.Text, nullable=True)

    # Content Catalog reference
    content_catalog_url = db.Column(db.String(500), nullable=True)

    # Timestamps
    synced_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = db.Column(db.DateTime, nullable=True)
    published_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        """
        Serialize the synced content to a dictionary for API responses.

        Returns:
            Dictionary containing all synced content fields
        """
        return {
            'id': self.id,
            'source_uuid': self.source_uuid,
            'title': self.title,
            'description': self.description,
            'filename': self.filename,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'duration': self.duration,
            'resolution': self.resolution,
            'format': self.format,
            'thumbnail_url': self.thumbnail_url,
            'category': self.category,
            'tags': self.tags,
            'status': self.status,
            'organization_id': self.organization_id,
            'organization_name': self.organization_name,
            'network_ids': self.get_network_ids_list(),
            'content_catalog_url': self.content_catalog_url,
            'synced_at': self.synced_at.isoformat() if self.synced_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'published_at': self.published_at.isoformat() if self.published_at else None
        }

    def to_content_card(self):
        """
        Return data for content card display in CMS UI.

        This is a simplified representation suitable for grid/list views.

        Returns:
            Dictionary with essential content metadata for display
        """
        return {
            'id': self.id,
            'source_uuid': self.source_uuid,
            'title': self.title,
            'filename': self.filename,
            'duration': self.duration,
            'format': self.format,
            'thumbnail_url': self.thumbnail_url,
            'status': self.status,
            'organization_name': self.organization_name,
            'content_type': self.content_type
        }

    @property
    def content_type(self):
        """
        Determine the content type based on format.

        Returns:
            str: 'video', 'image', 'audio', or 'other'
        """
        if self.is_video:
            return 'video'
        elif self.is_image:
            return 'image'
        elif self.is_audio:
            return 'audio'
        return 'other'

    @property
    def is_video(self):
        """
        Check if content is a video file.

        Returns:
            bool: True if format indicates video content
        """
        video_formats = ['mp4', 'webm', 'avi', 'mov', 'mkv', 'wmv', 'flv']
        return self.format.lower() in video_formats if self.format else False

    @property
    def is_image(self):
        """
        Check if content is an image file.

        Returns:
            bool: True if format indicates image content
        """
        image_formats = ['jpeg', 'jpg', 'png', 'gif', 'webp', 'svg', 'bmp']
        return self.format.lower() in image_formats if self.format else False

    @property
    def is_audio(self):
        """
        Check if content is an audio file.

        Returns:
            bool: True if format indicates audio content
        """
        audio_formats = ['mp3', 'wav', 'ogg', 'aac', 'flac', 'm4a']
        return self.format.lower() in audio_formats if self.format else False

    @property
    def is_published(self):
        """Check if content is published."""
        return self.status == self.STATUS_PUBLISHED

    @property
    def is_approved(self):
        """Check if content is approved."""
        return self.status == self.STATUS_APPROVED

    def get_network_ids_list(self):
        """
        Get network IDs as a Python list.

        Returns:
            list: List of network ID strings, empty list if none
        """
        if not self.network_ids:
            return []
        try:
            return json.loads(self.network_ids)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_network_ids_list(self, network_ids_list):
        """
        Set network IDs from a Python list.

        Args:
            network_ids_list: List of network ID strings
        """
        if network_ids_list:
            self.network_ids = json.dumps(network_ids_list)
        else:
            self.network_ids = None

    def has_network(self, network_id):
        """
        Check if content is assigned to a specific network.

        Args:
            network_id: The network ID to check

        Returns:
            bool: True if content is assigned to the network
        """
        return network_id in self.get_network_ids_list()

    @classmethod
    def get_by_source_uuid(cls, source_uuid):
        """
        Get synced content by its Content Catalog UUID.

        Args:
            source_uuid: The UUID from Content Catalog

        Returns:
            SyncedContent instance or None
        """
        return cls.query.filter_by(source_uuid=source_uuid).first()

    @classmethod
    def get_by_network(cls, network_id):
        """
        Get all synced content for a specific network.

        Args:
            network_id: The network ID to filter by

        Returns:
            list: List of SyncedContent instances for the network
        """
        # Since network_ids is JSON, use LIKE for filtering
        return cls.query.filter(
            cls.network_ids.like(f'%{network_id}%')
        ).order_by(cls.synced_at.desc()).all()

    @classmethod
    def get_by_organization(cls, organization_id):
        """
        Get all synced content for a specific organization.

        Args:
            organization_id: The organization ID to filter by

        Returns:
            list: List of SyncedContent instances for the organization
        """
        return cls.query.filter_by(
            organization_id=organization_id
        ).order_by(cls.synced_at.desc()).all()

    @classmethod
    def get_by_status(cls, status):
        """
        Get all synced content with a specific status.

        Args:
            status: The status to filter by

        Returns:
            list: List of SyncedContent instances with the status
        """
        return cls.query.filter_by(
            status=status
        ).order_by(cls.synced_at.desc()).all()

    @classmethod
    def get_all_organizations(cls):
        """
        Get distinct organization names from synced content.

        Returns:
            list: List of unique organization names
        """
        results = cls.query.with_entities(
            cls.organization_id,
            cls.organization_name
        ).distinct().filter(
            cls.organization_name.isnot(None)
        ).all()
        return [{'id': r.organization_id, 'name': r.organization_name} for r in results]

    @classmethod
    def upsert_from_catalog(cls, db_session, catalog_data, organization_name=None, content_catalog_url=None):
        """
        Insert or update synced content from Content Catalog API response.

        Args:
            db_session: SQLAlchemy database session
            catalog_data: Dictionary from Content Catalog API (ContentAsset.to_dict())
            organization_name: Cached organization name for display
            content_catalog_url: Base URL of Content Catalog

        Returns:
            SyncedContent: The created or updated instance
        """
        source_uuid = catalog_data.get('uuid')
        if not source_uuid:
            raise ValueError("source_uuid (uuid) is required in catalog_data")

        # Try to find existing synced content
        synced = cls.query.filter_by(source_uuid=source_uuid).first()

        if synced is None:
            synced = cls(
                source_uuid=source_uuid
            )
            db_session.add(synced)

        # Update fields from catalog data
        synced.title = catalog_data.get('title', 'Untitled')
        synced.source_id = catalog_data.get('id')
        synced.description = catalog_data.get('description')
        synced.filename = catalog_data.get('filename', 'unknown')
        synced.file_path = catalog_data.get('file_path')
        synced.file_size = catalog_data.get('file_size')
        synced.duration = catalog_data.get('duration')
        synced.resolution = catalog_data.get('resolution')
        synced.format = catalog_data.get('format')
        synced.thumbnail_url = catalog_data.get('thumbnail_path')
        synced.category = catalog_data.get('category')
        synced.tags = catalog_data.get('tags')
        synced.status = catalog_data.get('status', cls.STATUS_APPROVED)
        synced.organization_id = catalog_data.get('organization_id')
        synced.organization_name = organization_name
        synced.network_ids = catalog_data.get('networks')
        synced.content_catalog_url = content_catalog_url
        synced.synced_at = datetime.now(timezone.utc)

        # Parse timestamps from ISO format strings
        created_at = catalog_data.get('created_at')
        if created_at and isinstance(created_at, str):
            try:
                synced.created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except ValueError:
                synced.created_at = None

        published_at = catalog_data.get('published_at')
        if published_at and isinstance(published_at, str):
            try:
                synced.published_at = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            except ValueError:
                synced.published_at = None

        return synced

    def __repr__(self):
        """String representation for debugging."""
        return f'<SyncedContent {self.title}>'
