"""
Screen database model for tracking Jetson screens connected to this hub.

This model maintains information about each screen registered with the hub:
- Identity: hardware_id (unique), name
- Status: online/offline status, last heartbeat time
- Feature flags: camera_enabled, loyalty_enabled, etc.
- Configuration: playlist assignment, database versions

Screens register via the /api/v1/screens/register endpoint and send
periodic heartbeats. Screens are marked offline after 2 minutes without
a heartbeat.
"""

from datetime import datetime
from models import db


class Screen(db.Model):
    """
    Database model for Jetson screens connected to this hub.

    Each screen is uniquely identified by its hardware_id and tracked
    for heartbeat/status monitoring. Feature flags control which
    capabilities are enabled on each screen.

    Attributes:
        id: Primary key
        hardware_id: Unique hardware identifier from Jetson device
        name: Human-readable screen name/label
        status: Current status (online, offline, unknown)
        last_heartbeat: Timestamp of most recent heartbeat
        camera_enabled: Whether camera/facial recognition is enabled
        loyalty_enabled: Whether loyalty program features are enabled
        ncmec_enabled: Whether NCMEC scanning is enabled
        current_playlist_id: Active playlist identifier from HQ
        ncmec_db_version: Currently installed NCMEC database version
        loyalty_db_version: Currently installed Loyalty database version
        created_at: When screen was first registered
        updated_at: Last modification timestamp
    """
    __tablename__ = 'screens'

    id = db.Column(db.Integer, primary_key=True)
    hardware_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(128), nullable=True)

    # Status tracking
    status = db.Column(db.String(20), default='online', nullable=False)
    last_heartbeat = db.Column(db.DateTime, default=datetime.utcnow)

    # Feature flags
    camera_enabled = db.Column(db.Boolean, default=False, nullable=False)
    loyalty_enabled = db.Column(db.Boolean, default=False, nullable=False)
    ncmec_enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Configuration from HQ
    current_playlist_id = db.Column(db.String(64), nullable=True)
    ncmec_db_version = db.Column(db.String(32), nullable=True)
    loyalty_db_version = db.Column(db.String(32), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """
        Serialize model to dictionary for JSON responses.

        Returns:
            dict: Complete screen data including feature flags
        """
        return {
            'id': self.id,
            'hardware_id': self.hardware_id,
            'name': self.name,
            'status': self.status,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'camera_enabled': self.camera_enabled,
            'loyalty_enabled': self.loyalty_enabled,
            'ncmec_enabled': self.ncmec_enabled,
            'current_playlist_id': self.current_playlist_id,
            'ncmec_db_version': self.ncmec_db_version,
            'loyalty_db_version': self.loyalty_db_version,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def to_config_dict(self):
        """
        Return configuration data for screen config endpoint.

        This is the data returned by GET /api/v1/screens/{id}/config
        that the Jetson screen uses to configure itself.

        Returns:
            dict: Configuration data including feature flags and DB versions
        """
        return {
            'screen_id': self.id,
            'playlist_id': self.current_playlist_id,
            'camera_enabled': self.camera_enabled,
            'loyalty_enabled': self.loyalty_enabled,
            'ncmec_enabled': self.ncmec_enabled,
            'ncmec_db_version': self.ncmec_db_version,
            'loyalty_db_version': self.loyalty_db_version
        }

    def update_heartbeat(self):
        """
        Update last_heartbeat timestamp and set status to online.

        Call this when receiving a heartbeat from the screen.
        """
        self.last_heartbeat = datetime.utcnow()
        self.status = 'online'
        db.session.commit()

    @property
    def is_online(self):
        """
        Check if screen is currently online.

        Returns:
            bool: True if status is 'online'
        """
        return self.status == 'online'

    @classmethod
    def get_by_hardware_id(cls, hardware_id):
        """
        Find screen by hardware identifier.

        Args:
            hardware_id: The hardware_id to search for

        Returns:
            Screen or None: The screen record if found
        """
        return cls.query.filter_by(hardware_id=hardware_id).first()

    @classmethod
    def register(cls, hardware_id, name=None):
        """
        Register a new screen or return existing one.

        If a screen with this hardware_id exists, update its heartbeat
        and return it. Otherwise create a new screen record.

        Args:
            hardware_id: Unique hardware identifier
            name: Optional human-readable name

        Returns:
            tuple: (Screen instance, bool created)
        """
        screen = cls.get_by_hardware_id(hardware_id)
        if screen:
            # Existing screen - update heartbeat
            screen.update_heartbeat()
            if name and not screen.name:
                screen.name = name
                db.session.commit()
            return screen, False

        # New screen
        screen = cls(
            hardware_id=hardware_id,
            name=name,
            status='online',
            last_heartbeat=datetime.utcnow()
        )
        db.session.add(screen)
        db.session.commit()
        return screen, True

    @classmethod
    def get_all_online(cls):
        """
        Get all screens with online status.

        Returns:
            list: List of Screen instances with status='online'
        """
        return cls.query.filter_by(status='online').all()

    @classmethod
    def get_all_offline(cls):
        """
        Get all screens with offline status.

        Returns:
            list: List of Screen instances with status='offline'
        """
        return cls.query.filter_by(status='offline').all()

    def __repr__(self):
        """String representation."""
        return f"<Screen id={self.id} hardware_id={self.hardware_id} status={self.status}>"
