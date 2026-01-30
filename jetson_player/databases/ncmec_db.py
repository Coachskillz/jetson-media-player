"""
NCMEC Face Database for safety pipeline.

Manages the FAISS index of missing children face embeddings.
Downloaded from the local hub and loaded to GPU memory for
sub-millisecond search.

PRIVACY: This database contains ONLY embeddings provided by NCMEC.
No captured images or embeddings from the camera are stored here.
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
NCMEC_INDEX_FILE = "ncmec.faiss"
NCMEC_METADATA_FILE = "ncmec_metadata.json"
DEFAULT_MATCH_THRESHOLD = 0.6


class NCMECDatabase:
    """
    NCMEC missing children face embedding database.

    Loads a FAISS index (CPU or GPU) and associated metadata
    for real-time face matching in the safety camera pipeline.
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        use_gpu: bool = True,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    ):
        self.db_path = Path(os.environ.get("SKILLZ_NCMEC_DB_PATH", db_path))
        self.use_gpu = use_gpu
        self.match_threshold = float(
            os.environ.get("SKILLZ_NCMEC_THRESHOLD", match_threshold)
        )

        self._index = None
        self._gpu_index = None
        self._metadata: List[Dict] = []
        self._index_hash: Optional[str] = None
        self._loaded_at: Optional[float] = None
        self._entry_count: int = 0

    def load(self) -> bool:
        """
        Load NCMEC FAISS index and metadata from disk.

        Returns:
            True if loaded successfully.
        """
        try:
            import faiss
        except ImportError:
            logger.error("FAISS not available - install faiss-gpu")
            return False

        index_path = self.db_path / NCMEC_INDEX_FILE
        metadata_path = self.db_path / NCMEC_METADATA_FILE

        if not index_path.exists():
            logger.warning(f"NCMEC index not found: {index_path}")
            return False

        try:
            # Load FAISS index
            cpu_index = faiss.read_index(str(index_path))
            self._entry_count = cpu_index.ntotal

            if self.use_gpu:
                res = faiss.StandardGpuResources()
                self._gpu_index = faiss.index_cpu_to_gpu(res, 0, cpu_index)
                self._index = self._gpu_index
                logger.info(
                    f"NCMEC index loaded to GPU: {self._entry_count} entries"
                )
            else:
                self._index = cpu_index
                logger.info(
                    f"NCMEC index loaded to CPU: {self._entry_count} entries"
                )

            # Load metadata
            if metadata_path.exists():
                with open(metadata_path, "r") as f:
                    self._metadata = json.load(f)
            else:
                logger.warning("NCMEC metadata file not found")
                self._metadata = []

            # Track index version
            self._index_hash = self._compute_file_hash(index_path)
            self._loaded_at = time.time()

            return True

        except Exception as e:
            logger.error(f"Failed to load NCMEC index: {e}")
            return False

    def search(
        self,
        embedding: np.ndarray,
        k: int = 1,
    ) -> List[Dict]:
        """
        Search for matching faces in the NCMEC database.

        Args:
            embedding: 512-dim normalized face embedding.
            k: Number of nearest neighbors.

        Returns:
            List of match dicts with ncmec_id, similarity, and metadata.
            Empty list if no match above threshold.
        """
        if self._index is None:
            return []

        from jetson_player.processors.face_recognizer import FaceRecognizer

        query = embedding.reshape(1, -1).astype(np.float32)
        distances, indices = self._index.search(query, k)

        matches = []
        for i in range(k):
            idx = int(indices[0][i])
            if idx < 0:
                continue

            similarity = FaceRecognizer.l2_to_cosine(distances[0][i])
            if similarity < self.match_threshold:
                continue

            match = {
                "index": idx,
                "similarity": float(similarity),
            }

            # Attach metadata if available
            if idx < len(self._metadata):
                match["ncmec_id"] = self._metadata[idx].get("ncmec_id")
                match["case_number"] = self._metadata[idx].get("case_number")
                match["first_name"] = self._metadata[idx].get("first_name")
                match["last_name"] = self._metadata[idx].get("last_name")
                match["missing_date"] = self._metadata[idx].get("missing_date")

            matches.append(match)

        return matches

    def check_for_update(self) -> bool:
        """
        Check if the on-disk index has changed since last load.

        Returns:
            True if a newer index is available.
        """
        index_path = self.db_path / NCMEC_INDEX_FILE
        if not index_path.exists():
            return False

        current_hash = self._compute_file_hash(index_path)
        return current_hash != self._index_hash

    def reload(self) -> bool:
        """Reload index if updated on disk."""
        if self.check_for_update():
            logger.info("NCMEC index update detected, reloading...")
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
