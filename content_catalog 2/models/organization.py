"""
Organization Model for Content Catalog Service.

Represents a partner company, advertiser, or internal organization that
manages content and users within the Content Catalog system.
"""

import json
import secrets
from datetime import datetime, timezone

from content_catalog.models import db


class Organization(db.Model):
    """
    SQLAlchemy model representing an organization.

    Organizations are the top-level entity for multi-tenancy:
    - Partners and advertisers belong to organizations
    - Content assets are scoped to organizations
    - API keys authenticate external system integrations

    Organization Types (legacy):
        - 'internal': Skillz Media internal organization
        - 'partner': External partner company
        - 'advertiser': Advertising company

    Org Type Values (Thea Catalog):
        - 'SKILLZ': Skillz Media internal - can see all assets
        - 'RETAILER': Retailer organization - can see tenant assets (non-internal)
        - 'BRAND': Brand organization - can see own assets only
        - 'AGENCY': Agency organization - can see allowed brand assets

    Status Values:
        - 'active': Organization is active and operational
        - 'pending': Awaiting approval
        - 'suspended': Temporarily suspended
        - 'deactivated': Permanently deactivated

    Attributes:
        id: Unique integer identifier
        name: Human-readable organization name
        type: Organization type (internal, partner, advertiser) - legacy field
        org_type: Thea organization type (SKILLZ, RETAILER, BRAND, AGENCY)
        allowed_brand_ids: JSON array of brand org IDs that agencies can access
        logo_url: URL to organization's logo image
        contact_email: Primary contact email for the organization
        zoho_account_id: External reference to ZOHO CRM account
        api_key: Unique API key for external system authentication
        status: Current organization status
        created_by: User ID who created this organization
        approved_by: User ID who approved this organization
        approved_at: Timestamp when organization was approved
        created_at: Timestamp when organization was created
    """

    __tablename__ = 'organizations'

    # Org type constants for Thea visibility rules
    ORG_TYPE_SKILLZ = 'SKILLZ'
    ORG_TYPE_RETAILER = 'RETAILER'
    ORG_TYPE_BRAND = 'BRAND'
    ORG_TYPE_AGENCY = 'AGENCY'

    VALID_ORG_TYPES = [
        ORG_TYPE_SKILLZ,
        ORG_TYPE_RETAILER,
        ORG_TYPE_BRAND,
        ORG_TYPE_AGENCY
    ]

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # 'internal', 'partner', 'advertiser' (legacy)
    org_type = db.Column(db.String(50), nullable=True, index=True)  # Thea: SKILLZ, RETAILER, BRAND, AGENCY
    allowed_brand_ids = db.Column(db.Text, nullable=True)  # JSON array of brand org IDs (for agencies)
    logo_url = db.Column(db.String(500), nullable=True)
    contact_email = db.Column(db.String(255), nullable=True)
    zoho_account_id = db.Column(db.String(100), nullable=True)
    api_key = db.Column(db.String(255), unique=True, nullable=True, index=True)
    status = db.Column(db.String(50), default='active', nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships will be added as other models are created
    # users = db.relationship('User', back_populates='organization',
    #                         foreign_keys='User.organization_id', lazy='dynamic')
    # content_assets = db.relationship('ContentAsset', back_populates='organization', lazy='dynamic')

    # Relationships for created_by and approved_by
    # creator = db.relationship('User', foreign_keys=[created_by], backref='created_organizations')
    # approver = db.relationship('User', foreign_keys=[approved_by], backref='approved_organizations')

    def to_dict(self, include_api_key=False):
        """
        Serialize the organization to a dictionary for API responses.

        Args:
            include_api_key: If True, includes the api_key in response (default False)

        Returns:
            Dictionary containing all organization fields (excluding sensitive data by default)
        """
        result = {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'org_type': self.org_type,
            'allowed_brand_ids': self.get_allowed_brand_ids(),
            'logo_url': self.logo_url,
            'contact_email': self.contact_email,
            'zoho_account_id': self.zoho_account_id,
            'has_api_key': self.api_key is not None,
            'status': self.status,
            'created_by': self.created_by,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        if include_api_key and self.api_key:
            result['api_key'] = self.api_key
        return result

    def generate_api_key(self):
        """
        Generate a new secure random API key for this organization.

        Uses secrets.token_urlsafe(32) which generates a 43-character
        URL-safe base64-encoded string suitable for API authentication.

        Returns:
            The newly generated API key string
        """
        self.api_key = secrets.token_urlsafe(32)
        return self.api_key

    def get_allowed_brand_ids(self):
        """
        Get the list of allowed brand IDs for agency organizations.

        Parses the JSON-encoded allowed_brand_ids field.

        Returns:
            list: List of integer brand organization IDs, or empty list if not set
        """
        if not self.allowed_brand_ids:
            return []
        try:
            return json.loads(self.allowed_brand_ids)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_allowed_brand_ids(self, brand_ids):
        """
        Set the list of allowed brand IDs for agency organizations.

        Args:
            brand_ids: List of integer brand organization IDs

        Returns:
            None
        """
        if brand_ids is None:
            self.allowed_brand_ids = None
        else:
            self.allowed_brand_ids = json.dumps(brand_ids)

    def add_allowed_brand_id(self, brand_id):
        """
        Add a brand ID to the allowed brands list.

        Args:
            brand_id: Integer brand organization ID to add

        Returns:
            bool: True if brand was added, False if already present
        """
        current_ids = self.get_allowed_brand_ids()
        if brand_id not in current_ids:
            current_ids.append(brand_id)
            self.set_allowed_brand_ids(current_ids)
            return True
        return False

    def remove_allowed_brand_id(self, brand_id):
        """
        Remove a brand ID from the allowed brands list.

        Args:
            brand_id: Integer brand organization ID to remove

        Returns:
            bool: True if brand was removed, False if not present
        """
        current_ids = self.get_allowed_brand_ids()
        if brand_id in current_ids:
            current_ids.remove(brand_id)
            self.set_allowed_brand_ids(current_ids)
            return True
        return False

    def can_access_brand(self, brand_org_id):
        """
        Check if this organization can access assets from a brand.

        Agency organizations can only access brands in their allowed list.
        SKILLZ organizations can access all brands.
        RETAILER organizations follow tenant rules (checked elsewhere).
        BRAND organizations can only access their own assets.

        Args:
            brand_org_id: Integer brand organization ID to check access for

        Returns:
            bool: True if organization can access the brand's assets
        """
        if self.org_type == self.ORG_TYPE_SKILLZ:
            return True
        if self.org_type == self.ORG_TYPE_AGENCY:
            return brand_org_id in self.get_allowed_brand_ids()
        if self.org_type == self.ORG_TYPE_BRAND:
            return brand_org_id == self.id
        # RETAILER visibility is handled by tenant rules
        return False

    @property
    def is_skillz(self):
        """Check if organization is Skillz Media internal."""
        return self.org_type == self.ORG_TYPE_SKILLZ

    @property
    def is_retailer(self):
        """Check if organization is a retailer."""
        return self.org_type == self.ORG_TYPE_RETAILER

    @property
    def is_brand(self):
        """Check if organization is a brand."""
        return self.org_type == self.ORG_TYPE_BRAND

    @property
    def is_agency(self):
        """Check if organization is an agency."""
        return self.org_type == self.ORG_TYPE_AGENCY

    @classmethod
    def get_by_org_type(cls, org_type):
        """
        Get all organizations of a specific org type.

        Args:
            org_type: The org type to filter by (SKILLZ, RETAILER, BRAND, AGENCY)

        Returns:
            list: List of Organization instances matching the org type
        """
        return cls.query.filter_by(org_type=org_type, status='active').all()

    def __repr__(self):
        """String representation for debugging."""
        return f'<Organization {self.name}>'
