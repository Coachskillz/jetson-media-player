"""
Hub Model for CMS Service.

Represents a physical location or hub within a network that contains multiple devices.
Each hub has a unique code for identification and belongs to a network.
Hubs can sync content from the CMS and serve connected devices.

Includes PendingHub for hubs that have announced but not yet been paired by an admin.
"""

from datetime import datetime, timezone, timedelta
import uuid

from cms.models import db


class PendingHub(db.Model):
    """
    SQLAlchemy model representing a hub awaiting admin pairing.

    When a hub first connects to the CMS, it announces itself with a pairing code.
    The hub remains in pending state until an admin enters the pairing code in the CMS UI.
    Pairing codes expire after 15 minutes for security.

    Attributes:
        id: Unique integer identifier
        hardware_id: Unique hardware identifier from the hub device
        pairing_code: 6-character code displayed on hub screen (format: XXX-XXX)
        wan_ip: Public IP address (5G/WAN connection)
        lan_ip: Local network IP (typically 10.10.10.1)
        tunnel_url: Cloudflare tunnel URL for remote access
        version: Hub software version
        created_at: When the hub first announced
        expires_at: When the pairing code expires
    """

    __tablename__ = 'pending_hubs'

    id = db.Column(db.Integer, primary_key=True)
    hardware_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    pairing_code = db.Column(db.String(20), nullable=False, index=True)
    wan_ip = db.Column(db.String(45), nullable=True)
    lan_ip = db.Column(db.String(45), nullable=True)
    tunnel_url = db.Column(db.String(200), nullable=True)
    version = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        """Serialize pending hub to dictionary."""
        now = datetime.now(timezone.utc)
        expires_at_aware = self.expires_at.replace(tzinfo=timezone.utc) if self.expires_at and self.expires_at.tzinfo is None else self.expires_at
        minutes_remaining = int((expires_at_aware - now).total_seconds() / 60) if expires_at_aware and expires_at_aware > now else 0

        return {
            'id': self.id,
            'hardware_id': self.hardware_id,
            'pairing_code': self.pairing_code,
            'wan_ip': self.wan_ip,
            'lan_ip': self.lan_ip,
            'tunnel_url': self.tunnel_url,
            'version': self.version,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'minutes_remaining': minutes_remaining
        }

    def __repr__(self):
        return f'<PendingHub {self.hardware_id} code={self.pairing_code}>'


class Hub(db.Model):
    """
    SQLAlchemy model representing a paired and active hub (physical location).

    A hub is a physical location that contains multiple devices/screens.
    It belongs to a network and serves as an organizational unit for
    grouping devices together.

    Attributes:
        id: Unique UUID identifier
        code: Unique code for the hub (URL-friendly identifier)
        name: Human-readable hub name (store name)
        network_id: Foreign key reference to the parent network
        status: Current status (online, offline, maintenance)
        created_at: Timestamp when the hub was created

        # Hardware identification
        hardware_id: Unique hardware identifier from the hub device

        # Network/connectivity fields
        ip_address: LAN IP address (typically 10.10.10.1)
        wan_ip: Public IP address (5G/WAN connection)
        tunnel_url: Cloudflare tunnel URL for remote access
        mac_address: MAC address of the hub's network interface
        hostname: Hostname of the hub machine

        # Status/monitoring
        last_heartbeat: Timestamp of last hub heartbeat/check-in
        screens_connected: Number of Jetson devices connected to this hub
        version: Hub software version

        # Authentication
        api_token: API token for hub authentication with CMS

        # Timestamps
        paired_at: When the hub was paired by admin
    """

    __tablename__ = 'hubs'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    network_id = db.Column(db.String(36), db.ForeignKey('networks.id'), nullable=False, index=True)
    status = db.Column(db.String(50), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Hardware identification
    hardware_id = db.Column(db.String(50), unique=True, nullable=True, index=True)

    # Network/connectivity fields for sync protocol
    ip_address = db.Column(db.String(45), nullable=True)  # LAN IP (10.10.10.1)
    wan_ip = db.Column(db.String(45), nullable=True)  # Public/5G IP
    tunnel_url = db.Column(db.String(200), nullable=True)  # Cloudflare tunnel
    mac_address = db.Column(db.String(17), nullable=True)  # Format: XX:XX:XX:XX:XX:XX
    hostname = db.Column(db.String(255), nullable=True)

    # Status/monitoring
    last_heartbeat = db.Column(db.DateTime, nullable=True)
    screens_connected = db.Column(db.Integer, default=0)
    version = db.Column(db.String(20), nullable=True)

    # Authentication
    api_token = db.Column(db.String(255), nullable=True, unique=True, index=True)

    # Timestamps
    paired_at = db.Column(db.DateTime, nullable=True)
    location = db.Column(db.String(500), nullable=True)  # Physical address

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
            'hardware_id': self.hardware_id,
            'ip_address': self.ip_address,
            'wan_ip': self.wan_ip,
            'tunnel_url': self.tunnel_url,
            'mac_address': self.mac_address,
            'hostname': self.hostname,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'screens_connected': self.screens_connected,
            'version': self.version,
            'api_token': self.api_token,
            'paired_at': self.paired_at.isoformat() if self.paired_at else None,
            'location': self.location
        }

    def __repr__(self):
        """String representation for debugging."""
        return f'<Hub {self.code}>'
