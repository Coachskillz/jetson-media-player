"""
Category Model for Content Catalog Service.

Represents a category for organizing assets within a catalog.
Categories support hierarchical nesting via parent_id.
"""

from datetime import datetime, timezone
import uuid

from content_catalog.models import db


class Category(db.Model):
    """
    SQLAlchemy model representing a content category.

    Categories organize assets within catalogs and support
    hierarchical nesting (subcategories).

    Examples:
    - "Videos" > "Product Demos" > "Marine Electronics"
    - "Images" > "Logos" > "Partner Logos"
    - "PDFs" > "Spec Sheets"

    Attributes:
        id: UUID primary key
        catalog_id: Foreign key to parent catalog
        tenant_id: Foreign key to tenant (denormalized for queries)
        name: Category name
        description: Optional description
        parent_id: Foreign key to parent category (for nesting)
        sort_order: Display order within parent
        is_active: Whether category is active
        created_at: Timestamp when category was created
        updated_at: Timestamp of last update
    """

    __tablename__ = 'categories'

    # Primary key (UUID)
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Catalog and tenant ownership
    catalog_id = db.Column(db.String(36), db.ForeignKey('catalogs.id'), nullable=False, index=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)

    # Category info
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Hierarchical nesting
    parent_id = db.Column(db.String(36), db.ForeignKey('categories.id'), nullable=True, index=True)

    # Display order
    sort_order = db.Column(db.Integer, default=0)

    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    # Self-referential relationship for subcategories
    children = db.relationship(
        'Category',
        backref=db.backref('parent', remote_side=[id]),
        lazy='dynamic'
    )

    def to_dict(self, include_children=False):
        """
        Serialize category to dictionary.

        Args:
            include_children: Whether to include nested subcategories

        Returns:
            Dictionary representation of category
        """
        result = {
            'id': self.id,
            'catalog_id': self.catalog_id,
            'tenant_id': self.tenant_id,
            'name': self.name,
            'description': self.description,
            'parent_id': self.parent_id,
            'sort_order': self.sort_order,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

        if include_children:
            result['children'] = [
                child.to_dict(include_children=True)
                for child in self.children.filter_by(is_active=True).order_by(Category.sort_order)
            ]

        return result

    def __repr__(self):
        return f'<Category {self.name}>'
