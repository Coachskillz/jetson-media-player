"""
Face Encoding Service

Extracts 128-dimensional face encodings from photos using the face_recognition
library (dlib). Encodings are stored as binary blobs (512 bytes) for efficient
database storage and FAISS compatibility.
"""

import logging
import os
from pathlib import Path
from typing import Optional, Tuple

import face_recognition
import numpy as np

from central_hub.config import get_config

logger = logging.getLogger(__name__)


class FaceEncodingError(Exception):
    """Base exception for face encoding errors."""
    pass


class NoFaceDetectedError(FaceEncodingError):
    """Raised when no face is detected in the image."""
    pass


class InvalidImageError(FaceEncodingError):
    """Raised when the image file is invalid or unsupported."""
    pass


def validate_image_file(file_path: str) -> bool:
    """
    Validate that the file exists and has a supported image extension.

    Args:
        file_path: Path to the image file.

    Returns:
        True if the file is valid.

    Raises:
        InvalidImageError: If the file doesn't exist or has unsupported format.
    """
    path = Path(file_path)

    if not path.exists():
        raise InvalidImageError(f"Image file not found: {file_path}")

    if not path.is_file():
        raise InvalidImageError(f"Path is not a file: {file_path}")

    config = get_config()
    extension = path.suffix.lower().lstrip('.')

    if extension not in config.ALLOWED_IMAGE_EXTENSIONS:
        allowed = ', '.join(sorted(config.ALLOWED_IMAGE_EXTENSIONS))
        raise InvalidImageError(
            f"Unsupported image format: {extension}. Supported formats: {allowed}"
        )

    # Check file size
    file_size = path.stat().st_size
    if file_size > config.MAX_CONTENT_LENGTH:
        max_mb = config.MAX_CONTENT_LENGTH / (1024 * 1024)
        raise InvalidImageError(f"File size exceeds maximum allowed ({max_mb}MB)")

    return True


def extract_encoding(image_path: str) -> bytes:
    """
    Extract 128-dimensional face encoding from an image file.

    Uses face_recognition library (dlib) to detect faces and extract
    encodings. The encoding is converted to float32 and stored as bytes
    for FAISS compatibility.

    Args:
        image_path: Path to the image file (jpg, png supported).

    Returns:
        Face encoding as bytes (512 bytes = 128 dimensions * 4 bytes per float32).

    Raises:
        InvalidImageError: If the image file is invalid or unsupported.
        NoFaceDetectedError: If no face is detected in the image.
    """
    # Validate the image file first
    validate_image_file(image_path)

    config = get_config()

    try:
        # Load the image
        image = face_recognition.load_image_file(image_path)
    except Exception as e:
        logger.error(f"Failed to load image {image_path}: {e}")
        raise InvalidImageError(f"Failed to load image: {e}")

    try:
        # Extract face encodings with configured jitter for accuracy
        encodings = face_recognition.face_encodings(
            image,
            num_jitters=config.FACE_ENCODING_NUM_JITTERS
        )
    except Exception as e:
        logger.error(f"Face encoding extraction failed for {image_path}: {e}")
        raise FaceEncodingError(f"Face encoding extraction failed: {e}")

    if not encodings:
        logger.warning(f"No face detected in image: {image_path}")
        raise NoFaceDetectedError("No face detected in uploaded image")

    # Log warning if multiple faces detected (use first face)
    if len(encodings) > 1:
        logger.warning(
            f"Multiple faces ({len(encodings)}) detected in {image_path}, "
            "using first detected face"
        )

    # Convert to float32 (FAISS requirement) and return as bytes
    encoding = encodings[0].astype(np.float32)

    # Verify encoding dimensions
    if encoding.shape[0] != config.FACE_ENCODING_DIMENSIONS:
        raise FaceEncodingError(
            f"Unexpected encoding dimensions: {encoding.shape[0]}, "
            f"expected {config.FACE_ENCODING_DIMENSIONS}"
        )

    return encoding.tobytes()


def extract_encoding_from_bytes(image_data: bytes) -> bytes:
    """
    Extract face encoding from image bytes.

    Useful for processing uploaded files without saving to disk first.

    Args:
        image_data: Raw image bytes.

    Returns:
        Face encoding as bytes (512 bytes).

    Raises:
        InvalidImageError: If the image data is invalid.
        NoFaceDetectedError: If no face is detected in the image.
    """
    import tempfile

    config = get_config()

    # Check size limit
    if len(image_data) > config.MAX_CONTENT_LENGTH:
        max_mb = config.MAX_CONTENT_LENGTH / (1024 * 1024)
        raise InvalidImageError(f"Image data exceeds maximum allowed ({max_mb}MB)")

    # Write to temporary file for face_recognition processing
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
        tmp.write(image_data)
        tmp_path = tmp.name

    try:
        # Load the image
        try:
            image = face_recognition.load_image_file(tmp_path)
        except Exception as e:
            logger.error(f"Failed to load image from bytes: {e}")
            raise InvalidImageError(f"Failed to load image: {e}")

        try:
            # Extract face encodings
            encodings = face_recognition.face_encodings(
                image,
                num_jitters=config.FACE_ENCODING_NUM_JITTERS
            )
        except Exception as e:
            logger.error(f"Face encoding extraction failed: {e}")
            raise FaceEncodingError(f"Face encoding extraction failed: {e}")

        if not encodings:
            logger.warning("No face detected in image bytes")
            raise NoFaceDetectedError("No face detected in uploaded image")

        # Log warning if multiple faces detected
        if len(encodings) > 1:
            logger.warning(
                f"Multiple faces ({len(encodings)}) detected, "
                "using first detected face"
            )

        # Convert to float32 and return as bytes
        encoding = encodings[0].astype(np.float32)

        if encoding.shape[0] != config.FACE_ENCODING_DIMENSIONS:
            raise FaceEncodingError(
                f"Unexpected encoding dimensions: {encoding.shape[0]}, "
                f"expected {config.FACE_ENCODING_DIMENSIONS}"
            )

        return encoding.tobytes()
    finally:
        # Clean up temporary file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def encoding_from_bytes(encoding_bytes: bytes) -> np.ndarray:
    """
    Convert stored encoding bytes back to numpy array.

    Useful for FAISS operations and similarity comparisons.

    Args:
        encoding_bytes: Face encoding as bytes (512 bytes).

    Returns:
        Face encoding as numpy float32 array (128 dimensions).

    Raises:
        ValueError: If the encoding bytes are invalid.
    """
    config = get_config()

    if len(encoding_bytes) != config.FACE_ENCODING_BYTES:
        raise ValueError(
            f"Invalid encoding size: {len(encoding_bytes)} bytes, "
            f"expected {config.FACE_ENCODING_BYTES}"
        )

    return np.frombuffer(encoding_bytes, dtype=np.float32)


def get_face_locations(image_path: str) -> list:
    """
    Get face locations in an image for debugging/preview purposes.

    Args:
        image_path: Path to the image file.

    Returns:
        List of face locations as (top, right, bottom, left) tuples.

    Raises:
        InvalidImageError: If the image file is invalid.
    """
    validate_image_file(image_path)

    try:
        image = face_recognition.load_image_file(image_path)
        return face_recognition.face_locations(image)
    except Exception as e:
        logger.error(f"Failed to get face locations for {image_path}: {e}")
        raise InvalidImageError(f"Failed to process image: {e}")
