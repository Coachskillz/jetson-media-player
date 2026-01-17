"""
Hub Model for CMS Service.

Represents a physical location or hub within a network that contains multiple devices.
Each hub has a unique code for identification and belongs to a network.
Hubs can sync content from the CMS and serve connected devices.
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
        ip_address: IP address of the hub on the local network
        mac_address: MAC address of the hub's network interface
        hostname: Hostname of the hub machine
        last_heartbeat: Timestamp of last hub heartbeat/check-in
        api_token: API token for hub authentication with CMS
    """

    __tablename__ = 'hubs'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    network_id = db.Column(db.String(36), db.ForeignKey('networks.id'), nullable=False, index=True)
    status = db.Column(db.String(50), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Network/connectivity fields for sync protocol
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4 or IPv6
    mac_address = db.Column(db.String(17), nullable=True)  # Format: XX:XX:XX:XX:XX:XX
    hostname = db.Column(db.String(255), nullable=True)
    last_heartbeat = db.Column(db.DateTime, nullable=True)
    api_token = db.Column(db.String(255), nullable=True, unique=True, index=True)

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
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'ip_address': self.ip_address,
            'mac_address': self.mac_address,
            'hostname': self.hostname,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'api_token': self.api_token
        }

    def __repr__(self):
        """String representation for debugging."""
        return f'<Hub {self.code}>'
