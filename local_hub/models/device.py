"""
Device database model for tracking devices connected to this hub.
"""

from datetime import datetime
from models import db


class Device(db.Model):
    """Database model for devices connected to this hub."""
    __tablename__ = 'devices'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(50), unique=True, nullable=True, index=True)
    hardware_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=True)
    location = db.Column(db.String(200), nullable=True)

    # Network settings
    ip_address = db.Column(db.String(45), nullable=True)
    stream_port = db.Column(db.Integer, default=8080)
    stream_path = db.Column(db.String(100), default='/stream')
    snapshot_path = db.Column(db.String(100), default='/snapshot')

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

    @property
    def camera_enabled(self):
        """Check if any camera is enabled."""
        return self.camera1_enabled or self.camera2_enabled

    @property
    def stream_url(self):
        """Get full stream URL for this device."""
        if self.ip_address:
            return f"http://{self.ip_address}:{self.stream_port or 8080}{self.stream_path or '/stream'}"
        return None

    def to_dict(self):
        """Serialize model to dictionary for JSON responses."""
        return {
            'id': self.id,
            'device_id': self.device_id,
            'hardware_id': self.hardware_id,
            'name': self.name,
            'location': self.location,
            'ip_address': self.ip_address,
            'stream_port': self.stream_port,
            'stream_path': self.stream_path,
            'snapshot_path': self.snapshot_path,
            'mode': self.mode,
            'status': self.status,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'camera_enabled': self.camera_enabled,
            'camera1_enabled': self.camera1_enabled,
            'camera1_demographics': self.camera1_demographics,
            'camera1_loyalty': self.camera1_loyalty,
            'camera2_enabled': self.camera2_enabled,
            'camera2_ncmec': self.camera2_ncmec,
            'stream_url': self.stream_url,
            'cms_device_id': self.cms_device_id,
            'synced_at': self.synced_at.isoformat() if self.synced_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def to_heartbeat_dict(self):
        """Return data for heartbeat batching to CMS."""
        return {
            'device_id': self.device_id,
            'hardware_id': self.hardware_id,
            'status': self.status,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None
        }

    def update_heartbeat(self, ip_address=None):
        """Update last_heartbeat timestamp and set status to online."""
        self.last_heartbeat = datetime.utcnow()
        self.status = 'online'
        if ip_address:
            self.ip_address = ip_address
        db.session.commit()

    @property
    def is_online(self):
        return self.status == 'online'

    @property
    def is_synced(self):
        return self.cms_device_id is not None

    @classmethod
    def get_by_hardware_id(cls, hardware_id):
        return cls.query.filter_by(hardware_id=hardware_id).first()

    @classmethod
    def get_by_device_id(cls, device_id):
        return cls.query.filter_by(device_id=device_id).first()

    @classmethod
    def register(cls, hardware_id, name=None, mode='hub', ip_address=None, location=None):
        """Register a new device or return existing one."""
        device = cls.get_by_hardware_id(hardware_id)
        if device:
            device.update_heartbeat(ip_address)
            if name and not device.name:
                device.name = name
            if location:
                device.location = location
            db.session.commit()
            return device, False

        device = cls(
            hardware_id=hardware_id,
            name=name,
            mode=mode,
            ip_address=ip_address,
            location=location,
            status='pending',
            last_heartbeat=datetime.utcnow()
        )
        db.session.add(device)
        db.session.commit()
        return device, True

    @classmethod
    def update_from_cms(cls, hardware_id, cms_data):
        """Update local device record with data from CMS."""
        device = cls.get_by_hardware_id(hardware_id)
        if not device:
            return None

        if 'id' in cms_data:
            device.cms_device_id = cms_data['id']
        if 'device_id' in cms_data:
            device.device_id = cms_data['device_id']
        if 'status' in cms_data:
            device.status = cms_data['status']
        if 'location' in cms_data:
            device.location = cms_data['location']
        if 'name' in cms_data:
            device.name = cms_data['name']

        # Update camera settings if provided
        for field in ['camera1_enabled', 'camera1_demographics', 'camera1_loyalty',
                      'camera2_enabled', 'camera2_ncmec']:
            if field in cms_data:
                setattr(device, field, cms_data[field])

        device.synced_at = datetime.utcnow()
        db.session.commit()
        return device

    @classmethod
    def get_all_online(cls):
        return cls.query.filter_by(status='online').all()

    @classmethod
    def get_all_with_cameras(cls):
        """Get all devices with any camera enabled."""
        return cls.query.filter(
            db.or_(cls.camera1_enabled == True, cls.camera2_enabled == True)
        ).all()

    @classmethod
    def get_all_pending(cls):
        return cls.query.filter_by(status='pending').all()

    @classmethod
    def get_all_for_heartbeat(cls):
        return cls.query.filter(
            cls.status == 'online',
            cls.cms_device_id.isnot(None)
        ).all()

    @classmethod
    def mark_offline(cls, hardware_id):
        device = cls.get_by_hardware_id(hardware_id)
        if device:
            device.status = 'offline'
            db.session.commit()
        return device

    def __repr__(self):
        return f"<Device id={self.id} hardware_id={self.hardware_id} status={self.status}>"
