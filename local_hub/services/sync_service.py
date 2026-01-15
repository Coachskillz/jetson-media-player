"""
Sync Service - Content and database synchronization with HQ.

This module provides the SyncService class for synchronizing content
and databases from the cloud HQ to the local hub. It handles:
- Fetching content manifests from HQ
- Comparing manifests to detect new/changed/deleted content
- Downloading new or updated content files
- Verifying file integrity via SHA256 hash
- Cleaning up orphaned content no longer in manifest
- Tracking sync status for all resource types

The service is designed to work gracefully in offline scenarios,
continuing to serve cached content when HQ is unreachable.

Example:
    from services.sync_service import SyncService
    from services.hq_client import HQClient
    from config import load_config

    config = load_config()
    hq_client = HQClient(config.hq_url, token='...')
    sync_service = SyncService(hq_client, config)

    # Sync all content from HQ
    result = sync_service.sync_content()
"""

import hashlib
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services import SyncError
from services.hq_client import HQClient
from config import HubConfig


logger = logging.getLogger(__name__)


class SyncService:
    """
    Service for synchronizing content and databases from HQ.

    This service handles all synchronization operations:
    - Content files (videos, images, audio)
    - NCMEC database (facial recognition FAISS)
    - Loyalty database (member recognition FAISS)

    Attributes:
        hq_client: HQClient instance for HQ communication
        config: HubConfig instance for configuration
        content_path: Local path for content storage
        databases_path: Local path for database storage
    """

    def __init__(self, hq_client: HQClient, config: HubConfig):
        """
        Initialize the sync service.

        Args:
            hq_client: HQClient instance (should be authenticated)
            config: HubConfig instance with storage paths
        """
        self.hq_client = hq_client
        self.config = config
        self.content_path = config.content_path
        self.databases_path = config.databases_path

        # Ensure storage directories exist
        self._ensure_directories()

        logger.info(f"SyncService initialized with content_path={self.content_path}")

    def _ensure_directories(self) -> None:
        """Ensure required storage directories exist."""
        os.makedirs(self.content_path, exist_ok=True)
        os.makedirs(self.databases_path, exist_ok=True)
        logger.debug(f"Storage directories ensured: {self.content_path}, {self.databases_path}")

    @staticmethod
    def calculate_file_hash(file_path: str) -> str:
        """
        Calculate SHA256 hash of a file.

        Args:
            file_path: Path to the file

        Returns:
            Hexadecimal SHA256 hash string

        Raises:
            SyncError: If file cannot be read
        """
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except IOError as e:
            raise SyncError(
                message=f"Cannot read file for hashing: {file_path}",
                details={'error': str(e)},
            )

    def _get_content_local_path(self, content_id: str, filename: str) -> str:
        """
        Get local file path for content item.

        Args:
            content_id: Content identifier from HQ
            filename: Original filename

        Returns:
            Local file path for storing content
        """
        # Use content_id as directory to avoid filename collisions
        content_dir = os.path.join(self.content_path, content_id)
        return os.path.join(content_dir, filename)

    # -------------------------------------------------------------------------
    # Content Sync
    # -------------------------------------------------------------------------

    def fetch_content_manifest(self) -> List[Dict[str, Any]]:
        """
        Fetch content manifest from HQ.

        The manifest contains metadata for all content items that should
        be cached locally, including file_hash for change detection.

        Returns:
            List of content item dictionaries from HQ

        Raises:
            SyncError: If manifest cannot be fetched
        """
        try:
            logger.info("Fetching content manifest from HQ")
            response = self.hq_client.get('/api/v1/content/manifest')

            # Handle both direct list and wrapped response
            if isinstance(response, list):
                manifest = response
            else:
                manifest = response.get('content', response.get('items', []))

            logger.info(f"Received manifest with {len(manifest)} content items")
            return manifest

        except Exception as e:
            logger.error(f"Failed to fetch content manifest: {e}")
            raise SyncError(
                message="Failed to fetch content manifest from HQ",
                details={'error': str(e)},
            )

    def compare_manifest(
        self,
        hq_manifest: List[Dict[str, Any]],
        local_content: List[Any],
    ) -> Tuple[List[Dict], List[Dict], List[Any]]:
        """
        Compare HQ manifest with local content to determine sync actions.

        Args:
            hq_manifest: Content manifest from HQ
            local_content: List of local Content model instances

        Returns:
            Tuple of (to_download, to_update, to_delete):
            - to_download: New content items to download
            - to_update: Existing content items with changed hash
            - to_delete: Local content no longer in HQ manifest
        """
        # Build lookup by content_id for local content
        local_by_id = {}
        for content in local_content:
            if hasattr(content, 'content_id'):
                local_by_id[content.content_id] = content
            elif isinstance(content, dict):
                local_by_id[content.get('content_id')] = content

        # Track content IDs in HQ manifest
        hq_content_ids = set()

        to_download = []
        to_update = []

        for item in hq_manifest:
            content_id = item.get('content_id')
            if not content_id:
                continue

            hq_content_ids.add(content_id)
            hq_hash = item.get('file_hash')

            local = local_by_id.get(content_id)

            if local is None:
                # New content - needs download
                to_download.append(item)
                logger.debug(f"New content to download: {content_id}")

            elif local is not None:
                # Check if content needs update
                local_hash = (
                    local.file_hash if hasattr(local, 'file_hash')
                    else local.get('file_hash')
                )

                if hq_hash and local_hash != hq_hash:
                    to_update.append(item)
                    logger.debug(f"Content to update (hash changed): {content_id}")

        # Find orphaned content (in local but not in HQ manifest)
        to_delete = []
        for content_id, content in local_by_id.items():
            if content_id not in hq_content_ids:
                to_delete.append(content)
                logger.debug(f"Orphaned content to delete: {content_id}")

        logger.info(
            f"Manifest comparison: {len(to_download)} new, "
            f"{len(to_update)} updated, {len(to_delete)} orphaned"
        )

        return to_download, to_update, to_delete

    def download_content_item(
        self,
        content_item: Dict[str, Any],
        verify_hash: bool = True,
    ) -> Tuple[str, str, int]:
        """
        Download a single content item from HQ.

        Args:
            content_item: Content item dict from manifest
            verify_hash: Whether to verify downloaded file hash

        Returns:
            Tuple of (local_path, file_hash, file_size)

        Raises:
            SyncError: If download fails or hash verification fails
        """
        content_id = content_item.get('content_id')
        filename = content_item.get('filename', f'{content_id}.bin')
        expected_hash = content_item.get('file_hash')

        logger.info(f"Downloading content: {content_id} ({filename})")

        # Prepare local path
        local_path = self._get_content_local_path(content_id, filename)
        local_dir = os.path.dirname(local_path)
        os.makedirs(local_dir, exist_ok=True)

        # Download to temporary file first
        temp_path = f"{local_path}.tmp"

        try:
            # Download file from HQ
            endpoint = f'/api/v1/content/{content_id}/download'
            self.hq_client.download_file(endpoint, temp_path)

            # Calculate hash of downloaded file
            actual_hash = self.calculate_file_hash(temp_path)
            file_size = os.path.getsize(temp_path)

            # Verify hash if expected hash is provided
            if verify_hash and expected_hash and actual_hash != expected_hash:
                os.remove(temp_path)
                raise SyncError(
                    message=f"Hash mismatch for content {content_id}",
                    details={
                        'expected': expected_hash,
                        'actual': actual_hash,
                        'content_id': content_id,
                    },
                )

            # Move temp file to final location
            shutil.move(temp_path, local_path)

            logger.info(f"Downloaded content {content_id}: {file_size} bytes, hash={actual_hash[:8]}...")

            return local_path, actual_hash, file_size

        except SyncError:
            raise
        except Exception as e:
            # Clean up temp file if exists
            if os.path.exists(temp_path):
                os.remove(temp_path)

            logger.error(f"Failed to download content {content_id}: {e}")
            raise SyncError(
                message=f"Failed to download content {content_id}",
                details={'error': str(e), 'content_id': content_id},
            )

    def delete_content_file(self, local_path: str) -> bool:
        """
        Delete a content file from local storage.

        Args:
            local_path: Path to the content file

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
                logger.debug(f"Deleted content file: {local_path}")

                # Remove parent directory if empty
                parent_dir = os.path.dirname(local_path)
                if os.path.isdir(parent_dir) and not os.listdir(parent_dir):
                    os.rmdir(parent_dir)
                    logger.debug(f"Removed empty directory: {parent_dir}")

                return True
            return False
        except OSError as e:
            logger.warning(f"Failed to delete content file {local_path}: {e}")
            return False

    def sync_content(
        self,
        app_context: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Perform full content synchronization with HQ.

        This method:
        1. Fetches content manifest from HQ
        2. Compares with local content to find changes
        3. Downloads new/updated content
        4. Deletes orphaned content
        5. Updates database records and sync status

        Args:
            app_context: Optional Flask app context for database operations

        Returns:
            Sync result dictionary with counts and errors

        Raises:
            SyncError: If sync fails critically
        """
        from models import db
        from models.content import Content
        from models.sync_status import SyncStatus

        result = {
            'downloaded': 0,
            'updated': 0,
            'deleted': 0,
            'errors': [],
            'started_at': datetime.utcnow().isoformat(),
            'completed_at': None,
            'success': False,
        }

        sync_status = None

        try:
            # Get or create sync status record
            sync_status = SyncStatus.get_content_status()

            # Fetch manifest from HQ
            hq_manifest = self.fetch_content_manifest()

            # Get local content records
            local_content = Content.query.all()

            # Compare manifests
            to_download, to_update, to_delete = self.compare_manifest(
                hq_manifest, local_content
            )

            # Process new content downloads
            for item in to_download:
                try:
                    local_path, file_hash, file_size = self.download_content_item(item)

                    # Create content record
                    content, _ = Content.create_or_update(
                        content_id=item.get('content_id'),
                        filename=item.get('filename', ''),
                        content_type=item.get('content_type', 'video'),
                        duration_seconds=item.get('duration_seconds'),
                        playlist_ids=item.get('playlist_ids'),
                    )
                    content.update_cache_info(local_path, file_hash, file_size)

                    result['downloaded'] += 1

                except Exception as e:
                    error_msg = f"Failed to download {item.get('content_id')}: {e}"
                    logger.error(error_msg)
                    result['errors'].append(error_msg)

            # Process content updates (re-download)
            for item in to_update:
                try:
                    local_path, file_hash, file_size = self.download_content_item(item)

                    # Update content record
                    content = Content.get_by_content_id(item.get('content_id'))
                    if content:
                        content.update_cache_info(local_path, file_hash, file_size)

                    result['updated'] += 1

                except Exception as e:
                    error_msg = f"Failed to update {item.get('content_id')}: {e}"
                    logger.error(error_msg)
                    result['errors'].append(error_msg)

            # Process deletions
            for content in to_delete:
                try:
                    content_id = (
                        content.content_id if hasattr(content, 'content_id')
                        else content.get('content_id')
                    )
                    local_path = (
                        content.local_path if hasattr(content, 'local_path')
                        else content.get('local_path')
                    )

                    # Delete file from disk
                    if local_path:
                        self.delete_content_file(local_path)

                    # Delete database record
                    if hasattr(content, 'id'):
                        db.session.delete(content)
                        db.session.commit()

                    result['deleted'] += 1

                except Exception as e:
                    content_id = (
                        content.content_id if hasattr(content, 'content_id')
                        else content.get('content_id', 'unknown')
                    )
                    error_msg = f"Failed to delete {content_id}: {e}"
                    logger.error(error_msg)
                    result['errors'].append(error_msg)

            # Update sync status
            result['completed_at'] = datetime.utcnow().isoformat()
            result['success'] = len(result['errors']) == 0

            if result['success']:
                sync_status.mark_sync_success(
                    version=datetime.utcnow().isoformat(),
                )
            else:
                sync_status.mark_sync_failure(
                    error_message=f"{len(result['errors'])} errors during sync"
                )

            logger.info(
                f"Content sync completed: {result['downloaded']} downloaded, "
                f"{result['updated']} updated, {result['deleted']} deleted, "
                f"{len(result['errors'])} errors"
            )

            return result

        except Exception as e:
            result['completed_at'] = datetime.utcnow().isoformat()
            result['success'] = False
            result['errors'].append(str(e))

            if sync_status:
                sync_status.mark_sync_failure(error_message=str(e))

            logger.error(f"Content sync failed: {e}")
            raise SyncError(
                message="Content sync failed",
                details={'error': str(e), 'result': result},
            )

    # -------------------------------------------------------------------------
    # NCMEC Database Sync
    # -------------------------------------------------------------------------

    def get_ncmec_db_path(self) -> str:
        """
        Get local file path for NCMEC database.

        Returns:
            Path to ncmec.faiss file in databases directory
        """
        return os.path.join(self.databases_path, 'ncmec.faiss')

    def fetch_ncmec_version(self) -> Dict[str, Any]:
        """
        Fetch NCMEC database version info from HQ.

        Returns:
            Version info dict with version, file_hash, file_size

        Raises:
            SyncError: If version info cannot be fetched
        """
        try:
            logger.info("Fetching NCMEC database version from HQ")
            response = self.hq_client.get('/api/v1/databases/ncmec/version')

            # Extract version info from response
            version_info = {
                'version': response.get('version'),
                'file_hash': response.get('file_hash'),
                'file_size': response.get('file_size'),
            }

            logger.info(f"HQ NCMEC DB version: {version_info['version']}")
            return version_info

        except Exception as e:
            logger.error(f"Failed to fetch NCMEC version from HQ: {e}")
            raise SyncError(
                message="Failed to fetch NCMEC database version from HQ",
                details={'error': str(e)},
            )

    def download_ncmec_database(self, expected_hash: Optional[str] = None) -> Tuple[str, str, int]:
        """
        Download NCMEC database file from HQ.

        Args:
            expected_hash: Expected SHA256 hash for verification

        Returns:
            Tuple of (local_path, file_hash, file_size)

        Raises:
            SyncError: If download fails or hash verification fails
        """
        local_path = self.get_ncmec_db_path()
        temp_path = f"{local_path}.tmp"

        logger.info("Downloading NCMEC database from HQ")

        try:
            # Ensure databases directory exists
            os.makedirs(self.databases_path, exist_ok=True)

            # Download to temporary file first
            endpoint = '/api/v1/databases/ncmec/download'
            self.hq_client.download_file(endpoint, temp_path)

            # Calculate hash of downloaded file
            actual_hash = self.calculate_file_hash(temp_path)
            file_size = os.path.getsize(temp_path)

            # Verify hash if expected hash is provided
            if expected_hash and actual_hash != expected_hash:
                os.remove(temp_path)
                raise SyncError(
                    message="NCMEC database hash mismatch",
                    details={
                        'expected': expected_hash,
                        'actual': actual_hash,
                    },
                )

            # Atomically replace existing database
            # Remove old file if exists
            if os.path.exists(local_path):
                os.remove(local_path)

            # Move temp file to final location
            shutil.move(temp_path, local_path)

            logger.info(f"Downloaded NCMEC database: {file_size} bytes, hash={actual_hash[:8]}...")

            return local_path, actual_hash, file_size

        except SyncError:
            raise
        except Exception as e:
            # Clean up temp file if exists
            if os.path.exists(temp_path):
                os.remove(temp_path)

            logger.error(f"Failed to download NCMEC database: {e}")
            raise SyncError(
                message="Failed to download NCMEC database",
                details={'error': str(e)},
            )

    def sync_ncmec_database(self) -> Dict[str, Any]:
        """
        Synchronize NCMEC database from HQ.

        This method:
        1. Fetches version info from HQ
        2. Compares with local version to determine if update needed
        3. Downloads new database if version/hash differs
        4. Verifies integrity via SHA256 hash
        5. Atomically replaces local database file
        6. Updates SyncStatus record

        Returns:
            Sync result dictionary with:
            - updated: bool indicating if database was updated
            - version: Current version after sync
            - file_hash: Current file hash after sync
            - file_size: Current file size after sync
            - error: Error message if sync failed (None on success)

        Raises:
            SyncError: If sync fails critically
        """
        from models.sync_status import SyncStatus

        result = {
            'updated': False,
            'version': None,
            'file_hash': None,
            'file_size': None,
            'error': None,
            'started_at': datetime.utcnow().isoformat(),
            'completed_at': None,
        }

        sync_status = None

        try:
            # Get or create sync status record
            sync_status = SyncStatus.get_ncmec_db_status()

            # Fetch version info from HQ
            hq_version_info = self.fetch_ncmec_version()
            hq_version = hq_version_info.get('version')
            hq_hash = hq_version_info.get('file_hash')
            hq_size = hq_version_info.get('file_size')

            # Check if update is needed
            if not sync_status.needs_update(new_version=hq_version, new_hash=hq_hash):
                # No update needed
                logger.info(f"NCMEC database is up to date (version={hq_version})")
                result['version'] = sync_status.version
                result['file_hash'] = sync_status.file_hash
                result['file_size'] = sync_status.file_size
                result['completed_at'] = datetime.utcnow().isoformat()
                return result

            # Download new database
            logger.info(f"Updating NCMEC database from {sync_status.version} to {hq_version}")
            local_path, actual_hash, file_size = self.download_ncmec_database(
                expected_hash=hq_hash
            )

            # Update sync status
            sync_status.mark_sync_success(
                version=hq_version,
                file_hash=actual_hash,
                file_size=file_size,
            )

            result['updated'] = True
            result['version'] = hq_version
            result['file_hash'] = actual_hash
            result['file_size'] = file_size
            result['completed_at'] = datetime.utcnow().isoformat()

            logger.info(
                f"NCMEC database sync completed: version={hq_version}, "
                f"size={file_size} bytes"
            )

            return result

        except Exception as e:
            result['completed_at'] = datetime.utcnow().isoformat()
            result['error'] = str(e)

            if sync_status:
                sync_status.mark_sync_failure(error_message=str(e))

            logger.error(f"NCMEC database sync failed: {e}")
            raise SyncError(
                message="NCMEC database sync failed",
                details={'error': str(e), 'result': result},
            )

    def get_ncmec_db_status(self) -> Dict[str, Any]:
        """
        Get current status of NCMEC database.

        Returns:
            Dictionary with version info and local file status
        """
        from models.sync_status import SyncStatus

        sync_status = SyncStatus.get_ncmec_db_status()
        local_path = self.get_ncmec_db_path()

        status = sync_status.to_version_info()
        status['local_path'] = local_path
        status['file_exists'] = os.path.exists(local_path)

        # Verify integrity if file exists
        if status['file_exists'] and sync_status.file_hash:
            try:
                actual_hash = self.calculate_file_hash(local_path)
                status['integrity_ok'] = (actual_hash == sync_status.file_hash)
            except SyncError:
                status['integrity_ok'] = False
        else:
            status['integrity_ok'] = None

        return status

    # -------------------------------------------------------------------------
    # Loyalty Database Sync
    # -------------------------------------------------------------------------

    def get_loyalty_db_path(self) -> str:
        """
        Get local file path for Loyalty database.

        Returns:
            Path to loyalty.faiss file in databases directory
        """
        return os.path.join(self.databases_path, 'loyalty.faiss')

    def fetch_loyalty_version(self) -> Dict[str, Any]:
        """
        Fetch Loyalty database version info from HQ.

        Returns:
            Version info dict with version, file_hash, file_size

        Raises:
            SyncError: If version info cannot be fetched
        """
        try:
            logger.info("Fetching Loyalty database version from HQ")
            response = self.hq_client.get('/api/v1/databases/loyalty/version')

            # Extract version info from response
            version_info = {
                'version': response.get('version'),
                'file_hash': response.get('file_hash'),
                'file_size': response.get('file_size'),
            }

            logger.info(f"HQ Loyalty DB version: {version_info['version']}")
            return version_info

        except Exception as e:
            logger.error(f"Failed to fetch Loyalty version from HQ: {e}")
            raise SyncError(
                message="Failed to fetch Loyalty database version from HQ",
                details={'error': str(e)},
            )

    def download_loyalty_database(self, expected_hash: Optional[str] = None) -> Tuple[str, str, int]:
        """
        Download Loyalty database file from HQ.

        Args:
            expected_hash: Expected SHA256 hash for verification

        Returns:
            Tuple of (local_path, file_hash, file_size)

        Raises:
            SyncError: If download fails or hash verification fails
        """
        local_path = self.get_loyalty_db_path()
        temp_path = f"{local_path}.tmp"

        logger.info("Downloading Loyalty database from HQ")

        try:
            # Ensure databases directory exists
            os.makedirs(self.databases_path, exist_ok=True)

            # Download to temporary file first
            endpoint = '/api/v1/databases/loyalty/download'
            self.hq_client.download_file(endpoint, temp_path)

            # Calculate hash of downloaded file
            actual_hash = self.calculate_file_hash(temp_path)
            file_size = os.path.getsize(temp_path)

            # Verify hash if expected hash is provided
            if expected_hash and actual_hash != expected_hash:
                os.remove(temp_path)
                raise SyncError(
                    message="Loyalty database hash mismatch",
                    details={
                        'expected': expected_hash,
                        'actual': actual_hash,
                    },
                )

            # Atomically replace existing database
            # Remove old file if exists
            if os.path.exists(local_path):
                os.remove(local_path)

            # Move temp file to final location
            shutil.move(temp_path, local_path)

            logger.info(f"Downloaded Loyalty database: {file_size} bytes, hash={actual_hash[:8]}...")

            return local_path, actual_hash, file_size

        except SyncError:
            raise
        except Exception as e:
            # Clean up temp file if exists
            if os.path.exists(temp_path):
                os.remove(temp_path)

            logger.error(f"Failed to download Loyalty database: {e}")
            raise SyncError(
                message="Failed to download Loyalty database",
                details={'error': str(e)},
            )

    def sync_loyalty_database(self) -> Dict[str, Any]:
        """
        Synchronize Loyalty database from HQ.

        This method:
        1. Fetches version info from HQ
        2. Compares with local version to determine if update needed
        3. Downloads new database if version/hash differs
        4. Verifies integrity via SHA256 hash
        5. Atomically replaces local database file
        6. Updates SyncStatus record

        Returns:
            Sync result dictionary with:
            - updated: bool indicating if database was updated
            - version: Current version after sync
            - file_hash: Current file hash after sync
            - file_size: Current file size after sync
            - error: Error message if sync failed (None on success)

        Raises:
            SyncError: If sync fails critically
        """
        from models.sync_status import SyncStatus

        result = {
            'updated': False,
            'version': None,
            'file_hash': None,
            'file_size': None,
            'error': None,
            'started_at': datetime.utcnow().isoformat(),
            'completed_at': None,
        }

        sync_status = None

        try:
            # Get or create sync status record
            sync_status = SyncStatus.get_loyalty_db_status()

            # Fetch version info from HQ
            hq_version_info = self.fetch_loyalty_version()
            hq_version = hq_version_info.get('version')
            hq_hash = hq_version_info.get('file_hash')
            hq_size = hq_version_info.get('file_size')

            # Check if update is needed
            if not sync_status.needs_update(new_version=hq_version, new_hash=hq_hash):
                # No update needed
                logger.info(f"Loyalty database is up to date (version={hq_version})")
                result['version'] = sync_status.version
                result['file_hash'] = sync_status.file_hash
                result['file_size'] = sync_status.file_size
                result['completed_at'] = datetime.utcnow().isoformat()
                return result

            # Download new database
            logger.info(f"Updating Loyalty database from {sync_status.version} to {hq_version}")
            local_path, actual_hash, file_size = self.download_loyalty_database(
                expected_hash=hq_hash
            )

            # Update sync status
            sync_status.mark_sync_success(
                version=hq_version,
                file_hash=actual_hash,
                file_size=file_size,
            )

            result['updated'] = True
            result['version'] = hq_version
            result['file_hash'] = actual_hash
            result['file_size'] = file_size
            result['completed_at'] = datetime.utcnow().isoformat()

            logger.info(
                f"Loyalty database sync completed: version={hq_version}, "
                f"size={file_size} bytes"
            )

            return result

        except Exception as e:
            result['completed_at'] = datetime.utcnow().isoformat()
            result['error'] = str(e)

            if sync_status:
                sync_status.mark_sync_failure(error_message=str(e))

            logger.error(f"Loyalty database sync failed: {e}")
            raise SyncError(
                message="Loyalty database sync failed",
                details={'error': str(e), 'result': result},
            )

    def get_loyalty_db_status(self) -> Dict[str, Any]:
        """
        Get current status of Loyalty database.

        Returns:
            Dictionary with version info and local file status
        """
        from models.sync_status import SyncStatus

        sync_status = SyncStatus.get_loyalty_db_status()
        local_path = self.get_loyalty_db_path()

        status = sync_status.to_version_info()
        status['local_path'] = local_path
        status['file_exists'] = os.path.exists(local_path)

        # Verify integrity if file exists
        if status['file_exists'] and sync_status.file_hash:
            try:
                actual_hash = self.calculate_file_hash(local_path)
                status['integrity_ok'] = (actual_hash == sync_status.file_hash)
            except SyncError:
                status['integrity_ok'] = False
        else:
            status['integrity_ok'] = None

        return status

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def get_local_content_stats(self) -> Dict[str, Any]:
        """
        Get statistics about locally cached content.

        Returns:
            Dictionary with content statistics
        """
        from models.content import Content

        all_content = Content.query.all()
        cached_content = Content.get_all_cached()

        total_size = sum(c.file_size or 0 for c in cached_content)

        return {
            'total_items': len(all_content),
            'cached_items': len(cached_content),
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
        }

    def verify_content_integrity(self) -> Dict[str, Any]:
        """
        Verify integrity of all cached content files.

        Returns:
            Dictionary with verification results
        """
        from models.content import Content

        results = {
            'verified': 0,
            'corrupted': [],
            'missing': [],
        }

        cached_content = Content.get_all_cached()

        for content in cached_content:
            if not content.local_path:
                continue

            if not os.path.exists(content.local_path):
                results['missing'].append(content.content_id)
                logger.warning(f"Missing content file: {content.content_id}")
                continue

            try:
                actual_hash = self.calculate_file_hash(content.local_path)
                if content.file_hash and actual_hash != content.file_hash:
                    results['corrupted'].append({
                        'content_id': content.content_id,
                        'expected_hash': content.file_hash,
                        'actual_hash': actual_hash,
                    })
                    logger.warning(f"Corrupted content file: {content.content_id}")
                else:
                    results['verified'] += 1
            except SyncError as e:
                results['corrupted'].append({
                    'content_id': content.content_id,
                    'error': str(e),
                })

        logger.info(
            f"Content integrity check: {results['verified']} verified, "
            f"{len(results['corrupted'])} corrupted, {len(results['missing'])} missing"
        )

        return results

    def cleanup_orphaned_files(self) -> int:
        """
        Remove files from content directory that are not in database.

        Returns:
            Number of orphaned files removed
        """
        from models.content import Content

        removed = 0
        cached_content = Content.get_all_cached()

        # Build set of known local paths
        known_paths = set()
        for content in cached_content:
            if content.local_path:
                known_paths.add(os.path.normpath(content.local_path))

        # Walk content directory and find orphans
        for root, dirs, files in os.walk(self.content_path):
            for filename in files:
                file_path = os.path.normpath(os.path.join(root, filename))
                if file_path not in known_paths:
                    try:
                        os.remove(file_path)
                        removed += 1
                        logger.debug(f"Removed orphaned file: {file_path}")
                    except OSError as e:
                        logger.warning(f"Failed to remove orphaned file {file_path}: {e}")

        # Remove empty directories
        for root, dirs, files in os.walk(self.content_path, topdown=False):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                if not os.listdir(dir_path):
                    try:
                        os.rmdir(dir_path)
                        logger.debug(f"Removed empty directory: {dir_path}")
                    except OSError:
                        pass

        if removed > 0:
            logger.info(f"Cleaned up {removed} orphaned files")

        return removed

    def __repr__(self) -> str:
        """String representation."""
        return f"<SyncService content_path={self.content_path}>"
