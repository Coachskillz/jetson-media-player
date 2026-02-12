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
    hub_code = db.Column(db.String(4), nullable=True)  # 2-4 uppercase letters (e.g., WM, HON)
    hub_name = db.Column(db.String(200), nullable=True)
    hub_token = db.Column(db.String(256), nullable=True)
    network_id = db.Column(db.String(64), nullable=True)
    store_id = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, active, inactive
    registered_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Store information (populated during pairing)
    store_address = db.Column(db.String(300), nullable=True)
    store_city = db.Column(db.String(100), nullable=True)
    store_state = db.Column(db.String(50), nullable=True)
    store_zipcode = db.Column(db.String(20), nullable=True)
    manager_name = db.Column(db.String(200), nullable=True)
    store_phone = db.Column(db.String(30), nullable=True)

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
            'hub_code': self.hub_code,
            'hub_name': self.hub_name,
            'network_id': self.network_id,
            'store_id': self.store_id,
            'status': self.status,
            'registered_at': self.registered_at.isoformat() if self.registered_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            # Store info
            'store_address': self.store_address,
            'store_city': self.store_city,
            'store_state': self.store_state,
            'store_zipcode': self.store_zipcode,
            'manager_name': self.manager_name,
            'store_phone': self.store_phone,
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
    def update_registration(cls, hub_id, hub_token, hub_code=None, hub_name=None,
                            network_id=None, store_id=None, status='pending',
                            store_address=None, store_city=None, store_state=None,
                            store_zipcode=None, manager_name=None, store_phone=None):
        """
        Update hub registration data from CMS response.

        Args:
            hub_id: Hub identifier from CMS (UUID)
            hub_token: Authentication token (api_token) from CMS
            hub_code: Hub code (2-4 uppercase letters)
            hub_name: Hub display name
            network_id: Network identifier
            store_id: Optional store identifier
            status: Hub status (pending, active, inactive)
            store_address: Store street address
            store_city: Store city
            store_state: Store state
            store_zipcode: Store ZIP code
            manager_name: Store manager name
            store_phone: Store phone number

        Returns:
            HubConfig: Updated config instance
        """
        config = cls.get_instance()
        config.hub_id = hub_id
        config.hub_code = hub_code
        config.hub_name = hub_name
        config.hub_token = hub_token
        config.network_id = network_id
        config.store_id = store_id
        config.status = status
        config.registered_at = datetime.utcnow()
        # Store info
        config.store_address = store_address
        config.store_city = store_city
        config.store_state = store_state
        config.store_zipcode = store_zipcode
        config.manager_name = manager_name
        config.store_phone = store_phone
        db.session.commit()
        return config

    @classmethod
    def reset_registration(cls):
        """
        Clear hub registration to force re-pairing.

        This clears the hub_id and hub_token so the hub will
        go through the pairing flow again on next startup.

        Returns:
            HubConfig: The reset config instance
        """
        config = cls.get_instance()
        config.hub_id = None
        config.hub_token = None
        config.hub_code = None
        config.hub_name = None
        config.network_id = None
        config.store_id = None
        config.status = 'pending'
        config.registered_at = None
        # Clear store info
        config.store_address = None
        config.store_city = None
        config.store_state = None
        config.store_zipcode = None
        config.manager_name = None
        config.store_phone = None
        db.session.commit()
        return config

    def __repr__(self):
        """String representation."""
        return f"<HubConfig hub_id={self.hub_id} registered={self.is_registered}>"
