"""
Content Asset Model for Content Catalog Service.

Represents uploaded media content with file metadata, organization ownership,
and approval workflow status for the content catalog system.
"""

from datetime import datetime, timezone
import uuid

from content_catalog.models import db


class ContentAsset(db.Model):
    """
    SQLAlchemy model representing an uploaded content asset.

    Content assets are media files (images, videos, audio) managed through the
    Content Catalog system. Each asset goes through an approval workflow:
    DRAFT → PENDING_REVIEW → APPROVED → PUBLISHED

    Status Values:
        - 'draft': Initial state, not yet submitted for review
        - 'pending_review': Submitted for review, awaiting approval
        - 'approved': Approved but not yet published
        - 'rejected': Rejected during review process
        - 'published': Published and available in catalog
        - 'archived': No longer active but retained for records

    Attributes:
        id: Unique integer identifier (internal)
        uuid: Unique UUID for external API references
        title: Human-readable title for the asset
        description: Optional description of the content
        filename: Stored filename (may be sanitized from original)
        file_path: Server path to the stored file
        file_size: File size in bytes
        duration: Duration in seconds (for video/audio)
        resolution: Video/image resolution (e.g., "1920x1080")
        format: File format/codec (e.g., "mp4", "jpeg")
        thumbnail_path: Path to generated thumbnail image
        checksum: File checksum for integrity verification
        organization_id: Foreign key to owning organization
        uploaded_by: Foreign key to user who uploaded
        status: Current workflow status
        reviewed_by: Foreign key to user who reviewed
        reviewed_at: Timestamp of review
        review_notes: Feedback from reviewer
        published_at: Timestamp when published
        tags: Comma-separated tags for categorization
        category: Content category
        networks: JSON string of network IDs for distribution
        zoho_campaign_id: External reference to ZOHO CRM campaign
        created_at: Timestamp when asset was created
        updated_at: Timestamp of last update
    """

    __tablename__ = 'content_assets'

    # Status constants for workflow (extended for Thea spec)
    STATUS_DRAFT = 'draft'
    STATUS_PENDING_REVIEW = 'pending_review'  # Legacy alias for SUBMITTED
    STATUS_SUBMITTED = 'submitted'  # Thea spec
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED = 'archived'
    STATUS_PROMOTED = 'promoted'  # Thea spec: promoted to CMS
    STATUS_REVOKED = 'revoked'  # Thea spec: access revoked
    STATUS_EXPIRED = 'expired'  # Thea spec: past expiration date

    VALID_STATUSES = [
        STATUS_DRAFT,
        STATUS_PENDING_REVIEW,
        STATUS_SUBMITTED,
        STATUS_APPROVED,
        STATUS_REJECTED,
        STATUS_PUBLISHED,
        STATUS_ARCHIVED,
        STATUS_PROMOTED,
        STATUS_REVOKED,
        STATUS_EXPIRED
    ]

    # Owner organization types (Thea spec)
    ORG_TYPE_SKILLZ = 'SKILLZ'
    ORG_TYPE_RETAILER = 'RETAILER'
    ORG_TYPE_BRAND = 'BRAND'
    ORG_TYPE_AGENCY = 'AGENCY'

    VALID_ORG_TYPES = [ORG_TYPE_SKILLZ, ORG_TYPE_RETAILER, ORG_TYPE_BRAND, ORG_TYPE_AGENCY]

    # Asset types
    ASSET_TYPE_VIDEO = 'video'
    ASSET_TYPE_IMAGE = 'image'
    ASSET_TYPE_PDF = 'pdf'

    VALID_ASSET_TYPES = [ASSET_TYPE_VIDEO, ASSET_TYPE_IMAGE, ASSET_TYPE_PDF]

    # Primary key (internal use)
    id = db.Column(db.Integer, primary_key=True)

    # UUID for external API references
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)

    # Content metadata
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # File information
    filename = db.Column(db.String(500), nullable=False)
    file_path = db.Column(db.String(1000), nullable=False)
    file_size = db.Column(db.Integer, nullable=True)
    duration = db.Column(db.Float, nullable=True)  # Legacy - use duration_ms
    resolution = db.Column(db.String(50), nullable=True)
    format = db.Column(db.String(50), nullable=True)
    thumbnail_path = db.Column(db.String(1000), nullable=True)
    checksum = db.Column(db.String(255), nullable=True)  # Legacy - use file_hash

    # Enhanced file metadata (Thea spec)
    file_hash = db.Column(db.String(64), nullable=True, index=True)  # SHA256
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    aspect_ratio = db.Column(db.String(20), nullable=True)  # e.g., "16:9"
    duration_ms = db.Column(db.Integer, nullable=True)  # milliseconds
    recommended_display_duration = db.Column(db.Integer, nullable=True)  # seconds
    container = db.Column(db.String(50), nullable=True)  # e.g., "mp4", "webm"
    codec = db.Column(db.String(50), nullable=True)  # e.g., "h264", "vp9"
    fps = db.Column(db.Float, nullable=True)  # frames per second
    pages = db.Column(db.Integer, nullable=True)  # PDF page count
    preview_url = db.Column(db.String(1000), nullable=True)

    # Content type
    asset_type = db.Column(db.String(20), nullable=True)  # video / image / pdf

    # Multi-tenant support (Thea spec)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    catalog_id = db.Column(db.String(36), db.ForeignKey('catalogs.id'), nullable=True, index=True)
    category_id = db.Column(db.String(36), db.ForeignKey('categories.id'), nullable=True, index=True)

    # Organization ownership
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True, index=True)
    owner_org_type = db.Column(db.String(20), nullable=True)  # SKILLZ / RETAILER / BRAND / AGENCY

    # Versioning
    version = db.Column(db.Integer, default=1, nullable=False)
    previous_version_id = db.Column(db.Integer, db.ForeignKey('content_assets.id'), nullable=True)

    # Expiration
    expires_at = db.Column(db.DateTime, nullable=True)

    # Upload tracking
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    # Workflow status
    status = db.Column(db.String(50), default=STATUS_DRAFT, nullable=False, index=True)

    # Review fields
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)

    # Approval (Thea spec)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    # Publishing
    published_at = db.Column(db.DateTime, nullable=True)

    # Categorization
    tags = db.Column(db.Text, nullable=True)  # Comma-separated tags
    category = db.Column(db.String(100), nullable=True)
    networks = db.Column(db.Text, nullable=True)  # JSON string of network IDs

    # External integration
    zoho_campaign_id = db.Column(db.String(100), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    organization = db.relationship(
        'Organization',
        foreign_keys=[organization_id],
        backref=db.backref('content_assets', lazy='dynamic')
    )
    uploader = db.relationship(
        'User',
        foreign_keys=[uploaded_by],
        backref=db.backref('uploaded_assets', lazy='dynamic')
    )
    reviewer = db.relationship(
        'User',
        foreign_keys=[reviewed_by],
        backref=db.backref('reviewed_assets', lazy='dynamic')
    )
    approver = db.relationship(
        'User',
        foreign_keys=[approved_by_user_id],
        backref=db.backref('approved_assets', lazy='dynamic')
    )

    # Multi-tenant relationships
    tenant = db.relationship('Tenant', backref=db.backref('assets', lazy='dynamic'))
    catalog = db.relationship('Catalog', backref=db.backref('assets', lazy='dynamic'))
    asset_category = db.relationship('Category', backref=db.backref('assets', lazy='dynamic'))

    # Version chain
    previous_version = db.relationship(
        'ContentAsset',
        remote_side=[id],
        backref=db.backref('next_versions', lazy='dynamic')
    )

    def to_dict(self):
        """
        Serialize the content asset to a dictionary for API responses.

        Returns:
            Dictionary containing all content asset fields
        """
        return {
            'id': self.id,
            'uuid': self.uuid,
            'title': self.title,
            'description': self.description,
            'filename': self.filename,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'duration': self.duration,
            'resolution': self.resolution,
            'format': self.format,
            'thumbnail_path': self.thumbnail_path,
            'checksum': self.checksum,
            'organization_id': self.organization_id,
            'uploaded_by': self.uploaded_by,
            'status': self.status,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_notes': self.review_notes,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'tags': self.tags,
            'category': self.category,
            'networks': self.networks,
            'zoho_campaign_id': self.zoho_campaign_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def to_catalog_item(self):
        """
        Return data for public catalog API responses.

        This is the data returned in public catalog endpoints
        for content distribution. Excludes internal fields.

        Returns:
            Dictionary with essential content metadata for catalog
        """
        return {
            'uuid': self.uuid,
            'title': self.title,
            'description': self.description,
            'filename': self.filename,
            'file_size': self.file_size,
            'duration': self.duration,
            'resolution': self.resolution,
            'format': self.format,
            'thumbnail_path': self.thumbnail_path,
            'tags': self.tags,
            'category': self.category,
            'published_at': self.published_at.isoformat() if self.published_at else None
        }

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
    def is_draft(self):
        """Check if asset is in draft status."""
        return self.status == self.STATUS_DRAFT

    @property
    def is_pending_review(self):
        """Check if asset is pending review."""
        return self.status == self.STATUS_PENDING_REVIEW

    @property
    def is_approved(self):
        """Check if asset has been approved."""
        return self.status == self.STATUS_APPROVED

    @property
    def is_published(self):
        """Check if asset is published."""
        return self.status == self.STATUS_PUBLISHED

    @property
    def is_rejected(self):
        """Check if asset was rejected."""
        return self.status == self.STATUS_REJECTED

    def can_submit_for_review(self):
        """
        Check if asset can be submitted for review.

        Only draft or rejected assets can be submitted.

        Returns:
            bool: True if asset can be submitted for review
        """
        return self.status in [self.STATUS_DRAFT, self.STATUS_REJECTED]

    def can_approve(self):
        """
        Check if asset can be approved.

        Only pending review assets can be approved.

        Returns:
            bool: True if asset can be approved
        """
        return self.status == self.STATUS_PENDING_REVIEW

    def can_publish(self):
        """
        Check if asset can be published.

        Only approved assets can be published.

        Returns:
            bool: True if asset can be published
        """
        return self.status == self.STATUS_APPROVED

    @classmethod
    def get_by_uuid(cls, asset_uuid):
        """
        Get an asset by its UUID.

        Args:
            asset_uuid: The UUID to search for

        Returns:
            ContentAsset instance or None
        """
        return cls.query.filter_by(uuid=asset_uuid).first()

    @classmethod
    def get_by_organization(cls, organization_id, status=None):
        """
        Get all assets for a specific organization.

        Args:
            organization_id: The organization ID to filter by
            status: Optional status filter

        Returns:
            list: List of ContentAsset instances for the organization
        """
        query = cls.query.filter_by(organization_id=organization_id)
        if status:
            query = query.filter_by(status=status)
        return query.order_by(cls.created_at.desc()).all()

    @classmethod
    def get_pending_review(cls, organization_id=None):
        """
        Get all assets pending review.

        Args:
            organization_id: Optional organization ID to filter by

        Returns:
            list: List of ContentAsset instances pending review
        """
        query = cls.query.filter_by(status=cls.STATUS_PENDING_REVIEW)
        if organization_id:
            query = query.filter_by(organization_id=organization_id)
        return query.order_by(cls.created_at.asc()).all()

    @classmethod
    def get_published(cls, organization_id=None):
        """
        Get all published assets.

        Args:
            organization_id: Optional organization ID to filter by

        Returns:
            list: List of published ContentAsset instances
        """
        query = cls.query.filter_by(status=cls.STATUS_PUBLISHED)
        if organization_id:
            query = query.filter_by(organization_id=organization_id)
        return query.order_by(cls.published_at.desc()).all()

    def __repr__(self):
        """String representation for debugging."""
        return f'<ContentAsset {self.title}>'


class ContentApprovalRequest(db.Model):
    """
    SQLAlchemy model representing a content approval request.

    Tracks the approval workflow for content assets. Requests are created
    when content is submitted for review and are assigned to approvers who
    can approve or reject based on their role hierarchy.

    Status Values:
        - 'pending': Awaiting review
        - 'approved': Content approved
        - 'rejected': Content rejected

    Attributes:
        id: Unique integer identifier
        asset_id: Foreign key to the content asset being approved
        requested_by: User ID who initiated the request (typically the uploader)
        assigned_to: User ID of the approver assigned to review
        status: Current request status
        notes: Notes or feedback about the request
        created_at: Timestamp when request was created
        resolved_at: Timestamp when request was resolved (approved/rejected)
    """

    __tablename__ = 'content_approval_requests'

    # Valid status values
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    VALID_STATUSES = [
        STATUS_PENDING,
        STATUS_APPROVED,
        STATUS_REJECTED
    ]

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Content asset being approved
    asset_id = db.Column(
        db.Integer,
        db.ForeignKey('content_assets.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )

    # Request source and assignment
    requested_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    assigned_to = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )

    # Status and notes
    status = db.Column(db.String(50), default=STATUS_PENDING, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    asset = db.relationship(
        'ContentAsset',
        foreign_keys=[asset_id],
        backref=db.backref('approval_requests', lazy='dynamic', cascade='all, delete-orphan')
    )
    requester = db.relationship(
        'User',
        foreign_keys=[requested_by],
        backref=db.backref('initiated_content_approval_requests', lazy='dynamic')
    )
    assignee = db.relationship(
        'User',
        foreign_keys=[assigned_to],
        backref=db.backref('assigned_content_approval_requests', lazy='dynamic')
    )

    def to_dict(self):
        """
        Serialize the approval request to a dictionary for API responses.

        Returns:
            Dictionary containing approval request fields
        """
        return {
            'id': self.id,
            'asset_id': self.asset_id,
            'requested_by': self.requested_by,
            'assigned_to': self.assigned_to,
            'status': self.status,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None
        }

    def to_dict_with_relations(self):
        """
        Serialize the approval request with related asset and user info.

        Returns:
            Dictionary containing approval request fields with nested data
        """
        result = self.to_dict()
        result['asset'] = self.asset.to_dict() if self.asset else None
        result['requester'] = self.requester.to_dict() if self.requester else None
        result['assignee'] = self.assignee.to_dict() if self.assignee else None
        return result

    def is_pending(self):
        """
        Check if the request is still pending.

        Returns:
            True if request is pending, False otherwise
        """
        return self.status == self.STATUS_PENDING

    @classmethod
    def get_pending_for_asset(cls, asset_id):
        """
        Get all pending approval requests for a specific asset.

        Args:
            asset_id: The asset ID to filter by

        Returns:
            list: List of pending ContentApprovalRequest instances
        """
        return cls.query.filter_by(
            asset_id=asset_id,
            status=cls.STATUS_PENDING
        ).all()

    @classmethod
    def get_pending_for_assignee(cls, assignee_id):
        """
        Get all pending approval requests assigned to a specific user.

        Args:
            assignee_id: The assignee user ID to filter by

        Returns:
            list: List of pending ContentApprovalRequest instances ordered by creation date
        """
        return cls.query.filter_by(
            assigned_to=assignee_id,
            status=cls.STATUS_PENDING
        ).order_by(cls.created_at.asc()).all()

    def __repr__(self):
        """String representation for debugging."""
        return f'<ContentApprovalRequest asset={self.asset_id} status={self.status}>'
