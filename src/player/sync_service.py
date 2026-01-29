"""
Hub Sync Service for Jetson Media Player.
Handles playlist and content synchronization with the local hub at 5-minute intervals.
"""

import hashlib
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from .config import PlayerConfig, get_player_config
from src.common.logger import setup_logger


logger = setup_logger(__name__)


class SyncService:
    """
    Synchronizes playlists and content from the local hub.
    Runs in background thread at configurable intervals (default 5 minutes).
    """

    # Default sync interval in seconds (5 minutes)
    DEFAULT_SYNC_INTERVAL = 300

    # Default media directory on Jetson devices
    DEFAULT_MEDIA_DIR = "/home/skillz/media"

    # Request timeout in seconds
    REQUEST_TIMEOUT = 10

    # Download timeout in seconds (for large files)
    DOWNLOAD_TIMEOUT = 120

    def __init__(
        self,
        config: Optional[PlayerConfig] = None,
        media_dir: Optional[str] = None,
        sync_interval: int = DEFAULT_SYNC_INTERVAL,
        on_sync_complete: Optional[Callable[[bool], None]] = None,
        on_content_updated: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the sync service.

        Args:
            config: PlayerConfig instance (uses global if None)
            media_dir: Path to media files directory
            sync_interval: Seconds between sync attempts (default 300 = 5 min)
            on_sync_complete: Callback after sync attempt (passed success bool)
            on_content_updated: Callback when new content is downloaded
        """
        self._config = config or get_player_config()
        self.media_dir = Path(media_dir) if media_dir else Path(self.DEFAULT_MEDIA_DIR)
        self.sync_interval = sync_interval
        self._on_sync_complete = on_sync_complete
        self._on_content_updated = on_content_updated

        # Ensure media directory exists
        self.media_dir.mkdir(parents=True, exist_ok=True)

        # Background thread state
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()

        # Sync statistics
        self._last_sync_time: Optional[datetime] = None
        self._last_sync_success = False
        self._consecutive_failures = 0
        self._total_syncs = 0
        self._total_failures = 0

        logger.info(
            "SyncService initialized - hub_url: %s, media_dir: %s, interval: %ds",
            self._config.hub_url,
            self.media_dir,
            self.sync_interval
        )

    @property
    def hub_url(self) -> str:
        """Get the hub URL from config."""
        return self._config.hub_url

    @property
    def cms_url(self) -> str:
        """Get the CMS URL from config."""
        return self._config.cms_url

    @property
    def connection_mode(self) -> str:
        """Get connection mode (hub or direct)."""
        return self._config.connection_mode

    @property
    def hardware_id(self) -> str:
        """Get the hardware ID from config."""
        return self._config.hardware_id

    @property
    def screen_id(self) -> str:
        """Get the screen ID from config."""
        return self._config.screen_id

    @property
    def base_url(self) -> str:
        """Get the base URL for API calls based on connection mode."""
        if self.connection_mode == "hub":
            return self.hub_url
        return self.cms_url

    def start(self) -> None:
        """Start the background sync thread."""
        if self._running:
            logger.warning("Sync service already running")
            return

        self._running = True
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._sync_loop,
            name="SyncService",
            daemon=True
        )
        self._thread.start()

        logger.info("Sync service started")

    def stop(self) -> None:
        """Stop the background sync thread."""
        if not self._running:
            return

        logger.info("Stopping sync service...")
        self._running = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        logger.info("Sync service stopped")

    def _sync_loop(self) -> None:
        """Background thread sync loop."""
        logger.info("Sync loop started - interval: %ds", self.sync_interval)

        # Initial sync
        self.sync_now()

        while self._running:
            # Wait for interval or stop signal
            if self._stop_event.wait(timeout=self.sync_interval):
                # Stop signal received
                break

            if self._running:
                self.sync_now()

        logger.info("Sync loop ended")

    def sync_now(self) -> bool:
        """
        Perform a sync operation immediately.

        Returns:
            True if sync was successful, False otherwise
        """
        logger.info("Starting sync...")
        self._total_syncs += 1

        try:
            # Fetch config from hub
            remote_config = self._fetch_screen_config()

            if remote_config is None:
                # Hub unreachable - continue with cached content
                logger.warning("Hub unreachable - using cached content")
                self._record_failure()
                return False

            # Check if content update is needed
            content_updated = False

            # Check playlist version
            remote_version = remote_config.get('playlist_version', 0)
            local_version = self._config.playlist_version

            if remote_version > local_version:
                logger.info(
                    "Playlist update available: v%d -> v%d",
                    local_version,
                    remote_version
                )
                if self._update_playlist(remote_config):
                    content_updated = True

            # Download any missing content
            if self._sync_content(remote_config):
                content_updated = True

            # Update settings if changed
            self._update_settings(remote_config)

            # Record success
            self._record_success()

            # Notify if content was updated
            if content_updated and self._on_content_updated:
                self._on_content_updated()

            logger.info("Sync completed successfully")
            return True

        except Exception as e:
            logger.error("Sync failed with error: %s", e)
            self._record_failure()
            return False

    def _fetch_screen_config(self) -> Optional[Dict[str, Any]]:
        """
        Fetch screen configuration from hub or CMS depending on connection mode.

        In hub mode: GET {hub_url}/api/v1/screens/{screen_id}/config
        In direct mode: GET {cms_url}/api/v1/devices/{hardware_id}/playlist
                    and GET {cms_url}/api/v1/devices/{hardware_id}/layout

        Returns:
            Config dictionary or None if unavailable
        """
        if self.connection_mode == "direct":
            return self._fetch_config_direct()
        else:
            return self._fetch_config_hub()

    def _fetch_config_hub(self) -> Optional[Dict[str, Any]]:
        """Fetch config from local hub."""
        if not self.screen_id:
            logger.warning("No screen_id configured - cannot fetch config")
            return None

        url = f"{self.hub_url}/api/v1/screens/{self.screen_id}/config"

        try:
            response = requests.get(url, timeout=self.REQUEST_TIMEOUT)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                logger.error("Screen not found: %s", self.screen_id)
                return None
            else:
                logger.error(
                    "Failed to fetch config from hub - status: %d",
                    response.status_code
                )
                return None

        except requests.Timeout:
            logger.warning("Timeout fetching config from hub")
            return None
        except requests.RequestException as e:
            logger.warning("Hub request failed: %s", e)
            return None

    def _fetch_config_direct(self) -> Optional[Dict[str, Any]]:
        """Fetch config directly from CMS using device endpoints."""
        if not self.hardware_id:
            logger.warning("No hardware_id configured - cannot fetch config")
            return None

        # Fetch playlist data
        playlist_url = f"{self.cms_url}/api/v1/devices/{self.hardware_id}/playlist"
        layout_url = f"{self.cms_url}/api/v1/devices/{self.hardware_id}/layout"

        try:
            # Fetch playlist
            playlist_resp = requests.get(playlist_url, timeout=self.REQUEST_TIMEOUT)
            if playlist_resp.status_code != 200:
                logger.error(
                    "Failed to fetch playlist from CMS - status: %d",
                    playlist_resp.status_code
                )
                return None

            playlist_data = playlist_resp.json()

            # Fetch layout (optional - may not be assigned)
            layout_data = None
            try:
                layout_resp = requests.get(layout_url, timeout=self.REQUEST_TIMEOUT)
                if layout_resp.status_code == 200:
                    layout_data = layout_resp.json()
            except requests.RequestException:
                logger.debug("No layout available from CMS")

            # Convert CMS response format to the config format sync expects
            config = self._convert_cms_to_sync_format(playlist_data, layout_data)
            return config

        except requests.Timeout:
            logger.warning("Timeout fetching config from CMS")
            return None
        except requests.RequestException as e:
            logger.warning("CMS request failed: %s", e)
            return None

    def _convert_cms_to_sync_format(
        self,
        playlist_data: Dict[str, Any],
        layout_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Convert CMS playlist/layout response to the sync config format.

        The hub provides a unified config. When running direct mode,
        we assemble the same format from CMS playlist + layout endpoints.
        """
        items = playlist_data.get('items', [])

        # Build default playlist from CMS items
        default_items = []
        for item in items:
            default_items.append({
                'content_id': item.get('content_id', ''),
                'filename': item.get('filename', ''),
                'duration': item.get('duration', 10),
                'file_hash': item.get('file_hash', ''),
                'url': item.get('url', ''),
            })

        config = {
            'playlist_version': hash(str(items)) & 0xFFFFFFFF,
            'updated_at': None,
            'default_playlist': {
                'items': default_items,
            },
            'triggered_playlists': [],
            'settings': {},
        }

        # Extract triggered playlists from layout if available
        if layout_data and layout_data.get('layout'):
            layout = layout_data['layout']
            for layer in layout.get('layers', []):
                for tp in layer.get('trigger_playlists', []):
                    triggered = {
                        'playlist_id': tp.get('playlist_id', ''),
                        'rule': {
                            'type': tp.get('trigger_type', 'default'),
                        },
                        'items': [],
                    }
                    for tp_item in tp.get('items', []):
                        triggered['items'].append({
                            'content_id': tp_item.get('content_id', ''),
                            'filename': tp_item.get('filename', ''),
                            'duration': tp_item.get('duration', 10),
                            'file_hash': tp_item.get('file_hash', ''),
                            'url': tp_item.get('url', ''),
                        })
                    config['triggered_playlists'].append(triggered)

        return config

    def _update_playlist(self, remote_config: Dict[str, Any]) -> bool:
        """
        Update local playlist configuration.

        Args:
            remote_config: Configuration from hub

        Returns:
            True if playlist was updated
        """
        try:
            # Extract playlist data
            default_playlist = remote_config.get('default_playlist', {})
            triggered_playlists = remote_config.get('triggered_playlists', [])
            playlist_version = remote_config.get('playlist_version', 0)
            updated_at = remote_config.get('updated_at', datetime.now().isoformat())

            # Update config
            self._config.default_playlist = default_playlist
            self._config.triggered_playlists = triggered_playlists
            self._config.playlist_version = playlist_version
            self._config.playlist_updated_at = updated_at

            # Save to disk
            self._config.save_playlist()

            logger.info("Playlist updated to version %d", playlist_version)
            return True

        except Exception as e:
            logger.error("Failed to update playlist: %s", e)
            return False

    def _sync_content(self, remote_config: Dict[str, Any]) -> bool:
        """
        Download any missing content files.

        Args:
            remote_config: Configuration from hub

        Returns:
            True if any new content was downloaded
        """
        # Collect all content files needed
        content_files = self._get_required_content(remote_config)

        if not content_files:
            logger.debug("No content files to sync")
            return False

        downloaded_any = False

        for content in content_files:
            content_id = content.get('content_id', '')
            filename = content.get('filename', '')

            if not filename:
                continue

            local_path = self.media_dir / filename

            # Skip if file already exists with correct hash
            if local_path.exists():
                expected_hash = content.get('file_hash')
                if expected_hash and self._verify_file_hash(local_path, expected_hash):
                    logger.debug("Content already exists: %s", filename)
                    continue
                elif expected_hash:
                    logger.warning(
                        "Content hash mismatch, re-downloading: %s",
                        filename
                    )

            # Download the content
            if self._download_content(content_id, filename):
                downloaded_any = True

        return downloaded_any

    def _get_required_content(
        self,
        remote_config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Get list of all content files needed.

        Args:
            remote_config: Configuration from hub

        Returns:
            List of content dictionaries with content_id, filename, file_hash
        """
        content_list = []
        seen_files = set()

        # Default playlist items
        default_playlist = remote_config.get('default_playlist', {})
        for item in default_playlist.get('items', []):
            filename = item.get('filename')
            if filename and filename not in seen_files:
                content_list.append({
                    'content_id': item.get('content_id', ''),
                    'filename': filename,
                    'file_hash': item.get('file_hash')
                })
                seen_files.add(filename)

        # Triggered playlist items
        for playlist in remote_config.get('triggered_playlists', []):
            for item in playlist.get('items', []):
                filename = item.get('filename')
                if filename and filename not in seen_files:
                    content_list.append({
                        'content_id': item.get('content_id', ''),
                        'filename': filename,
                        'file_hash': item.get('file_hash')
                    })
                    seen_files.add(filename)

        return content_list

    def _download_content(self, content_id: str, filename: str) -> bool:
        """
        Download a content file from hub.

        Args:
            content_id: Content ID for download URL
            filename: Local filename to save as

        Returns:
            True if download successful
        """
        if not content_id:
            logger.warning("No content_id for file: %s", filename)
            return False

        local_path = self.media_dir / filename
        temp_path = self.media_dir / f".{filename}.tmp"
        url = f"{self.base_url}/api/v1/content/{content_id}/download"

        try:
            logger.info("Downloading: %s", filename)

            response = requests.get(
                url,
                stream=True,
                timeout=self.DOWNLOAD_TIMEOUT
            )

            if response.status_code != 200:
                logger.error(
                    "Failed to download %s - status: %d",
                    filename,
                    response.status_code
                )
                return False

            # Download to temp file first
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # Move to final location
            temp_path.rename(local_path)

            logger.info("Downloaded: %s", filename)
            return True

        except requests.Timeout:
            logger.error("Timeout downloading: %s", filename)
            self._cleanup_temp_file(temp_path)
            return False
        except requests.RequestException as e:
            logger.error("Download failed for %s: %s", filename, e)
            self._cleanup_temp_file(temp_path)
            return False
        except IOError as e:
            logger.error("IO error downloading %s: %s", filename, e)
            self._cleanup_temp_file(temp_path)
            return False

    def _cleanup_temp_file(self, temp_path: Path) -> None:
        """Remove a temporary file if it exists."""
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass

    def _verify_file_hash(self, file_path: Path, expected_hash: str) -> bool:
        """
        Verify a file's SHA256 hash.

        Args:
            file_path: Path to file
            expected_hash: Expected SHA256 hash

        Returns:
            True if hash matches
        """
        try:
            sha256 = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256.update(chunk)

            actual_hash = sha256.hexdigest()
            return actual_hash.lower() == expected_hash.lower()

        except Exception as e:
            logger.warning("Hash verification failed for %s: %s", file_path, e)
            return False

    def _update_settings(self, remote_config: Dict[str, Any]) -> None:
        """
        Update settings from remote config if present.

        Args:
            remote_config: Configuration from hub
        """
        settings = remote_config.get('settings')
        if not settings:
            return

        try:
            # Update individual settings if present
            if 'camera_enabled' in settings:
                self._config.camera_enabled = settings['camera_enabled']

            if 'ncmec_enabled' in settings:
                self._config.ncmec_enabled = settings['ncmec_enabled']

            if 'loyalty_enabled' in settings:
                self._config.loyalty_enabled = settings['loyalty_enabled']

            if 'demographics_enabled' in settings:
                self._config.demographics_enabled = settings['demographics_enabled']

            if 'ncmec_db_version' in settings:
                self._config.ncmec_db_version = settings['ncmec_db_version']

            if 'loyalty_db_version' in settings:
                self._config.loyalty_db_version = settings['loyalty_db_version']

            # Save to disk
            self._config.save_settings()

            logger.debug("Settings updated from remote config")

        except Exception as e:
            logger.warning("Failed to update settings: %s", e)

    def _record_success(self) -> None:
        """Record a successful sync."""
        self._last_sync_time = datetime.now()
        self._last_sync_success = True
        self._consecutive_failures = 0

        if self._on_sync_complete:
            self._on_sync_complete(True)

    def _record_failure(self) -> None:
        """Record a failed sync."""
        self._last_sync_time = datetime.now()
        self._last_sync_success = False
        self._consecutive_failures += 1
        self._total_failures += 1

        if self._on_sync_complete:
            self._on_sync_complete(False)

    @property
    def is_running(self) -> bool:
        """Check if sync service is running."""
        return self._running

    @property
    def last_sync_time(self) -> Optional[datetime]:
        """Get time of last sync attempt."""
        return self._last_sync_time

    @property
    def last_sync_success(self) -> bool:
        """Check if last sync was successful."""
        return self._last_sync_success

    @property
    def consecutive_failures(self) -> int:
        """Get number of consecutive sync failures."""
        return self._consecutive_failures

    def get_status(self) -> Dict[str, Any]:
        """
        Get sync service status for reporting.

        Returns:
            Dictionary with sync status information
        """
        return {
            'running': self._running,
            'last_sync_time': self._last_sync_time.isoformat() if self._last_sync_time else None,
            'last_sync_success': self._last_sync_success,
            'consecutive_failures': self._consecutive_failures,
            'total_syncs': self._total_syncs,
            'total_failures': self._total_failures,
            'sync_interval': self.sync_interval,
            'hub_url': self.hub_url,
            'screen_id': self.screen_id,
            'media_dir': str(self.media_dir)
        }

    def check_disk_space(self) -> Optional[float]:
        """
        Check available disk space in media directory.

        Returns:
            Free space in GB or None if unavailable
        """
        try:
            stat = os.statvfs(self.media_dir)
            free_bytes = stat.f_bavail * stat.f_frsize
            return free_bytes / (1024 ** 3)  # Convert to GB
        except Exception as e:
            logger.warning("Could not check disk space: %s", e)
            return None

    def cleanup_orphaned_files(
        self,
        remote_config: Dict[str, Any]
    ) -> List[str]:
        """
        Remove media files not referenced in playlists.

        Args:
            remote_config: Configuration from hub

        Returns:
            List of removed filenames
        """
        required_files = set()

        # Collect all required files
        for content in self._get_required_content(remote_config):
            if content.get('filename'):
                required_files.add(content['filename'])

        removed = []

        try:
            for file_path in self.media_dir.glob('*'):
                if file_path.is_file() and file_path.name not in required_files:
                    # Skip hidden and temp files
                    if file_path.name.startswith('.'):
                        continue

                    logger.info("Removing orphaned file: %s", file_path.name)
                    file_path.unlink()
                    removed.append(file_path.name)

        except Exception as e:
            logger.error("Error during cleanup: %s", e)

        return removed

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"SyncService(hub_url={self.hub_url}, "
            f"screen_id={self.screen_id}, "
            f"interval={self.sync_interval}s)"
        )


# Global sync service instance
_global_sync_service: Optional[SyncService] = None


def get_sync_service(
    config: Optional[PlayerConfig] = None,
    media_dir: Optional[str] = None,
    sync_interval: int = SyncService.DEFAULT_SYNC_INTERVAL,
    on_sync_complete: Optional[Callable[[bool], None]] = None,
    on_content_updated: Optional[Callable[[], None]] = None
) -> SyncService:
    """
    Get the global sync service instance.

    Args:
        config: PlayerConfig instance (only used on first call)
        media_dir: Path to media files directory (only used on first call)
        sync_interval: Seconds between sync attempts (only used on first call)
        on_sync_complete: Callback after sync (only used on first call)
        on_content_updated: Callback for content updates (only used on first call)

    Returns:
        SyncService instance
    """
    global _global_sync_service

    if _global_sync_service is None:
        _global_sync_service = SyncService(
            config=config,
            media_dir=media_dir,
            sync_interval=sync_interval,
            on_sync_complete=on_sync_complete,
            on_content_updated=on_content_updated
        )

    return _global_sync_service
