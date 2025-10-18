"""
Content management for local media storage.
Handles content caching, validation, and organization.
"""

from pathlib import Path
from typing import List, Optional, Dict
import hashlib
import json
from src.common.logger import get_logger

logger = get_logger(__name__)


class ContentManager:
    """Manages local media content storage and caching."""
    
    def __init__(self, content_dir: str):
        """
        Initialize content manager.
        
        Args:
            content_dir: Path to local content storage directory
        """
        self.content_dir = Path(content_dir)
        self.content_dir.mkdir(parents=True, exist_ok=True)
        
        # Manifest file tracks what content is cached locally
        self.manifest_file = self.content_dir / "manifest.json"
        self.manifest: Dict[str, Dict] = self._load_manifest()
    
    def _load_manifest(self) -> Dict[str, Dict]:
        """Load content manifest from disk."""
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load manifest: {e}")
                return {}
        return {}
    
    def _save_manifest(self) -> None:
        """Save content manifest to disk."""
        try:
            with open(self.manifest_file, 'w') as f:
                json.dump(self.manifest, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save manifest: {e}")
    
    def add_content(
        self,
        content_id: str,
        filename: str,
        source_path: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        Add content to local storage.
        
        Args:
            content_id: Unique content identifier
            filename: Original filename
            source_path: Path to source file (if copying)
            metadata: Additional metadata
            
        Returns:
            Path to stored content file
        """
        # Create content file path
        dest_path = self.content_dir / filename
        
        # Copy file if source provided
        if source_path:
            import shutil
            shutil.copy2(source_path, dest_path)
            logger.info(f"Copied content: {source_path} -> {dest_path}")
        
        # Calculate file hash for verification
        file_hash = self._calculate_hash(dest_path) if dest_path.exists() else None
        
        # Update manifest
        self.manifest[content_id] = {
            "filename": filename,
            "path": str(dest_path),
            "hash": file_hash,
            "metadata": metadata or {}
        }
        self._save_manifest()
        
        return str(dest_path)
    
    def get_content_path(self, content_id: str) -> Optional[str]:
        """
        Get local path for content ID.
        
        Args:
            content_id: Content identifier
            
        Returns:
            Path to content file or None if not found
        """
        if content_id in self.manifest:
            path = self.manifest[content_id]["path"]
            if Path(path).exists():
                return path
            else:
                logger.warning(f"Content file missing: {path}")
        return None
    
    def verify_content(self, content_id: str) -> bool:
        """
        Verify content file integrity.
        
        Args:
            content_id: Content identifier
            
        Returns:
            True if content exists and hash matches
        """
        if content_id not in self.manifest:
            return False
        
        path = Path(self.manifest[content_id]["path"])
        if not path.exists():
            return False
        
        stored_hash = self.manifest[content_id].get("hash")
        if stored_hash:
            current_hash = self._calculate_hash(path)
            return current_hash == stored_hash
        
        return True
    
    def list_content(self) -> List[Dict]:
        """
        List all cached content.
        
        Returns:
            List of content metadata dictionaries
        """
        return [
            {
                "id": content_id,
                **info
            }
            for content_id, info in self.manifest.items()
        ]
    
    def remove_content(self, content_id: str) -> bool:
        """
        Remove content from local storage.
        
        Args:
            content_id: Content identifier
            
        Returns:
            True if removed successfully
        """
        if content_id not in self.manifest:
            return False
        
        path = Path(self.manifest[content_id]["path"])
        try:
            if path.exists():
                path.unlink()
            del self.manifest[content_id]
            self._save_manifest()
            logger.info(f"Removed content: {content_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove content {content_id}: {e}")
            return False
    
    def _calculate_hash(self, filepath: Path) -> str:
        """Calculate SHA256 hash of file."""
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def get_storage_stats(self) -> Dict:
        """Get storage statistics."""
        total_size = sum(
            Path(info["path"]).stat().st_size
            for info in self.manifest.values()
            if Path(info["path"]).exists()
        )
        
        return {
            "content_count": len(self.manifest),
            "total_size_bytes": total_size,
            "total_size_mb": total_size / (1024 * 1024),
            "content_dir": str(self.content_dir)
        }
