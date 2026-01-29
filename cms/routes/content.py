"""
CMS Content Routes

Blueprint for content management API endpoints:
- POST /upload: Upload content file with metadata
- GET /: List all content
- GET /<content_id>: Get content metadata
- GET /<content_id>/download: Download content file
- PUT /<content_id>/status: Update content approval status
- DELETE /<content_id>: Delete content
- POST /sync: Trigger content sync from Content Catalog
- GET /sync: Get content sync status
- GET /synced: List synced content with filters

All endpoints are prefixed with /api/v1/content when registered with the app.

Thea Content Catalog Proxy Blueprint (thea_bp):
- GET /approved-assets: Proxy to Content Catalog for browsing approved assets
- POST /checkout/<asset_id>: Checkout asset from Content Catalog with hash verification

The thea_bp is registered at /api/v1/thea for CMS integration with Thea Content Catalog.
"""

import hashlib
import os
import uuid
from pathlib import Path

from flask import Blueprint, request, jsonify, send_file, current_app
from werkzeug.utils import secure_filename

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError as ReqConnectionError

from cms.models import db, Content, Network, ContentStatus
from cms.utils.auth import login_required
from cms.utils.audit import log_action
from cms.services.content_sync_service import (
    ContentSyncService,
    ContentSyncError,
    ContentCatalogUnavailableError,
)


# Create content blueprint
content_bp = Blueprint('content', __name__)

# Create Thea integration blueprint for proxying requests to Content Catalog
thea_bp = Blueprint('thea', __name__)


def allowed_file(filename):
    """
    Check if file extension is allowed.

    Args:
        filename: The original filename to check

    Returns:
        bool: True if file extension is allowed
    """
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    allowed = current_app.config.get('ALLOWED_EXTENSIONS', set())
    return ext in allowed


def get_mime_type(filename):
    """
    Determine MIME type based on file extension.

    Args:
        filename: The filename to check

    Returns:
        str: MIME type string
    """
    if '.' not in filename:
        return 'application/octet-stream'

    ext = filename.rsplit('.', 1)[1].lower()

    video_types = {
        'mp4': 'video/mp4',
        'avi': 'video/x-msvideo',
        'mov': 'video/quicktime',
        'mkv': 'video/x-matroska',
        'webm': 'video/webm'
    }

    image_types = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'webp': 'image/webp'
    }

    if ext in video_types:
        return video_types[ext]
    if ext in image_types:
        return image_types[ext]

    return 'application/octet-stream'


@content_bp.route('/upload', methods=['POST'])
@content_bp.route('', methods=['POST'])
@login_required
def upload_content():
    """
    Upload a content file directly to the CMS.

    Accepts multipart/form-data with:
        file: The media file (required)
        network_id: Network UUID to assign to (optional)
        width, height: Resolution (optional)
        duration: Duration in seconds (optional)

    Returns:
        201: Content created successfully
        400: Invalid file or parameters
        500: Server error
    """
    # Check if file was included in request
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    # Check if filename is empty
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Validate file type
    if not allowed_file(file.filename):
        allowed = current_app.config.get('ALLOWED_EXTENSIONS', set())
        return jsonify({
            'error': f'File type not allowed. Allowed types: {", ".join(sorted(allowed))}'
        }), 400

    # Validate network_id if provided
    network_id = request.form.get('network_id')
    if network_id:
        network = db.session.get(Network, network_id)
        if not network:
            return jsonify({
                'error': f'Network with id {network_id} not found'
            }), 400

    # Generate unique filename
    original_filename = secure_filename(file.filename)
    file_ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
    unique_filename = f"{uuid.uuid4()}.{file_ext}" if file_ext else str(uuid.uuid4())

    # Get upload path from config
    uploads_path = current_app.config.get('UPLOADS_PATH')
    if uploads_path is None:
        return jsonify({'error': 'Upload path not configured'}), 500

    # Ensure uploads directory exists
    uploads_path = Path(uploads_path)
    uploads_path.mkdir(parents=True, exist_ok=True)

    # Save file
    file_path = uploads_path / unique_filename
    try:
        file.save(str(file_path))
    except Exception as e:
        return jsonify({
            'error': f'Failed to save file: {str(e)}'
        }), 500

    # Get file size
    file_size = os.path.getsize(str(file_path))

    # Get MIME type
    mime_type = get_mime_type(original_filename)

    # Parse optional metadata
    width = request.form.get('width')
    height = request.form.get('height')
    duration = request.form.get('duration')

    try:
        width = int(width) if width else None
    except ValueError:
        width = None

    try:
        height = int(height) if height else None
    except ValueError:
        height = None

    try:
        duration = int(duration) if duration else None
    except ValueError:
        duration = None

    # Create content record
    content = Content(
        filename=unique_filename,
        original_name=original_filename,
        mime_type=mime_type,
        file_size=file_size,
        width=width,
        height=height,
        duration=duration,
        network_id=network_id
    )

    try:
        db.session.add(content)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Clean up uploaded file on database error
        try:
            os.remove(str(file_path))
        except OSError:
            pass
        return jsonify({
            'error': f'Failed to save content record: {str(e)}'
        }), 500

    # Log content upload
    log_action(
        action='content.upload',
        action_category='content',
        resource_type='content',
        resource_id=content.id,
        resource_name=original_filename,
        details={
            'filename': unique_filename,
            'original_name': original_filename,
            'mime_type': mime_type,
            'file_size': file_size,
            'network_id': network_id,
        }
    )

    return jsonify(content.to_dict()), 201


@content_bp.route('', methods=['GET'])
@login_required
def list_content():
    """
    List all content.

    Returns a list of all content items in the CMS,
    with optional filtering by network, MIME type, or status.

    Query Parameters:
        network_id: Filter by network UUID
        type: Filter by content type (video, image)
        status: Filter by approval status (pending, approved, rejected)

    Returns:
        200: List of content
            {
                "content": [ { content data }, ... ],
                "count": 5
            }
        400: Invalid status value
            {
                "error": "Invalid status: xyz. Valid values: pending, approved, rejected"
            }
    """
    # Build query with optional filters
    query = Content.query

    # Filter by network
    network_id = request.args.get('network_id')
    if network_id:
        query = query.filter_by(network_id=network_id)

    # Filter by content type
    content_type = request.args.get('type')
    if content_type:
        if content_type == 'video':
            query = query.filter(Content.mime_type.like('video/%'))
        elif content_type == 'image':
            query = query.filter(Content.mime_type.like('image/%'))
        elif content_type == 'audio':
            query = query.filter(Content.mime_type.like('audio/%'))

    # Filter by status
    status = request.args.get('status')
    if status:
        valid_statuses = [s.value for s in ContentStatus]
        if status not in valid_statuses:
            return jsonify({
                'error': f"Invalid status: {status}. Valid values: {', '.join(valid_statuses)}"
            }), 400
        query = query.filter_by(status=status)

    # Execute query
    content_list = query.order_by(Content.created_at.desc()).all()

    return jsonify({
        'content': [c.to_dict() for c in content_list],
        'count': len(content_list)
    }), 200


@content_bp.route('/<content_id>', methods=['GET'])
@login_required
def get_content(content_id):
    """
    Get metadata for a specific content item.

    Args:
        content_id: Content UUID

    Returns:
        200: Content metadata
            { content data }
        400: Invalid content_id format
            {
                "error": "Invalid content_id format"
            }
        404: Content not found
            {
                "error": "Content not found"
            }
    """
    # Validate content_id format (basic sanitization)
    if not isinstance(content_id, str) or len(content_id) > 64:
        return jsonify({
            'error': 'Invalid content_id format'
        }), 400

    content = db.session.get(Content, content_id)

    if not content:
        return jsonify({'error': 'Content not found'}), 404

    return jsonify(content.to_dict()), 200


@content_bp.route('/<content_id>/download', methods=['GET'])
def download_content(content_id):
    """
    Download a specific content file.

    Devices and hubs call this endpoint to download content files
    from the CMS storage. The file is streamed with appropriate
    content type headers.

    Args:
        content_id: Content UUID

    Returns:
        200: File streamed with appropriate content type
        400: Invalid content_id format
            {
                "error": "Invalid content_id format"
            }
        404: Content not found or file missing
            {
                "error": "Content not found"
            }
    """
    # Validate content_id format (basic sanitization)
    if not isinstance(content_id, str) or len(content_id) > 64:
        return jsonify({
            'error': 'Invalid content_id format'
        }), 400

    content = db.session.get(Content, content_id)

    if not content:
        return jsonify({'error': 'Content not found'}), 404

    # Get upload path from config
    uploads_path = current_app.config.get('UPLOADS_PATH')
    if uploads_path is None:
        return jsonify({'error': 'Upload path not configured'}), 500

    # Build file path
    file_path = Path(uploads_path) / content.filename

    # Verify file exists
    if not file_path.is_file():
        return jsonify({'error': 'Content file not found on disk'}), 404

    # Stream the file
    return send_file(
        str(file_path),
        mimetype=content.mime_type,
        as_attachment=True,
        download_name=content.original_name
    )


@content_bp.route('/<content_id>', methods=['DELETE'])
@login_required
def delete_content(content_id):
    """
    Delete a content item and its associated file.

    Removes the content record from the database and deletes
    the associated file from storage.

    Args:
        content_id: Content UUID

    Returns:
        200: Content deleted successfully
            {
                "message": "Content deleted successfully",
                "id": "uuid"
            }
        400: Invalid content_id format
            {
                "error": "Invalid content_id format"
            }
        404: Content not found
            {
                "error": "Content not found"
            }
    """
    # Validate content_id format (basic sanitization)
    if not isinstance(content_id, str) or len(content_id) > 64:
        return jsonify({
            'error': 'Invalid content_id format'
        }), 400

    content = db.session.get(Content, content_id)

    if not content:
        return jsonify({'error': 'Content not found'}), 404

    # Store info for audit log and response before deleting
    content_id_response = content.id
    filename = content.filename
    original_name = content.original_name
    mime_type = content.mime_type
    file_size = content.file_size
    network_id = content.network_id

    # Delete from database
    try:
        db.session.delete(content)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to delete content record: {str(e)}'
        }), 500

    # Delete file from storage
    uploads_path = current_app.config.get('UPLOADS_PATH')
    if uploads_path:
        file_path = Path(uploads_path) / filename
        try:
            if file_path.is_file():
                os.remove(str(file_path))
        except OSError:
            # File deletion failed, but database record is already deleted
            # Log this in production, but don't fail the request
            pass

    # Log content deletion
    log_action(
        action='content.delete',
        action_category='content',
        resource_type='content',
        resource_id=content_id_response,
        resource_name=original_name,
        details={
            'filename': filename,
            'original_name': original_name,
            'mime_type': mime_type,
            'file_size': file_size,
            'network_id': network_id,
        }
    )

    return jsonify({
        'message': 'Content deleted successfully',
        'id': content_id_response
    }), 200


@content_bp.route('/<content_id>/status', methods=['PUT'])
@login_required
def update_content_status(content_id):
    """
    Update the approval status of a content item.

    Changes the status of a content item between pending, approved, and rejected.
    Only approved content can be added to playlists.

    Args:
        content_id: Content UUID

    Request Body:
        {
            "status": "approved" | "pending" | "rejected" (required)
        }

    Returns:
        200: Status updated successfully
            { content data with updated status }
        400: Missing required field or invalid status value
            {
                "error": "error message"
            }
        404: Content not found
            {
                "error": "Content not found"
            }
    """
    # Validate content_id format (basic sanitization)
    if not isinstance(content_id, str) or len(content_id) > 64:
        return jsonify({
            'error': 'Invalid content_id format'
        }), 400

    content = db.session.get(Content, content_id)

    if not content:
        return jsonify({'error': 'Content not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate status
    status = data.get('status')
    if not status:
        return jsonify({'error': 'status is required'}), 400

    valid_statuses = [s.value for s in ContentStatus]
    if status not in valid_statuses:
        return jsonify({
            'error': f"Invalid status: {status}. Valid values: {', '.join(valid_statuses)}"
        }), 400

    # Update status
    old_status = content.status
    content.status = status

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update content status: {str(e)}'
        }), 500

    # Log status change
    log_action(
        action='content.status_update',
        action_category='content',
        resource_type='content',
        resource_id=content.id,
        resource_name=content.original_name,
        details={
            'old_status': old_status,
            'new_status': status,
        }
    )

    return jsonify(content.to_dict()), 200


# =============================================================================
# Content Sync Endpoints
# =============================================================================

@content_bp.route('/sync', methods=['POST'])
@login_required
def sync_content():
    """
    Trigger content sync from Content Catalog.

    Fetches all approved/published content from the Content Catalog service
    and caches it locally in the SyncedContent table. This enables the CMS
    to display content without direct upload capability.

    Query Parameters:
        network_id: Filter sync to specific network (optional)
        organization_id: Filter sync to specific organization (optional)
        category: Filter sync to specific category (optional)

    Returns:
        200: Sync completed successfully
            {
                "message": "Content sync completed",
                "synced_count": 42,
                "created_count": 10,
                "updated_count": 32,
                "total_in_catalog": 42,
                "synced_at": "2024-01-15T10:00:00Z",
                "errors": []
            }
        503: Content Catalog service unavailable
            {
                "error": "Content Catalog service unavailable",
                "message": "Using cached content",
                "catalog_url": "http://localhost:5003"
            }
        500: Sync failed
            {
                "error": "Content sync failed",
                "message": "error details"
            }
    """
    # Parse optional filter parameters
    network_id = request.args.get('network_id')
    organization_id = request.args.get('organization_id')
    category = request.args.get('category')

    # Convert organization_id to int if provided
    if organization_id:
        try:
            organization_id = int(organization_id)
        except ValueError:
            return jsonify({
                'error': 'Invalid organization_id: must be an integer'
            }), 400

    try:
        sync_service = ContentSyncService()

        # First, sync networks from Content Catalog tenants
        # This ensures CMS networks match Content Catalog tenants
        network_result = sync_service.sync_networks()

        # Then sync content
        result = sync_service.sync_approved_content(
            network_id=network_id,
            organization_id=organization_id,
            category=category
        )

        # Include network sync info in response
        result['networks_synced'] = network_result.get('synced_count', 0)
        result['networks_created'] = network_result.get('created_count', 0)

        return jsonify(result), 200

    except ContentCatalogUnavailableError as e:
        return jsonify({
            'error': 'Content Catalog service unavailable',
            'message': str(e),
            'catalog_url': current_app.config.get('CONTENT_CATALOG_URL')
        }), 503

    except ContentSyncError as e:
        return jsonify({
            'error': 'Content sync failed',
            'message': str(e)
        }), 500

    except Exception as e:
        return jsonify({
            'error': 'Content sync failed',
            'message': str(e)
        }), 500


@content_bp.route('/sync-networks', methods=['POST'])
@login_required
def sync_networks():
    """
    Sync networks from Content Catalog tenants.

    Fetches all tenants from the Content Catalog service and creates/updates
    corresponding Network records in CMS. This ensures CMS networks match
    the Content Catalog's tenant definitions.

    Returns:
        200: Networks synced successfully
            {
                "synced_count": 4,
                "created_count": 2,
                "updated_count": 1,
                "deleted_count": 0,
                "networks": ["Test", "West Marine", "The High Octane Network"]
            }
        503: Content Catalog service unavailable
        500: Sync failed
    """
    try:
        sync_service = ContentSyncService()
        result = sync_service.sync_networks()

        if result.get('errors'):
            return jsonify({
                'error': 'Network sync had errors',
                'result': result
            }), 500

        return jsonify(result), 200

    except ContentCatalogUnavailableError as e:
        return jsonify({
            'error': 'Content Catalog service unavailable',
            'message': str(e),
            'catalog_url': current_app.config.get('CONTENT_CATALOG_URL')
        }), 503

    except Exception as e:
        return jsonify({
            'error': 'Network sync failed',
            'message': str(e)
        }), 500


# =============================================================================
# Thea Content Catalog Proxy Endpoints
# =============================================================================

# Request timeout settings (in seconds)
THEA_REQUEST_TIMEOUT = 30
THEA_CONNECT_TIMEOUT = 10


def get_content_catalog_url():
    """
    Get the Content Catalog (Thea) base URL from configuration.

    Returns:
        str: Content Catalog base URL
    """
    return current_app.config.get('CONTENT_CATALOG_URL', 'http://localhost:5003')


@thea_bp.route('/approved-assets', methods=['GET'])
def list_approved_assets():
    """
    Proxy endpoint to fetch approved assets from Content Catalog (Thea).

    This endpoint proxies requests to the Content Catalog's /api/v1/approved-assets
    endpoint, allowing the CMS to browse approved assets available for checkout
    and import.

    Query Parameters:
        page: Page number (default: 1)
        per_page: Items per page (default: 20, max: 100)
        organization_id: Filter by organization ID
        category: Filter by category
        format: Filter by file format (e.g., mp4, jpg)
        search: Search term for title/description

    Returns:
        200: List of approved assets
            {
                "assets": [
                    {
                        "uuid": "asset-uuid",
                        "title": "Asset Title",
                        "description": "Asset description",
                        "filename": "file.mp4",
                        "format": "mp4",
                        "file_size": 52428800,
                        "file_hash": "sha256:...",
                        "organization_id": 1,
                        "organization_name": "Organization",
                        "category": "Category Name",
                        "status": "approved",
                        "approved_at": "2024-01-15T10:00:00Z",
                        "download_url": "/api/v1/assets/{uuid}/download"
                    },
                    ...
                ],
                "count": 20,
                "total": 150,
                "page": 1,
                "pages": 8
            }
        503: Content Catalog service unavailable
            {
                "error": "Content Catalog service unavailable",
                "message": "error details",
                "catalog_url": "http://localhost:5003"
            }
        502: Bad Gateway - upstream error
            {
                "error": "Bad gateway",
                "message": "error details"
            }
    """
    # Build request parameters from incoming query string
    params = {}

    # Pagination parameters
    page = request.args.get('page')
    if page:
        try:
            params['page'] = int(page)
        except ValueError:
            return jsonify({
                'error': 'Invalid page parameter: must be an integer'
            }), 400

    per_page = request.args.get('per_page')
    if per_page:
        try:
            per_page_int = int(per_page)
            # Enforce maximum
            params['per_page'] = min(per_page_int, 100)
        except ValueError:
            return jsonify({
                'error': 'Invalid per_page parameter: must be an integer'
            }), 400

    # Filter parameters
    if request.args.get('organization_id'):
        params['organization_id'] = request.args.get('organization_id')

    if request.args.get('category'):
        params['category'] = request.args.get('category')

    if request.args.get('format'):
        params['format'] = request.args.get('format')

    if request.args.get('search'):
        params['search'] = request.args.get('search')

    # Build URL to Content Catalog
    catalog_url = get_content_catalog_url()
    url = f"{catalog_url}/api/v1/approved-assets"

    try:
        response = requests.get(
            url,
            params=params,
            timeout=(THEA_CONNECT_TIMEOUT, THEA_REQUEST_TIMEOUT),
        )

        # Pass through the response from Content Catalog
        if response.status_code == 200:
            return jsonify(response.json()), 200
        else:
            # Forward error response from Content Catalog
            try:
                error_data = response.json()
            except ValueError:
                error_data = {'message': response.text}

            return jsonify({
                'error': 'Content Catalog returned an error',
                'status_code': response.status_code,
                'details': error_data
            }), response.status_code

    except ReqConnectionError:
        return jsonify({
            'error': 'Content Catalog service unavailable',
            'message': f'Cannot connect to Content Catalog at {catalog_url}',
            'catalog_url': catalog_url
        }), 503

    except Timeout:
        return jsonify({
            'error': 'Content Catalog service unavailable',
            'message': 'Request to Content Catalog timed out',
            'catalog_url': catalog_url
        }), 503

    except RequestException as e:
        return jsonify({
            'error': 'Bad gateway',
            'message': f'Request to Content Catalog failed: {str(e)}'
        }), 502


# Download timeout settings (larger for file downloads)
THEA_DOWNLOAD_TIMEOUT = 120


def calculate_sha256(file_path):
    """
    Calculate SHA256 hash of a file.

    Args:
        file_path: Path to the file to hash

    Returns:
        str: Hexadecimal SHA256 hash string
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        # Read in chunks to handle large files efficiently
        for chunk in iter(lambda: f.read(8192), b''):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


@thea_bp.route('/checkout/<asset_id>', methods=['POST'])
@login_required
def checkout_asset(asset_id):
    """
    Checkout an asset from Thea Content Catalog, download, verify hash, and import.

    This endpoint performs a full checkout workflow:
    1. Fetches asset metadata from Content Catalog
    2. Downloads the file from Content Catalog
    3. Verifies the SHA256 hash matches the expected checksum
    4. Saves the file to cms/uploads/trusted/ directory
    5. Creates a Content record in the CMS database

    Args:
        asset_id: The UUID of the asset in Content Catalog (Thea)

    Request Body (optional):
        {
            "network_id": "uuid" (optional) - Network to assign the imported content to
        }

    Returns:
        201: Asset checked out and imported successfully
            {
                "message": "Asset checked out and imported successfully",
                "content": {
                    "id": "uuid",
                    "filename": "stored-filename.mp4",
                    "original_name": "my-video.mp4",
                    "mime_type": "video/mp4",
                    "file_size": 52428800,
                    "created_at": "2024-01-15T10:00:00Z"
                },
                "source_asset_uuid": "thea-asset-uuid",
                "hash_verified": true,
                "hash": "sha256:abc123..."
            }
        400: Invalid asset_id format or hash verification failed
            {
                "error": "error message"
            }
        404: Asset not found in Content Catalog
            {
                "error": "Asset not found"
            }
        503: Content Catalog service unavailable
            {
                "error": "Content Catalog service unavailable",
                "message": "error details"
            }
        502: Bad Gateway - download failed
            {
                "error": "Bad gateway",
                "message": "error details"
            }
    """
    # Validate asset_id format (UUID should be 36 chars)
    if not isinstance(asset_id, str) or len(asset_id) > 64:
        return jsonify({
            'error': 'Invalid asset_id format'
        }), 400

    # Parse optional network_id from request body
    data = request.get_json(silent=True) or {}
    network_id = data.get('network_id')

    # Validate network_id if provided
    if network_id:
        network = db.session.get(Network, network_id)
        if not network:
            return jsonify({
                'error': f'Network with id {network_id} not found'
            }), 400

    catalog_url = get_content_catalog_url()

    # Step 1: Fetch asset metadata from Content Catalog
    asset_url = f"{catalog_url}/api/v1/assets/{asset_id}"

    try:
        response = requests.get(
            asset_url,
            timeout=(THEA_CONNECT_TIMEOUT, THEA_REQUEST_TIMEOUT),
        )

        if response.status_code == 404:
            return jsonify({
                'error': 'Asset not found in Content Catalog'
            }), 404

        if response.status_code != 200:
            try:
                error_data = response.json()
            except ValueError:
                error_data = {'message': response.text}

            return jsonify({
                'error': 'Failed to fetch asset metadata',
                'status_code': response.status_code,
                'details': error_data
            }), response.status_code

        asset_data = response.json()

    except ReqConnectionError:
        return jsonify({
            'error': 'Content Catalog service unavailable',
            'message': f'Cannot connect to Content Catalog at {catalog_url}',
            'catalog_url': catalog_url
        }), 503

    except Timeout:
        return jsonify({
            'error': 'Content Catalog service unavailable',
            'message': 'Request to Content Catalog timed out',
            'catalog_url': catalog_url
        }), 503

    except RequestException as e:
        return jsonify({
            'error': 'Bad gateway',
            'message': f'Request to Content Catalog failed: {str(e)}'
        }), 502

    # Extract asset metadata
    asset_uuid = asset_data.get('uuid')
    asset_filename = asset_data.get('filename', 'unknown')
    asset_title = asset_data.get('title', 'Untitled')
    asset_checksum = asset_data.get('checksum')
    asset_file_size = asset_data.get('file_size')
    asset_format = asset_data.get('format', '')
    asset_duration = asset_data.get('duration')
    asset_resolution = asset_data.get('resolution')
    asset_status = asset_data.get('status')

    # Check if asset is approved or published
    if asset_status not in ['approved', 'published']:
        return jsonify({
            'error': f"Cannot checkout asset: status is '{asset_status}'. Only approved or published assets can be checked out."
        }), 400

    # Step 2: Download the file from Content Catalog
    download_url = f"{catalog_url}/api/v1/assets/{asset_id}/download"

    # Prepare trusted uploads directory
    uploads_path = current_app.config.get('UPLOADS_PATH')
    if uploads_path is None:
        return jsonify({'error': 'Upload path not configured'}), 500

    trusted_path = Path(uploads_path) / 'trusted'
    trusted_path.mkdir(parents=True, exist_ok=True)

    # Generate unique filename for local storage
    file_ext = asset_filename.rsplit('.', 1)[1].lower() if '.' in asset_filename else ''
    unique_filename = f"{uuid.uuid4()}.{file_ext}" if file_ext else str(uuid.uuid4())
    local_file_path = trusted_path / unique_filename

    try:
        # Stream download to handle large files
        with requests.get(
            download_url,
            timeout=(THEA_CONNECT_TIMEOUT, THEA_DOWNLOAD_TIMEOUT),
            stream=True
        ) as download_response:

            if download_response.status_code == 404:
                return jsonify({
                    'error': 'Asset file not found in Content Catalog'
                }), 404

            if download_response.status_code != 200:
                return jsonify({
                    'error': 'Failed to download asset file',
                    'status_code': download_response.status_code
                }), download_response.status_code

            # Write file to disk in chunks
            with open(local_file_path, 'wb') as f:
                for chunk in download_response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

    except ReqConnectionError:
        return jsonify({
            'error': 'Content Catalog service unavailable',
            'message': f'Cannot connect to Content Catalog at {catalog_url} for download',
            'catalog_url': catalog_url
        }), 503

    except Timeout:
        return jsonify({
            'error': 'Content Catalog service unavailable',
            'message': 'Download from Content Catalog timed out',
            'catalog_url': catalog_url
        }), 503

    except RequestException as e:
        # Clean up partial download
        try:
            if local_file_path.exists():
                os.remove(str(local_file_path))
        except OSError:
            pass
        return jsonify({
            'error': 'Bad gateway',
            'message': f'Download from Content Catalog failed: {str(e)}'
        }), 502

    # Step 3: Calculate and verify hash
    calculated_hash = calculate_sha256(str(local_file_path))
    hash_verified = True
    hash_mismatch_error = None

    if asset_checksum:
        # Normalize checksum format (may or may not have sha256: prefix)
        expected_hash = asset_checksum
        if expected_hash.startswith('sha256:'):
            expected_hash = expected_hash[7:]

        if calculated_hash.lower() != expected_hash.lower():
            hash_verified = False
            hash_mismatch_error = (
                f"Hash verification failed. Expected: {expected_hash}, "
                f"Calculated: {calculated_hash}"
            )
            # Clean up the downloaded file
            try:
                os.remove(str(local_file_path))
            except OSError:
                pass
            return jsonify({
                'error': 'Hash verification failed',
                'message': hash_mismatch_error,
                'expected_hash': expected_hash,
                'calculated_hash': calculated_hash
            }), 400

    # Get actual file size
    actual_file_size = os.path.getsize(str(local_file_path))

    # Determine MIME type
    mime_type = get_mime_type(asset_filename)

    # Parse dimensions from resolution (e.g., "1920x1080")
    width = None
    height = None
    if asset_resolution:
        try:
            parts = asset_resolution.lower().split('x')
            if len(parts) == 2:
                width = int(parts[0].strip())
                height = int(parts[1].strip())
        except (ValueError, IndexError):
            pass

    # Parse duration
    duration = None
    if asset_duration:
        try:
            duration = int(float(asset_duration))
        except (ValueError, TypeError):
            pass

    # Step 4: Create Content record in CMS database
    content = Content(
        filename=unique_filename,
        original_name=asset_title or asset_filename,
        mime_type=mime_type,
        file_size=actual_file_size,
        width=width,
        height=height,
        duration=duration,
        network_id=network_id,
        status=ContentStatus.APPROVED.value  # Auto-approve since it's from trusted source
    )

    try:
        db.session.add(content)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Clean up downloaded file on database error
        try:
            os.remove(str(local_file_path))
        except OSError:
            pass
        return jsonify({
            'error': f'Failed to create content record: {str(e)}'
        }), 500

    # Log the checkout action
    log_action(
        action='thea.checkout',
        action_category='content',
        resource_type='content',
        resource_id=content.id,
        resource_name=content.original_name,
        details={
            'source_asset_uuid': asset_uuid,
            'source_catalog_url': catalog_url,
            'filename': unique_filename,
            'original_name': content.original_name,
            'mime_type': mime_type,
            'file_size': actual_file_size,
            'hash_verified': hash_verified,
            'hash': f'sha256:{calculated_hash}',
            'network_id': network_id,
            'stored_path': str(local_file_path)
        }
    )

    return jsonify({
        'message': 'Asset checked out and imported successfully',
        'content': content.to_dict(),
        'source_asset_uuid': asset_uuid,
        'hash_verified': hash_verified,
        'hash': f'sha256:{calculated_hash}'
    }), 201

@content_bp.route('/from-catalog', methods=['POST'])
def add_content_from_catalog():
    """
    Add content to CMS from Content Catalog drag-and-drop.
    
    Called when user drags an approved asset from Content Catalog
    and drops it into CMS content library.
    """
    from cms.models import db
    from cms.models.content import Content
    from datetime import datetime, timezone
    
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    catalog_uuid = data.get('catalog_uuid')
    if not catalog_uuid:
        return jsonify({'error': 'catalog_uuid is required'}), 400
    
    # Check if content already exists
    existing = Content.query.filter_by(catalog_asset_uuid=catalog_uuid).first()
    if existing:
        return jsonify({
            'error': 'Content already exists',
            'message': f'This asset is already in your library as "{existing.title or existing.original_name}"',
            'content_id': existing.id
        }), 409
    
    # Create new content entry
    try:
        content = Content(
            title=data.get('title', 'Untitled'),
            original_name=data.get('filename', ''),
            content_type=data.get('format', 'video'),
            file_size=data.get('file_size', 0),
            duration=data.get('duration', 0),
            catalog_asset_uuid=catalog_uuid,
            source='catalog',
            created_at=datetime.now(timezone.utc)
        )
        
        db.session.add(content)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Content added to library',
            'content_id': content.id,
            'title': content.title
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': 'Failed to add content',
            'message': str(e)
        }), 500
