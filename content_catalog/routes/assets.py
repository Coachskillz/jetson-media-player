"""
Content Catalog Assets Routes

Blueprint for content asset management API endpoints:
- POST /upload: Upload a content file with metadata
- POST /: Create a new content asset (metadata only)
- GET /: List all content assets
- GET /<asset_id>: Get a specific content asset by UUID
- PUT /<asset_id>: Update a content asset
- DELETE /<asset_id>: Delete a content asset
- GET /<asset_id>/download: Download the content file
- GET /<asset_id>/thumbnail: Get the asset thumbnail
- POST /<asset_id>/submit: Submit asset for review
- POST /<asset_id>/approve: Approve a pending asset
- POST /<asset_id>/reject: Reject a pending asset
- POST /<asset_id>/publish: Publish an approved asset

All endpoints are prefixed with /api/v1/assets when registered with the app.
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, request, jsonify, current_app, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from werkzeug.utils import secure_filename

from content_catalog.models import db, ContentAsset, ContentApprovalRequest, Organization, User
from content_catalog.services.audit_service import AuditService


# Create assets blueprint
assets_bp = Blueprint('assets', __name__)


def _get_current_user():
    """
    Get the current authenticated user from JWT identity.

    Returns:
        User object or None if not found
    """
    current_user_id = get_jwt_identity()
    if current_user_id is None:
        return None
    return db.session.get(User, current_user_id)


def _can_manage_content(user):
    """
    Check if the user has permission to manage content (approve/reject/publish).

    Only Super Admins, Admins, and Content Managers can manage content.

    Args:
        user: The User object to check permissions for

    Returns:
        True if user can manage content, False otherwise
    """
    if not user:
        return False
    return user.role in [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER
    ]


def _can_upload_content(user):
    """
    Check if the user has permission to upload and submit content.

    Super Admins, Admins, Content Managers, Partners, and Advertisers can upload.

    Args:
        user: The User object to check permissions for

    Returns:
        True if user can upload content, False otherwise
    """
    if not user:
        return False
    return user.role in [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER,
        User.ROLE_PARTNER,
        User.ROLE_ADVERTISER
    ]


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


@assets_bp.route('/upload', methods=['POST'])
@jwt_required()
def upload_asset():
    """
    Upload a content file and create an asset record.

    Content files are media files (images, videos) that are stored
    with UUID-based filenames for secure storage.

    Requires JWT authentication.

    Form Data:
        file: The media file to upload (required)
        title: Asset title (required)
        description: Description of the content (optional)
        organization_id: ID of the organization this asset belongs to (optional)
        duration: Duration in seconds for video/audio (optional)
        resolution: Resolution string e.g. "1920x1080" (optional)
        tags: Comma-separated tags (optional)
        category: Asset category (optional)
        networks: JSON string of network assignments (optional)
        zoho_campaign_id: Zoho campaign ID (optional)

    Returns:
        201: Content asset created successfully
            {
                "id": 1,
                "uuid": "uuid-string",
                "title": "My Video",
                "filename": "uuid.mp4",
                "file_path": "/uploads/uuid.mp4",
                "file_size": 52428800,
                "format": "mp4",
                "created_at": "2024-01-15T10:00:00Z"
            }
        400: Missing file or invalid data
            {
                "error": "error message"
            }
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions to upload content
        413: File too large (handled by Flask)
    """
    # Get current user and check permissions
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to upload content
    if not _can_upload_content(current_user):
        return jsonify({'error': 'Insufficient permissions to upload content'}), 403

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

    # Validate title (required for content assets)
    title = request.form.get('title')
    if not title:
        return jsonify({'error': 'title is required'}), 400

    if len(title) > 500:
        return jsonify({
            'error': 'title must be a string with max 500 characters'
        }), 400

    # Validate organization_id if provided
    organization_id = request.form.get('organization_id')
    if organization_id:
        try:
            organization_id = int(organization_id)
        except (ValueError, TypeError):
            return jsonify({
                'error': 'organization_id must be a valid integer'
            }), 400

        organization = db.session.get(Organization, organization_id)
        if not organization:
            return jsonify({
                'error': f'Organization with id {organization_id} not found'
            }), 400

    # Generate unique UUID-based filename
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

    # Get MIME type and format
    mime_type = get_mime_type(original_filename)
    file_format = file_ext if file_ext else None

    # Parse optional metadata
    description = request.form.get('description')
    duration = request.form.get('duration')
    resolution = request.form.get('resolution')
    tags = request.form.get('tags')
    category = request.form.get('category')
    networks = request.form.get('networks')
    zoho_campaign_id = request.form.get('zoho_campaign_id')

    # Validate and parse duration
    if duration:
        try:
            duration = float(duration)
            if duration < 0:
                duration = None
        except (ValueError, TypeError):
            duration = None

    # Create content asset record
    asset = ContentAsset(
        title=title,
        description=description,
        filename=unique_filename,
        file_path=str(file_path),
        file_size=file_size,
        duration=duration,
        resolution=resolution,
        format=file_format,
        organization_id=organization_id,
        uploaded_by=current_user.id,
        tags=tags,
        category=category,
        networks=networks,
        zoho_campaign_id=zoho_campaign_id
    )

    try:
        db.session.add(asset)
        db.session.flush()  # Get asset.id without committing

        # Log the upload action
        AuditService.log_action(
            db_session=db.session,
            action='content.uploaded',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'asset_uuid': asset.uuid,
                'asset_title': asset.title,
                'filename': asset.filename,
                'file_size': asset.file_size,
                'format': asset.format,
                'organization_id': asset.organization_id
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Clean up uploaded file on database error
        try:
            os.remove(str(file_path))
        except OSError:
            pass
        return jsonify({
            'error': f'Failed to create content asset: {str(e)}'
        }), 500

    return jsonify(asset.to_dict()), 201


@assets_bp.route('', methods=['POST'])
def create_asset():
    """
    Create a new content asset.

    Content assets represent media files with metadata in the content catalog.
    This endpoint creates asset metadata; file upload is handled separately.

    Request Body:
        {
            "title": "My Video" (required),
            "description": "Description of the content" (optional),
            "filename": "video.mp4" (required),
            "file_path": "/path/to/video.mp4" (required),
            "file_size": 52428800 (optional),
            "duration": 120.5 (optional, seconds),
            "resolution": "1920x1080" (optional),
            "format": "mp4" (optional),
            "thumbnail_path": "/path/to/thumb.jpg" (optional),
            "checksum": "abc123..." (optional),
            "organization_id": 1 (optional),
            "tags": "tag1,tag2,tag3" (optional),
            "category": "entertainment" (optional),
            "networks": "[\"network1\", \"network2\"]" (optional, JSON string),
            "zoho_campaign_id": "12345" (optional)
        }

    Returns:
        201: Content asset created successfully
            { asset data }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate required fields
    title = data.get('title')
    if not title:
        return jsonify({'error': 'title is required'}), 400

    if not isinstance(title, str) or len(title) > 500:
        return jsonify({
            'error': 'title must be a string with max 500 characters'
        }), 400

    filename = data.get('filename')
    if not filename:
        return jsonify({'error': 'filename is required'}), 400

    if not isinstance(filename, str) or len(filename) > 500:
        return jsonify({
            'error': 'filename must be a string with max 500 characters'
        }), 400

    file_path = data.get('file_path')
    if not file_path:
        return jsonify({'error': 'file_path is required'}), 400

    if not isinstance(file_path, str) or len(file_path) > 1000:
        return jsonify({
            'error': 'file_path must be a string with max 1000 characters'
        }), 400

    # Validate description if provided
    description = data.get('description')
    if description is not None and not isinstance(description, str):
        return jsonify({
            'error': 'description must be a string'
        }), 400

    # Validate file_size if provided
    file_size = data.get('file_size')
    if file_size is not None:
        try:
            file_size = int(file_size)
            if file_size < 0:
                return jsonify({
                    'error': 'file_size must be a non-negative integer'
                }), 400
        except (ValueError, TypeError):
            return jsonify({
                'error': 'file_size must be a valid integer'
            }), 400

    # Validate duration if provided
    duration = data.get('duration')
    if duration is not None:
        try:
            duration = float(duration)
            if duration < 0:
                return jsonify({
                    'error': 'duration must be a non-negative number'
                }), 400
        except (ValueError, TypeError):
            return jsonify({
                'error': 'duration must be a valid number'
            }), 400

    # Validate resolution if provided
    resolution = data.get('resolution')
    if resolution is not None:
        if not isinstance(resolution, str) or len(resolution) > 50:
            return jsonify({
                'error': 'resolution must be a string with max 50 characters'
            }), 400

    # Validate format if provided
    file_format = data.get('format')
    if file_format is not None:
        if not isinstance(file_format, str) or len(file_format) > 50:
            return jsonify({
                'error': 'format must be a string with max 50 characters'
            }), 400

    # Validate thumbnail_path if provided
    thumbnail_path = data.get('thumbnail_path')
    if thumbnail_path is not None:
        if not isinstance(thumbnail_path, str) or len(thumbnail_path) > 1000:
            return jsonify({
                'error': 'thumbnail_path must be a string with max 1000 characters'
            }), 400

    # Validate checksum if provided
    checksum = data.get('checksum')
    if checksum is not None:
        if not isinstance(checksum, str) or len(checksum) > 255:
            return jsonify({
                'error': 'checksum must be a string with max 255 characters'
            }), 400

    # Validate organization_id if provided
    organization_id = data.get('organization_id')
    if organization_id is not None:
        try:
            organization_id = int(organization_id)
        except (ValueError, TypeError):
            return jsonify({
                'error': 'organization_id must be a valid integer'
            }), 400

        organization = db.session.get(Organization, organization_id)
        if not organization:
            return jsonify({
                'error': f'Organization with id {organization_id} not found'
            }), 400

    # Validate tags if provided
    tags = data.get('tags')
    if tags is not None and not isinstance(tags, str):
        return jsonify({
            'error': 'tags must be a comma-separated string'
        }), 400

    # Validate category if provided
    category = data.get('category')
    if category is not None:
        if not isinstance(category, str) or len(category) > 100:
            return jsonify({
                'error': 'category must be a string with max 100 characters'
            }), 400

    # Validate networks if provided
    networks = data.get('networks')
    if networks is not None and not isinstance(networks, str):
        return jsonify({
            'error': 'networks must be a JSON string'
        }), 400

    # Validate zoho_campaign_id if provided
    zoho_campaign_id = data.get('zoho_campaign_id')
    if zoho_campaign_id is not None:
        if not isinstance(zoho_campaign_id, str) or len(zoho_campaign_id) > 100:
            return jsonify({
                'error': 'zoho_campaign_id must be a string with max 100 characters'
            }), 400

    # Create content asset
    asset = ContentAsset(
        title=title,
        description=description,
        filename=filename,
        file_path=file_path,
        file_size=file_size,
        duration=duration,
        resolution=resolution,
        format=file_format,
        thumbnail_path=thumbnail_path,
        checksum=checksum,
        organization_id=organization_id,
        tags=tags,
        category=category,
        networks=networks,
        zoho_campaign_id=zoho_campaign_id
    )

    try:
        db.session.add(asset)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create content asset: {str(e)}'
        }), 500

    return jsonify(asset.to_dict()), 201


@assets_bp.route('', methods=['GET'])
def list_assets():
    """
    List all content assets.

    Returns a list of all content assets in the catalog,
    with optional filtering by organization, status, or category.

    Query Parameters:
        organization_id: Filter by organization ID (optional)
        status: Filter by asset status (optional)
        category: Filter by category (optional)
        format: Filter by file format (optional)

    Returns:
        200: List of content assets
            {
                "assets": [ { asset data }, ... ],
                "count": 10
            }
    """
    # Build query
    query = ContentAsset.query

    # Filter by organization_id if provided
    organization_id = request.args.get('organization_id')
    if organization_id:
        try:
            organization_id = int(organization_id)
            query = query.filter_by(organization_id=organization_id)
        except ValueError:
            return jsonify({
                'error': 'organization_id must be a valid integer'
            }), 400

    # Filter by status if provided
    status = request.args.get('status')
    if status:
        if status not in ContentAsset.VALID_STATUSES:
            return jsonify({
                'error': f"status must be one of: {', '.join(ContentAsset.VALID_STATUSES)}"
            }), 400
        query = query.filter_by(status=status)

    # Filter by category if provided
    category = request.args.get('category')
    if category:
        query = query.filter_by(category=category)

    # Filter by format if provided
    file_format = request.args.get('format')
    if file_format:
        query = query.filter_by(format=file_format)

    # Execute query ordered by creation date (newest first)
    assets = query.order_by(ContentAsset.created_at.desc()).all()

    return jsonify({
        'assets': [asset.to_dict() for asset in assets],
        'count': len(assets)
    }), 200


@assets_bp.route('/<asset_id>', methods=['GET'])
def get_asset(asset_id):
    """
    Get a specific content asset by UUID.

    Args:
        asset_id: Content asset UUID

    Returns:
        200: Content asset data
            { asset data }
        400: Invalid asset_id format
            {
                "error": "Invalid asset_id format"
            }
        404: Content asset not found
            {
                "error": "Content asset not found"
            }
    """
    # Validate asset_id format (UUID should be 36 chars)
    if not isinstance(asset_id, str) or len(asset_id) > 64:
        return jsonify({
            'error': 'Invalid asset_id format'
        }), 400

    # Look up by UUID
    asset = ContentAsset.get_by_uuid(asset_id)

    if not asset:
        return jsonify({'error': 'Content asset not found'}), 404

    return jsonify(asset.to_dict()), 200


@assets_bp.route('/<asset_id>', methods=['PUT'])
def update_asset(asset_id):
    """
    Update an existing content asset.

    Args:
        asset_id: Content asset UUID

    Request Body:
        {
            "title": "Updated Title" (optional),
            "description": "Updated description" (optional),
            "filename": "updated.mp4" (optional),
            "file_path": "/new/path/to/file.mp4" (optional),
            "file_size": 12345678 (optional),
            "duration": 180.5 (optional),
            "resolution": "3840x2160" (optional),
            "format": "mp4" (optional),
            "thumbnail_path": "/path/to/new_thumb.jpg" (optional),
            "checksum": "new_checksum..." (optional),
            "organization_id": 2 (optional),
            "status": "pending_review" (optional),
            "tags": "new,tags,here" (optional),
            "category": "marketing" (optional),
            "networks": "[\"net1\"]" (optional),
            "zoho_campaign_id": "67890" (optional)
        }

    Returns:
        200: Updated content asset
            { asset data }
        400: Invalid data
            {
                "error": "error message"
            }
        404: Content asset not found
            {
                "error": "Content asset not found"
            }
    """
    # Validate asset_id format
    if not isinstance(asset_id, str) or len(asset_id) > 64:
        return jsonify({
            'error': 'Invalid asset_id format'
        }), 400

    # Look up by UUID
    asset = ContentAsset.get_by_uuid(asset_id)

    if not asset:
        return jsonify({'error': 'Content asset not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Update title if provided
    if 'title' in data:
        title = data['title']
        if not title:
            return jsonify({'error': 'title cannot be empty'}), 400
        if not isinstance(title, str) or len(title) > 500:
            return jsonify({
                'error': 'title must be a string with max 500 characters'
            }), 400
        asset.title = title

    # Update description if provided
    if 'description' in data:
        description = data['description']
        if description is not None and not isinstance(description, str):
            return jsonify({
                'error': 'description must be a string'
            }), 400
        asset.description = description

    # Update filename if provided
    if 'filename' in data:
        filename = data['filename']
        if not filename:
            return jsonify({'error': 'filename cannot be empty'}), 400
        if not isinstance(filename, str) or len(filename) > 500:
            return jsonify({
                'error': 'filename must be a string with max 500 characters'
            }), 400
        asset.filename = filename

    # Update file_path if provided
    if 'file_path' in data:
        file_path = data['file_path']
        if not file_path:
            return jsonify({'error': 'file_path cannot be empty'}), 400
        if not isinstance(file_path, str) or len(file_path) > 1000:
            return jsonify({
                'error': 'file_path must be a string with max 1000 characters'
            }), 400
        asset.file_path = file_path

    # Update file_size if provided
    if 'file_size' in data:
        file_size = data['file_size']
        if file_size is not None:
            try:
                file_size = int(file_size)
                if file_size < 0:
                    return jsonify({
                        'error': 'file_size must be a non-negative integer'
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'error': 'file_size must be a valid integer'
                }), 400
        asset.file_size = file_size

    # Update duration if provided
    if 'duration' in data:
        duration = data['duration']
        if duration is not None:
            try:
                duration = float(duration)
                if duration < 0:
                    return jsonify({
                        'error': 'duration must be a non-negative number'
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'error': 'duration must be a valid number'
                }), 400
        asset.duration = duration

    # Update resolution if provided
    if 'resolution' in data:
        resolution = data['resolution']
        if resolution is not None:
            if not isinstance(resolution, str) or len(resolution) > 50:
                return jsonify({
                    'error': 'resolution must be a string with max 50 characters'
                }), 400
        asset.resolution = resolution

    # Update format if provided
    if 'format' in data:
        file_format = data['format']
        if file_format is not None:
            if not isinstance(file_format, str) or len(file_format) > 50:
                return jsonify({
                    'error': 'format must be a string with max 50 characters'
                }), 400
        asset.format = file_format

    # Update thumbnail_path if provided
    if 'thumbnail_path' in data:
        thumbnail_path = data['thumbnail_path']
        if thumbnail_path is not None:
            if not isinstance(thumbnail_path, str) or len(thumbnail_path) > 1000:
                return jsonify({
                    'error': 'thumbnail_path must be a string with max 1000 characters'
                }), 400
        asset.thumbnail_path = thumbnail_path

    # Update checksum if provided
    if 'checksum' in data:
        checksum = data['checksum']
        if checksum is not None:
            if not isinstance(checksum, str) or len(checksum) > 255:
                return jsonify({
                    'error': 'checksum must be a string with max 255 characters'
                }), 400
        asset.checksum = checksum

    # Update organization_id if provided
    if 'organization_id' in data:
        organization_id = data['organization_id']
        if organization_id is not None:
            try:
                organization_id = int(organization_id)
            except (ValueError, TypeError):
                return jsonify({
                    'error': 'organization_id must be a valid integer'
                }), 400

            organization = db.session.get(Organization, organization_id)
            if not organization:
                return jsonify({
                    'error': f'Organization with id {organization_id} not found'
                }), 400
        asset.organization_id = organization_id

    # Update status if provided
    if 'status' in data:
        status = data['status']
        if not status:
            return jsonify({'error': 'status cannot be empty'}), 400
        if status not in ContentAsset.VALID_STATUSES:
            return jsonify({
                'error': f"status must be one of: {', '.join(ContentAsset.VALID_STATUSES)}"
            }), 400
        asset.status = status

    # Update tags if provided
    if 'tags' in data:
        tags = data['tags']
        if tags is not None and not isinstance(tags, str):
            return jsonify({
                'error': 'tags must be a comma-separated string'
            }), 400
        asset.tags = tags

    # Update category if provided
    if 'category' in data:
        category = data['category']
        if category is not None:
            if not isinstance(category, str) or len(category) > 100:
                return jsonify({
                    'error': 'category must be a string with max 100 characters'
                }), 400
        asset.category = category

    # Update networks if provided
    if 'networks' in data:
        networks = data['networks']
        if networks is not None and not isinstance(networks, str):
            return jsonify({
                'error': 'networks must be a JSON string'
            }), 400
        asset.networks = networks

    # Update zoho_campaign_id if provided
    if 'zoho_campaign_id' in data:
        zoho_campaign_id = data['zoho_campaign_id']
        if zoho_campaign_id is not None:
            if not isinstance(zoho_campaign_id, str) or len(zoho_campaign_id) > 100:
                return jsonify({
                    'error': 'zoho_campaign_id must be a string with max 100 characters'
                }), 400
        asset.zoho_campaign_id = zoho_campaign_id

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update content asset: {str(e)}'
        }), 500

    return jsonify(asset.to_dict()), 200


@assets_bp.route('/<asset_id>', methods=['DELETE'])
def delete_asset(asset_id):
    """
    Delete a content asset.

    Removes the content asset record from the database.
    Note: This does not delete the actual file from storage.

    Args:
        asset_id: Content asset UUID

    Returns:
        200: Content asset deleted successfully
            {
                "message": "Content asset deleted successfully",
                "id": 1,
                "uuid": "uuid-string"
            }
        400: Invalid asset_id format
            {
                "error": "Invalid asset_id format"
            }
        404: Content asset not found
            {
                "error": "Content asset not found"
            }
    """
    # Validate asset_id format
    if not isinstance(asset_id, str) or len(asset_id) > 64:
        return jsonify({
            'error': 'Invalid asset_id format'
        }), 400

    # Look up by UUID
    asset = ContentAsset.get_by_uuid(asset_id)

    if not asset:
        return jsonify({'error': 'Content asset not found'}), 404

    # Store info for response
    asset_id_response = asset.id
    asset_uuid = asset.uuid

    # Delete from database
    try:
        db.session.delete(asset)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to delete content asset: {str(e)}'
        }), 500

    return jsonify({
        'message': 'Content asset deleted successfully',
        'id': asset_id_response,
        'uuid': asset_uuid
    }), 200


@assets_bp.route('/<asset_id>/download', methods=['GET'])
def download_asset(asset_id):
    """
    Download the content file for an asset.

    Args:
        asset_id: Content asset UUID

    Returns:
        200: File download stream
        400: Invalid asset_id format
            {
                "error": "Invalid asset_id format"
            }
        404: Content asset not found or file not found
            {
                "error": "error message"
            }
        500: Server error
            {
                "error": "error message"
            }
    """
    # Validate asset_id format
    if not isinstance(asset_id, str) or len(asset_id) > 64:
        return jsonify({
            'error': 'Invalid asset_id format'
        }), 400

    # Look up by UUID
    asset = ContentAsset.get_by_uuid(asset_id)

    if not asset:
        return jsonify({'error': 'Content asset not found'}), 404

    # Check if file path exists
    if not asset.file_path:
        return jsonify({'error': 'File path not available'}), 404

    file_path = Path(asset.file_path)

    # Check if file exists on disk
    if not file_path.exists():
        return jsonify({'error': 'File not found on disk'}), 404

    # Determine MIME type
    mime_type = get_mime_type(asset.filename or asset.file_path)

    try:
        return send_file(
            str(file_path),
            mimetype=mime_type,
            as_attachment=True,
            download_name=asset.filename
        )
    except Exception as e:
        return jsonify({
            'error': f'Failed to download file: {str(e)}'
        }), 500


@assets_bp.route('/<asset_id>/thumbnail', methods=['GET'])
def get_asset_thumbnail(asset_id):
    """
    Get the thumbnail image for an asset.

    Args:
        asset_id: Content asset UUID

    Returns:
        200: Thumbnail image stream
        400: Invalid asset_id format
            {
                "error": "Invalid asset_id format"
            }
        404: Content asset not found or thumbnail not available
            {
                "error": "error message"
            }
        500: Server error
            {
                "error": "error message"
            }
    """
    # Validate asset_id format
    if not isinstance(asset_id, str) or len(asset_id) > 64:
        return jsonify({
            'error': 'Invalid asset_id format'
        }), 400

    # Look up by UUID
    asset = ContentAsset.get_by_uuid(asset_id)

    if not asset:
        return jsonify({'error': 'Content asset not found'}), 404

    # Check if thumbnail path exists
    if not asset.thumbnail_path:
        return jsonify({'error': 'Thumbnail not available'}), 404

    thumbnail_path = Path(asset.thumbnail_path)

    # Check if thumbnail file exists on disk
    if not thumbnail_path.exists():
        return jsonify({'error': 'Thumbnail file not found on disk'}), 404

    # Determine MIME type for thumbnail
    mime_type = get_mime_type(asset.thumbnail_path)

    try:
        return send_file(
            str(thumbnail_path),
            mimetype=mime_type,
            as_attachment=False
        )
    except Exception as e:
        return jsonify({
            'error': f'Failed to retrieve thumbnail: {str(e)}'
        }), 500


@assets_bp.route('/<asset_id>/submit', methods=['POST'])
@jwt_required()
def submit_asset(asset_id):
    """
    Submit a content asset for review.

    Changes the asset status from 'draft' or 'rejected' to 'pending_review'.
    Creates a content approval request for tracking the workflow.

    Args:
        asset_id: Content asset UUID

    Request Body (optional):
        {
            "notes": "Submission notes" (optional)
        }

    Returns:
        200: Asset submitted for review successfully
            {
                "message": "Asset submitted for review",
                "asset": { asset data }
            }
        400: Invalid asset_id format
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions to submit content
        404: Content asset not found
        409: Asset cannot be submitted (wrong status)
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to submit content
    if not _can_upload_content(current_user):
        return jsonify({'error': 'Insufficient permissions to submit content'}), 403

    # Validate asset_id format
    if not isinstance(asset_id, str) or len(asset_id) > 64:
        return jsonify({
            'error': 'Invalid asset_id format'
        }), 400

    # Look up by UUID
    asset = ContentAsset.get_by_uuid(asset_id)

    if not asset:
        return jsonify({'error': 'Content asset not found'}), 404

    # Check if asset can be submitted for review
    if not asset.can_submit_for_review():
        return jsonify({
            'error': f"Cannot submit asset: status is '{asset.status}'. Only 'draft' or 'rejected' assets can be submitted for review."
        }), 409

    # Parse request body if provided
    data = request.get_json(silent=True) or {}

    # Validate notes if provided
    notes = data.get('notes')
    if notes and (not isinstance(notes, str) or len(notes) > 1000):
        return jsonify({
            'error': 'notes must be a string with max 1000 characters'
        }), 400

    # Update asset status
    previous_status = asset.status
    asset.status = ContentAsset.STATUS_PENDING_REVIEW

    # Create content approval request for tracking
    approval_request = ContentApprovalRequest(
        asset_id=asset.id,
        requested_by=current_user.id,
        status=ContentApprovalRequest.STATUS_PENDING,
        notes=notes
    )

    try:
        db.session.add(approval_request)

        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='content.submitted',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'asset_uuid': asset.uuid,
                'asset_title': asset.title,
                'previous_status': previous_status,
                'new_status': asset.status,
                'notes': notes
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to submit asset: {str(e)}'}), 500

    return jsonify({
        'message': 'Asset submitted for review',
        'asset': asset.to_dict()
    }), 200


@assets_bp.route('/<asset_id>/approve', methods=['POST'])
@jwt_required()
def approve_asset(asset_id):
    """
    Approve a pending content asset.

    Changes the asset status from 'pending_review' to 'approved'.
    Only Content Managers and above can approve content.

    Args:
        asset_id: Content asset UUID

    Request Body (optional):
        {
            "notes": "Approval notes" (optional)
        }

    Returns:
        200: Asset approved successfully
            {
                "message": "Asset approved successfully",
                "asset": { asset data }
            }
        400: Invalid asset_id format
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions to approve content
        404: Content asset not found
        409: Asset cannot be approved (wrong status)
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to approve content
    if not _can_manage_content(current_user):
        return jsonify({'error': 'Insufficient permissions to approve content'}), 403

    # Validate asset_id format
    if not isinstance(asset_id, str) or len(asset_id) > 64:
        return jsonify({
            'error': 'Invalid asset_id format'
        }), 400

    # Look up by UUID
    asset = ContentAsset.get_by_uuid(asset_id)

    if not asset:
        return jsonify({'error': 'Content asset not found'}), 404

    # Check if asset can be approved
    if not asset.can_approve():
        return jsonify({
            'error': f"Cannot approve asset: status is '{asset.status}'. Only 'pending_review' assets can be approved."
        }), 409

    # Parse request body if provided
    data = request.get_json(silent=True) or {}

    # Validate notes if provided
    notes = data.get('notes')
    if notes and (not isinstance(notes, str) or len(notes) > 1000):
        return jsonify({
            'error': 'notes must be a string with max 1000 characters'
        }), 400

    # Update asset status and review fields
    previous_status = asset.status
    asset.status = ContentAsset.STATUS_APPROVED
    asset.reviewed_by = current_user.id
    asset.reviewed_at = datetime.now(timezone.utc)
    asset.review_notes = notes

    # Update pending approval request if exists
    pending_request = ContentApprovalRequest.query.filter_by(
        asset_id=asset.id,
        status=ContentApprovalRequest.STATUS_PENDING
    ).first()

    if pending_request:
        pending_request.status = ContentApprovalRequest.STATUS_APPROVED
        pending_request.assigned_to = current_user.id
        pending_request.resolved_at = datetime.now(timezone.utc)
        if notes:
            pending_request.notes = notes

    try:
        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='content.approved',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'asset_uuid': asset.uuid,
                'asset_title': asset.title,
                'previous_status': previous_status,
                'new_status': asset.status,
                'notes': notes
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to approve asset: {str(e)}'}), 500

    return jsonify({
        'message': 'Asset approved successfully',
        'asset': asset.to_dict()
    }), 200


@assets_bp.route('/<asset_id>/reject', methods=['POST'])
@jwt_required()
def reject_asset(asset_id):
    """
    Reject a pending content asset.

    Changes the asset status from 'pending_review' to 'rejected'.
    Only Content Managers and above can reject content.
    A rejection reason is required.

    Args:
        asset_id: Content asset UUID

    Request Body:
        {
            "reason": "Rejection reason" (required)
        }

    Returns:
        200: Asset rejected successfully
            {
                "message": "Asset rejected successfully",
                "asset": { asset data }
            }
        400: Missing or invalid rejection reason
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions to reject content
        404: Content asset not found
        409: Asset cannot be rejected (wrong status)
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to reject content
    if not _can_manage_content(current_user):
        return jsonify({'error': 'Insufficient permissions to reject content'}), 403

    # Validate asset_id format
    if not isinstance(asset_id, str) or len(asset_id) > 64:
        return jsonify({
            'error': 'Invalid asset_id format'
        }), 400

    # Look up by UUID
    asset = ContentAsset.get_by_uuid(asset_id)

    if not asset:
        return jsonify({'error': 'Content asset not found'}), 404

    # Check if asset can be rejected (must be pending_review)
    if not asset.can_approve():  # Same check as approve - must be pending_review
        return jsonify({
            'error': f"Cannot reject asset: status is '{asset.status}'. Only 'pending_review' assets can be rejected."
        }), 409

    # Parse request body
    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate rejection reason (required)
    reason = data.get('reason')
    if not reason:
        return jsonify({'error': 'reason is required'}), 400

    if not isinstance(reason, str) or len(reason) > 1000:
        return jsonify({
            'error': 'reason must be a string with max 1000 characters'
        }), 400

    reason = reason.strip()
    if not reason:
        return jsonify({'error': 'reason cannot be empty'}), 400

    # Update asset status and review fields
    previous_status = asset.status
    asset.status = ContentAsset.STATUS_REJECTED
    asset.reviewed_by = current_user.id
    asset.reviewed_at = datetime.now(timezone.utc)
    asset.review_notes = reason

    # Update pending approval request if exists
    pending_request = ContentApprovalRequest.query.filter_by(
        asset_id=asset.id,
        status=ContentApprovalRequest.STATUS_PENDING
    ).first()

    if pending_request:
        pending_request.status = ContentApprovalRequest.STATUS_REJECTED
        pending_request.assigned_to = current_user.id
        pending_request.resolved_at = datetime.now(timezone.utc)
        pending_request.notes = reason

    try:
        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='content.rejected',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'asset_uuid': asset.uuid,
                'asset_title': asset.title,
                'previous_status': previous_status,
                'new_status': asset.status,
                'reason': reason
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to reject asset: {str(e)}'}), 500

    return jsonify({
        'message': 'Asset rejected successfully',
        'asset': asset.to_dict()
    }), 200


@assets_bp.route('/<asset_id>/publish', methods=['POST'])
@jwt_required()
def publish_asset(asset_id):
    """
    Publish an approved content asset.

    Changes the asset status from 'approved' to 'published'.
    Only Content Managers and above can publish content.

    Args:
        asset_id: Content asset UUID

    Request Body (optional):
        {
            "notes": "Publishing notes" (optional)
        }

    Returns:
        200: Asset published successfully
            {
                "message": "Asset published successfully",
                "asset": { asset data }
            }
        400: Invalid asset_id format
        401: Unauthorized (missing or invalid token)
        403: Insufficient permissions to publish content
        404: Content asset not found
        409: Asset cannot be published (wrong status)
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to publish content
    if not _can_manage_content(current_user):
        return jsonify({'error': 'Insufficient permissions to publish content'}), 403

    # Validate asset_id format
    if not isinstance(asset_id, str) or len(asset_id) > 64:
        return jsonify({
            'error': 'Invalid asset_id format'
        }), 400

    # Look up by UUID
    asset = ContentAsset.get_by_uuid(asset_id)

    if not asset:
        return jsonify({'error': 'Content asset not found'}), 404

    # Check if asset can be published
    if not asset.can_publish():
        return jsonify({
            'error': f"Cannot publish asset: status is '{asset.status}'. Only 'approved' assets can be published."
        }), 409

    # Parse request body if provided
    data = request.get_json(silent=True) or {}

    # Validate notes if provided
    notes = data.get('notes')
    if notes and (not isinstance(notes, str) or len(notes) > 1000):
        return jsonify({
            'error': 'notes must be a string with max 1000 characters'
        }), 400

    # Update asset status and publishing timestamp
    previous_status = asset.status
    asset.status = ContentAsset.STATUS_PUBLISHED
    asset.published_at = datetime.now(timezone.utc)

    try:
        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='content.published',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'asset_uuid': asset.uuid,
                'asset_title': asset.title,
                'previous_status': previous_status,
                'new_status': asset.status,
                'published_at': asset.published_at.isoformat(),
                'notes': notes
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to publish asset: {str(e)}'}), 500

    return jsonify({
        'message': 'Asset published successfully',
        'asset': asset.to_dict()
    }), 200
