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
"""

import os
import uuid
from pathlib import Path

from flask import Blueprint, request, jsonify, send_file, current_app
from werkzeug.utils import secure_filename

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
    Upload a new content file.

    Content files are media files (images, videos) that can be assigned
    to playlists and displayed on devices. Files are saved to the uploads
    directory with a unique filename.

    Form Data:
        file: The media file to upload (required)
        network_id: UUID of the network this content belongs to (optional)
        width: Content width in pixels (optional)
        height: Content height in pixels (optional)
        duration: Duration in seconds for video/audio (optional)

    Returns:
        201: Content created successfully
            {
                "id": "uuid",
                "filename": "stored-filename.mp4",
                "original_name": "my-video.mp4",
                "mime_type": "video/mp4",
                "file_size": 52428800,
                "created_at": "2024-01-15T10:00:00Z"
            }
        400: Missing file or invalid data
            {
                "error": "error message"
            }
        413: File too large (handled by Flask)
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
        result = sync_service.sync_content(
            network_id=network_id,
            organization_id=organization_id,
            category=category
        )

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