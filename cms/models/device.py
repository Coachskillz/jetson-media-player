"""
Device Model for CMS Service.

Represents a device (screen/display) that can operate in two modes:
- Direct mode: Device connects directly to the CMS (ID format: SKZ-D-XXXX)
- Hub mode: Device connects through a hub (ID format: SKZ-H-{CODE}-XXXX)
"""

from datetime import datetime, timezone
import uuid

from cms.models import db


class Device(db.Model):
    """
    SQLAlchemy model representing a device (screen/display).

    A device is an individual screen that displays content. Devices can operate
    in two modes:
    - Direct mode: Connects directly to CMS, gets device_id like SKZ-D-0001
    - Hub mode: Connects through a hub, gets device_id like SKZ-H-WM-0001

    Attributes:
        id: Unique UUID identifier (internal database ID)
        device_id: Unique display ID (SKZ-D-XXXX or SKZ-H-CODE-XXXX)
        hardware_id: Unique hardware identifier from the physical device
        mode: Operation mode ('direct' or 'hub')
        hub_id: Foreign key reference to the parent hub (required for hub mode)
        network_id: Foreign key reference to the network (optional until paired)
        name: Human-readable device name
        status: Current status (pending, active, offline, etc.)
        last_seen: Timestamp of last device check-in
        created_at: Timestamp when the device was registered
    """

    __tablename__ = 'devices'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    hardware_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    mode = db.Column(db.String(20), nullable=False)
    hub_id = db.Column(db.String(36), db.ForeignKey('hubs.id'), nullable=True, index=True)
    network_id = db.Column(db.String(36), db.ForeignKey('networks.id'), nullable=True, index=True)
    name = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(50), nullable=False, default='pending')
    last_seen = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    hub = db.relationship('Hub', backref=db.backref('devices', lazy='dynamic'))
    network = db.relationship('Network', backref=db.backref('devices', lazy='dynamic'))

    def to_dict(self):
        """
        Serialize the device to a dictionary for API responses.

        Returns:
            Dictionary containing all device fields
        """
        return {
            'id': self.id,
            'device_id': self.device_id,
            'hardware_id': self.hardware_id,
            'mode': self.mode,
            'hub_id': self.hub_id,
            'network_id': self.network_id,
            'name': self.name,
            'status': self.status,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        """String representation for debugging."""
        return f'<Device {self.device_id}>'
