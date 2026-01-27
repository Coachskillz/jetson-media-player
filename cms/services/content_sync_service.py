"""
Content Sync Service for CMS.

Provides content synchronization from the Content Catalog service including:
- Fetching approved/published content via REST API
- Caching content metadata in SyncedContent model
- Network-based filtering for multi-tenant content isolation
- Handling Content Catalog unavailability gracefully

This service enables the CMS to display content from the Content Catalog
without requiring direct upload capability. All content management happens
in the Content Catalog/Partner Portal.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

from flask import current_app
from cms.models import db
from cms.models.synced_content import SyncedContent
from cms.models.network import Network


# Configure logging
logger = logging.getLogger(__name__)


class ContentSyncError(Exception):
    """Base exception for content sync errors."""
    pass


class ContentCatalogUnavailableError(ContentSyncError):
    """Raised when Content Catalog service is unavailable."""
    pass


class ContentSyncService:
    """
    Service class for syncing content from Content Catalog.

    This service provides methods to fetch approved content from the
    Content Catalog API and cache it locally in the SyncedContent table.
    All methods use class methods following the CMS service pattern.

    The service handles:
    - API communication with Content Catalog
    - Pagination for large content sets
    - Network filtering for multi-tenant isolation
    - Graceful handling of Content Catalog unavailability
    - Upsert logic to avoid duplicate entries
    """

    # Default Content Catalog URL (can be overridden by environment variable)
    CONTENT_CATALOG_URL = os.environ.get('CONTENT_CATALOG_URL', 'http://localhost:5003')

    # API endpoint path
    APPROVED_CONTENT_ENDPOINT = '/api/v1/approvals/content/approved'

    # Default pagination settings
    DEFAULT_PAGE_SIZE = 100
    MAX_PAGE_SIZE = 500

    # Request timeout settings (in seconds)
    REQUEST_TIMEOUT = 30
    CONNECT_TIMEOUT = 10


    # ==========================================================================
    # Network Sync from Content Catalog
    # ==========================================================================

    # Tenants API endpoint (tenants in Content Catalog = networks in CMS)
    # Use /active endpoint which accepts service API key authentication
    TENANTS_ENDPOINT = '/api/v1/tenants/active'

    @classmethod
    def fetch_tenants(cls) -> List[Dict[str, Any]]:
        """
        Fetch all tenants from Content Catalog.

        Tenants in Content Catalog are equivalent to Networks in CMS.
        This method fetches the tenant list to sync networks.

        Returns:
            List of tenant dictionaries with uuid, name, slug, is_active

        Raises:
            ContentCatalogUnavailableError: If Content Catalog is unreachable
        """
        url = f"{cls.CONTENT_CATALOG_URL}{cls.TENANTS_ENDPOINT}"

        headers = cls._get_auth_headers()

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=(cls.CONNECT_TIMEOUT, cls.REQUEST_TIMEOUT),
            )

            if response.status_code == 200:
                data = response.json()
                # Handle both list response and dict with 'tenants' key
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and 'tenants' in data:
                    return data['tenants']
                else:
                    return []

            elif response.status_code == 401:
                # Try without auth for public endpoint
                response = requests.get(
                    url,
                    timeout=(cls.CONNECT_TIMEOUT, cls.REQUEST_TIMEOUT),
                )
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and 'tenants' in data:
                        return data['tenants']

                logger.warning("Tenants endpoint requires authentication")
                return []

            else:
                logger.error(f"Failed to fetch tenants: {response.status_code}")
                return []

        except (ConnectionError, Timeout) as e:
            raise ContentCatalogUnavailableError(f"Content Catalog unavailable: {str(e)}")
        except RequestException as e:
            logger.error(f"Error fetching tenants: {str(e)}")
            return []

    @classmethod
    def sync_networks(cls) -> Dict[str, Any]:
        """
        Sync networks from Content Catalog tenants.

        Fetches all tenants from Content Catalog and creates/updates
        corresponding Network records in CMS. This ensures CMS networks
        match the Content Catalog's tenant definitions.

        Returns:
            Dictionary containing:
                - synced_count: Number of networks synced
                - created_count: Number of new networks created
                - updated_count: Number of existing networks updated
                - deleted_count: Number of orphan networks deleted
                - networks: List of network names
        """
        logger.info("Starting network sync from Content Catalog tenants")

        result = {
            'synced_count': 0,
            'created_count': 0,
            'updated_count': 0,
            'deleted_count': 0,
            'networks': [],
            'errors': [],
        }

        try:
            tenants = cls.fetch_tenants()

            if not tenants:
                logger.warning("No tenants returned from Content Catalog")
                result['errors'].append("No tenants returned from Content Catalog")
                return result

            tenant_slugs = set()

            for tenant in tenants:
                slug = tenant.get('slug')
                name = tenant.get('name')
                is_active = tenant.get('is_active', True)

                if not slug or not name:
                    continue

                tenant_slugs.add(slug)

                # Skip inactive tenants
                if not is_active:
                    continue

                # Check if network exists
                existing = Network.query.filter_by(slug=slug).first()

                if existing:
                    # Update name if changed
                    if existing.name != name:
                        existing.name = name
                        result['updated_count'] += 1
                        logger.info(f"Updated network: {name} (slug: {slug})")
                else:
                    # Create new network
                    new_network = Network(name=name, slug=slug)
                    db.session.add(new_network)
                    result['created_count'] += 1
                    logger.info(f"Created network: {name} (slug: {slug})")

                result['synced_count'] += 1
                result['networks'].append(name)

            # Remove networks that don't exist in Content Catalog
            for network in Network.query.all():
                if network.slug not in tenant_slugs:
                    logger.info(f"Removing orphan network: {network.name} (slug: {network.slug})")
                    db.session.delete(network)
                    result['deleted_count'] += 1

            db.session.commit()
            logger.info(f"Network sync completed: {result['synced_count']} networks")

        except ContentCatalogUnavailableError as e:
            result['errors'].append(str(e))
            logger.error(f"Network sync failed: {e}")

        except Exception as e:
            result['errors'].append(str(e))
            logger.error(f"Network sync error: {e}")

        return result

    @classmethod
    def _get_auth_headers(cls) -> Dict[str, str]:
        """Get authentication headers for Content Catalog API."""
        api_key = os.environ.get('CONTENT_CATALOG_SERVICE_KEY', 'skillz-cms-service-key-2026')
        return {
            'X-Service-API-Key': api_key,
            'Content-Type': 'application/json',
        }

    # ==========================================================================
    # File Download Operations
    # ==========================================================================

    @classmethod
    def download_asset_file(cls, asset_id, filename, uploads_path):
        """
        Download an asset file from Content Catalog to local CMS storage.

        Args:
            asset_id: Integer ID of the asset in Content Catalog
            filename: Original filename to save as
            uploads_path: Path to CMS uploads directory

        Returns:
            Local file path if successful, None if failed
        """
        if not asset_id:
            logger.warning("No asset_id provided for download")
            return None

        download_url = f"{cls.CONTENT_CATALOG_URL}/api/v1/assets/{asset_id}/download"
        
        try:
            logger.info(f"Downloading asset {asset_id} from {download_url}")
            
            response = requests.get(
                download_url,
                stream=True,
                timeout=(cls.CONNECT_TIMEOUT, 120)
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to download asset {asset_id}: HTTP {response.status_code}")
                return None
            
            os.makedirs(uploads_path, exist_ok=True)
            
            import uuid as uuid_module
            file_ext = os.path.splitext(filename)[1] if filename else ""
            unique_filename = f"{uuid_module.uuid4()}{file_ext}"
            local_path = os.path.join(uploads_path, unique_filename)
            
            with open(local_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"Downloaded asset {asset_id} to {local_path}")
            return local_path
            
        except Timeout:
            logger.error(f"Timeout downloading asset {asset_id}")
            return None
        except ConnectionError:
            logger.error(f"Connection error downloading asset {asset_id}")
            return None
        except Exception as e:
            logger.error(f"Error downloading asset {asset_id}: {str(e)}")
            return None

    # ==========================================================================
    # Core Sync Operations
    # ==========================================================================

    @classmethod
    def sync_approved_content(
        cls,
        network_id: Optional[str] = None,
        organization_id: Optional[int] = None,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Sync all approved content from Content Catalog.

        Fetches all approved/published content from the Content Catalog API
        and upserts it into the SyncedContent table. Handles pagination
        automatically to fetch all matching content.

        Args:
            network_id: Optional network ID to filter content
            organization_id: Optional organization ID to filter content
            category: Optional category to filter content

        Returns:
            Dictionary containing:
                - synced_count: Number of content items synced
                - created_count: Number of new items created
                - updated_count: Number of existing items updated
                - total_in_catalog: Total items available in Content Catalog
                - synced_at: Timestamp of sync completion
                - errors: List of any errors encountered

        Raises:
            ContentCatalogUnavailableError: If Content Catalog is unreachable
        """
        logger.info("Starting content sync from Content Catalog")

        result = {
            'synced_count': 0,
            'created_count': 0,
            'updated_count': 0,
            'total_in_catalog': 0,
            'synced_at': None,
            'errors': [],
        }

        try:
            # Fetch all pages of content
            page = 1
            total_pages = None
            all_assets = []

            while total_pages is None or page <= total_pages:
                response = cls.fetch_approved_content(
                    network_id=network_id,
                    organization_id=organization_id,
                    category=category,
                    page=page,
                    per_page=cls.DEFAULT_PAGE_SIZE,
                )

                assets = response.get('assets', [])
                all_assets.extend(assets)

                # Update pagination info
                result['total_in_catalog'] = response.get('total', len(assets))
                total_pages = response.get('pages', 1)

                page += 1

                # Safety check to prevent infinite loops
                if page > 1000:
                    logger.warning("Exceeded maximum page limit during sync")
                    break

            # Upsert all fetched content
            uploads_path = str(current_app.config.get('UPLOADS_PATH', './uploads'))

            for asset_data in all_assets:
                try:
                    existing = SyncedContent.get_by_source_uuid(asset_data.get('uuid'))
                    
                    # Download file for new content (not existing)
                    local_file_path = None
                    if not existing:
                        asset_id = asset_data.get('id')
                        filename = asset_data.get('filename', 'unknown')
                        local_file_path = cls.download_asset_file(asset_id, filename, uploads_path)
                        
                        if local_file_path:
                            # Update asset_data with local path
                            asset_data['file_path'] = local_file_path
                        else:
                            logger.warning(f"Could not download file for asset {asset_data.get('uuid')}, using remote path")
                    
                    synced = SyncedContent.upsert_from_catalog(
                        db_session=db.session,
                        catalog_data=asset_data,
                        organization_name=asset_data.get('organization_name'),
                        content_catalog_url=cls.CONTENT_CATALOG_URL,
                    )

                    if existing:
                        result['updated_count'] += 1
                    else:
                        result['created_count'] += 1

                    result['synced_count'] += 1

                except Exception as e:
                    error_msg = f"Failed to sync asset {asset_data.get('uuid')}: {str(e)}"
                    logger.error(error_msg)
                    result['errors'].append(error_msg)

            # Commit all changes
            db.session.commit()

            result['synced_at'] = datetime.now(timezone.utc).isoformat()
            logger.info(
                f"Content sync completed: {result['synced_count']} items synced "
                f"({result['created_count']} created, {result['updated_count']} updated)"
            )

        except ContentCatalogUnavailableError:
            raise
        except Exception as e:
            logger.error(f"Content sync failed: {str(e)}")
            db.session.rollback()
            raise ContentSyncError(f"Sync failed: {str(e)}")

        return result

    @classmethod
    def fetch_approved_content(
        cls,
        network_id: Optional[str] = None,
        organization_id: Optional[int] = None,
        category: Optional[str] = None,
        page: int = 1,
        per_page: int = None,
    ) -> Dict[str, Any]:
        """
        Fetch approved content from Content Catalog API.

        Makes a single API request to the Content Catalog service to fetch
        a page of approved/published content.

        Args:
            network_id: Optional network ID to filter content
            organization_id: Optional organization ID to filter content
            category: Optional category to filter content
            page: Page number (1-indexed)
            per_page: Items per page (default: 100)

        Returns:
            Dictionary containing:
                - assets: List of content asset dictionaries
                - count: Number of items in this page
                - total: Total number of matching items
                - page: Current page number
                - pages: Total number of pages

        Raises:
            ContentCatalogUnavailableError: If Content Catalog is unreachable
            ContentSyncError: If the API returns an error
        """
        per_page = per_page or cls.DEFAULT_PAGE_SIZE
        per_page = min(per_page, cls.MAX_PAGE_SIZE)

        # Build request parameters
        params = {
            'page': page,
            'per_page': per_page,
        }

        if network_id:
            params['network_id'] = network_id

        if organization_id:
            params['organization_id'] = organization_id

        if category:
            params['category'] = category

        # Build URL
        url = f"{cls.CONTENT_CATALOG_URL}{cls.APPROVED_CONTENT_ENDPOINT}"

        logger.debug(f"Fetching approved content from {url} with params {params}")

        try:
            response = requests.get(
                url,
                params=params,
                timeout=(cls.CONNECT_TIMEOUT, cls.REQUEST_TIMEOUT),
                headers={"X-Service-API-Key": os.environ.get("CONTENT_CATALOG_SERVICE_KEY", "skillz-cms-service-key-2026")},
            )

            response.raise_for_status()

            data = response.json()
            return data

        except ConnectionError as e:
            logger.error(f"Cannot connect to Content Catalog at {cls.CONTENT_CATALOG_URL}: {e}")
            raise ContentCatalogUnavailableError(
                f"Content Catalog service unavailable at {cls.CONTENT_CATALOG_URL}"
            )

        except Timeout as e:
            logger.error(f"Timeout connecting to Content Catalog: {e}")
            raise ContentCatalogUnavailableError(
                "Content Catalog service timed out"
            )

        except RequestException as e:
            logger.error(f"Request to Content Catalog failed: {e}")
            raise ContentSyncError(f"API request failed: {str(e)}")

        except ValueError as e:
            logger.error(f"Invalid JSON response from Content Catalog: {e}")
            raise ContentSyncError("Invalid response from Content Catalog")

    # ==========================================================================
    # Query Operations (Local Cache)
    # ==========================================================================

    @classmethod
    def get_synced_content(
        cls,
        network_id: Optional[str] = None,
        organization_id: Optional[int] = None,
        content_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> Dict[str, Any]:
        """
        Get synced content from local cache with filtering.

        Queries the SyncedContent table with optional filters for network,
        organization, content type, and status.

        Args:
            network_id: Optional network ID to filter content
            organization_id: Optional organization ID to filter content
            content_type: Optional content type ('video', 'image', 'audio')
            status: Optional status filter ('approved', 'published')
            page: Page number (1-indexed)
            per_page: Items per page (default: 20)

        Returns:
            Dictionary containing:
                - items: List of SyncedContent dictionaries
                - count: Number of items in this page
                - total: Total number of matching items
                - page: Current page number
                - pages: Total number of pages
        """
        query = SyncedContent.query

        # Apply filters
        if network_id:
            query = query.filter(
                SyncedContent.network_ids.like(f'%"{network_id}"%')
            )

        if organization_id:
            query = query.filter(SyncedContent.organization_id == organization_id)

        if status:
            query = query.filter(SyncedContent.status == status)

        if content_type:
            # Filter by content type based on format
            if content_type == 'video':
                video_formats = ['mp4', 'webm', 'avi', 'mov', 'mkv', 'wmv', 'flv']
                query = query.filter(SyncedContent.format.in_(video_formats))
            elif content_type == 'image':
                image_formats = ['jpeg', 'jpg', 'png', 'gif', 'webp', 'svg', 'bmp']
                query = query.filter(SyncedContent.format.in_(image_formats))
            elif content_type == 'audio':
                audio_formats = ['mp3', 'wav', 'ogg', 'aac', 'flac', 'm4a']
                query = query.filter(SyncedContent.format.in_(audio_formats))

        # Get total count
        total = query.count()

        # Apply ordering and pagination
        query = query.order_by(SyncedContent.synced_at.desc())
        query = query.offset((page - 1) * per_page).limit(per_page)

        items = query.all()

        # Calculate total pages
        pages = (total + per_page - 1) // per_page if total > 0 else 1

        return {
            'items': [item.to_dict() for item in items],
            'count': len(items),
            'total': total,
            'page': page,
            'pages': pages,
        }

    @classmethod
    def get_content_by_uuid(cls, source_uuid: str) -> Optional[Dict[str, Any]]:
        """
        Get a single synced content item by its source UUID.

        Args:
            source_uuid: The UUID from Content Catalog

        Returns:
            Dictionary of content data or None if not found
        """
        content = SyncedContent.get_by_source_uuid(source_uuid)
        return content.to_dict() if content else None

    @classmethod
    def get_organizations(cls) -> List[Dict[str, Any]]:
        """
        Get list of unique organizations from synced content.

        Returns:
            List of dictionaries with organization id and name
        """
        return SyncedContent.get_all_organizations()

    @classmethod
    def get_sync_status(cls) -> Dict[str, Any]:
        """
        Get current sync status and statistics.

        Returns:
            Dictionary containing:
                - total_synced: Total number of synced content items
                - by_status: Count breakdown by status
                - by_organization: Count breakdown by organization
                - last_synced: Most recent sync timestamp
        """
        total = SyncedContent.query.count()

        # Get counts by status
        status_counts = db.session.query(
            SyncedContent.status,
            db.func.count(SyncedContent.id)
        ).group_by(SyncedContent.status).all()

        # Get counts by organization
        org_counts = db.session.query(
            SyncedContent.organization_name,
            db.func.count(SyncedContent.id)
        ).group_by(SyncedContent.organization_name).all()

        # Get most recent sync time
        last_synced = db.session.query(
            db.func.max(SyncedContent.synced_at)
        ).scalar()

        return {
            'total_synced': total,
            'by_status': {status: count for status, count in status_counts if status},
            'by_organization': {org: count for org, count in org_counts if org},
            'last_synced': last_synced.isoformat() if last_synced else None,
        }

    # ==========================================================================
    # Maintenance Operations
    # ==========================================================================

    @classmethod
    def remove_archived_content(cls) -> int:
        """
        Remove archived content from local cache.

        Deletes any synced content with status 'archived' as it should
        no longer be visible in the CMS.

        Returns:
            Number of items removed
        """
        archived = SyncedContent.query.filter_by(
            status=SyncedContent.STATUS_ARCHIVED
        ).all()

        count = len(archived)

        for item in archived:
            db.session.delete(item)

        db.session.commit()

        logger.info(f"Removed {count} archived content items from cache")
        return count

    @classmethod
    def clear_synced_content(cls) -> int:
        """
        Clear all synced content from local cache.

        Use with caution - this removes all cached content and requires
        a full re-sync to restore.

        Returns:
            Number of items removed
        """
        count = SyncedContent.query.count()
        SyncedContent.query.delete()
        db.session.commit()

        logger.info(f"Cleared {count} synced content items from cache")
        return count

    # ==========================================================================
    # Health Check Operations
    # ==========================================================================

    @classmethod
    def check_content_catalog_health(cls) -> Dict[str, Any]:
        """
        Check if Content Catalog service is available.

        Makes a lightweight request to verify the Content Catalog is
        reachable and responding.

        Returns:
            Dictionary containing:
                - available: Boolean indicating if service is available
                - url: Content Catalog URL
                - response_time_ms: Response time in milliseconds (if available)
                - error: Error message (if unavailable)
        """
        import time

        result = {
            'available': False,
            'url': cls.CONTENT_CATALOG_URL,
            'response_time_ms': None,
            'error': None,
        }

        try:
            start_time = time.time()

            # Try to fetch first page with minimal items
            response = requests.get(
                f"{cls.CONTENT_CATALOG_URL}{cls.APPROVED_CONTENT_ENDPOINT}",
                params={'page': 1, 'per_page': 1},
                timeout=(cls.CONNECT_TIMEOUT, 5),  # Short timeout for health check
            )

            elapsed_ms = (time.time() - start_time) * 1000

            response.raise_for_status()

            result['available'] = True
            result['response_time_ms'] = round(elapsed_ms, 2)

        except ConnectionError:
            result['error'] = 'Cannot connect to Content Catalog service'

        except Timeout:
            result['error'] = 'Content Catalog service timed out'

        except RequestException as e:
            result['error'] = f'Request failed: {str(e)}'

        return result

    @classmethod
    def get_catalog_url(cls) -> str:
        """
        Get the configured Content Catalog URL.

        Returns:
            Content Catalog base URL
        """
        return cls.CONTENT_CATALOG_URL
