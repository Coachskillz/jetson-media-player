"""
Database Sync Service for Jetson Media Player.

Downloads NCMEC and Loyalty FAISS indexes from the local hub (or CMS in direct mode),
verifies integrity via SHA256, and stores them on disk for the detection pipelines.

Supports both hub mode (local_hub serves databases) and direct mode (CMS serves databases).

Sync intervals:
- NCMEC: Every 6 hours
- Loyalty: Every 4 hours

The device can operate fully offline using the last successfully downloaded indexes.
"""

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import requests

from src.common.logger import setup_logger

logger = setup_logger(__name__)

# Default paths
DEFAULT_DB_PATH = "/opt/skillz/detection/databases"
DEFAULT_METADATA_PATH = "/opt/skillz/detection/databases"

# Database filenames (must match what the FAISS loaders expect)
NCMEC_INDEX_FILE = "ncmec.faiss"
NCMEC_METADATA_FILE = "ncmec_metadata.json"
LOYALTY_INDEX_FILE = "loyalty.faiss"
LOYALTY_METADATA_FILE = "loyalty_metadata.json"

# Sync intervals in seconds
NCMEC_SYNC_INTERVAL = 6 * 3600   # 6 hours
LOYALTY_SYNC_INTERVAL = 4 * 3600  # 4 hours

# Retry settings
MAX_DOWNLOAD_RETRIES = 3
RETRY_DELAY_BASE = 30  # seconds, exponential backoff
DOWNLOAD_TIMEOUT = 120  # seconds for large file downloads
VERSION_CHECK_TIMEOUT = 15  # seconds for version API calls

# Local version tracking file
VERSION_TRACKING_FILE = "db_versions.json"


class DatabaseSyncService:
    """
    Manages downloading and updating NCMEC and Loyalty FAISS databases
    from the hub or CMS onto the Jetson device.

    On startup, checks for updates immediately. Then runs periodic
    checks in a background thread.
    """

    def __init__(
        self,
        hub_url: str = "",
        cms_url: str = "",
        connection_mode: str = "hub",
        db_path: str = DEFAULT_DB_PATH,
        ncmec_interval: int = NCMEC_SYNC_INTERVAL,
        loyalty_interval: int = LOYALTY_SYNC_INTERVAL,
    ):
        self.hub_url = hub_url.rstrip("/")
        self.cms_url = cms_url.rstrip("/")
        self.connection_mode = connection_mode
        self.db_path = Path(os.environ.get("SKILLZ_DATABASES_PATH", db_path))
        self.ncmec_interval = ncmec_interval
        self.loyalty_interval = loyalty_interval

        # Version tracking
        self._versions: Dict[str, Dict] = {}
        self._version_file = self.db_path / VERSION_TRACKING_FILE

        # Thread management
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Statistics
        self._ncmec_last_sync: Optional[float] = None
        self._loyalty_last_sync: Optional[float] = None
        self._ncmec_last_check: Optional[float] = None
        self._loyalty_last_check: Optional[float] = None
        self._sync_errors: int = 0

        # Ensure db directory exists
        self.db_path.mkdir(parents=True, exist_ok=True)

        # Load saved version info
        self._load_versions()

        logger.info(
            "DatabaseSyncService initialized: mode=%s, db_path=%s",
            connection_mode, self.db_path
        )

    @property
    def base_url(self) -> str:
        """Get the base URL for database API calls based on connection mode."""
        if self.connection_mode == "direct":
            return self.cms_url
        return self.hub_url

    # ─── Version Tracking ───────────────────────────────────────────

    def _load_versions(self) -> None:
        """Load saved version hashes from disk."""
        if self._version_file.exists():
            try:
                with open(self._version_file, "r") as f:
                    self._versions = json.load(f)
                logger.info("Loaded database versions: %s", self._versions)
            except Exception as e:
                logger.warning("Could not load version file: %s", e)
                self._versions = {}

    def _save_versions(self) -> None:
        """Persist version hashes to disk."""
        try:
            with open(self._version_file, "w") as f:
                json.dump(self._versions, f, indent=2)
        except Exception as e:
            logger.error("Could not save version file: %s", e)

    def _get_local_hash(self, db_type: str) -> Optional[str]:
        """Get the saved hash for a database type."""
        return self._versions.get(db_type, {}).get("file_hash")

    def _update_local_version(self, db_type: str, version_info: Dict) -> None:
        """Update saved version info for a database type."""
        self._versions[db_type] = {
            "file_hash": version_info.get("file_hash"),
            "version": version_info.get("version"),
            "last_updated": time.time(),
        }
        self._save_versions()

    # ─── Hash Verification ──────────────────────────────────────────

    @staticmethod
    def _compute_file_hash(file_path: Path) -> str:
        """Compute SHA256 hash of a file."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    # ─── Version Check ──────────────────────────────────────────────

    def check_ncmec_version(self) -> Optional[Dict]:
        """
        Check the hub/CMS for the current NCMEC database version.

        Returns:
            Version info dict with file_hash, version, file_size,
            or None if unavailable.
        """
        url = f"{self.base_url}/api/v1/databases/ncmec/version"
        try:
            response = requests.get(url, timeout=VERSION_CHECK_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return data
            elif response.status_code == 404:
                logger.debug("NCMEC database not yet available on hub")
            else:
                logger.warning(
                    "NCMEC version check failed: HTTP %d", response.status_code
                )
        except requests.exceptions.RequestException as e:
            logger.warning("NCMEC version check error: %s", e)
        return None

    def check_loyalty_version(self) -> Optional[Dict]:
        """
        Check the hub/CMS for the current Loyalty database version.

        Returns:
            Version info dict or None if unavailable.
        """
        url = f"{self.base_url}/api/v1/databases/loyalty/version"
        try:
            response = requests.get(url, timeout=VERSION_CHECK_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return data
            elif response.status_code == 404:
                logger.debug("Loyalty database not yet available on hub")
            else:
                logger.warning(
                    "Loyalty version check failed: HTTP %d", response.status_code
                )
        except requests.exceptions.RequestException as e:
            logger.warning("Loyalty version check error: %s", e)
        return None

    # ─── Download ───────────────────────────────────────────────────

    def _download_file(self, url: str, dest_path: Path) -> bool:
        """
        Download a file from the hub/CMS with retry and integrity check.

        Downloads to a temp file first, then atomically renames to avoid
        corrupted partial files.

        Args:
            url: Download URL
            dest_path: Final destination path

        Returns:
            True if download succeeded.
        """
        tmp_path = dest_path.with_suffix(".tmp")

        for attempt in range(1, MAX_DOWNLOAD_RETRIES + 1):
            try:
                logger.info(
                    "Downloading %s (attempt %d/%d)",
                    dest_path.name, attempt, MAX_DOWNLOAD_RETRIES
                )
                response = requests.get(
                    url, stream=True, timeout=DOWNLOAD_TIMEOUT
                )
                response.raise_for_status()

                # Stream to temp file
                bytes_written = 0
                with open(tmp_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        bytes_written += len(chunk)

                # Atomic rename
                tmp_path.rename(dest_path)
                logger.info(
                    "Downloaded %s: %d bytes",
                    dest_path.name, bytes_written
                )
                return True

            except requests.exceptions.RequestException as e:
                logger.warning(
                    "Download failed (attempt %d/%d): %s",
                    attempt, MAX_DOWNLOAD_RETRIES, e
                )
                if tmp_path.exists():
                    tmp_path.unlink()

                if attempt < MAX_DOWNLOAD_RETRIES:
                    delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    logger.info("Retrying in %d seconds...", delay)
                    time.sleep(delay)

        return False

    def _download_metadata(self, db_type: str) -> bool:
        """
        Download the metadata JSON for a database type.

        Args:
            db_type: "ncmec" or "loyalty"

        Returns:
            True if download succeeded.
        """
        if db_type == "ncmec":
            filename = NCMEC_METADATA_FILE
        else:
            filename = LOYALTY_METADATA_FILE

        # The hub may serve metadata alongside the FAISS file,
        # or it may be embedded in the version response.
        # Try downloading from a metadata endpoint first.
        url = f"{self.base_url}/api/v1/databases/{db_type}/metadata"
        dest_path = self.db_path / filename

        try:
            response = requests.get(url, timeout=VERSION_CHECK_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                # Extract records list for the metadata file
                records = data.get("records") or data.get("members") or []
                with open(dest_path, "w") as f:
                    json.dump(records, f, indent=2)
                logger.info("Downloaded %s metadata: %d records", db_type, len(records))
                return True
        except Exception as e:
            logger.debug("Metadata endpoint not available for %s: %s", db_type, e)

        # If no metadata endpoint, create a minimal metadata file
        # The FAISS index will still work; metadata is for display only
        if not dest_path.exists():
            with open(dest_path, "w") as f:
                json.dump([], f)
            logger.info("Created empty metadata file for %s", db_type)

        return True

    # ─── Sync Logic ─────────────────────────────────────────────────

    def sync_ncmec(self) -> bool:
        """
        Check for and download updated NCMEC database.

        Returns:
            True if database was updated (or already up to date).
        """
        self._ncmec_last_check = time.time()

        # Check remote version
        version_info = self.check_ncmec_version()
        if not version_info:
            logger.debug("NCMEC database not available from hub")
            return False

        remote_hash = version_info.get("file_hash")
        local_hash = self._get_local_hash("ncmec")

        # Check if we already have this version
        if remote_hash and remote_hash == local_hash:
            # Also verify the file actually exists on disk
            index_path = self.db_path / NCMEC_INDEX_FILE
            if index_path.exists():
                logger.debug("NCMEC database is up to date (hash: %s...)", remote_hash[:12])
                return True

        logger.info("NCMEC database update available, downloading...")

        # Download FAISS index
        download_url = f"{self.base_url}/api/v1/databases/ncmec/download"
        index_path = self.db_path / NCMEC_INDEX_FILE

        if not self._download_file(download_url, index_path):
            logger.error("Failed to download NCMEC database")
            self._sync_errors += 1
            return False

        # Verify hash if provided
        if remote_hash:
            actual_hash = self._compute_file_hash(index_path)
            if actual_hash != remote_hash:
                logger.error(
                    "NCMEC database integrity check FAILED: "
                    "expected %s, got %s. Deleting corrupt file.",
                    remote_hash, actual_hash
                )
                index_path.unlink()
                self._sync_errors += 1
                return False
            logger.info("NCMEC database integrity verified")

        # Download metadata
        self._download_metadata("ncmec")

        # Update version tracking
        self._update_local_version("ncmec", version_info)
        self._ncmec_last_sync = time.time()

        logger.info(
            "NCMEC database synced successfully: version=%s, hash=%s...",
            version_info.get("version"), (remote_hash or "unknown")[:12]
        )
        return True

    def sync_loyalty(self) -> bool:
        """
        Check for and download updated Loyalty database.

        Returns:
            True if database was updated (or already up to date).
        """
        self._loyalty_last_check = time.time()

        # Check remote version
        version_info = self.check_loyalty_version()
        if not version_info:
            logger.debug("Loyalty database not available from hub")
            return False

        remote_hash = version_info.get("file_hash")
        local_hash = self._get_local_hash("loyalty")

        # Check if we already have this version
        if remote_hash and remote_hash == local_hash:
            index_path = self.db_path / LOYALTY_INDEX_FILE
            if index_path.exists():
                logger.debug("Loyalty database is up to date (hash: %s...)", remote_hash[:12])
                return True

        logger.info("Loyalty database update available, downloading...")

        # Download FAISS index
        download_url = f"{self.base_url}/api/v1/databases/loyalty/download"
        index_path = self.db_path / LOYALTY_INDEX_FILE

        if not self._download_file(download_url, index_path):
            logger.error("Failed to download Loyalty database")
            self._sync_errors += 1
            return False

        # Verify hash
        if remote_hash:
            actual_hash = self._compute_file_hash(index_path)
            if actual_hash != remote_hash:
                logger.error(
                    "Loyalty database integrity check FAILED: "
                    "expected %s, got %s. Deleting corrupt file.",
                    remote_hash, actual_hash
                )
                index_path.unlink()
                self._sync_errors += 1
                return False
            logger.info("Loyalty database integrity verified")

        # Download metadata
        self._download_metadata("loyalty")

        # Update version tracking
        self._update_local_version("loyalty", version_info)
        self._loyalty_last_sync = time.time()

        logger.info(
            "Loyalty database synced successfully: version=%s, hash=%s...",
            version_info.get("version"), (remote_hash or "unknown")[:12]
        )
        return True

    def sync_all(self) -> Dict[str, bool]:
        """
        Sync both NCMEC and Loyalty databases.

        Returns:
            Dict with sync results for each database type.
        """
        results = {}
        results["ncmec"] = self.sync_ncmec()
        results["loyalty"] = self.sync_loyalty()
        return results

    # ─── Background Scheduler ───────────────────────────────────────

    def start(self) -> None:
        """Start the background sync scheduler."""
        if self._running:
            logger.warning("Database sync scheduler already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._sync_loop,
            name="database-sync",
            daemon=True
        )
        self._thread.start()
        logger.info(
            "Database sync scheduler started: "
            "NCMEC every %d hours, Loyalty every %d hours",
            self.ncmec_interval // 3600,
            self.loyalty_interval // 3600
        )

    def stop(self) -> None:
        """Stop the background sync scheduler."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("Database sync scheduler stopped")

    def _sync_loop(self) -> None:
        """
        Background loop that periodically checks for database updates.

        On first run, syncs immediately. Then checks at configured intervals.
        Uses a 60-second sleep cycle so we can stop the thread quickly.
        """
        # Initial sync on startup
        logger.info("Running initial database sync...")
        try:
            self.sync_all()
        except Exception as e:
            logger.error("Initial database sync failed: %s", e)

        while self._running:
            try:
                now = time.time()

                # Check NCMEC
                if self._should_sync_ncmec(now):
                    try:
                        self.sync_ncmec()
                    except Exception as e:
                        logger.error("NCMEC sync error: %s", e)
                        self._sync_errors += 1

                # Check Loyalty
                if self._should_sync_loyalty(now):
                    try:
                        self.sync_loyalty()
                    except Exception as e:
                        logger.error("Loyalty sync error: %s", e)
                        self._sync_errors += 1

                # Sleep in short intervals so we can stop quickly
                for _ in range(60):
                    if not self._running:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error("Database sync loop error: %s", e)
                time.sleep(60)

    def _should_sync_ncmec(self, now: float) -> bool:
        """Check if it's time to sync NCMEC database."""
        if self._ncmec_last_check is None:
            return True
        return (now - self._ncmec_last_check) >= self.ncmec_interval

    def _should_sync_loyalty(self, now: float) -> bool:
        """Check if it's time to sync Loyalty database."""
        if self._loyalty_last_check is None:
            return True
        return (now - self._loyalty_last_check) >= self.loyalty_interval

    # ─── Status ─────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Get current sync status for monitoring."""
        ncmec_path = self.db_path / NCMEC_INDEX_FILE
        loyalty_path = self.db_path / LOYALTY_INDEX_FILE

        return {
            "running": self._running,
            "connection_mode": self.connection_mode,
            "base_url": self.base_url,
            "db_path": str(self.db_path),
            "ncmec": {
                "available": ncmec_path.exists(),
                "file_size": ncmec_path.stat().st_size if ncmec_path.exists() else 0,
                "version": self._versions.get("ncmec", {}).get("version"),
                "hash": self._versions.get("ncmec", {}).get("file_hash", "")[:12],
                "last_sync": self._ncmec_last_sync,
                "last_check": self._ncmec_last_check,
            },
            "loyalty": {
                "available": loyalty_path.exists(),
                "file_size": loyalty_path.stat().st_size if loyalty_path.exists() else 0,
                "version": self._versions.get("loyalty", {}).get("version"),
                "hash": self._versions.get("loyalty", {}).get("file_hash", "")[:12],
                "last_sync": self._loyalty_last_sync,
                "last_check": self._loyalty_last_check,
            },
            "sync_errors": self._sync_errors,
        }

    def has_ncmec_database(self) -> bool:
        """Check if NCMEC database is available on disk."""
        return (self.db_path / NCMEC_INDEX_FILE).exists()

    def has_loyalty_database(self) -> bool:
        """Check if Loyalty database is available on disk."""
        return (self.db_path / LOYALTY_INDEX_FILE).exists()
