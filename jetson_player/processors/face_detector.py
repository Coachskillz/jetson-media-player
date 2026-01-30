"""
Face Detector wrapper for RetinaFace TensorRT engine.

Provides a high-level interface to the RetinaFace face detection model
used by both safety and commercial pipelines.
"""

import os
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class FaceDetection:
    """A detected face with bounding box and confidence."""
    x: int
    y: int
    width: int
    height: int
    confidence: float
    track_id: Optional[int] = None

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple:
        return (self.x + self.width // 2, self.y + self.height // 2)


class FaceDetector:
    """
    RetinaFace face detection wrapper.

    In the DeepStream pipeline, face detection is handled by nvinfer (PGIE).
    This class provides configuration and utility methods for the detector.
    The actual inference runs inside the DeepStream pipeline.
    """

    DEFAULT_CONFIG = {
        "model_engine": "retinaface_fp16.engine",
        "confidence_threshold": 0.7,
        "nms_iou_threshold": 0.5,
        "min_face_width": 64,
        "min_face_height": 64,
        "input_width": 640,
        "input_height": 640,
        "precision": "fp16",
        "batch_size": 1,
        "process_interval": 2,
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

    def get_nvinfer_config(self) -> dict:
        """
        Get nvinfer configuration parameters for DeepStream pipeline.

        Returns dict suitable for setting nvinfer element properties.
        """
        return {
            "model-engine-file": self._engine_path,
            "batch-size": self.config["batch_size"],
            "interval": self.config["process_interval"],
            "unique-id": 1,
            "network-mode": 2 if self.config["precision"] == "fp16" else 0,
        }

    def filter_detections(self, detections: List[FaceDetection]) -> List[FaceDetection]:
        """
        Filter detections by minimum size and confidence.

        Args:
            detections: Raw detections from the pipeline

        Returns:
            Filtered list of valid face detections
        """
        min_w = self.config["min_face_width"]
        min_h = self.config["min_face_height"]
        threshold = self.config["confidence_threshold"]

        return [
            d for d in detections
            if d.width >= min_w and d.height >= min_h and d.confidence >= threshold
        ]

    def get_status(self) -> dict:
        return {
            "engine_path": self._engine_path,
            "engine_exists": self.engine_exists,
            "config": self.config,
        }
