"""
PDF Service for CMS.

Provides PDF processing capabilities including:
- PDF-to-image conversion using PyMuPDF (fitz)
- Page metadata extraction (count, dimensions)
- Thumbnail generation
- Multi-page PDF handling

This service is used for converting uploaded PDFs into image sequences
for display on media players.

Note: PyMuPDF is imported as 'fitz' (legacy import name).
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# PyMuPDF import - try both import names for compatibility
try:
    import fitz  # PyMuPDF
except ImportError:
    try:
        import pymupdf as fitz
    except ImportError:
        fitz = None


class PDFServiceError(Exception):
    """Base exception for PDF service errors."""
    pass


class PDFNotFoundError(PDFServiceError):
    """Raised when the PDF file does not exist."""
    pass


class PDFProcessingError(PDFServiceError):
    """Raised when PDF processing fails."""
    pass


class PDFService:
    """
    Service class for processing PDF files.

    This service provides methods to convert PDF pages to images,
    extract metadata, and generate thumbnails. It uses PyMuPDF (fitz)
    for all PDF operations.

    All methods are class methods following the CMS service pattern.
    """

    # Default settings
    DEFAULT_DPI = 150  # Standard screen resolution
    THUMBNAIL_DPI = 72  # Lower resolution for thumbnails
    DEFAULT_IMAGE_FORMAT = 'png'  # PNG for quality, JPEG for smaller size
    SUPPORTED_FORMATS = {'png', 'jpeg', 'jpg'}

    # Validation constants
    MIN_DPI = 36
    MAX_DPI = 600
    MAX_PAGE_COUNT = 1000  # Safety limit for processing

    @classmethod
    def is_available(cls) -> bool:
        """
        Check if PyMuPDF is installed and available.

        Returns:
            bool: True if PyMuPDF is available, False otherwise.
        """
        return fitz is not None

    @classmethod
    def get_pdf_info(cls, pdf_path: str) -> Dict[str, Any]:
        """
        Extract metadata from a PDF file.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            Dictionary containing:
                - page_count: Number of pages
                - page_sizes: List of (width, height) tuples for each page
                - title: PDF title (if available)
                - author: PDF author (if available)
                - subject: PDF subject (if available)
                - creator: PDF creator application (if available)
                - creation_date: Creation date (if available)
                - modification_date: Modification date (if available)

        Raises:
            PDFNotFoundError: If the file does not exist.
            PDFProcessingError: If the PDF cannot be read.
        """
        cls._ensure_available()
        cls._validate_file_exists(pdf_path)

        try:
            doc = fitz.open(pdf_path)
            try:
                metadata = doc.metadata or {}
                page_sizes = []

                for page in doc:
                    rect = page.rect
                    page_sizes.append((int(rect.width), int(rect.height)))

                return {
                    'page_count': doc.page_count,
                    'page_sizes': page_sizes,
                    'title': metadata.get('title', ''),
                    'author': metadata.get('author', ''),
                    'subject': metadata.get('subject', ''),
                    'creator': metadata.get('creator', ''),
                    'creation_date': metadata.get('creationDate', ''),
                    'modification_date': metadata.get('modDate', ''),
                }
            finally:
                doc.close()
        except fitz.FileDataError as e:
            raise PDFProcessingError(f"Invalid or corrupted PDF file: {e}")
        except Exception as e:
            raise PDFProcessingError(f"Failed to read PDF: {e}")

    @classmethod
    def get_page_count(cls, pdf_path: str) -> int:
        """
        Get the number of pages in a PDF file.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            Number of pages in the PDF.

        Raises:
            PDFNotFoundError: If the file does not exist.
            PDFProcessingError: If the PDF cannot be read.
        """
        info = cls.get_pdf_info(pdf_path)
        return info['page_count']

    @classmethod
    def convert_page_to_image(
        cls,
        pdf_path: str,
        page_number: int,
        output_path: str,
        dpi: int = None,
        image_format: str = None,
    ) -> Dict[str, Any]:
        """
        Convert a single PDF page to an image.

        Args:
            pdf_path: Path to the PDF file.
            page_number: Page number to convert (0-indexed).
            output_path: Path where the image will be saved.
            dpi: Resolution in dots per inch (default: 150).
            image_format: Output format - 'png' or 'jpeg' (default: 'png').

        Returns:
            Dictionary containing:
                - output_path: Path to the saved image
                - width: Image width in pixels
                - height: Image height in pixels
                - page_number: The page number converted
                - format: The image format used

        Raises:
            PDFNotFoundError: If the PDF file does not exist.
            PDFProcessingError: If conversion fails.
            ValueError: If parameters are invalid.
        """
        cls._ensure_available()
        cls._validate_file_exists(pdf_path)

        # Apply defaults
        dpi = dpi or cls.DEFAULT_DPI
        image_format = (image_format or cls.DEFAULT_IMAGE_FORMAT).lower()

        # Validate parameters
        cls._validate_dpi(dpi)
        cls._validate_image_format(image_format)

        try:
            doc = fitz.open(pdf_path)
            try:
                # Validate page number
                if page_number < 0 or page_number >= doc.page_count:
                    raise ValueError(
                        f"Page number {page_number} out of range "
                        f"(0-{doc.page_count - 1})"
                    )

                page = doc[page_number]

                # Calculate zoom matrix for desired DPI
                # PDF default is 72 DPI, so we scale accordingly
                zoom = dpi / 72.0
                matrix = fitz.Matrix(zoom, zoom)

                # Render page to pixmap
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)

                # Ensure output directory exists
                output_dir = os.path.dirname(output_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)

                # Save the image
                if image_format in ('jpeg', 'jpg'):
                    pixmap.save(output_path, output='jpeg', jpg_quality=90)
                else:
                    pixmap.save(output_path, output='png')

                return {
                    'output_path': output_path,
                    'width': pixmap.width,
                    'height': pixmap.height,
                    'page_number': page_number,
                    'format': image_format,
                }
            finally:
                doc.close()
        except ValueError:
            raise
        except fitz.FileDataError as e:
            raise PDFProcessingError(f"Invalid or corrupted PDF file: {e}")
        except Exception as e:
            raise PDFProcessingError(f"Failed to convert page {page_number}: {e}")

    @classmethod
    def convert_all_pages(
        cls,
        pdf_path: str,
        output_dir: str,
        filename_prefix: str = None,
        dpi: int = None,
        image_format: str = None,
        max_pages: int = None,
    ) -> List[Dict[str, Any]]:
        """
        Convert all pages of a PDF to images.

        Args:
            pdf_path: Path to the PDF file.
            output_dir: Directory where images will be saved.
            filename_prefix: Prefix for output filenames (default: PDF filename).
            dpi: Resolution in dots per inch (default: 150).
            image_format: Output format - 'png' or 'jpeg' (default: 'png').
            max_pages: Maximum number of pages to convert (default: all).

        Returns:
            List of dictionaries, each containing:
                - output_path: Path to the saved image
                - width: Image width in pixels
                - height: Image height in pixels
                - page_number: The page number (0-indexed)
                - format: The image format used

        Raises:
            PDFNotFoundError: If the PDF file does not exist.
            PDFProcessingError: If conversion fails.
            ValueError: If parameters are invalid.
        """
        cls._ensure_available()
        cls._validate_file_exists(pdf_path)

        # Apply defaults
        dpi = dpi or cls.DEFAULT_DPI
        image_format = (image_format or cls.DEFAULT_IMAGE_FORMAT).lower()

        # Validate parameters
        cls._validate_dpi(dpi)
        cls._validate_image_format(image_format)

        # Default filename prefix to PDF filename without extension
        if filename_prefix is None:
            filename_prefix = Path(pdf_path).stem

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        try:
            doc = fitz.open(pdf_path)
            try:
                page_count = doc.page_count

                # Apply max_pages limit
                if max_pages is not None:
                    page_count = min(page_count, max_pages)

                # Safety limit
                if page_count > cls.MAX_PAGE_COUNT:
                    raise ValueError(
                        f"PDF has {doc.page_count} pages, exceeding limit of "
                        f"{cls.MAX_PAGE_COUNT}"
                    )

                results = []
                zoom = dpi / 72.0
                matrix = fitz.Matrix(zoom, zoom)

                for page_num in range(page_count):
                    page = doc[page_num]
                    pixmap = page.get_pixmap(matrix=matrix, alpha=False)

                    # Generate output filename with zero-padded page number
                    ext = 'jpg' if image_format in ('jpeg', 'jpg') else image_format
                    filename = f"{filename_prefix}_page_{page_num + 1:04d}.{ext}"
                    output_path = os.path.join(output_dir, filename)

                    # Save the image
                    if image_format in ('jpeg', 'jpg'):
                        pixmap.save(output_path, output='jpeg', jpg_quality=90)
                    else:
                        pixmap.save(output_path, output='png')

                    results.append({
                        'output_path': output_path,
                        'width': pixmap.width,
                        'height': pixmap.height,
                        'page_number': page_num,
                        'format': image_format,
                    })

                return results
            finally:
                doc.close()
        except ValueError:
            raise
        except fitz.FileDataError as e:
            raise PDFProcessingError(f"Invalid or corrupted PDF file: {e}")
        except Exception as e:
            raise PDFProcessingError(f"Failed to convert PDF: {e}")

    @classmethod
    def generate_thumbnail(
        cls,
        pdf_path: str,
        output_path: str,
        max_width: int = 300,
        max_height: int = 300,
        page_number: int = 0,
    ) -> Dict[str, Any]:
        """
        Generate a thumbnail from a PDF page.

        Creates a scaled-down image that fits within the specified dimensions
        while maintaining aspect ratio.

        Args:
            pdf_path: Path to the PDF file.
            output_path: Path where the thumbnail will be saved.
            max_width: Maximum thumbnail width (default: 300).
            max_height: Maximum thumbnail height (default: 300).
            page_number: Page to use for thumbnail (default: 0, first page).

        Returns:
            Dictionary containing:
                - output_path: Path to the saved thumbnail
                - width: Thumbnail width in pixels
                - height: Thumbnail height in pixels
                - page_number: The page used

        Raises:
            PDFNotFoundError: If the PDF file does not exist.
            PDFProcessingError: If thumbnail generation fails.
        """
        cls._ensure_available()
        cls._validate_file_exists(pdf_path)

        try:
            doc = fitz.open(pdf_path)
            try:
                # Validate page number
                if page_number < 0 or page_number >= doc.page_count:
                    page_number = 0  # Default to first page

                page = doc[page_number]
                rect = page.rect

                # Calculate scale to fit within max dimensions
                width_scale = max_width / rect.width
                height_scale = max_height / rect.height
                scale = min(width_scale, height_scale)

                # Create matrix for scaling
                matrix = fitz.Matrix(scale, scale)

                # Render to pixmap
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)

                # Ensure output directory exists
                output_dir = os.path.dirname(output_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)

                # Save as JPEG for smaller file size
                pixmap.save(output_path, output='jpeg', jpg_quality=85)

                return {
                    'output_path': output_path,
                    'width': pixmap.width,
                    'height': pixmap.height,
                    'page_number': page_number,
                }
            finally:
                doc.close()
        except fitz.FileDataError as e:
            raise PDFProcessingError(f"Invalid or corrupted PDF file: {e}")
        except Exception as e:
            raise PDFProcessingError(f"Failed to generate thumbnail: {e}")

    @classmethod
    def process_pdf_for_content(
        cls,
        pdf_path: str,
        output_base_dir: str,
        content_id: str = None,
        dpi: int = None,
        image_format: str = None,
        generate_thumbnails: bool = True,
    ) -> Dict[str, Any]:
        """
        Process a PDF file for use as content in layouts.

        This is a convenience method that:
        1. Extracts PDF metadata
        2. Converts all pages to images
        3. Optionally generates thumbnails

        Args:
            pdf_path: Path to the PDF file.
            output_base_dir: Base directory for output (subdirs created).
            content_id: Unique ID for this content (auto-generated if None).
            dpi: Resolution for page images (default: 150).
            image_format: Image format - 'png' or 'jpeg' (default: 'png').
            generate_thumbnails: Whether to generate thumbnails (default: True).

        Returns:
            Dictionary containing:
                - content_id: The content identifier
                - pdf_info: PDF metadata dict
                - pages: List of page image info dicts
                - pages_dir: Directory containing page images
                - thumbnail_path: Path to first-page thumbnail (if generated)

        Raises:
            PDFNotFoundError: If the PDF file does not exist.
            PDFProcessingError: If processing fails.
        """
        cls._ensure_available()
        cls._validate_file_exists(pdf_path)

        # Generate content ID if not provided
        content_id = content_id or str(uuid.uuid4())

        # Apply defaults
        dpi = dpi or cls.DEFAULT_DPI
        image_format = (image_format or cls.DEFAULT_IMAGE_FORMAT).lower()

        # Create output directories
        content_dir = os.path.join(output_base_dir, content_id)
        pages_dir = os.path.join(content_dir, 'pages')
        os.makedirs(pages_dir, exist_ok=True)

        # Get PDF info
        pdf_info = cls.get_pdf_info(pdf_path)

        # Convert all pages
        pages = cls.convert_all_pages(
            pdf_path=pdf_path,
            output_dir=pages_dir,
            filename_prefix='page',
            dpi=dpi,
            image_format=image_format,
        )

        result = {
            'content_id': content_id,
            'pdf_info': pdf_info,
            'pages': pages,
            'pages_dir': pages_dir,
            'thumbnail_path': None,
        }

        # Generate thumbnail from first page
        if generate_thumbnails and pdf_info['page_count'] > 0:
            thumbnail_path = os.path.join(content_dir, 'thumbnail.jpg')
            cls.generate_thumbnail(
                pdf_path=pdf_path,
                output_path=thumbnail_path,
            )
            result['thumbnail_path'] = thumbnail_path

        return result

    # ==========================================================================
    # Validation Methods
    # ==========================================================================

    @classmethod
    def _ensure_available(cls) -> None:
        """
        Ensure PyMuPDF is available.

        Raises:
            PDFProcessingError: If PyMuPDF is not installed.
        """
        if not cls.is_available():
            raise PDFProcessingError(
                "PyMuPDF (fitz) is not installed. "
                "Install with: pip install PyMuPDF"
            )

    @classmethod
    def _validate_file_exists(cls, file_path: str) -> None:
        """
        Validate that a file exists.

        Args:
            file_path: Path to check.

        Raises:
            PDFNotFoundError: If the file does not exist.
        """
        if not os.path.exists(file_path):
            raise PDFNotFoundError(f"PDF file not found: {file_path}")
        if not os.path.isfile(file_path):
            raise PDFNotFoundError(f"Path is not a file: {file_path}")

    @classmethod
    def _validate_dpi(cls, dpi: int) -> None:
        """
        Validate DPI value.

        Args:
            dpi: DPI value to validate.

        Raises:
            ValueError: If DPI is out of range.
        """
        if not isinstance(dpi, (int, float)):
            raise ValueError(f"DPI must be a number, got {type(dpi).__name__}")
        if dpi < cls.MIN_DPI or dpi > cls.MAX_DPI:
            raise ValueError(
                f"DPI must be between {cls.MIN_DPI} and {cls.MAX_DPI}, "
                f"got {dpi}"
            )

    @classmethod
    def _validate_image_format(cls, image_format: str) -> None:
        """
        Validate image format.

        Args:
            image_format: Format to validate.

        Raises:
            ValueError: If format is not supported.
        """
        if image_format not in cls.SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported image format: {image_format}. "
                f"Supported formats: {', '.join(cls.SUPPORTED_FORMATS)}"
            )
