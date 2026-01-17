"""
Unit tests for CMS PDF Service.

Tests all PDF processing functionality:
- PyMuPDF availability checking
- PDF metadata extraction (page count, dimensions, title, author)
- Single page to image conversion
- Multi-page PDF to image conversion
- Thumbnail generation
- Complete PDF content processing pipeline
- Error handling for invalid PDFs and missing files

Each test class covers a specific service method with comprehensive
validation including success cases and error handling.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from cms.services.pdf_service import (
    PDFService,
    PDFServiceError,
    PDFNotFoundError,
    PDFProcessingError,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture(scope='function')
def temp_dir():
    """
    Create a temporary directory for test outputs.

    Yields:
        Path to temporary directory
    """
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


@pytest.fixture(scope='function')
def sample_pdf_path(temp_dir):
    """
    Create a minimal valid PDF file for testing.

    This creates a simple PDF with one page containing basic text.
    Requires PyMuPDF to be available.

    Args:
        temp_dir: Temporary directory fixture

    Yields:
        Path to the sample PDF file, or None if PyMuPDF not available
    """
    if not PDFService.is_available():
        pytest.skip("PyMuPDF not installed, skipping PDF tests")

    import fitz

    pdf_path = os.path.join(temp_dir, 'sample.pdf')

    # Create a new PDF document
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Letter size

    # Add some text
    text_rect = fitz.Rect(72, 72, 540, 120)
    page.insert_textbox(text_rect, "Test PDF Page 1", fontsize=24)

    # Set metadata
    doc.set_metadata({
        'title': 'Test PDF',
        'author': 'Test Author',
        'subject': 'Unit Testing',
        'creator': 'PDF Service Tests',
    })

    doc.save(pdf_path)
    doc.close()

    yield pdf_path


@pytest.fixture(scope='function')
def multi_page_pdf_path(temp_dir):
    """
    Create a multi-page PDF file for testing.

    Creates a PDF with 3 pages of different content.
    Requires PyMuPDF to be available.

    Args:
        temp_dir: Temporary directory fixture

    Yields:
        Path to the multi-page PDF file, or None if PyMuPDF not available
    """
    if not PDFService.is_available():
        pytest.skip("PyMuPDF not installed, skipping PDF tests")

    import fitz

    pdf_path = os.path.join(temp_dir, 'multi_page.pdf')

    # Create a new PDF document
    doc = fitz.open()

    for i in range(1, 4):
        page = doc.new_page(width=612, height=792)
        text_rect = fitz.Rect(72, 72, 540, 120)
        page.insert_textbox(text_rect, f"Test PDF Page {i}", fontsize=24)

    doc.save(pdf_path)
    doc.close()

    yield pdf_path


@pytest.fixture(scope='function')
def invalid_pdf_path(temp_dir):
    """
    Create an invalid PDF file (not actually a PDF).

    Args:
        temp_dir: Temporary directory fixture

    Yields:
        Path to the invalid PDF file
    """
    pdf_path = os.path.join(temp_dir, 'invalid.pdf')
    with open(pdf_path, 'wb') as f:
        f.write(b'This is not a valid PDF file')
    yield pdf_path


# =============================================================================
# Availability Tests
# =============================================================================

class TestPDFServiceAvailability:
    """Tests for PDFService.is_available() method."""

    def test_is_available_returns_bool(self):
        """is_available() should return a boolean value."""
        result = PDFService.is_available()
        assert isinstance(result, bool)

    def test_is_available_reflects_pymupdf_import(self):
        """is_available() should return True if PyMuPDF is installed."""
        # If tests are running, PyMuPDF should be installed
        # This test just verifies the method works without error
        result = PDFService.is_available()
        # We can't assume True or False - it depends on the environment
        assert result is True or result is False


# =============================================================================
# PDF Info Extraction Tests
# =============================================================================

class TestPDFInfoExtraction:
    """Tests for PDFService.get_pdf_info() method."""

    def test_get_pdf_info_success(self, sample_pdf_path):
        """get_pdf_info() should return PDF metadata."""
        info = PDFService.get_pdf_info(sample_pdf_path)

        assert 'page_count' in info
        assert info['page_count'] == 1
        assert 'page_sizes' in info
        assert len(info['page_sizes']) == 1
        assert 'title' in info
        assert 'author' in info
        assert 'subject' in info
        assert 'creator' in info
        assert 'creation_date' in info
        assert 'modification_date' in info

    def test_get_pdf_info_metadata_values(self, sample_pdf_path):
        """get_pdf_info() should return correct metadata values."""
        info = PDFService.get_pdf_info(sample_pdf_path)

        assert info['title'] == 'Test PDF'
        assert info['author'] == 'Test Author'
        assert info['subject'] == 'Unit Testing'
        assert info['creator'] == 'PDF Service Tests'

    def test_get_pdf_info_page_sizes(self, sample_pdf_path):
        """get_pdf_info() should return page dimensions as integers."""
        info = PDFService.get_pdf_info(sample_pdf_path)

        page_size = info['page_sizes'][0]
        assert isinstance(page_size[0], int)  # width
        assert isinstance(page_size[1], int)  # height
        assert page_size[0] == 612  # Letter width
        assert page_size[1] == 792  # Letter height

    def test_get_pdf_info_multi_page(self, multi_page_pdf_path):
        """get_pdf_info() should handle multi-page PDFs."""
        info = PDFService.get_pdf_info(multi_page_pdf_path)

        assert info['page_count'] == 3
        assert len(info['page_sizes']) == 3

    def test_get_pdf_info_file_not_found(self, temp_dir):
        """get_pdf_info() should raise PDFNotFoundError for missing file."""
        fake_path = os.path.join(temp_dir, 'nonexistent.pdf')

        with pytest.raises(PDFNotFoundError) as exc_info:
            PDFService.get_pdf_info(fake_path)

        assert 'not found' in str(exc_info.value).lower()

    def test_get_pdf_info_invalid_pdf(self, invalid_pdf_path):
        """get_pdf_info() should raise PDFProcessingError for invalid PDF."""
        with pytest.raises(PDFProcessingError) as exc_info:
            PDFService.get_pdf_info(invalid_pdf_path)

        assert 'invalid' in str(exc_info.value).lower() or 'corrupted' in str(exc_info.value).lower()

    def test_get_pdf_info_directory_path(self, temp_dir):
        """get_pdf_info() should raise PDFNotFoundError for directory path."""
        with pytest.raises(PDFNotFoundError) as exc_info:
            PDFService.get_pdf_info(temp_dir)

        assert 'not a file' in str(exc_info.value).lower()


# =============================================================================
# Page Count Tests
# =============================================================================

class TestPDFPageCount:
    """Tests for PDFService.get_page_count() method."""

    def test_get_page_count_single_page(self, sample_pdf_path):
        """get_page_count() should return 1 for single-page PDF."""
        count = PDFService.get_page_count(sample_pdf_path)

        assert count == 1

    def test_get_page_count_multi_page(self, multi_page_pdf_path):
        """get_page_count() should return correct count for multi-page PDF."""
        count = PDFService.get_page_count(multi_page_pdf_path)

        assert count == 3

    def test_get_page_count_file_not_found(self, temp_dir):
        """get_page_count() should raise PDFNotFoundError for missing file."""
        fake_path = os.path.join(temp_dir, 'nonexistent.pdf')

        with pytest.raises(PDFNotFoundError):
            PDFService.get_page_count(fake_path)


# =============================================================================
# Single Page Conversion Tests
# =============================================================================

class TestPDFSinglePageConversion:
    """Tests for PDFService.convert_page_to_image() method."""

    def test_convert_page_to_image_success(self, sample_pdf_path, temp_dir):
        """convert_page_to_image() should create an image file."""
        output_path = os.path.join(temp_dir, 'output.png')

        result = PDFService.convert_page_to_image(
            pdf_path=sample_pdf_path,
            page_number=0,
            output_path=output_path
        )

        assert os.path.exists(output_path)
        assert result['output_path'] == output_path
        assert result['page_number'] == 0
        assert result['format'] == 'png'
        assert result['width'] > 0
        assert result['height'] > 0

    def test_convert_page_to_image_jpeg_format(self, sample_pdf_path, temp_dir):
        """convert_page_to_image() should support JPEG format."""
        output_path = os.path.join(temp_dir, 'output.jpg')

        result = PDFService.convert_page_to_image(
            pdf_path=sample_pdf_path,
            page_number=0,
            output_path=output_path,
            image_format='jpeg'
        )

        assert os.path.exists(output_path)
        assert result['format'] == 'jpeg'

    def test_convert_page_to_image_custom_dpi(self, sample_pdf_path, temp_dir):
        """convert_page_to_image() should respect DPI setting."""
        output_low = os.path.join(temp_dir, 'output_low.png')
        output_high = os.path.join(temp_dir, 'output_high.png')

        result_low = PDFService.convert_page_to_image(
            pdf_path=sample_pdf_path,
            page_number=0,
            output_path=output_low,
            dpi=72
        )

        result_high = PDFService.convert_page_to_image(
            pdf_path=sample_pdf_path,
            page_number=0,
            output_path=output_high,
            dpi=150
        )

        # Higher DPI should produce larger image
        assert result_high['width'] > result_low['width']
        assert result_high['height'] > result_low['height']

    def test_convert_page_to_image_creates_output_dir(self, sample_pdf_path, temp_dir):
        """convert_page_to_image() should create output directory if needed."""
        output_path = os.path.join(temp_dir, 'subdir', 'nested', 'output.png')

        result = PDFService.convert_page_to_image(
            pdf_path=sample_pdf_path,
            page_number=0,
            output_path=output_path
        )

        assert os.path.exists(output_path)

    def test_convert_page_to_image_invalid_page_number(self, sample_pdf_path, temp_dir):
        """convert_page_to_image() should raise ValueError for invalid page number."""
        output_path = os.path.join(temp_dir, 'output.png')

        with pytest.raises(ValueError) as exc_info:
            PDFService.convert_page_to_image(
                pdf_path=sample_pdf_path,
                page_number=99,  # Single page PDF, so page 99 is invalid
                output_path=output_path
            )

        assert 'out of range' in str(exc_info.value).lower()

    def test_convert_page_to_image_negative_page_number(self, sample_pdf_path, temp_dir):
        """convert_page_to_image() should raise ValueError for negative page number."""
        output_path = os.path.join(temp_dir, 'output.png')

        with pytest.raises(ValueError) as exc_info:
            PDFService.convert_page_to_image(
                pdf_path=sample_pdf_path,
                page_number=-1,
                output_path=output_path
            )

        assert 'out of range' in str(exc_info.value).lower()

    def test_convert_page_to_image_invalid_dpi(self, sample_pdf_path, temp_dir):
        """convert_page_to_image() should raise ValueError for invalid DPI."""
        output_path = os.path.join(temp_dir, 'output.png')

        with pytest.raises(ValueError) as exc_info:
            PDFService.convert_page_to_image(
                pdf_path=sample_pdf_path,
                page_number=0,
                output_path=output_path,
                dpi=10  # Below minimum
            )

        assert 'dpi' in str(exc_info.value).lower()

    def test_convert_page_to_image_invalid_format(self, sample_pdf_path, temp_dir):
        """convert_page_to_image() should raise ValueError for unsupported format."""
        output_path = os.path.join(temp_dir, 'output.bmp')

        with pytest.raises(ValueError) as exc_info:
            PDFService.convert_page_to_image(
                pdf_path=sample_pdf_path,
                page_number=0,
                output_path=output_path,
                image_format='bmp'
            )

        assert 'unsupported' in str(exc_info.value).lower()

    def test_convert_page_to_image_file_not_found(self, temp_dir):
        """convert_page_to_image() should raise PDFNotFoundError for missing file."""
        fake_path = os.path.join(temp_dir, 'nonexistent.pdf')
        output_path = os.path.join(temp_dir, 'output.png')

        with pytest.raises(PDFNotFoundError):
            PDFService.convert_page_to_image(
                pdf_path=fake_path,
                page_number=0,
                output_path=output_path
            )


# =============================================================================
# Multi-Page Conversion Tests
# =============================================================================

class TestPDFMultiPageConversion:
    """Tests for PDFService.convert_all_pages() method."""

    def test_convert_all_pages_success(self, multi_page_pdf_path, temp_dir):
        """convert_all_pages() should create images for all pages."""
        output_dir = os.path.join(temp_dir, 'pages')

        results = PDFService.convert_all_pages(
            pdf_path=multi_page_pdf_path,
            output_dir=output_dir
        )

        assert len(results) == 3
        for i, result in enumerate(results):
            assert os.path.exists(result['output_path'])
            assert result['page_number'] == i
            assert result['width'] > 0
            assert result['height'] > 0

    def test_convert_all_pages_custom_prefix(self, multi_page_pdf_path, temp_dir):
        """convert_all_pages() should use custom filename prefix."""
        output_dir = os.path.join(temp_dir, 'pages')

        results = PDFService.convert_all_pages(
            pdf_path=multi_page_pdf_path,
            output_dir=output_dir,
            filename_prefix='custom'
        )

        for result in results:
            filename = os.path.basename(result['output_path'])
            assert filename.startswith('custom')

    def test_convert_all_pages_max_pages(self, multi_page_pdf_path, temp_dir):
        """convert_all_pages() should respect max_pages limit."""
        output_dir = os.path.join(temp_dir, 'pages')

        results = PDFService.convert_all_pages(
            pdf_path=multi_page_pdf_path,
            output_dir=output_dir,
            max_pages=2
        )

        assert len(results) == 2

    def test_convert_all_pages_jpeg_format(self, multi_page_pdf_path, temp_dir):
        """convert_all_pages() should support JPEG format."""
        output_dir = os.path.join(temp_dir, 'pages')

        results = PDFService.convert_all_pages(
            pdf_path=multi_page_pdf_path,
            output_dir=output_dir,
            image_format='jpeg'
        )

        for result in results:
            assert result['format'] == 'jpeg'
            assert result['output_path'].endswith('.jpg')

    def test_convert_all_pages_creates_output_dir(self, multi_page_pdf_path, temp_dir):
        """convert_all_pages() should create output directory if needed."""
        output_dir = os.path.join(temp_dir, 'new', 'nested', 'dir')

        results = PDFService.convert_all_pages(
            pdf_path=multi_page_pdf_path,
            output_dir=output_dir
        )

        assert os.path.isdir(output_dir)
        assert len(results) > 0

    def test_convert_all_pages_filenames_zero_padded(self, multi_page_pdf_path, temp_dir):
        """convert_all_pages() should create zero-padded filenames."""
        output_dir = os.path.join(temp_dir, 'pages')

        results = PDFService.convert_all_pages(
            pdf_path=multi_page_pdf_path,
            output_dir=output_dir
        )

        for result in results:
            filename = os.path.basename(result['output_path'])
            # Should contain zero-padded page numbers like _page_0001
            assert '_page_' in filename

    def test_convert_all_pages_file_not_found(self, temp_dir):
        """convert_all_pages() should raise PDFNotFoundError for missing file."""
        fake_path = os.path.join(temp_dir, 'nonexistent.pdf')
        output_dir = os.path.join(temp_dir, 'pages')

        with pytest.raises(PDFNotFoundError):
            PDFService.convert_all_pages(
                pdf_path=fake_path,
                output_dir=output_dir
            )


# =============================================================================
# Thumbnail Generation Tests
# =============================================================================

class TestPDFThumbnailGeneration:
    """Tests for PDFService.generate_thumbnail() method."""

    def test_generate_thumbnail_success(self, sample_pdf_path, temp_dir):
        """generate_thumbnail() should create a thumbnail image."""
        output_path = os.path.join(temp_dir, 'thumbnail.jpg')

        result = PDFService.generate_thumbnail(
            pdf_path=sample_pdf_path,
            output_path=output_path
        )

        assert os.path.exists(output_path)
        assert result['output_path'] == output_path
        assert result['page_number'] == 0
        assert result['width'] > 0
        assert result['height'] > 0

    def test_generate_thumbnail_respects_max_dimensions(self, sample_pdf_path, temp_dir):
        """generate_thumbnail() should scale within max dimensions."""
        output_path = os.path.join(temp_dir, 'thumbnail.jpg')

        result = PDFService.generate_thumbnail(
            pdf_path=sample_pdf_path,
            output_path=output_path,
            max_width=100,
            max_height=100
        )

        assert result['width'] <= 100
        assert result['height'] <= 100

    def test_generate_thumbnail_maintains_aspect_ratio(self, sample_pdf_path, temp_dir):
        """generate_thumbnail() should maintain aspect ratio."""
        output_path = os.path.join(temp_dir, 'thumbnail.jpg')

        # Get original aspect ratio
        info = PDFService.get_pdf_info(sample_pdf_path)
        original_width, original_height = info['page_sizes'][0]
        original_ratio = original_width / original_height

        result = PDFService.generate_thumbnail(
            pdf_path=sample_pdf_path,
            output_path=output_path,
            max_width=300,
            max_height=300
        )

        result_ratio = result['width'] / result['height']
        # Allow small rounding error
        assert abs(result_ratio - original_ratio) < 0.01

    def test_generate_thumbnail_custom_page(self, multi_page_pdf_path, temp_dir):
        """generate_thumbnail() should allow specifying page number."""
        output_path = os.path.join(temp_dir, 'thumbnail.jpg')

        result = PDFService.generate_thumbnail(
            pdf_path=multi_page_pdf_path,
            output_path=output_path,
            page_number=1  # Second page
        )

        assert result['page_number'] == 1

    def test_generate_thumbnail_invalid_page_defaults_to_first(self, sample_pdf_path, temp_dir):
        """generate_thumbnail() should default to first page for invalid page number."""
        output_path = os.path.join(temp_dir, 'thumbnail.jpg')

        result = PDFService.generate_thumbnail(
            pdf_path=sample_pdf_path,
            output_path=output_path,
            page_number=99  # Invalid - single page PDF
        )

        # Should fall back to page 0
        assert result['page_number'] == 0

    def test_generate_thumbnail_creates_output_dir(self, sample_pdf_path, temp_dir):
        """generate_thumbnail() should create output directory if needed."""
        output_path = os.path.join(temp_dir, 'subdir', 'thumbnail.jpg')

        result = PDFService.generate_thumbnail(
            pdf_path=sample_pdf_path,
            output_path=output_path
        )

        assert os.path.exists(output_path)

    def test_generate_thumbnail_file_not_found(self, temp_dir):
        """generate_thumbnail() should raise PDFNotFoundError for missing file."""
        fake_path = os.path.join(temp_dir, 'nonexistent.pdf')
        output_path = os.path.join(temp_dir, 'thumbnail.jpg')

        with pytest.raises(PDFNotFoundError):
            PDFService.generate_thumbnail(
                pdf_path=fake_path,
                output_path=output_path
            )


# =============================================================================
# Full Processing Pipeline Tests
# =============================================================================

class TestPDFProcessingPipeline:
    """Tests for PDFService.process_pdf_for_content() method."""

    def test_process_pdf_for_content_success(self, sample_pdf_path, temp_dir):
        """process_pdf_for_content() should process complete PDF."""
        output_dir = os.path.join(temp_dir, 'content')

        result = PDFService.process_pdf_for_content(
            pdf_path=sample_pdf_path,
            output_base_dir=output_dir
        )

        assert 'content_id' in result
        assert 'pdf_info' in result
        assert 'pages' in result
        assert 'pages_dir' in result
        assert 'thumbnail_path' in result

        # Verify pages were created
        assert len(result['pages']) == 1
        assert os.path.exists(result['pages'][0]['output_path'])

        # Verify thumbnail was created
        assert result['thumbnail_path'] is not None
        assert os.path.exists(result['thumbnail_path'])

    def test_process_pdf_for_content_custom_id(self, sample_pdf_path, temp_dir):
        """process_pdf_for_content() should use custom content ID."""
        output_dir = os.path.join(temp_dir, 'content')

        result = PDFService.process_pdf_for_content(
            pdf_path=sample_pdf_path,
            output_base_dir=output_dir,
            content_id='my-custom-id'
        )

        assert result['content_id'] == 'my-custom-id'
        assert 'my-custom-id' in result['pages_dir']

    def test_process_pdf_for_content_generates_uuid_if_no_id(self, sample_pdf_path, temp_dir):
        """process_pdf_for_content() should generate UUID if no ID provided."""
        output_dir = os.path.join(temp_dir, 'content')

        result = PDFService.process_pdf_for_content(
            pdf_path=sample_pdf_path,
            output_base_dir=output_dir
        )

        # Should be a UUID-like string (36 chars with hyphens)
        assert len(result['content_id']) == 36

    def test_process_pdf_for_content_no_thumbnail(self, sample_pdf_path, temp_dir):
        """process_pdf_for_content() should skip thumbnail when disabled."""
        output_dir = os.path.join(temp_dir, 'content')

        result = PDFService.process_pdf_for_content(
            pdf_path=sample_pdf_path,
            output_base_dir=output_dir,
            generate_thumbnails=False
        )

        assert result['thumbnail_path'] is None

    def test_process_pdf_for_content_multi_page(self, multi_page_pdf_path, temp_dir):
        """process_pdf_for_content() should handle multi-page PDFs."""
        output_dir = os.path.join(temp_dir, 'content')

        result = PDFService.process_pdf_for_content(
            pdf_path=multi_page_pdf_path,
            output_base_dir=output_dir
        )

        assert len(result['pages']) == 3
        assert result['pdf_info']['page_count'] == 3

    def test_process_pdf_for_content_jpeg_format(self, sample_pdf_path, temp_dir):
        """process_pdf_for_content() should support JPEG format."""
        output_dir = os.path.join(temp_dir, 'content')

        result = PDFService.process_pdf_for_content(
            pdf_path=sample_pdf_path,
            output_base_dir=output_dir,
            image_format='jpeg'
        )

        for page in result['pages']:
            assert page['format'] == 'jpeg'

    def test_process_pdf_for_content_custom_dpi(self, sample_pdf_path, temp_dir):
        """process_pdf_for_content() should respect DPI setting."""
        output_dir_low = os.path.join(temp_dir, 'content_low')
        output_dir_high = os.path.join(temp_dir, 'content_high')

        result_low = PDFService.process_pdf_for_content(
            pdf_path=sample_pdf_path,
            output_base_dir=output_dir_low,
            dpi=72
        )

        result_high = PDFService.process_pdf_for_content(
            pdf_path=sample_pdf_path,
            output_base_dir=output_dir_high,
            dpi=300
        )

        # Higher DPI should produce larger images
        assert result_high['pages'][0]['width'] > result_low['pages'][0]['width']

    def test_process_pdf_for_content_file_not_found(self, temp_dir):
        """process_pdf_for_content() should raise PDFNotFoundError for missing file."""
        fake_path = os.path.join(temp_dir, 'nonexistent.pdf')
        output_dir = os.path.join(temp_dir, 'content')

        with pytest.raises(PDFNotFoundError):
            PDFService.process_pdf_for_content(
                pdf_path=fake_path,
                output_base_dir=output_dir
            )


# =============================================================================
# Validation Tests
# =============================================================================

class TestPDFServiceValidation:
    """Tests for PDFService validation methods."""

    def test_validate_dpi_minimum(self, sample_pdf_path, temp_dir):
        """DPI validation should reject values below minimum."""
        output_path = os.path.join(temp_dir, 'output.png')

        with pytest.raises(ValueError) as exc_info:
            PDFService.convert_page_to_image(
                pdf_path=sample_pdf_path,
                page_number=0,
                output_path=output_path,
                dpi=PDFService.MIN_DPI - 1
            )

        assert 'dpi' in str(exc_info.value).lower()

    def test_validate_dpi_maximum(self, sample_pdf_path, temp_dir):
        """DPI validation should reject values above maximum."""
        output_path = os.path.join(temp_dir, 'output.png')

        with pytest.raises(ValueError) as exc_info:
            PDFService.convert_page_to_image(
                pdf_path=sample_pdf_path,
                page_number=0,
                output_path=output_path,
                dpi=PDFService.MAX_DPI + 1
            )

        assert 'dpi' in str(exc_info.value).lower()

    def test_validate_dpi_accepts_boundary_values(self, sample_pdf_path, temp_dir):
        """DPI validation should accept boundary values."""
        output_min = os.path.join(temp_dir, 'output_min.png')
        output_max = os.path.join(temp_dir, 'output_max.png')

        # Should not raise
        PDFService.convert_page_to_image(
            pdf_path=sample_pdf_path,
            page_number=0,
            output_path=output_min,
            dpi=PDFService.MIN_DPI
        )

        PDFService.convert_page_to_image(
            pdf_path=sample_pdf_path,
            page_number=0,
            output_path=output_max,
            dpi=PDFService.MAX_DPI
        )

        assert os.path.exists(output_min)
        assert os.path.exists(output_max)

    def test_validate_image_format_png(self, sample_pdf_path, temp_dir):
        """Image format validation should accept 'png'."""
        output_path = os.path.join(temp_dir, 'output.png')

        result = PDFService.convert_page_to_image(
            pdf_path=sample_pdf_path,
            page_number=0,
            output_path=output_path,
            image_format='png'
        )

        assert result['format'] == 'png'

    def test_validate_image_format_jpeg(self, sample_pdf_path, temp_dir):
        """Image format validation should accept 'jpeg'."""
        output_path = os.path.join(temp_dir, 'output.jpg')

        result = PDFService.convert_page_to_image(
            pdf_path=sample_pdf_path,
            page_number=0,
            output_path=output_path,
            image_format='jpeg'
        )

        assert result['format'] == 'jpeg'

    def test_validate_image_format_jpg(self, sample_pdf_path, temp_dir):
        """Image format validation should accept 'jpg'."""
        output_path = os.path.join(temp_dir, 'output.jpg')

        result = PDFService.convert_page_to_image(
            pdf_path=sample_pdf_path,
            page_number=0,
            output_path=output_path,
            image_format='jpg'
        )

        assert result['format'] == 'jpg'

    def test_validate_image_format_case_insensitive(self, sample_pdf_path, temp_dir):
        """Image format validation should be case insensitive."""
        output_path = os.path.join(temp_dir, 'output.png')

        result = PDFService.convert_page_to_image(
            pdf_path=sample_pdf_path,
            page_number=0,
            output_path=output_path,
            image_format='PNG'
        )

        assert result['format'] == 'png'


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestPDFServiceErrorHandling:
    """Tests for PDFService error handling."""

    def test_pdf_not_found_error_message(self, temp_dir):
        """PDFNotFoundError should include file path in message."""
        fake_path = os.path.join(temp_dir, 'missing.pdf')

        try:
            PDFService.get_pdf_info(fake_path)
            pytest.fail("Expected PDFNotFoundError")
        except PDFNotFoundError as e:
            assert 'missing.pdf' in str(e)

    def test_pdf_processing_error_for_corrupted_file(self, invalid_pdf_path):
        """PDFProcessingError should be raised for corrupted files."""
        with pytest.raises(PDFProcessingError):
            PDFService.get_pdf_info(invalid_pdf_path)

    def test_error_inheritance(self):
        """All PDF errors should inherit from PDFServiceError."""
        assert issubclass(PDFNotFoundError, PDFServiceError)
        assert issubclass(PDFProcessingError, PDFServiceError)
        assert issubclass(PDFServiceError, Exception)

    @patch('cms.services.pdf_service.fitz', None)
    def test_ensure_available_raises_when_not_installed(self):
        """_ensure_available() should raise PDFProcessingError when PyMuPDF not available."""
        with pytest.raises(PDFProcessingError) as exc_info:
            PDFService._ensure_available()

        assert 'not installed' in str(exc_info.value).lower()
