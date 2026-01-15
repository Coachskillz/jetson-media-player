"""
Test Face Encoder Service

Tests the face_encoder service for face encoding extraction functionality.
Uses mocking since face_recognition requires actual face images.
"""

import os
import pytest
import numpy as np
from unittest.mock import patch, MagicMock
import tempfile

# Set testing environment
os.environ['FLASK_ENV'] = 'testing'


class TestExtractEncoding:
    """Tests for extract_encoding function."""

    @patch('central_hub.services.face_encoder.face_recognition')
    @patch('central_hub.services.face_encoder.validate_image_file')
    def test_extract_encoding_valid_image(self, mock_validate, mock_face_rec, app):
        """Test encoding extraction returns 512 bytes for valid face image."""
        from central_hub.services.face_encoder import extract_encoding

        # Setup mocks
        mock_validate.return_value = True
        mock_image = np.zeros((100, 100, 3), dtype=np.uint8)
        mock_face_rec.load_image_file.return_value = mock_image

        # Create mock encoding (128 float64 values - what face_recognition returns)
        mock_encoding = np.random.rand(128).astype(np.float64)
        mock_face_rec.face_encodings.return_value = [mock_encoding]

        with app.app_context():
            encoding = extract_encoding('/fake/test_face.jpg')

            # Verify 512 bytes (128 floats * 4 bytes per float32)
            assert encoding is not None
            assert len(encoding) == 512
            assert isinstance(encoding, bytes)

            # Verify face_recognition was called correctly
            mock_face_rec.load_image_file.assert_called_once_with('/fake/test_face.jpg')
            mock_face_rec.face_encodings.assert_called_once()

    @patch('central_hub.services.face_encoder.face_recognition')
    @patch('central_hub.services.face_encoder.validate_image_file')
    def test_extract_encoding_no_face(self, mock_validate, mock_face_rec, app):
        """Test encoding extraction raises NoFaceDetectedError for image without face."""
        from central_hub.services.face_encoder import (
            extract_encoding,
            NoFaceDetectedError
        )

        # Setup mocks - no faces detected
        mock_validate.return_value = True
        mock_image = np.zeros((100, 100, 3), dtype=np.uint8)
        mock_face_rec.load_image_file.return_value = mock_image
        mock_face_rec.face_encodings.return_value = []  # No faces

        with app.app_context():
            with pytest.raises(NoFaceDetectedError) as exc_info:
                extract_encoding('/fake/no_face.jpg')

            assert "No face detected" in str(exc_info.value)

    @patch('central_hub.services.face_encoder.validate_image_file')
    def test_extract_encoding_invalid_image(self, mock_validate, app):
        """Test encoding extraction raises InvalidImageError for corrupted/invalid file."""
        from central_hub.services.face_encoder import (
            extract_encoding,
            InvalidImageError
        )

        # Setup mock to raise InvalidImageError
        mock_validate.side_effect = InvalidImageError("Image file not found")

        with app.app_context():
            with pytest.raises(InvalidImageError) as exc_info:
                extract_encoding('/fake/invalid.xyz')

            assert "not found" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()

    @patch('central_hub.services.face_encoder.face_recognition')
    @patch('central_hub.services.face_encoder.validate_image_file')
    def test_extract_encoding_multiple_faces(self, mock_validate, mock_face_rec, app, caplog):
        """Test that multiple faces uses first face and logs warning."""
        from central_hub.services.face_encoder import extract_encoding
        import logging

        # Setup mocks - multiple faces detected
        mock_validate.return_value = True
        mock_image = np.zeros((100, 100, 3), dtype=np.uint8)
        mock_face_rec.load_image_file.return_value = mock_image

        # Multiple encodings
        mock_encoding1 = np.random.rand(128).astype(np.float64)
        mock_encoding2 = np.random.rand(128).astype(np.float64)
        mock_face_rec.face_encodings.return_value = [mock_encoding1, mock_encoding2]

        with app.app_context():
            with caplog.at_level(logging.WARNING):
                encoding = extract_encoding('/fake/multiple_faces.jpg')

            # Verify encoding is returned (uses first face)
            assert encoding is not None
            assert len(encoding) == 512

            # Verify warning was logged about multiple faces
            assert any("Multiple faces" in record.message or "multiple" in record.message.lower()
                      for record in caplog.records)


class TestValidateImageFile:
    """Tests for validate_image_file function."""

    def test_validate_image_file_not_found(self, app):
        """Test validation raises error for non-existent file."""
        from central_hub.services.face_encoder import (
            validate_image_file,
            InvalidImageError
        )

        with app.app_context():
            with pytest.raises(InvalidImageError) as exc_info:
                validate_image_file('/nonexistent/path/image.jpg')

            assert "not found" in str(exc_info.value).lower()

    def test_validate_image_file_unsupported_format(self, app):
        """Test validation raises error for unsupported format."""
        from central_hub.services.face_encoder import (
            validate_image_file,
            InvalidImageError
        )

        # Create temporary file with unsupported extension
        with tempfile.NamedTemporaryFile(suffix='.xyz', delete=False) as f:
            f.write(b'test data')
            tmp_path = f.name

        try:
            with app.app_context():
                with pytest.raises(InvalidImageError) as exc_info:
                    validate_image_file(tmp_path)

                assert "unsupported" in str(exc_info.value).lower()
        finally:
            os.unlink(tmp_path)

    def test_validate_image_file_valid(self, app):
        """Test validation returns True for valid image file."""
        from central_hub.services.face_encoder import validate_image_file

        # Create temporary file with valid extension
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            f.write(b'fake image data')
            tmp_path = f.name

        try:
            with app.app_context():
                result = validate_image_file(tmp_path)
                assert result is True
        finally:
            os.unlink(tmp_path)


class TestEncodingFromBytes:
    """Tests for encoding_from_bytes function."""

    def test_encoding_from_bytes_valid(self, app, mock_face_encoding):
        """Test converting valid encoding bytes back to numpy array."""
        from central_hub.services.face_encoder import encoding_from_bytes

        with app.app_context():
            array = encoding_from_bytes(mock_face_encoding)

            assert isinstance(array, np.ndarray)
            assert array.shape == (128,)
            assert array.dtype == np.float32

    def test_encoding_from_bytes_invalid_size(self, app):
        """Test error raised for invalid encoding size."""
        from central_hub.services.face_encoder import encoding_from_bytes

        # Wrong size bytes (not 512)
        invalid_bytes = b'x' * 100

        with app.app_context():
            with pytest.raises(ValueError) as exc_info:
                encoding_from_bytes(invalid_bytes)

            assert "invalid" in str(exc_info.value).lower() or "512" in str(exc_info.value)
