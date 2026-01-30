"""
Face Recognizer wrapper for ArcFace TensorRT engine.

Provides face embedding extraction and comparison utilities
used by both NCMEC matching (safety) and loyalty recognition (commercial).
"""

import os
import logging
import numpy as np
from dataclasses import dataclass
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class FaceMatch:
    """Result of a face matching operation."""
    index: int
    similarity: float
    metadata: Optional[dict] = None


class FaceRecognizer:
    """
    ArcFace face recognition and embedding wrapper.

    In the DeepStream pipeline, embedding extraction is handled by
    nvinfer (SGIE) with output-tensor-meta=1. This class provides
    utility methods for embedding comparison and FAISS operations.
    """

    DEFAULT_CONFIG = {
        "model_engine": "arcface_fp16.engine",
        "embedding_dim": 512,
        "precision": "fp16",
        "batch_size": 16,
        "input_width": 112,
        "input_height": 112,
    }

    def __init__(self, models_path: str = "/opt/skillz/models", **overrides):
        self.models_path = models_path
        self.config = {**self.DEFAULT_CONFIG, **overrides}
        self._engine_path = os.path.join(
            models_path, self.config["model_engine"]
        )

    @property
    def engine_path(self) -> str:
        return self._engine_path

    @property
    def engine_exists(self) -> bool:
        return os.path.exists(self._engine_path)

    @property
    def embedding_dim(self) -> int:
        return self.config["embedding_dim"]

    @staticmethod
    def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
        """L2 normalize an embedding vector."""
        norm = np.linalg.norm(embedding)
        if norm > 0:
            return embedding / norm
        return embedding

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two normalized embeddings."""
        return float(np.dot(a, b))

    @staticmethod
    def l2_to_cosine(l2_distance: float) -> float:
        """
        Convert L2 distance to cosine similarity.
        For L2-normalized vectors: cosine_sim = 1 - (L2^2 / 2)
        """
        return 1.0 - (l2_distance / 2.0)

    def search_faiss_index(
        self,
        index,
        embedding: np.ndarray,
        threshold: float,
        k: int = 1,
    ) -> List[FaceMatch]:
        """
        Search a FAISS index for matching faces.

        Args:
            index: FAISS index (GPU or CPU)
            embedding: 512-dim normalized face embedding
            threshold: Minimum cosine similarity for a match
            k: Number of nearest neighbors to return

        Returns:
            List of FaceMatch results above threshold
        """
        embedding_2d = embedding.reshape(1, -1).astype(np.float32)
        distances, indices = index.search(embedding_2d, k)

        matches = []
        for i in range(k):
            if indices[0][i] < 0:
                continue
            similarity = self.l2_to_cosine(distances[0][i])
            if similarity >= threshold:
                matches.append(FaceMatch(
                    index=int(indices[0][i]),
                    similarity=float(similarity),
                ))

        return matches

    def get_nvinfer_config(self, unique_id: int = 2) -> dict:
        """Get nvinfer SGIE configuration for DeepStream pipeline."""
        return {
            "model-engine-file": self._engine_path,
            "batch-size": self.config["batch_size"],
            "unique-id": unique_id,
            "network-mode": 2 if self.config["precision"] == "fp16" else 0,
            "network-type": 100,  # Custom (embedding output)
            "output-tensor-meta": 1,
        }

    def get_status(self) -> dict:
        return {
            "engine_path": self._engine_path,
            "engine_exists": self.engine_exists,
            "config": self.config,
        }
