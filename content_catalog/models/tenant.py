"""
Tenant Model for Content Catalog Service.

Represents a tenant (e.g., network, retailer) in the multi-tenant content catalog.
Tenants isolate content and users within the system.
"""

from datetime import datetime, timezone
import uuid

from content_catalog.models import db


class Tenant(db.Model):
    """
    SQLAlchemy model representing a tenant in the multi-tenant system.

    Tenants provide isolation for:
    - Content catalogs and categories
    - Users and organizations
    - Assets and approval workflows

    Examples:
    - "high-octane" - High Octane Network (convenience stores)
    - "on-the-wave" - On The Wave TV (West Marine)
    - "skillz-internal" - Internal Skillz Media content

    Attributes:
        id: UUID primary key
        name: Human-readable tenant name
        slug: URL-safe identifier (e.g., "high-octane")
        is_active: Whether tenant is active
        created_at: Timestamp when tenant was created
        updated_at: Timestamp of last update
    """

    __tablename__ = 'tenants'

    # Primary key (UUID)
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Tenant info
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)

    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    catalogs = db.relationship('Catalog', backref='tenant', lazy='dynamic')
    categories = db.relationship('Category', backref='tenant', lazy='dynamic')

    def to_dict(self):
        """Serialize tenant to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def __repr__(self):
        return f'<Tenant {self.slug}>'
