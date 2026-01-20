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
        connection_mode: Connection mode ('direct' or 'hub') for API routing
        hub_url: URL for local hub connection (e.g., http://192.168.1.100:5000)
        cms_url: URL for direct CMS connection (e.g., http://cms.skillzmedia.com:5002)
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

    # Camera 1 settings (demographics and loyalty recognition)
    camera1_enabled = db.Column(db.Boolean, default=False)
    camera1_demographics = db.Column(db.Boolean, default=False)
    camera1_loyalty = db.Column(db.Boolean, default=False)

    # Camera 2 settings (NCMEC detection)
    camera2_enabled = db.Column(db.Boolean, default=False)
    camera2_ncmec = db.Column(db.Boolean, default=False)

    # Connection mode settings
    connection_mode = db.Column(db.String(20), nullable=False, default='direct')
    hub_url = db.Column(db.String(500), nullable=True)  # e.g., http://192.168.1.100:5000
    cms_url = db.Column(db.String(500), nullable=True)  # e.g., http://cms.skillzmedia.com:5002
    pairing_code = db.Column(db.String(6), nullable=True, index=True)

    # Pairing code for device registration workflow
    pairing_code = db.Column(db.String(10), nullable=True, index=True)

    # Layout assignment
    layout_id = db.Column(db.String(36), db.ForeignKey('screen_layouts.id', ondelete='SET NULL'), nullable=True, index=True)

    # Store/Location information (required for pairing)
    store_name = db.Column(db.String(200), nullable=True)  # Store name or number
    store_address = db.Column(db.String(300), nullable=True)
    store_city = db.Column(db.String(100), nullable=True)
    store_state = db.Column(db.String(50), nullable=True)
    store_zipcode = db.Column(db.String(20), nullable=True)
    screen_location = db.Column(db.String(200), nullable=True)  # Location in store (entrance, checkout, aisle-1, etc.)
    manager_name = db.Column(db.String(200), nullable=True)
    store_phone = db.Column(db.String(30), nullable=True)

    # Relationships
    hub = db.relationship('Hub', backref=db.backref('devices', lazy='dynamic'))
    network = db.relationship('Network', backref=db.backref('devices', lazy='dynamic'))
    layout = db.relationship('ScreenLayout', backref=db.backref('devices', lazy='dynamic'))

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
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'camera1_enabled': self.camera1_enabled,
            'camera1_demographics': self.camera1_demographics,
            'camera1_loyalty': self.camera1_loyalty,
            'camera2_enabled': self.camera2_enabled,
            'camera2_ncmec': self.camera2_ncmec,
            'connection_mode': self.connection_mode,
            'hub_url': self.hub_url,
            'cms_url': self.cms_url,
            'pairing_code': self.pairing_code,
            'layout_id': self.layout_id,
            'layout_name': self.layout.name if self.layout else None,
            # Store/Location information
            'store_name': self.store_name,
            'store_address': self.store_address,
            'store_city': self.store_city,
            'store_state': self.store_state,
            'store_zipcode': self.store_zipcode,
            'screen_location': self.screen_location,
            'manager_name': self.manager_name,
            'store_phone': self.store_phone
        }

    def is_pairing_complete(self):
        """
        Check if all required pairing fields are filled.

        Returns:
            bool: True if all required pairing fields are complete
        """
        required_fields = [
            self.network_id,
            self.store_name,
            self.store_address,
            self.store_city,
            self.store_state,
            self.store_zipcode,
            self.screen_location,
            self.manager_name,
            self.store_phone
        ]
        return all(field is not None and str(field).strip() != '' for field in required_fields)

    def get_missing_pairing_fields(self):
        """
        Get list of missing required pairing fields.

        Returns:
            list: Names of missing required fields
        """
        missing = []
        field_names = {
            'network_id': 'Network',
            'store_name': 'Store Name',
            'store_address': 'Address',
            'store_city': 'City',
            'store_state': 'State',
            'store_zipcode': 'Zipcode',
            'screen_location': 'Screen Location',
            'manager_name': 'Manager Name',
            'store_phone': 'Store Phone'
        }
        for field, label in field_names.items():
            value = getattr(self, field, None)
            if value is None or str(value).strip() == '':
                missing.append(label)
        return missing

    def __repr__(self):
        """String representation for debugging."""
        return f'<Device {self.device_id}>'
