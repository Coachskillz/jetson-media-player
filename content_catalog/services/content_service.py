"""
Content Service for Content Catalog.

Provides content asset management functionality including CRUD operations,
workflow status management, and listing with filtering capabilities.

Key features:
- Asset upload with file metadata and organization ownership
- Asset retrieval by ID, UUID, or various criteria
- Asset updates with validation
- Asset deletion with proper cleanup
- Asset listing with filtering, pagination, and sorting
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid as uuid_module


class ContentService:
    """
    Content asset management service for the Content Catalog.

    This service handles:
    1. Creating (uploading) assets with file metadata
    2. Retrieving assets by various criteria
    3. Updating asset information and metadata
    4. Deleting assets
    5. Listing assets with filtering and pagination

    Usage:
        # Upload a new asset
        asset = ContentService.upload_asset(
            db_session=db.session,
            title='Promo Video',
            filename='promo.mp4',
            file_path='/uploads/promo.mp4',
            uploaded_by=user.id,
            organization_id=org.id,
            file_size=1024000,
            format='mp4'
        )

        # Get asset by ID
        asset = ContentService.get_asset(db.session, asset_id=1)

        # Update asset
        asset = ContentService.update_asset(
            db.session,
            asset_id=1,
            title='Updated Title',
            description='New description'
        )

        # Delete asset
        success = ContentService.delete_asset(db.session, asset_id=1)

        # List assets with filters
        assets, total = ContentService.list_assets(
            db.session,
            organization_id=1,
            status='published',
            page=1,
            per_page=20
        )
    """

    # Default pagination settings
    DEFAULT_PAGE = 1
    DEFAULT_PER_PAGE = 20
    MAX_PER_PAGE = 100

    @classmethod
    def upload_asset(
        cls,
        db_session,
        title: str,
        filename: str,
        file_path: str,
        uploaded_by: Optional[int] = None,
        organization_id: Optional[int] = None,
        description: Optional[str] = None,
        file_size: Optional[int] = None,
        duration: Optional[float] = None,
        resolution: Optional[str] = None,
        format: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
        checksum: Optional[str] = None,
        tags: Optional[str] = None,
        category: Optional[str] = None,
        networks: Optional[str] = None,
        zoho_campaign_id: Optional[str] = None
    ):
        """
        Upload (create) a new content asset.

        Creates a content asset record with the provided metadata.
        The asset starts in 'draft' status by default.

        Args:
            db_session: SQLAlchemy database session
            title: Human-readable title for the asset
            filename: Stored filename (may be sanitized from original)
            file_path: Server path to the stored file
            uploaded_by: User ID of the uploader
            organization_id: Organization ID that owns the asset
            description: Optional description of the content
            file_size: File size in bytes
            duration: Duration in seconds (for video/audio)
            resolution: Video/image resolution (e.g., "1920x1080")
            format: File format/codec (e.g., "mp4", "jpeg")
            thumbnail_path: Path to generated thumbnail image
            checksum: File checksum for integrity verification
            tags: Comma-separated tags for categorization
            category: Content category
            networks: JSON string of network IDs for distribution
            zoho_campaign_id: External reference to ZOHO CRM campaign

        Returns:
            ContentAsset: The created asset instance

        Raises:
            ValueError: If required fields are missing or invalid

        Note:
            The asset is added to the database session but not committed.
            The caller is responsible for committing the transaction.
        """
        from content_catalog.models.content import ContentAsset

        # Validate required fields
        if not title or not title.strip():
            raise ValueError("Title is required and cannot be empty")

        if not filename or not filename.strip():
            raise ValueError("Filename is required and cannot be empty")

        if not file_path or not file_path.strip():
            raise ValueError("File path is required and cannot be empty")

        # Create the asset with a new UUID
        asset = ContentAsset(
            uuid=str(uuid_module.uuid4()),
            title=title.strip(),
            filename=filename.strip(),
            file_path=file_path.strip(),
            uploaded_by=uploaded_by,
            organization_id=organization_id,
            description=description.strip() if description else None,
            file_size=file_size,
            duration=duration,
            resolution=resolution,
            format=format,
            thumbnail_path=thumbnail_path,
            checksum=checksum,
            tags=tags,
            category=category,
            networks=networks,
            zoho_campaign_id=zoho_campaign_id,
            status=ContentAsset.STATUS_DRAFT,
            created_at=datetime.now(timezone.utc)
        )

        db_session.add(asset)
        return asset

    @classmethod
    def get_asset(cls, db_session, asset_id: int) -> Optional['ContentAsset']:
        """
        Get a content asset by its ID.

        Args:
            db_session: SQLAlchemy database session
            asset_id: The asset's unique integer identifier

        Returns:
            ContentAsset: The asset instance if found, None otherwise
        """
        from content_catalog.models.content import ContentAsset

        return db_session.query(ContentAsset).filter_by(id=asset_id).first()

    @classmethod
    def get_asset_by_uuid(cls, db_session, asset_uuid: str) -> Optional['ContentAsset']:
        """
        Get a content asset by its UUID.

        UUIDs are used for external API references to avoid exposing
        internal database IDs.

        Args:
            db_session: SQLAlchemy database session
            asset_uuid: The asset's UUID string

        Returns:
            ContentAsset: The asset instance if found, None otherwise
        """
        from content_catalog.models.content import ContentAsset

        return db_session.query(ContentAsset).filter_by(uuid=asset_uuid).first()

    @classmethod
    def update_asset(
        cls,
        db_session,
        asset_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        filename: Optional[str] = None,
        file_path: Optional[str] = None,
        file_size: Optional[int] = None,
        duration: Optional[float] = None,
        resolution: Optional[str] = None,
        format: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
        checksum: Optional[str] = None,
        tags: Optional[str] = None,
        category: Optional[str] = None,
        networks: Optional[str] = None,
        zoho_campaign_id: Optional[str] = None
    ) -> Optional['ContentAsset']:
        """
        Update a content asset's information.

        Only provided fields will be updated. None values for optional
        parameters mean "don't update this field".

        Args:
            db_session: SQLAlchemy database session
            asset_id: The asset's unique identifier
            title: New title (optional)
            description: New description (optional)
            filename: New filename (optional)
            file_path: New file path (optional)
            file_size: New file size in bytes (optional)
            duration: New duration in seconds (optional)
            resolution: New resolution string (optional)
            format: New format/codec (optional)
            thumbnail_path: New thumbnail path (optional)
            checksum: New checksum (optional)
            tags: New comma-separated tags (optional)
            category: New category (optional)
            networks: New networks JSON string (optional)
            zoho_campaign_id: New ZOHO campaign ID (optional)

        Returns:
            ContentAsset: The updated asset instance, or None if not found

        Raises:
            ValueError: If provided values are invalid

        Note:
            Changes are made to the asset but not committed.
            The caller is responsible for committing the transaction.
        """
        from content_catalog.models.content import ContentAsset

        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return None

        # Update title if provided
        if title is not None:
            if not title.strip():
                raise ValueError("Title cannot be empty")
            asset.title = title.strip()

        # Update description if provided
        if description is not None:
            asset.description = description.strip() if description else None

        # Update filename if provided
        if filename is not None:
            if not filename.strip():
                raise ValueError("Filename cannot be empty")
            asset.filename = filename.strip()

        # Update file_path if provided
        if file_path is not None:
            if not file_path.strip():
                raise ValueError("File path cannot be empty")
            asset.file_path = file_path.strip()

        # Update file metadata if provided
        if file_size is not None:
            asset.file_size = file_size

        if duration is not None:
            asset.duration = duration

        if resolution is not None:
            asset.resolution = resolution

        if format is not None:
            asset.format = format

        if thumbnail_path is not None:
            asset.thumbnail_path = thumbnail_path

        if checksum is not None:
            asset.checksum = checksum

        # Update categorization if provided
        if tags is not None:
            asset.tags = tags

        if category is not None:
            asset.category = category

        if networks is not None:
            asset.networks = networks

        # Update external reference if provided
        if zoho_campaign_id is not None:
            asset.zoho_campaign_id = zoho_campaign_id

        # Update the updated_at timestamp
        asset.updated_at = datetime.now(timezone.utc)

        return asset

    @classmethod
    def delete_asset(cls, db_session, asset_id: int) -> bool:
        """
        Delete a content asset.

        Permanently removes the asset record from the database.
        Does not delete the actual file from storage - the caller
        should handle file cleanup separately.

        Args:
            db_session: SQLAlchemy database session
            asset_id: The asset's unique identifier

        Returns:
            bool: True if asset was deleted, False if not found

        Note:
            The deletion is performed but not committed.
            The caller is responsible for committing the transaction.
        """
        from content_catalog.models.content import ContentAsset

        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return False

        db_session.delete(asset)
        return True

    @classmethod
    def list_assets(
        cls,
        db_session,
        organization_id: Optional[int] = None,
        status: Optional[str] = None,
        uploaded_by: Optional[int] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        page: int = DEFAULT_PAGE,
        per_page: int = DEFAULT_PER_PAGE,
        sort_by: str = 'created_at',
        sort_order: str = 'desc'
    ) -> Tuple[List['ContentAsset'], int]:
        """
        List content assets with optional filtering, pagination, and sorting.

        Args:
            db_session: SQLAlchemy database session
            organization_id: Filter by organization (optional)
            status: Filter by status (optional)
            uploaded_by: Filter by uploader user ID (optional)
            category: Filter by category (optional)
            search: Search term for title or description (optional)
            page: Page number (1-indexed, default 1)
            per_page: Results per page (default 20, max 100)
            sort_by: Field to sort by (default 'created_at')
            sort_order: Sort order 'asc' or 'desc' (default 'desc')

        Returns:
            Tuple of (list of ContentAsset instances, total count)

        Example:
            assets, total = ContentService.list_assets(
                db.session,
                organization_id=1,
                status='published',
                page=2,
                per_page=10
            )
        """
        from content_catalog.models.content import ContentAsset

        # Build the base query
        query = db_session.query(ContentAsset)

        # Apply filters
        if organization_id is not None:
            query = query.filter(ContentAsset.organization_id == organization_id)

        if status is not None:
            query = query.filter(ContentAsset.status == status)

        if uploaded_by is not None:
            query = query.filter(ContentAsset.uploaded_by == uploaded_by)

        if category is not None:
            query = query.filter(ContentAsset.category == category)

        if search is not None:
            search_pattern = f'%{search}%'
            query = query.filter(
                (ContentAsset.title.ilike(search_pattern)) |
                (ContentAsset.description.ilike(search_pattern))
            )

        # Get total count before pagination
        total = query.count()

        # Apply sorting
        sort_column = getattr(ContentAsset, sort_by, ContentAsset.created_at)
        if sort_order.lower() == 'asc':
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

        # Apply pagination
        per_page = min(per_page, cls.MAX_PER_PAGE)
        offset = (page - 1) * per_page
        assets = query.offset(offset).limit(per_page).all()

        return assets, total

    @classmethod
    def get_assets_by_organization(
        cls,
        db_session,
        organization_id: int,
        status: Optional[str] = None
    ) -> List['ContentAsset']:
        """
        Get all assets for a specific organization.

        Args:
            db_session: SQLAlchemy database session
            organization_id: The organization ID to filter by
            status: Optional status filter

        Returns:
            list: List of ContentAsset instances for the organization
        """
        from content_catalog.models.content import ContentAsset

        query = db_session.query(ContentAsset).filter_by(
            organization_id=organization_id
        )
        if status is not None:
            query = query.filter_by(status=status)

        return query.order_by(ContentAsset.created_at.desc()).all()

    @classmethod
    def get_assets_by_status(cls, db_session, status: str) -> List['ContentAsset']:
        """
        Get all assets with a specific status.

        Args:
            db_session: SQLAlchemy database session
            status: The status to filter by

        Returns:
            list: List of ContentAsset instances with the specified status
        """
        from content_catalog.models.content import ContentAsset

        return db_session.query(ContentAsset).filter_by(
            status=status
        ).order_by(ContentAsset.created_at.desc()).all()

    @classmethod
    def get_pending_review_assets(
        cls,
        db_session,
        organization_id: Optional[int] = None
    ) -> List['ContentAsset']:
        """
        Get all assets pending review.

        Args:
            db_session: SQLAlchemy database session
            organization_id: Optional organization ID to filter by

        Returns:
            list: List of ContentAsset instances pending review
        """
        from content_catalog.models.content import ContentAsset

        query = db_session.query(ContentAsset).filter_by(
            status=ContentAsset.STATUS_PENDING_REVIEW
        )
        if organization_id is not None:
            query = query.filter_by(organization_id=organization_id)

        return query.order_by(ContentAsset.created_at.asc()).all()

    @classmethod
    def get_published_assets(
        cls,
        db_session,
        organization_id: Optional[int] = None
    ) -> List['ContentAsset']:
        """
        Get all published assets.

        Args:
            db_session: SQLAlchemy database session
            organization_id: Optional organization ID to filter by

        Returns:
            list: List of published ContentAsset instances
        """
        from content_catalog.models.content import ContentAsset

        query = db_session.query(ContentAsset).filter_by(
            status=ContentAsset.STATUS_PUBLISHED
        )
        if organization_id is not None:
            query = query.filter_by(organization_id=organization_id)

        return query.order_by(ContentAsset.published_at.desc()).all()

    @classmethod
    def submit_for_review(
        cls,
        db_session,
        asset_id: int,
        submitted_by: Optional[int] = None
    ) -> Optional['ContentAsset']:
        """
        Submit an asset for review.

        Changes the asset's status from 'draft' or 'rejected' to 'pending_review'.

        Args:
            db_session: SQLAlchemy database session
            asset_id: The asset ID to submit
            submitted_by: The user ID submitting for review (optional)

        Returns:
            ContentAsset: The updated asset instance, or None if not found

        Raises:
            ValueError: If asset is not in a submittable state
        """
        from content_catalog.models.content import ContentAsset

        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return None

        if not asset.can_submit_for_review():
            raise ValueError(
                f"Asset cannot be submitted for review in its current status: {asset.status}"
            )

        asset.status = ContentAsset.STATUS_PENDING_REVIEW
        asset.updated_at = datetime.now(timezone.utc)

        return asset

    @classmethod
    def approve_asset(
        cls,
        db_session,
        asset_id: int,
        approved_by: int,
        notes: Optional[str] = None
    ) -> Optional['ContentAsset']:
        """
        Approve an asset that is pending review.

        Args:
            db_session: SQLAlchemy database session
            asset_id: The asset ID to approve
            approved_by: The user ID approving the asset
            notes: Optional review notes

        Returns:
            ContentAsset: The updated asset instance, or None if not found

        Raises:
            ValueError: If asset is not in a state that can be approved
        """
        from content_catalog.models.content import ContentAsset

        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return None

        if not asset.can_approve():
            raise ValueError(
                f"Asset cannot be approved in its current status: {asset.status}"
            )

        asset.status = ContentAsset.STATUS_APPROVED
        asset.reviewed_by = approved_by
        asset.reviewed_at = datetime.now(timezone.utc)
        asset.review_notes = notes
        asset.updated_at = datetime.now(timezone.utc)

        return asset

    @classmethod
    def reject_asset(
        cls,
        db_session,
        asset_id: int,
        rejected_by: int,
        reason: str
    ) -> Optional['ContentAsset']:
        """
        Reject an asset that is pending review.

        Args:
            db_session: SQLAlchemy database session
            asset_id: The asset ID to reject
            rejected_by: The user ID rejecting the asset
            reason: The reason for rejection (required)

        Returns:
            ContentAsset: The updated asset instance, or None if not found

        Raises:
            ValueError: If asset is not in a state that can be rejected or reason is empty
        """
        from content_catalog.models.content import ContentAsset

        if not reason or not reason.strip():
            raise ValueError("Rejection reason is required")

        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return None

        if not asset.can_approve():  # Same check - must be pending review
            raise ValueError(
                f"Asset cannot be rejected in its current status: {asset.status}"
            )

        asset.status = ContentAsset.STATUS_REJECTED
        asset.reviewed_by = rejected_by
        asset.reviewed_at = datetime.now(timezone.utc)
        asset.review_notes = reason.strip()
        asset.updated_at = datetime.now(timezone.utc)

        return asset

    @classmethod
    def publish_asset(
        cls,
        db_session,
        asset_id: int
    ) -> Optional['ContentAsset']:
        """
        Publish an approved asset.

        Args:
            db_session: SQLAlchemy database session
            asset_id: The asset ID to publish

        Returns:
            ContentAsset: The updated asset instance, or None if not found

        Raises:
            ValueError: If asset is not in an approved state
        """
        from content_catalog.models.content import ContentAsset

        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return None

        if not asset.can_publish():
            raise ValueError(
                f"Asset cannot be published in its current status: {asset.status}"
            )

        asset.status = ContentAsset.STATUS_PUBLISHED
        asset.published_at = datetime.now(timezone.utc)
        asset.updated_at = datetime.now(timezone.utc)

        return asset

    @classmethod
    def archive_asset(
        cls,
        db_session,
        asset_id: int
    ) -> Optional['ContentAsset']:
        """
        Archive an asset.

        Moves the asset to archived status. Archived assets are retained
        for records but no longer appear in active listings.

        Args:
            db_session: SQLAlchemy database session
            asset_id: The asset ID to archive

        Returns:
            ContentAsset: The updated asset instance, or None if not found
        """
        from content_catalog.models.content import ContentAsset

        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return None

        asset.status = ContentAsset.STATUS_ARCHIVED
        asset.updated_at = datetime.now(timezone.utc)

        return asset

    @classmethod
    def get_approved_content(
        cls,
        db_session,
        network_id: Optional[str] = None,
        organization_id: Optional[int] = None,
        category: Optional[str] = None,
        page: int = DEFAULT_PAGE,
        per_page: int = DEFAULT_PER_PAGE
    ) -> Tuple[List['ContentAsset'], int]:
        """
        Get approved and published content assets for CMS integration.

        Returns content assets that have been approved or published,
        suitable for consumption by external systems like the CMS.
        Only returns content that has passed the approval workflow.

        Args:
            db_session: SQLAlchemy database session
            network_id: Filter by network ID (optional). Matches assets
                       where networks JSON field contains this ID.
            organization_id: Filter by organization (optional)
            category: Filter by content category (optional)
            page: Page number (1-indexed, default 1)
            per_page: Results per page (default 20, max 100)

        Returns:
            Tuple of (list of ContentAsset instances, total count)

        Example:
            assets, total = ContentService.get_approved_content(
                db.session,
                network_id='network-1',
                organization_id=1,
                page=1,
                per_page=20
            )
        """
        from content_catalog.models.content import ContentAsset

        # Build the base query for approved/published content only
        query = db_session.query(ContentAsset).filter(
            ContentAsset.status.in_([
                ContentAsset.STATUS_APPROVED,
                ContentAsset.STATUS_PUBLISHED
            ])
        )

        # Apply network filter if provided
        # Networks is stored as a JSON string, so we use LIKE for matching
        if network_id is not None:
            query = query.filter(ContentAsset.networks.like(f'%{network_id}%'))

        # Apply organization filter if provided
        if organization_id is not None:
            query = query.filter(ContentAsset.organization_id == organization_id)

        # Apply category filter if provided
        if category is not None:
            query = query.filter(ContentAsset.category == category)

        # Get total count before pagination
        total = query.count()

        # Apply sorting (newest first for approved, by published_at for published)
        query = query.order_by(ContentAsset.created_at.desc())

        # Apply pagination
        per_page = min(per_page, cls.MAX_PER_PAGE)
        offset = (page - 1) * per_page
        assets = query.offset(offset).limit(per_page).all()

        return assets, total
