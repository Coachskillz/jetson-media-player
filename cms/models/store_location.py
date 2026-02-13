"""
Store Location Model for CMS Service.

Represents a specific location within a store/hub where a screen can be placed.
Examples: 'Fishing Counter', 'Entrance', 'Checkout', 'Aisle 3'

Each location belongs to a Hub and can have one Device assigned to it.
"""

from datetime import datetime, timezone
import uuid

from cms.models import db, DateTimeUTC


class StoreLocation(db.Model):
    """
    A named position within a store where a screen is installed.

    Attributes:
        id: Unique UUID identifier
        hub_id: Foreign key to the Hub (store) this location belongs to
        name: Human-readable name (e.g., 'Fishing Counter')
        description: Optional notes about this location
        created_at: When this location was created
    """

    __tablename__ = 'store_locations'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    hub_id = db.Column(db.String(36), db.ForeignKey('hubs.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    created_at = db.Column(DateTimeUTC(), default=lambda: datetime.now(timezone.utc))

    # Relationships
    hub = db.relationship('Hub', backref=db.backref('store_locations', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'hub_id': self.hub_id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<StoreLocation {self.name}>'
