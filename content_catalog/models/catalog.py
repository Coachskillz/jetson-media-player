"""
Catalog Model for Content Catalog Service.

Represents a content catalog within a tenant. Catalogs organize assets
and can be marked as internal-only (visible only to Skillz users).
"""

from datetime import datetime, timezone
import uuid

from content_catalog.models import db


class Catalog(db.Model):
    """
    SQLAlchemy model representing a content catalog.

    Catalogs organize assets within a tenant and control visibility:
    - Regular catalogs are visible to all users in the tenant
    - Internal-only catalogs are visible only to Skillz staff

    Examples:
    - "Brand Assets" - Partner brand materials
    - "Network Promos" - Internal promotional content
    - "Seasonal Campaigns" - Time-limited campaign assets

    Attributes:
        id: UUID primary key
        tenant_id: Foreign key to owning tenant
        name: Human-readable catalog name
        description: Optional description
        is_internal_only: If true, only visible to Skillz users
        is_active: Whether catalog is active
        created_at: Timestamp when catalog was created
        updated_at: Timestamp of last update
    """

    __tablename__ = 'catalogs'

    # Primary key (UUID)
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Tenant ownership
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)

    # Catalog info
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Visibility
    is_internal_only = db.Column(db.Boolean, default=False, nullable=False)

    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    categories = db.relationship('Category', backref='catalog', lazy='dynamic')

    def to_dict(self):
        """Serialize catalog to dictionary."""
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'name': self.name,
            'description': self.description,
            'is_internal_only': self.is_internal_only,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def __repr__(self):
        return f'<Catalog {self.name}>'
