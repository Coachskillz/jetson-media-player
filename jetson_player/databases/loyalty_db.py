"""
Loyalty Face Database for commercial camera pipeline.

Manages the FAISS index of opted-in loyalty program members.
Each advertiser may have their own loyalty index.

PRIVACY: Only stores embeddings of users who have explicitly
opted in to facial recognition loyalty programs. All entries
include consent_date and opt_in_source for audit compliance.
"""

import os
import json
import logging
import time
import hashlib
from pathlib import Path
from typing import Optional, List, Dict

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "/opt/skillz/detection/databases"
LOYALTY_INDEX_FILE = "loyalty.faiss"
LOYALTY_METADATA_FILE = "loyalty_metadata.json"
DEFAULT_MATCH_THRESHOLD = 0.7


class LoyaltyDatabase:
    """
    Loyalty program face embedding database.

    Supports per-advertiser sub-indexes or a single combined index.
    All entries require documented opt-in consent.
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        use_gpu: bool = True,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    ):
        self.db_path = Path(os.environ.get("SKILLZ_LOYALTY_DB_PATH", db_path))
        self.use_gpu = use_gpu
        self.match_threshold = float(
            os.environ.get("SKILLZ_LOYALTY_THRESHOLD", match_threshold)
        )

        self._index = None
        self._gpu_index = None
        self._metadata: List[Dict] = []
        self._index_hash: Optional[str] = None
        self._loaded_at: Optional[float] = None
        self._entry_count: int = 0

    def load(self) -> bool:
        """
        Load loyalty FAISS index and metadata from disk.

        Returns:
            True if loaded successfully.
        """
        try:
            import faiss
        except ImportError:
            logger.error("FAISS not available - install faiss-gpu")
            return False

        index_path = self.db_path / LOYALTY_INDEX_FILE
        metadata_path = self.db_path / LOYALTY_METADATA_FILE

        if not index_path.exists():
            logger.info(f"No loyalty index found at {index_path}")
            return False

        try:
            cpu_index = faiss.read_index(str(index_path))
            self._entry_count = cpu_index.ntotal

            if self.use_gpu:
                res = faiss.StandardGpuResources()
                self._gpu_index = faiss.index_cpu_to_gpu(res, 0, cpu_index)
                self._index = self._gpu_index
                logger.info(
                    f"Loyalty index loaded to GPU: {self._entry_count} entries"
                )
            else:
                self._index = cpu_index
                logger.info(
                    f"Loyalty index loaded to CPU: {self._entry_count} entries"
                )

            if metadata_path.exists():
                with open(metadata_path, "r") as f:
                    self._metadata = json.load(f)
                # Validate consent fields
                self._validate_consent()
            else:
                logger.warning("Loyalty metadata file not found")
                self._metadata = []

            self._index_hash = self._compute_file_hash(index_path)
            self._loaded_at = time.time()

            return True

        except Exception as e:
            logger.error(f"Failed to load loyalty index: {e}")
            return False

    def search(
        self,
        embedding: np.ndarray,
        k: int = 1,
        advertiser_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Search for matching loyalty members.

        Args:
            embedding: 512-dim normalized face embedding.
            k: Number of nearest neighbors.
            advertiser_id: Optional filter to only match a specific advertiser.

        Returns:
            List of match dicts with member info and similarity.
        """
        if self._index is None:
            return []

        from jetson_player.processors.face_recognizer import FaceRecognizer

        query = embedding.reshape(1, -1).astype(np.float32)
        # Fetch extra results if we need to filter by advertiser
        search_k = k * 5 if advertiser_id else k
        distances, indices = self._index.search(query, search_k)

        matches = []
        for i in range(search_k):
            idx = int(indices[0][i])
            if idx < 0:
                continue

            similarity = FaceRecognizer.l2_to_cosine(distances[0][i])
            if similarity < self.match_threshold:
                continue

            # Get metadata
            meta = {}
            if idx < len(self._metadata):
                meta = self._metadata[idx]

            # Filter by advertiser if specified
            if advertiser_id and meta.get("advertiser_id") != advertiser_id:
                continue

            match = {
                "index": idx,
                "similarity": float(similarity),
                "member_id": meta.get("member_id"),
                "advertiser_id": meta.get("advertiser_id"),
                "tier": meta.get("tier", "standard"),
                "preferences": meta.get("preferences", {}),
            }
            matches.append(match)

            if len(matches) >= k:
                break

        return matches

    def _validate_consent(self):
        """Log warning for any entries missing consent documentation."""
        missing_consent = 0
        for entry in self._metadata:
            if not entry.get("consent_date"):
                missing_consent += 1

        if missing_consent:
            logger.warning(
                f"{missing_consent} loyalty entries missing consent_date field"
            )

    def check_for_update(self) -> bool:
        index_path = self.db_path / LOYALTY_INDEX_FILE
        if not index_path.exists():
            return False
        current_hash = self._compute_file_hash(index_path)
        return current_hash != self._index_hash

    def reload(self) -> bool:
        if self.check_for_update():
            logger.info("Loyalty index update detected, reloading...")
            return self.load()
        return False

    @staticmethod
    def _compute_file_hash(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @property
    def is_loaded(self) -> bool:
        return self._index is not None

    @property
    def entry_count(self) -> int:
        return self._entry_count

    def get_status(self) -> dict:
        return {
            "loaded": self.is_loaded,
            "entry_count": self._entry_count,
            "match_threshold": self.match_threshold,
            "use_gpu": self.use_gpu,
            "index_hash": self._index_hash,
            "loaded_at": self._loaded_at,
            "db_path": str(self.db_path),
        }
