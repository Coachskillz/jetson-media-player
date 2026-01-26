"""
Folder Model for CMS Service.

Represents a folder for organizing content within the CMS.
Supports nested folders (folders within folders).
"""

from datetime import datetime, timezone
import uuid

from cms.models import db


class Folder(db.Model):
    """
    SQLAlchemy model representing a content folder.

    Folders organize content within the CMS for campaigns,
    locations, stores, vendors, etc. Supports nesting.

    Attributes:
        id: Unique UUID identifier
        name: Folder name
        icon: Emoji icon for the folder
        color: Hex color code for the folder
        parent_id: ID of parent folder (None for root folders)
        network_id: ID of network this folder belongs to
        created_at: Timestamp when the folder was created
    """

    __tablename__ = 'folders'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False)
    icon = db.Column(db.String(10), default='📁')
    color = db.Column(db.String(20), default='#667eea')
    parent_id = db.Column(db.String(36), db.ForeignKey('folders.id'), nullable=True)
    network_id = db.Column(db.String(36), db.ForeignKey('networks.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Self-referential relationship for nested folders
    children = db.relationship('Folder', backref=db.backref('parent', remote_side=[id]), lazy='dynamic')

    # Network relationship
    network = db.relationship('Network', backref=db.backref('folders', lazy='dynamic'))

    def to_dict(self, include_children=False):
        """Convert folder to dictionary."""
        result = {
            'id': self.id,
            'name': self.name,
            'icon': self.icon,
            'color': self.color,
            'parent_id': self.parent_id,
            'network_id': self.network_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        if include_children:
            result['children'] = [child.to_dict(include_children=True) for child in self.children]
        return result
