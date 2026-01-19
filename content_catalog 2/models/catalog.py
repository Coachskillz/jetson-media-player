"""
Catalog and Category Models for Content Catalog Service.

Represents content catalogs and their categories for organizing
content assets in a hierarchical structure with multi-tenant support.
"""

from datetime import datetime, timezone
import uuid

from content_catalog.models import db


class Catalog(db.Model):
    """
    SQLAlchemy model representing a content catalog.

    Catalogs are top-level containers for organizing content assets.
    Each catalog belongs to a tenant and can be marked as internal-only
    to restrict visibility to internal users.

    Attributes:
        id: Unique integer identifier (internal)
        uuid: Unique UUID for external API references
        tenant_id: Foreign key to owning tenant (optional for global catalogs)
        name: Human-readable name for the catalog
        description: Optional description of the catalog
        is_internal_only: If True, only visible to internal users
        is_active: Whether the catalog is active
        created_at: Timestamp when catalog was created
        updated_at: Timestamp of last update
    """

    __tablename__ = 'catalogs'

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

    # Tenant ownership (nullable for global catalogs)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)

    # Catalog metadata
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Visibility flags
    is_internal_only = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self):
        """
        Serialize the catalog to a dictionary for API responses.

        Returns:
            Dictionary containing all catalog fields
        """
        return {
            'id': self.id,
            'uuid': self.uuid,
            'tenant_id': self.tenant_id,
            'name': self.name,
            'description': self.description,
            'is_internal_only': self.is_internal_only,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    @classmethod
    def get_by_uuid(cls, catalog_uuid):
        """
        Get a catalog by its UUID.

        Args:
            catalog_uuid: The UUID to search for

        Returns:
            Catalog instance or None
        """
        return cls.query.filter_by(uuid=catalog_uuid).first()

    @classmethod
    def get_active(cls, tenant_id=None, include_internal=False):
        """
        Get all active catalogs, optionally filtered by tenant.

        Args:
            tenant_id: Optional tenant ID to filter by
            include_internal: Whether to include internal-only catalogs

        Returns:
            list: List of active Catalog instances
        """
        query = cls.query.filter_by(is_active=True)
        if tenant_id is not None:
            # Include global catalogs (tenant_id=None) and tenant-specific ones
            query = query.filter(
                db.or_(cls.tenant_id == tenant_id, cls.tenant_id.is_(None))
            )
        if not include_internal:
            query = query.filter_by(is_internal_only=False)
        return query.order_by(cls.name.asc()).all()

    def __repr__(self):
        """String representation for debugging."""
        return f'<Catalog {self.name}>'


class Category(db.Model):
    """
    SQLAlchemy model representing a content category.

    Categories provide hierarchical organization within catalogs.
    Each category belongs to a catalog and optionally to a parent category
    for nested structures.

    Attributes:
        id: Unique integer identifier (internal)
        uuid: Unique UUID for external API references
        catalog_id: Foreign key to owning catalog
        tenant_id: Foreign key to owning tenant (denormalized for query efficiency)
        parent_id: Foreign key to parent category (nullable for root categories)
        name: Human-readable name for the category
        description: Optional description of the category
        sort_order: Display order within parent
        is_active: Whether the category is active
        created_at: Timestamp when category was created
        updated_at: Timestamp of last update
    """

    __tablename__ = 'categories'

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

    # Catalog and tenant ownership
    catalog_id = db.Column(
        db.Integer,
        db.ForeignKey('catalogs.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)

    # Hierarchy
    parent_id = db.Column(
        db.Integer,
        db.ForeignKey('categories.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )

    # Category metadata
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, default=0)

    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    catalog = db.relationship(
        'Catalog',
        foreign_keys=[catalog_id],
        backref=db.backref('categories', lazy='dynamic', cascade='all, delete-orphan')
    )
    parent = db.relationship(
        'Category',
        remote_side=[id],
        backref=db.backref('children', lazy='dynamic')
    )

    def to_dict(self, include_children=False):
        """
        Serialize the category to a dictionary for API responses.

        Args:
            include_children: Whether to include child categories

        Returns:
            Dictionary containing all category fields
        """
        result = {
            'id': self.id,
            'uuid': self.uuid,
            'catalog_id': self.catalog_id,
            'tenant_id': self.tenant_id,
            'parent_id': self.parent_id,
            'name': self.name,
            'description': self.description,
            'sort_order': self.sort_order,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        if include_children:
            result['children'] = [
                child.to_dict(include_children=False)
                for child in self.children.filter_by(is_active=True).order_by(Category.sort_order)
            ]
        return result

    @classmethod
    def get_by_uuid(cls, category_uuid):
        """
        Get a category by its UUID.

        Args:
            category_uuid: The UUID to search for

        Returns:
            Category instance or None
        """
        return cls.query.filter_by(uuid=category_uuid).first()

    @classmethod
    def get_root_categories(cls, catalog_id):
        """
        Get all root categories (no parent) for a catalog.

        Args:
            catalog_id: The catalog ID to filter by

        Returns:
            list: List of root Category instances
        """
        return cls.query.filter_by(
            catalog_id=catalog_id,
            parent_id=None,
            is_active=True
        ).order_by(cls.sort_order.asc(), cls.name.asc()).all()

    @classmethod
    def get_by_catalog(cls, catalog_id, include_inactive=False):
        """
        Get all categories for a specific catalog.

        Args:
            catalog_id: The catalog ID to filter by
            include_inactive: Whether to include inactive categories

        Returns:
            list: List of Category instances
        """
        query = cls.query.filter_by(catalog_id=catalog_id)
        if not include_inactive:
            query = query.filter_by(is_active=True)
        return query.order_by(cls.sort_order.asc(), cls.name.asc()).all()

    def get_ancestors(self):
        """
        Get all ancestor categories (parent chain to root).

        Returns:
            list: List of Category instances from immediate parent to root
        """
        ancestors = []
        current = self.parent
        while current:
            ancestors.append(current)
            current = current.parent
        return ancestors

    def get_full_path(self):
        """
        Get the full path from root to this category.

        Returns:
            str: Slash-separated path (e.g., "Root/Child/Grandchild")
        """
        ancestors = self.get_ancestors()
        ancestors.reverse()
        path_parts = [a.name for a in ancestors] + [self.name]
        return '/'.join(path_parts)

    def __repr__(self):
        """String representation for debugging."""
        return f'<Category {self.name}>'