"""
Tests for FaceRecognizer.

Covers embedding normalization, cosine similarity,
L2-to-cosine conversion, and FAISS search utilities.
"""

import numpy as np
import pytest
from unittest.mock import MagicMock

from jetson_player.processors.face_recognizer import FaceRecognizer, FaceMatch


class TestNormalizeEmbedding:
    """Test L2 normalization of embeddings."""

    def test_normalizes_to_unit_length(self):
        embedding = np.random.randn(512).astype(np.float32)
        normalized = FaceRecognizer.normalize_embedding(embedding)
        norm = np.linalg.norm(normalized)
        assert abs(norm - 1.0) < 1e-5

    def test_zero_vector_returns_zero(self):
        embedding = np.zeros(512, dtype=np.float32)
        normalized = FaceRecognizer.normalize_embedding(embedding)
        assert np.allclose(normalized, 0.0)

    def test_already_normalized_unchanged(self):
        embedding = np.random.randn(512).astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)
        normalized = FaceRecognizer.normalize_embedding(embedding)
        assert np.allclose(embedding, normalized, atol=1e-5)


class TestCosineSimilarity:
    """Test cosine similarity computation."""

    def test_identical_vectors_similarity_one(self):
        a = np.random.randn(512).astype(np.float32)
        a = a / np.linalg.norm(a)
        sim = FaceRecognizer.cosine_similarity(a, a)
        assert abs(sim - 1.0) < 1e-5

    def test_opposite_vectors_similarity_negative_one(self):
        a = np.random.randn(512).astype(np.float32)
        a = a / np.linalg.norm(a)
        sim = FaceRecognizer.cosine_similarity(a, -a)
        assert abs(sim - (-1.0)) < 1e-5

    def test_orthogonal_vectors_similarity_zero(self):
        a = np.zeros(512, dtype=np.float32)
        b = np.zeros(512, dtype=np.float32)
        a[0] = 1.0
        b[1] = 1.0
        sim = FaceRecognizer.cosine_similarity(a, b)
        assert abs(sim) < 1e-5


class TestL2ToCosine:
    """Test L2 distance to cosine similarity conversion."""

    def test_zero_distance_gives_similarity_one(self):
        assert FaceRecognizer.l2_to_cosine(0.0) == 1.0

    def test_max_l2_gives_similarity_zero(self):
        # For normalized vectors, max L2 distance is 2.0
        assert FaceRecognizer.l2_to_cosine(2.0) == 0.0

    def test_intermediate_distance(self):
        # L2 = 1.0 -> cosine = 0.5
        assert abs(FaceRecognizer.l2_to_cosine(1.0) - 0.5) < 1e-5


class TestSearchFaissIndex:
    """Test FAISS index search with mock index."""

    def test_returns_matches_above_threshold(self):
        recognizer = FaceRecognizer()

        # Mock FAISS index
        mock_index = MagicMock()
        # L2 distance 0.5 -> cosine ~0.75
        mock_index.search.return_value = (
            np.array([[0.5]], dtype=np.float32),
            np.array([[42]], dtype=np.int64),
        )

        embedding = np.random.randn(512).astype(np.float32)
        matches = recognizer.search_faiss_index(
            mock_index, embedding, threshold=0.7, k=1
        )

        assert len(matches) == 1
        assert matches[0].index == 42
        assert matches[0].similarity > 0.7

    def test_filters_below_threshold(self):
        recognizer = FaceRecognizer()

        mock_index = MagicMock()
        # L2 distance 1.5 -> cosine 0.25 (below 0.6 threshold)
        mock_index.search.return_value = (
            np.array([[1.5]], dtype=np.float32),
            np.array([[10]], dtype=np.int64),
        )

        embedding = np.random.randn(512).astype(np.float32)
        matches = recognizer.search_faiss_index(
            mock_index, embedding, threshold=0.6, k=1
        )

        assert len(matches) == 0

    def test_handles_negative_index(self):
        """FAISS returns -1 for empty slots."""
        recognizer = FaceRecognizer()

        mock_index = MagicMock()
        mock_index.search.return_value = (
            np.array([[0.0]], dtype=np.float32),
            np.array([[-1]], dtype=np.int64),
        )

        embedding = np.random.randn(512).astype(np.float32)
        matches = recognizer.search_faiss_index(
            mock_index, embedding, threshold=0.5, k=1
        )

        assert len(matches) == 0


class TestFaceRecognizerConfig:
    """Test configuration and status."""

    def test_default_config(self):
        recognizer = FaceRecognizer()
        assert recognizer.config["embedding_dim"] == 512
        assert recognizer.config["precision"] == "fp16"
        assert recognizer.config["batch_size"] == 16

    def test_config_override(self):
        recognizer = FaceRecognizer(batch_size=32, precision="int8")
        assert recognizer.config["batch_size"] == 32
        assert recognizer.config["precision"] == "int8"

    def test_engine_path(self):
        recognizer = FaceRecognizer(models_path="/tmp/models")
        assert recognizer.engine_path == "/tmp/models/arcface_fp16.engine"

    def test_nvinfer_config(self):
        recognizer = FaceRecognizer()
        cfg = recognizer.get_nvinfer_config(unique_id=3)
        assert cfg["unique-id"] == 3
        assert cfg["output-tensor-meta"] == 1
        assert cfg["network-mode"] == 2  # fp16

    def test_status_dict(self):
        recognizer = FaceRecognizer()
        status = recognizer.get_status()
        assert "engine_path" in status
        assert "engine_exists" in status
        assert "config" in status
