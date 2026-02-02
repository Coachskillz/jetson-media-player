"""
CMS Transfer Service

Handles automatic transfer of approved content from Content Catalog to CMS.
When content is fully approved (Skillz + Venue or auto-approved), this service:
1. Calls the CMS API to push the content record
2. CMS downloads the file from Content Catalog
3. CMS creates a Content record linked to the correct Network

Works both locally and on Railway (or any remote deployment) by using
HTTP API calls instead of direct file/database access.
"""

import os
import logging
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

logger = logging.getLogger(__name__)

# CMS endpoint URL - set via environment variable for production
CMS_ENDPOINT = os.environ.get('CMS_ENDPOINT', 'https://keen-ambition-production.up.railway.app')

# Service API key for CMS authentication
CMS_SERVICE_API_KEY = os.environ.get('CMS_SERVICE_API_KEY', 'skillz-cms-service-key-2026')

# Content Catalog base URL (for CMS to download files from)
CONTENT_CATALOG_BASE_URL = os.environ.get('BASE_URL', 'https://jetson-media-player-production.up.railway.app')


class CMSTransferService:
    """Service for transferring approved content to CMS via API."""

    @staticmethod
    def transfer_to_cms(content_asset, tenant):
        """
        Transfer an approved content asset to CMS via API.

        Calls the CMS /api/v1/content/from-catalog/push endpoint which:
        1. Creates a Content record in the CMS database
        2. Downloads the file from Content Catalog
        3. Links it to the matching Network by slug

        Args:
            content_asset: ContentAsset instance from Content Catalog
            tenant: Tenant instance the content is approved for

        Returns:
            dict with success status and details
        """
        try:
            # Build download URL for the CMS to fetch the file
            download_url = f"{CONTENT_CATALOG_BASE_URL}/api/v1/assets/{content_asset.id}/download"

            # Determine mime type
            format_to_mime = {
                'mp4': 'video/mp4',
                'mov': 'video/quicktime',
                'avi': 'video/x-msvideo',
                'mkv': 'video/x-matroska',
                'webm': 'video/webm',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'png': 'image/png',
                'gif': 'image/gif',
                'webp': 'image/webp',
            }
            mime_type = format_to_mime.get(
                (content_asset.format or '').lower(),
                getattr(content_asset, 'content_type', None) or 'video/mp4'
            )

            payload = {
                'catalog_uuid': content_asset.uuid,
                'title': content_asset.title,
                'filename': content_asset.filename,
                'mime_type': mime_type,
                'file_size': content_asset.file_size or 0,
                'duration': content_asset.duration or 0,
                'network_slug': tenant.slug,
                'download_url': download_url,
            }

            headers = {
                'X-Service-API-Key': CMS_SERVICE_API_KEY,
                'Content-Type': 'application/json',
            }

            url = f"{CMS_ENDPOINT}/api/v1/content/from-catalog/push"
            logger.info(
                "Transferring content %s to CMS at %s (network: %s)",
                content_asset.uuid, CMS_ENDPOINT, tenant.slug
            )

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=(10, 120),
            )

            data = response.json()

            if response.status_code in (200, 201):
                logger.info(
                    "Content transferred successfully: %s -> CMS content %s",
                    content_asset.uuid, data.get('cms_content_id')
                )
                return {
                    'success': True,
                    'message': data.get('message', 'Content transferred to CMS'),
                    'cms_content_id': data.get('cms_content_id'),
                    'network_id': data.get('network_id'),
                    'catalog_asset_uuid': content_asset.uuid,
                }

            elif response.status_code == 409:
                # Content already exists in CMS
                logger.info(
                    "Content already exists in CMS: %s",
                    content_asset.uuid
                )
                return {
                    'success': True,
                    'message': 'Content already exists in CMS',
                    'cms_content_id': data.get('cms_content_id'),
                    'catalog_asset_uuid': content_asset.uuid,
                }

            else:
                error_msg = data.get('error', f'HTTP {response.status_code}')
                logger.error("CMS transfer failed: %s", error_msg)
                return {
                    'success': False,
                    'error': error_msg,
                    'catalog_asset_uuid': content_asset.uuid,
                }

        except ConnectionError as e:
            logger.error("Cannot connect to CMS at %s: %s", CMS_ENDPOINT, e)
            return {
                'success': False,
                'error': f'Cannot connect to CMS: {e}',
            }

        except Timeout as e:
            logger.error("Timeout connecting to CMS: %s", e)
            return {
                'success': False,
                'error': f'CMS request timed out: {e}',
            }

        except RequestException as e:
            logger.error("CMS transfer request failed: %s", e)
            return {
                'success': False,
                'error': str(e),
            }

        except Exception as e:
            logger.error("Unexpected error during CMS transfer: %s", e)
            return {
                'success': False,
                'error': str(e),
            }

    @staticmethod
    def transfer_approved_content(content_venue_approval):
        """
        Transfer content when a ContentVenueApproval is fully approved.

        Args:
            content_venue_approval: ContentVenueApproval instance

        Returns:
            dict with success status and details
        """
        if not content_venue_approval.is_fully_approved():
            return {
                'success': False,
                'error': 'Content is not fully approved'
            }

        return CMSTransferService.transfer_to_cms(
            content_venue_approval.content_asset,
            content_venue_approval.tenant
        )
