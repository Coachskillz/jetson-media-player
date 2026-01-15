"""
HubConfig database model for storing hub registration data.

This model persists the hub's identity and authentication credentials
obtained during registration with HQ. It stores:
- hub_id: Unique identifier assigned by HQ
- hub_token: Authentication token for HQ API calls
- network_id: Network this hub belongs to
- store_id: Store location identifier

The hub should have exactly one HubConfig record after successful registration.
"""

from datetime import datetime
from models import db


class HubConfig(db.Model):
    """
    Database model for hub registration and identity data.

    This model stores credentials obtained from HQ during registration.
    There should be exactly one record in this table at any time.

    Attributes:
        id: Primary key
        hub_id: Unique hub identifier from HQ
        hub_token: Authentication token for HQ API
        network_id: Network identifier from HQ
        store_id: Store location identifier from HQ
        registered_at: Timestamp when hub was registered
        updated_at: Timestamp of last update
    """
    __tablename__ = 'hub_config'

    id = db.Column(db.Integer, primary_key=True)
    hub_id = db.Column(db.String(64), unique=True, nullable=True)
    hub_token = db.Column(db.String(256), nullable=True)
    network_id = db.Column(db.String(64), nullable=True)
    store_id = db.Column(db.String(64), nullable=True)
    registered_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """
        Serialize model to dictionary for JSON responses.

        Note: hub_token is intentionally excluded for security.

        Returns:
            dict: Model data without sensitive token
        """
        return {
            'id': self.id,
            'hub_id': self.hub_id,
            'network_id': self.network_id,
            'store_id': self.store_id,
            'registered_at': self.registered_at.isoformat() if self.registered_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    @property
    def is_registered(self):
        """
        Check if hub has valid registration credentials.

        Returns:
            bool: True if hub_id and hub_token are present
        """
        return bool(self.hub_id and self.hub_token)

    @classmethod
    def get_instance(cls):
        """
        Get the singleton HubConfig instance, creating if needed.

        Returns:
            HubConfig: The hub configuration instance
        """
        config = cls.query.first()
        if config is None:
            config = cls()
            db.session.add(config)
            db.session.commit()
        return config

    @classmethod
    def update_registration(cls, hub_id, hub_token, network_id=None, store_id=None):
        """
        Update hub registration data from HQ response.

        Args:
            hub_id: Hub identifier from HQ
            hub_token: Authentication token from HQ
            network_id: Optional network identifier
            store_id: Optional store identifier

        Returns:
            HubConfig: Updated config instance
        """
        config = cls.get_instance()
        config.hub_id = hub_id
        config.hub_token = hub_token
        config.network_id = network_id
        config.store_id = store_id
        config.registered_at = datetime.utcnow()
        db.session.commit()
        return config

    def __repr__(self):
        """String representation."""
        return f"<HubConfig hub_id={self.hub_id} registered={self.is_registered}>"
