"""
Heartbeat Model for CMS Service.

Tracks device health pings received from Hubs or direct devices.
Used for monitoring device status, uptime, and system health.
"""

from datetime import datetime, timezone
import uuid

from cms.models import db, DateTimeUTC


class Heartbeat(db.Model):
    """
    SQLAlchemy model representing a device heartbeat.

    Heartbeats are sent every 5 minutes from devices (via Hub or direct)
    to report their status, current content, and system metrics.

    Attributes:
        id: Unique auto-increment identifier
        device_id: Device identifier (e.g., SKZ-H-WM-0001)
        hub_id: Hub identifier if device connects through a hub
        network_id: Network identifier (e.g., west_marine, high_octane)
        store_name: Human-readable store name
        location: Screen location within the store
        status: Device status (online, offline, etc.)
        current_content: Filename currently playing
        ip_address: Device's IP address
        cpu_temp: CPU temperature in Celsius
        storage_free_mb: Free storage in megabytes
        software_version: Current software version
        mode: Device mode (hub or direct)
        timestamp: When the heartbeat was received
    """

    __tablename__ = 'heartbeats'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    device_id = db.Column(db.String(100), index=True, nullable=False)
    hub_id = db.Column(db.String(100), nullable=True, index=True)
    network_id = db.Column(db.String(100), nullable=True, index=True)
    store_name = db.Column(db.String(200), nullable=True)
    location = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), default='online')
    current_content = db.Column(db.String(500), nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    cpu_temp = db.Column(db.Float, nullable=True)
    storage_free_mb = db.Column(db.Integer, nullable=True)
    software_version = db.Column(db.String(20), nullable=True)
    mode = db.Column(db.String(20), nullable=True)
    timestamp = db.Column(DateTimeUTC(), default=lambda: datetime.now(timezone.utc), index=True)

    def to_dict(self):
        """Serialize the heartbeat to a dictionary for API responses."""
        return {
            'id': self.id,
            'device_id': self.device_id,
            'hub_id': self.hub_id,
            'network_id': self.network_id,
            'store_name': self.store_name,
            'location': self.location,
            'status': self.status,
            'current_content': self.current_content,
            'ip_address': self.ip_address,
            'cpu_temp': self.cpu_temp,
            'storage_free_mb': self.storage_free_mb,
            'software_version': self.software_version,
            'mode': self.mode,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }

    def __repr__(self):
        return f'<Heartbeat {self.device_id} at {self.timestamp}>'
