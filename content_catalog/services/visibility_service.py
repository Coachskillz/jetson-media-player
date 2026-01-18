"""
Visibility Service for Content Catalog.

Implements asset visibility rules based on user organization type:
- Skillz: See all assets (including internal-only)
- Retailer: See all assets in tenant (except internal-only)
- Brand: See only own brand's assets
- Agency: See assets for allowed brands they represent
"""

from typing import List, Optional
from sqlalchemy import or_, and_

from content_catalog.models import db, ContentAsset, User, Organization, Catalog


class VisibilityService:
    """
    Service for filtering assets based on user visibility permissions.

    Visibility rules:
    1. SKILLZ users can see everything (including internal-only catalogs)
    2. RETAILER users can see all tenant assets except internal-only
    3. BRAND users can only see their own brand's assets
    4. AGENCY users can see assets for brands they represent
    """

    # Organization type constants
    ORG_TYPE_SKILLZ = 'SKILLZ'
    ORG_TYPE_RETAILER = 'RETAILER'
    ORG_TYPE_BRAND = 'BRAND'
    ORG_TYPE_AGENCY = 'AGENCY'

    def __init__(self, user: User):
        """
        Initialize visibility service for a user.

        Args:
            user: The user to check visibility for
        """
        self.user = user
        self.organization = user.organization if hasattr(user, 'organization') else None
        self.org_type = self._get_org_type()
        self.tenant_ids = self._get_user_tenant_ids()
        self.allowed_brand_ids = self._get_allowed_brand_ids()

    def _get_org_type(self) -> Optional[str]:
        """Get the organization type for the user."""
        if self.organization:
            return getattr(self.organization, 'org_type', None)
        # Check user role for Skillz staff
        if hasattr(self.user, 'role'):
            if self.user.role in ('super_admin', 'admin', 'content_manager'):
                return self.ORG_TYPE_SKILLZ
        return None

    def _get_user_tenant_ids(self) -> List[str]:
        """Get list of tenant IDs the user has access to."""
        if hasattr(self.user, 'tenant_ids') and self.user.tenant_ids:
            # tenant_ids might be stored as JSON string
            if isinstance(self.user.tenant_ids, str):
                import json
                try:
                    return json.loads(self.user.tenant_ids)
                except json.JSONDecodeError:
                    return []
            return self.user.tenant_ids
        return []

    def _get_allowed_brand_ids(self) -> List[int]:
        """Get list of brand IDs an agency user can see."""
        if self.organization and hasattr(self.organization, 'allowed_brand_ids'):
            brand_ids = self.organization.allowed_brand_ids
            if brand_ids:
                if isinstance(brand_ids, str):
                    import json
                    try:
                        return json.loads(brand_ids)
                    except json.JSONDecodeError:
                        return []
                return brand_ids
        return []

    def is_skillz_user(self) -> bool:
        """Check if user is a Skillz staff member."""
        return self.org_type == self.ORG_TYPE_SKILLZ

    def is_retailer_user(self) -> bool:
        """Check if user is a retailer user."""
        return self.org_type == self.ORG_TYPE_RETAILER

    def is_brand_user(self) -> bool:
        """Check if user is a brand user."""
        return self.org_type == self.ORG_TYPE_BRAND

    def is_agency_user(self) -> bool:
        """Check if user is an agency user."""
        return self.org_type == self.ORG_TYPE_AGENCY

    def get_visible_assets_query(self, base_query=None):
        """
        Get a query for assets visible to this user.

        Args:
            base_query: Optional base query to filter (defaults to ContentAsset.query)

        Returns:
            SQLAlchemy query with visibility filters applied
        """
        if base_query is None:
            base_query = ContentAsset.query

        # Skillz users see everything
        if self.is_skillz_user():
            return base_query

        # Retailer users see tenant assets except internal-only
        if self.is_retailer_user():
            if self.tenant_ids:
                # Join with catalog to check internal_only flag
                return base_query.join(
                    Catalog, ContentAsset.catalog_id == Catalog.id, isouter=True
                ).filter(
                    ContentAsset.tenant_id.in_(self.tenant_ids),
                    or_(
                        Catalog.is_internal_only == False,
                        Catalog.is_internal_only.is_(None),
                        ContentAsset.catalog_id.is_(None)
                    )
                )
            return base_query.filter(False)  # No tenants = no access

        # Brand users see only their own assets
        if self.is_brand_user():
            if self.organization:
                return base_query.filter(
                    ContentAsset.organization_id == self.organization.id
                )
            return base_query.filter(False)  # No org = no access

        # Agency users see assets for their allowed brands
        if self.is_agency_user():
            if self.allowed_brand_ids:
                return base_query.filter(
                    ContentAsset.organization_id.in_(self.allowed_brand_ids)
                )
            return base_query.filter(False)  # No allowed brands = no access

        # Unknown org type - no access
        return base_query.filter(False)

    def can_view_asset(self, asset: ContentAsset) -> bool:
        """
        Check if user can view a specific asset.

        Args:
            asset: The asset to check

        Returns:
            True if user can view the asset
        """
        # Skillz users see everything
        if self.is_skillz_user():
            return True

        # Retailer users
        if self.is_retailer_user():
            # Must be in user's tenant
            if asset.tenant_id not in self.tenant_ids:
                return False
            # Cannot see internal-only catalogs
            if asset.catalog and asset.catalog.is_internal_only:
                return False
            return True

        # Brand users
        if self.is_brand_user():
            if self.organization:
                return asset.organization_id == self.organization.id
            return False

        # Agency users
        if self.is_agency_user():
            return asset.organization_id in self.allowed_brand_ids

        return False

    def can_edit_asset(self, asset: ContentAsset) -> bool:
        """
        Check if user can edit a specific asset.

        Args:
            asset: The asset to check

        Returns:
            True if user can edit the asset
        """
        # Skillz admins can edit anything
        if self.is_skillz_user():
            return True

        # Others can only edit if they uploaded it or own the org
        if asset.uploaded_by == self.user.id:
            return True

        if self.organization and asset.organization_id == self.organization.id:
            # Check if user has edit permissions for their org
            if hasattr(self.user, 'role'):
                return self.user.role in ('admin', 'content_manager', 'partner')

        return False

    def can_approve_asset(self, asset: ContentAsset) -> bool:
        """
        Check if user can approve a specific asset.

        Rules:
        1. User must have approval permission
        2. User cannot approve their own uploads (separation of duties)

        Args:
            asset: The asset to check

        Returns:
            True if user can approve the asset
        """
        # Cannot approve own uploads
        if asset.uploaded_by == self.user.id:
            return False

        # Must have approval permission
        if not getattr(self.user, 'can_approve_assets', False):
            return False

        # Must be able to view the asset
        if not self.can_view_asset(asset):
            return False

        return True


def get_visibility_service(user: User) -> VisibilityService:
    """
    Factory function to get a visibility service for a user.

    Args:
        user: The user to create service for

    Returns:
        VisibilityService instance
    """
    return VisibilityService(user)
