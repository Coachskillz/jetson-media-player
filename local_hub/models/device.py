"""
Device database model for tracking devices connected to this hub.

This model maintains information about each device registered with the hub:
- Identity: device_id (from CMS), hardware_id (unique), name
- Status: online/offline status, last heartbeat time
- Configuration: mode (direct/hub), camera settings
- CMS sync: cms_device_id for CMS correlation, synced_at timestamp

Devices register via the /api/v1/devices/register endpoint and send
periodic heartbeats. The hub batches these heartbeats and forwards them
to the CMS. When CMS is unreachable, heartbeats are queued locally.
"""

from datetime import datetime
from models import db


class Device(db.Model):
    """
    Database model for devices connected to this hub.

    Each device is uniquely identified by its hardware_id and tracked
    for heartbeat/status monitoring. The hub acts as a relay, forwarding
    device registrations and heartbeats to the CMS.

    Attributes:
        id: Primary key (local database)
        device_id: CMS-assigned device ID (SKZ-D-XXXX or SKZ-H-CODE-XXXX)
        hardware_id: Unique hardware identifier from physical device
        name: Human-readable device name/label
        mode: Operation mode ('direct' or 'hub')
        status: Current status (online, offline, pending)
        last_heartbeat: Timestamp of most recent heartbeat
        camera1_enabled: Whether camera 1 (demographics/loyalty) is enabled
        camera1_demographics: Whether demographics recognition is enabled
        camera1_loyalty: Whether loyalty recognition is enabled
        camera2_enabled: Whether camera 2 (NCMEC) is enabled
        camera2_ncmec: Whether NCMEC detection is enabled
        cms_device_id: The CMS internal UUID for this device
        synced_at: When device was last synced with CMS
        created_at: When device was first registered locally
        updated_at: Last modification timestamp
    """
    __tablename__ = 'devices'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(50), unique=True, nullable=True, index=True)
    hardware_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=True)

    # Operation mode
    mode = db.Column(db.String(20), default='hub', nullable=False)

    # Status tracking
    status = db.Column(db.String(20), default='pending', nullable=False)
    last_heartbeat = db.Column(db.DateTime, default=datetime.utcnow)

    # Camera 1 settings (demographics and loyalty recognition)
    camera1_enabled = db.Column(db.Boolean, default=False, nullable=False)
    camera1_demographics = db.Column(db.Boolean, default=False, nullable=False)
    camera1_loyalty = db.Column(db.Boolean, default=False, nullable=False)

    # Camera 2 settings (NCMEC detection)
    camera2_enabled = db.Column(db.Boolean, default=False, nullable=False)
    camera2_ncmec = db.Column(db.Boolean, default=False, nullable=False)

    # CMS correlation
    cms_device_id = db.Column(db.String(36), nullable=True)
    synced_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """
        Serialize model to dictionary for JSON responses.

        Returns:
            dict: Complete device data including camera settings
        """
        return {
            'id': self.id,
            'device_id': self.device_id,
            'hardware_id': self.hardware_id,
            'name': self.name,
            'mode': self.mode,
            'status': self.status,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'camera1_enabled': self.camera1_enabled,
            'camera1_demographics': self.camera1_demographics,
            'camera1_loyalty': self.camera1_loyalty,
            'camera2_enabled': self.camera2_enabled,
            'camera2_ncmec': self.camera2_ncmec,
            'cms_device_id': self.cms_device_id,
            'synced_at': self.synced_at.isoformat() if self.synced_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def to_heartbeat_dict(self):
        """
        Return data for heartbeat batching to CMS.

        This is the data sent in batched heartbeats to the CMS
        via POST /api/v1/hubs/{hub_id}/heartbeats.

        Returns:
            dict: Heartbeat data for CMS consumption
        """
        return {
            'device_id': self.device_id,
            'hardware_id': self.hardware_id,
            'status': self.status,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None
        }

    def update_heartbeat(self):
        """
        Update last_heartbeat timestamp and set status to online.

        Call this when receiving a heartbeat from the device.
        """
        self.last_heartbeat = datetime.utcnow()
        self.status = 'online'
        db.session.commit()

    @property
    def is_online(self):
        """
        Check if device is currently online.

        Returns:
            bool: True if status is 'online'
        """
        return self.status == 'online'

    @property
    def is_synced(self):
        """
        Check if device has been synced with CMS.

        Returns:
            bool: True if device has a CMS device ID
        """
        return self.cms_device_id is not None

    @classmethod
    def get_by_hardware_id(cls, hardware_id):
        """
        Find device by hardware identifier.

        Args:
            hardware_id: The hardware_id to search for

        Returns:
            Device or None: The device record if found
        """
        return cls.query.filter_by(hardware_id=hardware_id).first()

    @classmethod
    def get_by_device_id(cls, device_id):
        """
        Find device by CMS-assigned device ID.

        Args:
            device_id: The device_id (SKZ-D-XXXX) to search for

        Returns:
            Device or None: The device record if found
        """
        return cls.query.filter_by(device_id=device_id).first()

    @classmethod
    def register(cls, hardware_id, name=None, mode='hub'):
        """
        Register a new device or return existing one.

        If a device with this hardware_id exists, update its heartbeat
        and return it. Otherwise create a new device record.

        Args:
            hardware_id: Unique hardware identifier
            name: Optional human-readable name
            mode: Operation mode ('direct' or 'hub')

        Returns:
            tuple: (Device instance, bool created)
        """
        device = cls.get_by_hardware_id(hardware_id)
        if device:
            # Existing device - update heartbeat
            device.update_heartbeat()
            if name and not device.name:
                device.name = name
                db.session.commit()
            return device, False

        # New device
        device = cls(
            hardware_id=hardware_id,
            name=name,
            mode=mode,
            status='pending',
            last_heartbeat=datetime.utcnow()
        )
        db.session.add(device)
        db.session.commit()
        return device, True

    @classmethod
    def update_from_cms(cls, hardware_id, cms_data):
        """
        Update local device record with data from CMS.

        Called after CMS confirms device registration or during sync.

        Args:
            hardware_id: Hardware identifier to look up
            cms_data: Dictionary with CMS device data

        Returns:
            Device or None: Updated device if found
        """
        device = cls.get_by_hardware_id(hardware_id)
        if not device:
            return None

        # Update CMS correlation fields
        if 'id' in cms_data:
            device.cms_device_id = cms_data['id']
        if 'device_id' in cms_data:
            device.device_id = cms_data['device_id']
        if 'status' in cms_data:
            device.status = cms_data['status']

        # Update camera settings if provided
        if 'camera1_enabled' in cms_data:
            device.camera1_enabled = cms_data['camera1_enabled']
        if 'camera1_demographics' in cms_data:
            device.camera1_demographics = cms_data['camera1_demographics']
        if 'camera1_loyalty' in cms_data:
            device.camera1_loyalty = cms_data['camera1_loyalty']
        if 'camera2_enabled' in cms_data:
            device.camera2_enabled = cms_data['camera2_enabled']
        if 'camera2_ncmec' in cms_data:
            device.camera2_ncmec = cms_data['camera2_ncmec']

        device.synced_at = datetime.utcnow()
        db.session.commit()
        return device

    @classmethod
    def get_all_online(cls):
        """
        Get all devices with online status.

        Returns:
            list: List of Device instances with status='online'
        """
        return cls.query.filter_by(status='online').all()

    @classmethod
    def get_all_pending(cls):
        """
        Get all devices with pending status.

        Returns:
            list: List of Device instances with status='pending'
        """
        return cls.query.filter_by(status='pending').all()

    @classmethod
    def get_all_for_heartbeat(cls):
        """
        Get all devices that need heartbeat forwarding to CMS.

        Returns devices that are online and have been synced with CMS.

        Returns:
            list: List of Device instances ready for heartbeat batching
        """
        return cls.query.filter(
            cls.status == 'online',
            cls.cms_device_id.isnot(None)
        ).all()

    @classmethod
    def mark_offline(cls, hardware_id):
        """
        Mark a device as offline.

        Args:
            hardware_id: Hardware identifier of device

        Returns:
            Device or None: Updated device if found
        """
        device = cls.get_by_hardware_id(hardware_id)
        if device:
            device.status = 'offline'
            db.session.commit()
        return device

    def __repr__(self):
        """String representation."""
        return f"<Device id={self.id} hardware_id={self.hardware_id} status={self.status}>"
