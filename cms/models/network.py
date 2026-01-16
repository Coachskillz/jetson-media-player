"""
Network Model for CMS Service.

Represents a digital signage network that groups together hubs, devices, and content.
Each network has a unique slug for URL-friendly identification.
"""

from datetime import datetime, timezone
import uuid

from cms.models import db


class Network(db.Model):
    """
    SQLAlchemy model representing a digital signage network.

    A network is the top-level organizational unit that contains:
    - Hubs (physical locations with multiple devices)
    - Devices (individual screens/displays)
    - Content (media files)
    - Playlists (scheduled content sequences)

    Attributes:
        id: Unique UUID identifier
        name: Human-readable network name
        slug: URL-friendly unique identifier
        created_at: Timestamp when the network was created
    """

    __tablename__ = 'networks'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships will be added as other models are created
    # hubs = db.relationship('Hub', backref='network', lazy='dynamic')
    # devices = db.relationship('Device', backref='network', lazy='dynamic')
    # content = db.relationship('Content', backref='network', lazy='dynamic')
    # playlists = db.relationship('Playlist', backref='network', lazy='dynamic')

    def to_dict(self):
        """
        Serialize the network to a dictionary for API responses.

        Returns:
            Dictionary containing all network fields
        """
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        """String representation for debugging."""
        return f'<Network {self.slug}>'
