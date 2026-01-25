"""
Tenant Model for Content Catalog Service.

Represents a tenant in the multi-tenant content catalog system.
Tenants are top-level entities for data isolation, containing
catalogs, categories, assets, and organizations.
"""

from datetime import datetime, timezone
import uuid

from content_catalog.models import db


class Tenant(db.Model):
    """
    SQLAlchemy model representing a tenant in the Content Catalog system.

    Tenants provide multi-tenant data isolation. All content assets,
    catalogs, categories, and organizations are scoped to a specific tenant.
    Users can belong to multiple tenants via the tenant_ids field.

    Examples:
    - "high-octane" - High Octane Network (convenience stores)
    - "on-the-wave" - On The Wave TV (West Marine)
    - "skillz-internal" - Internal Skillz Media content

    Attributes:
        id: Unique integer identifier (internal)
        uuid: Unique UUID for external API references
        name: Human-readable name for the tenant
        slug: URL-friendly identifier for the tenant
        description: Optional description of the tenant
        is_active: Whether the tenant is active
        created_at: Timestamp when tenant was created
        updated_at: Timestamp of last update
    """

    __tablename__ = 'tenants'

    # Primary key (internal use)
    id = db.Column(db.Integer, primary_key=True)

    # UUID for external API references
    uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
        index=True
    )

    # Tenant metadata
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)

    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)


    # Content Approval Settings
    # TRUE: Venue must approve content before it plays on their screens
    # FALSE: Skillz-approved content auto-plays (trusted venue)
    requires_content_approval = db.Column(db.Boolean, default=True, nullable=False)
    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    catalogs = db.relationship('Catalog', backref='tenant', lazy='dynamic')
    categories = db.relationship('Category', backref='tenant', lazy='dynamic')

    def to_dict(self):
        """
        Serialize the tenant to a dictionary for API responses.

        Returns:
            Dictionary containing all tenant fields
        """
        return {
            'id': self.id,
            'uuid': self.uuid,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'is_active': self.is_active,
            'requires_content_approval': self.requires_content_approval,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    @classmethod
    def get_by_uuid(cls, tenant_uuid):
        """
        Get a tenant by its UUID.

        Args:
            tenant_uuid: The UUID to search for

        Returns:
            Tenant instance or None
        """
        return cls.query.filter_by(uuid=tenant_uuid).first()

    @classmethod
    def get_by_slug(cls, slug):
        """
        Get a tenant by its slug.

        Args:
            slug: The slug to search for

        Returns:
            Tenant instance or None
        """
        return cls.query.filter_by(slug=slug).first()

    @classmethod
    def get_active(cls):
        """
        Get all active tenants.

        Returns:
            list: List of active Tenant instances
        """
        return cls.query.filter_by(is_active=True).order_by(cls.name.asc()).all()

    def __repr__(self):
        """String representation for debugging."""
        return f'<Tenant {self.name}>'