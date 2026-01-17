"""
Organization Model for Content Catalog Service.

Represents a partner company, advertiser, or internal organization that
manages content and users within the Content Catalog system.
"""

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

    Organization Types:
        - 'internal': Skillz Media internal organization
        - 'partner': External partner company
        - 'advertiser': Advertising company

    Status Values:
        - 'active': Organization is active and operational
        - 'pending': Awaiting approval
        - 'suspended': Temporarily suspended
        - 'deactivated': Permanently deactivated

    Attributes:
        id: Unique integer identifier
        name: Human-readable organization name
        type: Organization type (internal, partner, advertiser)
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

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # 'internal', 'partner', 'advertiser'
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

    def __repr__(self):
        """String representation for debugging."""
        return f'<Organization {self.name}>'
