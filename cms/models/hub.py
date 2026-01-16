"""
Hub Model for CMS Service.

Represents a physical location or hub within a network that contains multiple devices.
Each hub has a unique code for identification and belongs to a network.
"""

from datetime import datetime, timezone
import uuid

from cms.models import db


class Hub(db.Model):
    """
    SQLAlchemy model representing a hub (physical location).

    A hub is a physical location that contains multiple devices/screens.
    It belongs to a network and serves as an organizational unit for
    grouping devices together.

    Attributes:
        id: Unique UUID identifier
        code: Unique code for the hub (URL-friendly identifier)
        name: Human-readable hub name
        network_id: Foreign key reference to the parent network
        status: Current status of the hub (active, inactive, etc.)
        created_at: Timestamp when the hub was created
    """

    __tablename__ = 'hubs'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    network_id = db.Column(db.String(36), db.ForeignKey('networks.id'), nullable=False, index=True)
    status = db.Column(db.String(50), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    network = db.relationship('Network', backref=db.backref('hubs', lazy='dynamic'))
    # devices = db.relationship('Device', backref='hub', lazy='dynamic')

    def to_dict(self):
        """
        Serialize the hub to a dictionary for API responses.

        Returns:
            Dictionary containing all hub fields
        """
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'network_id': self.network_id,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        """String representation for debugging."""
        return f'<Hub {self.code}>'
