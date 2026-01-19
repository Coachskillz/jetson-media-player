"""
Visibility Service for Content Catalog.

Provides visibility filtering for multi-tenant content access. Implements
asset visibility rules based on user organization type:
- Skillz: See all assets (including internal-only)
- Retailer: See all assets in tenant (except internal-only)
- Brand: See only own brand's assets
- Agency: See assets for allowed brands they represent

Key features:
- Multi-tenant access control via User.tenant_ids
- Org-type based visibility rules (SKILLZ/RETAILER/BRAND/AGENCY)
- Fast-track permission checking for privileged users
- Query filtering for assets based on user visibility
"""

from typing import Any, Dict, List, Optional, Tuple
import json

from sqlalchemy import or_, and_

from content_catalog.models import db, ContentAsset, User, Organization, Catalog


class VisibilityService:
    """
    Service for filtering assets based on user visibility permissions.

    This service handles:
    1. Determining which tenants a user can access via User.tenant_ids
    2. Applying org-type based visibility rules for asset access
    3. Filtering queries based on user visibility permissions
    4. Fast-track permission checking for privileged users

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

    @classmethod
    def _get_user_tenant_ids(cls, db_session, user_id: int) -> List[int]:
        """
        Get the list of tenant IDs a user has access to.

        This method retrieves tenant access from the User.tenant_ids field,
        which is a JSON array of tenant IDs the user belongs to.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user to check

        Returns:
            List of tenant IDs the user can access, or empty list if none
        """
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return []

        if hasattr(user, 'get_tenant_ids_list'):
            return user.get_tenant_ids_list()

        if hasattr(user, 'tenant_ids') and user.tenant_ids:
            if isinstance(user.tenant_ids, str):
                try:
                    return json.loads(user.tenant_ids)
                except json.JSONDecodeError:
                    return []
            return user.tenant_ids
        return []

    @classmethod
    def _get_user_organization(cls, db_session, user_id: int) -> Optional[Organization]:
        """
        Get the organization for a user.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user

        Returns:
            Organization instance or None if user has no organization
        """
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None or not hasattr(user, 'organization'):
            return None

        return user.organization

    @classmethod
    def _get_user_org_type(cls, db_session, user_id: int) -> Optional[str]:
        """
        Get the org_type for a user's organization.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user

        Returns:
            Org type string (SKILLZ, RETAILER, BRAND, AGENCY) or None
        """
        org = cls._get_user_organization(db_session, user_id)
        if org is None:
            return None
        return getattr(org, 'org_type', None)

    @classmethod
    def _is_skillz_user(cls, db_session, user_id: int) -> bool:
        """
        Check if user belongs to a SKILLZ organization.

        SKILLZ users have full visibility across all tenants and assets.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user

        Returns:
            True if user is a SKILLZ user, False otherwise
        """
        org_type = cls._get_user_org_type(db_session, user_id)
        return org_type == cls.ORG_TYPE_SKILLZ

    @classmethod
    def _is_super_admin(cls, db_session, user_id: int) -> bool:
        """
        Check if user is a super admin.

        Super admins have full visibility regardless of org type.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user

        Returns:
            True if user is a super admin, False otherwise
        """
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return False
        if hasattr(user, 'role'):
            return user.role in ('super_admin', 'admin')
        return False

    @classmethod
    def has_tenant_access(cls, db_session, user_id: int, tenant_id: int) -> bool:
        """
        Check if a user has access to a specific tenant.

        Access is granted if:
        1. User is a SKILLZ user or super admin (full access)
        2. Tenant ID is in the user's tenant_ids list

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user
            tenant_id: ID of the tenant to check

        Returns:
            True if user has access to the tenant, False otherwise
        """
        # Super admins and SKILLZ users have full access
        if cls._is_super_admin(db_session, user_id) or cls._is_skillz_user(db_session, user_id):
            return True

        # Check if tenant is in user's tenant_ids
        user_tenant_ids = cls._get_user_tenant_ids(db_session, user_id)
        return tenant_id in user_tenant_ids

    @classmethod
    def can_view_asset_by_id(
        cls,
        db_session,
        user_id: int,
        asset_id: int
    ) -> Tuple[bool, str]:
        """
        Check if a user can view a specific content asset.

        Visibility rules:
        1. Super admins and SKILLZ users can see all assets
        2. RETAILER users can see assets within their tenants (non-internal)
        3. BRAND users can only see their own organization's assets
        4. AGENCY users can see assets from brands in allowed_brand_ids

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user
            asset_id: ID of the content asset

        Returns:
            Tuple of (can_view: bool, reason: str)
            - If can_view is True, reason will be 'ok'
            - If can_view is False, reason explains why
        """
        # Fetch user
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return False, 'User not found'

        # Fetch asset
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return False, 'Asset not found'

        # Super admins can see everything
        if hasattr(user, 'role') and user.role in ('super_admin', 'admin'):
            return True, 'ok'

        # Get user's organization
        org = cls._get_user_organization(db_session, user_id)

        # If user has no organization, they can only see their own uploads
        if org is None:
            if asset.uploaded_by == user_id:
                return True, 'ok'
            return False, 'User has no organization and is not the uploader'

        # SKILLZ users can see all assets
        if getattr(org, 'org_type', None) == cls.ORG_TYPE_SKILLZ:
            return True, 'ok'

        # BRAND users can only see their own organization's assets
        if getattr(org, 'org_type', None) == cls.ORG_TYPE_BRAND:
            if asset.organization_id == org.id:
                return True, 'ok'
            return False, 'Brand users can only view their own assets'

        # AGENCY users can see assets from allowed brands
        if getattr(org, 'org_type', None) == cls.ORG_TYPE_AGENCY:
            if asset.organization_id == org.id:
                return True, 'ok'
            if hasattr(org, 'can_access_brand') and org.can_access_brand(asset.organization_id):
                return True, 'ok'
            if hasattr(org, 'allowed_brand_ids') and asset.organization_id in (org.allowed_brand_ids or []):
                return True, 'ok'
            return False, 'Agency does not have access to this brand\'s assets'

        # RETAILER users can see tenant assets (non-internal)
        if getattr(org, 'org_type', None) == cls.ORG_TYPE_RETAILER:
            # Check if asset is in an internal-only catalog
            if hasattr(asset, 'catalog') and asset.catalog and hasattr(asset.catalog, 'is_internal_only'):
                if asset.catalog.is_internal_only:
                    return False, 'Retailer cannot view internal-only assets'
            # Check user has access to any tenant
            user_tenant_ids = cls._get_user_tenant_ids(db_session, user_id)
            if not user_tenant_ids:
                # Fall back to organization-based check
                if asset.organization_id == org.id:
                    return True, 'ok'
                return False, 'Retailer user has no tenant access'
            # Retailers can see assets within their tenant scope
            return True, 'ok'

        return False, 'Unknown org type'

    @classmethod
    def filter_assets_for_user(
        cls,
        db_session,
        user_id: int,
        query=None,
        include_drafts: bool = False
    ) -> list:
        """
        Filter a content asset query to only show assets visible to the user.

        Applies org-type based visibility rules to filter the query results.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user
            query: Optional SQLAlchemy query to filter (defaults to ContentAsset.query)
            include_drafts: If True, include draft assets (default False)

        Returns:
            List of ContentAsset instances visible to the user
        """
        if query is None:
            query = db_session.query(ContentAsset)

        # Fetch user
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return []

        # Filter by status (exclude drafts by default)
        if not include_drafts and hasattr(ContentAsset, 'STATUS_DRAFT'):
            query = query.filter(ContentAsset.status != ContentAsset.STATUS_DRAFT)

        # Super admins see everything
        if hasattr(user, 'role') and user.role in ('super_admin', 'admin'):
            return query.all()

        # Get user's organization
        org = cls._get_user_organization(db_session, user_id)

        if org is None:
            # User without organization can only see their own uploads
            return query.filter(ContentAsset.uploaded_by == user_id).all()

        org_type = getattr(org, 'org_type', None)

        # SKILLZ users see all assets
        if org_type == cls.ORG_TYPE_SKILLZ:
            return query.all()

        # BRAND users see only their organization's assets
        if org_type == cls.ORG_TYPE_BRAND:
            return query.filter(ContentAsset.organization_id == org.id).all()

        # AGENCY users see their own + allowed brands
        if org_type == cls.ORG_TYPE_AGENCY:
            allowed_brand_ids = getattr(org, 'allowed_brand_ids', [])
            if isinstance(allowed_brand_ids, str):
                try:
                    allowed_brand_ids = json.loads(allowed_brand_ids)
                except json.JSONDecodeError:
                    allowed_brand_ids = []
            if hasattr(org, 'get_allowed_brand_ids'):
                allowed_brand_ids = org.get_allowed_brand_ids()
            allowed_org_ids = [org.id] + (allowed_brand_ids or [])
            return query.filter(ContentAsset.organization_id.in_(allowed_org_ids)).all()

        # RETAILER users see tenant assets
        if org_type == cls.ORG_TYPE_RETAILER:
            # Filter out internal-only catalogs
            query = query.join(
                Catalog, ContentAsset.catalog_id == Catalog.id, isouter=True
            ).filter(
                or_(
                    Catalog.is_internal_only == False,
                    Catalog.is_internal_only.is_(None),
                    ContentAsset.catalog_id.is_(None)
                )
            )
            user_tenant_ids = cls._get_user_tenant_ids(db_session, user_id)
            if not user_tenant_ids:
                # Fall back to organization-based filtering
                return query.filter(ContentAsset.organization_id == org.id).all()
            # For now, retailers see their organization's assets
            # TODO: Add tenant_id filtering when tenant_id is added to ContentAsset
            return query.filter(ContentAsset.organization_id == org.id).all()

        # Default: only own uploads
        return query.filter(ContentAsset.uploaded_by == user_id).all()

    @classmethod
    def get_visible_organization_ids(
        cls,
        db_session,
        user_id: int
    ) -> List[int]:
        """
        Get list of organization IDs whose assets are visible to the user.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user

        Returns:
            List of organization IDs the user can see assets from
        """
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return []

        # Super admins and SKILLZ users see all organizations
        if hasattr(user, 'role') and user.role in ('super_admin', 'admin'):
            orgs = db_session.query(Organization).filter(
                or_(
                    getattr(Organization, 'status', None) == 'active',
                    ~hasattr(Organization, 'status')
                )
            ).all()
            return [o.id for o in orgs]

        org = cls._get_user_organization(db_session, user_id)
        if org is None:
            return []

        org_type = getattr(org, 'org_type', None)

        if org_type == cls.ORG_TYPE_SKILLZ:
            orgs = db_session.query(Organization).filter(
                or_(
                    getattr(Organization, 'status', None) == 'active',
                    ~hasattr(Organization, 'status')
                )
            ).all()
            return [o.id for o in orgs]

        if org_type == cls.ORG_TYPE_BRAND:
            return [org.id]

        if org_type == cls.ORG_TYPE_AGENCY:
            allowed_brand_ids = getattr(org, 'allowed_brand_ids', [])
            if isinstance(allowed_brand_ids, str):
                try:
                    allowed_brand_ids = json.loads(allowed_brand_ids)
                except json.JSONDecodeError:
                    allowed_brand_ids = []
            if hasattr(org, 'get_allowed_brand_ids'):
                allowed_brand_ids = org.get_allowed_brand_ids()
            return [org.id] + (allowed_brand_ids or [])

        if org_type == cls.ORG_TYPE_RETAILER:
            # Retailers see their own org for now
            # TODO: Expand based on tenant memberships
            return [org.id]

        return [org.id]

    @classmethod
    def can_access_catalog(
        cls,
        db_session,
        user_id: int,
        catalog_id: int
    ) -> Tuple[bool, str]:
        """
        Check if a user can access a specific catalog.

        Access is granted if:
        1. User is a super admin or SKILLZ user
        2. Catalog ID is in user's allowed_catalog_ids (if set)
        3. Catalog belongs to user's organization

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user
            catalog_id: ID of the catalog

        Returns:
            Tuple of (can_access: bool, reason: str)
        """
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return False, 'User not found'

        # Super admins have full access
        if hasattr(user, 'role') and user.role in ('super_admin', 'admin'):
            return True, 'ok'

        # SKILLZ users have full access
        if cls._is_skillz_user(db_session, user_id):
            return True, 'ok'

        # Check allowed_catalog_ids if set
        if hasattr(user, 'get_allowed_catalog_ids_list'):
            allowed_catalogs = user.get_allowed_catalog_ids_list()
        elif hasattr(user, 'allowed_catalog_ids'):
            allowed_catalogs = user.allowed_catalog_ids
            if isinstance(allowed_catalogs, str):
                try:
                    allowed_catalogs = json.loads(allowed_catalogs)
                except json.JSONDecodeError:
                    allowed_catalogs = []
        else:
            allowed_catalogs = None

        if allowed_catalogs:
            if catalog_id in allowed_catalogs:
                return True, 'ok'
            return False, 'Catalog not in allowed list'

        # If no explicit catalog restrictions, allow access
        return True, 'ok'

    @classmethod
    def can_access_category(
        cls,
        db_session,
        user_id: int,
        category_id: int
    ) -> Tuple[bool, str]:
        """
        Check if a user can access a specific category.

        Access is granted if:
        1. User is a super admin or SKILLZ user
        2. Category is in user's allowed_category_ids (if set)

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user
            category_id: ID of the category

        Returns:
            Tuple of (can_access: bool, reason: str)
        """
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return False, 'User not found'

        # Super admins have full access
        if hasattr(user, 'role') and user.role in ('super_admin', 'admin'):
            return True, 'ok'

        # SKILLZ users have full access
        if cls._is_skillz_user(db_session, user_id):
            return True, 'ok'

        # Check allowed_category_ids if set
        if hasattr(user, 'get_allowed_category_ids_list'):
            allowed_categories = user.get_allowed_category_ids_list()
        elif hasattr(user, 'allowed_category_ids'):
            allowed_categories = user.allowed_category_ids
            if isinstance(allowed_categories, str):
                try:
                    allowed_categories = json.loads(allowed_categories)
                except json.JSONDecodeError:
                    allowed_categories = []
        else:
            allowed_categories = None

        if allowed_categories:
            if category_id in allowed_categories:
                return True, 'ok'
            return False, 'Category not in allowed list'

        # If no explicit category restrictions, allow access
        return True, 'ok'


def get_visibility_service(user: User) -> VisibilityService:
    """
    Factory function to get a visibility service for a user.

    Args:
        user: The user to create service for

    Returns:
        VisibilityService instance
    """
    return VisibilityService(user)