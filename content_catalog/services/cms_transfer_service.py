"""
CMS Transfer Service

Handles automatic transfer of approved content from Content Catalog to CMS.
When content is fully approved (Skillz + Venue or auto-approved), this service:
1. Copies the file to CMS storage
2. Creates a Content record in CMS database
3. Links it to the correct Network via slug matching
"""

import os
import shutil
import sqlite3
from datetime import datetime, timezone
import uuid
from pathlib import Path

# Paths - adjust these based on your deployment
CONTENT_CATALOG_UPLOADS = Path('/Users/skillzmedia/Projects/jetson-media-player/content_catalog/uploads')
CMS_UPLOADS = Path('/Users/skillzmedia/Projects/jetson-media-player/cms/uploads')
CMS_DATABASE = Path('/Users/skillzmedia/Projects/jetson-media-player/cms/data/cms.db')


class CMSTransferService:
    """Service for transferring approved content to CMS."""
    
    @staticmethod
    def get_cms_network_id(tenant_slug):
        """
        Find the CMS Network ID that matches the tenant slug.
        
        Args:
            tenant_slug: The slug of the Content Catalog tenant
            
        Returns:
            Network ID (UUID string) or None if not found
        """
        try:
            conn = sqlite3.connect(str(CMS_DATABASE))
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM networks WHERE slug = ?", (tenant_slug,))
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else None
        except Exception as e:
            print(f"Error finding CMS network: {e}")
            return None
    
    @staticmethod
    def content_exists_in_cms(catalog_asset_uuid):
        """
        Check if content with this catalog_asset_uuid already exists in CMS.
        
        Args:
            catalog_asset_uuid: The UUID of the content asset in Content Catalog
            
        Returns:
            True if exists, False otherwise
        """
        try:
            conn = sqlite3.connect(str(CMS_DATABASE))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM content WHERE catalog_asset_uuid = ?", 
                (catalog_asset_uuid,)
            )
            result = cursor.fetchone()
            conn.close()
            return result is not None
        except Exception as e:
            print(f"Error checking CMS content: {e}")
            return False
    
    @staticmethod
    def transfer_to_cms(content_asset, tenant):
        """
        Transfer an approved content asset to CMS.
        
        Args:
            content_asset: ContentAsset instance from Content Catalog
            tenant: Tenant instance the content is approved for
            
        Returns:
            dict with success status and details
        """
        try:
            # Check if already transferred
            if CMSTransferService.content_exists_in_cms(content_asset.uuid):
                return {
                    'success': False,
                    'error': 'Content already exists in CMS',
                    'catalog_asset_uuid': content_asset.uuid
                }
            
            # Find matching CMS network
            network_id = CMSTransferService.get_cms_network_id(tenant.slug)
            if not network_id:
                return {
                    'success': False,
                    'error': f'No matching CMS network found for tenant slug: {tenant.slug}',
                    'tenant_slug': tenant.slug
                }
            
            # Copy file to CMS uploads
            source_path = CONTENT_CATALOG_UPLOADS / content_asset.file_path
            if not source_path.exists():
                # Try with just filename
                source_path = CONTENT_CATALOG_UPLOADS / content_asset.filename
            
            if not source_path.exists():
                return {
                    'success': False,
                    'error': f'Source file not found: {source_path}',
                    'file_path': str(source_path)
                }
            
            # Create destination path
            CMS_UPLOADS.mkdir(parents=True, exist_ok=True)
            dest_filename = f"{content_asset.uuid}_{content_asset.filename}"
            dest_path = CMS_UPLOADS / dest_filename
            
            # Copy file
            shutil.copy2(str(source_path), str(dest_path))
            
            # Create CMS content record
            content_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            
            conn = sqlite3.connect(str(CMS_DATABASE))
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO content (
                    id, title, original_name, filename, content_type,
                    file_size, duration, network_id, catalog_asset_uuid,
                    source, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                content_id,
                content_asset.title,
                content_asset.filename,
                dest_filename,
                content_asset.format or 'video',
                content_asset.file_size or 0,
                content_asset.duration or 0,
                network_id,
                content_asset.uuid,
                'catalog',
                'active',
                now
            ))
            
            conn.commit()
            conn.close()
            
            return {
                'success': True,
                'message': 'Content transferred to CMS',
                'cms_content_id': content_id,
                'network_id': network_id,
                'catalog_asset_uuid': content_asset.uuid,
                'file_path': str(dest_path)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
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
