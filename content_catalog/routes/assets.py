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
- GET /fasttrack: List DRAFT/SUBMITTED assets for fast-track users

All endpoints are prefixed with /api/v1/assets when registered with the app.

CMS Integration Blueprint (approved_assets_bp):
- GET /: List approved/published assets for CMS browsing

The approved_assets_bp is registered at /api/v1/approved-assets.
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
            organization = db.session.get(Organization, organization_id)
            if not organization:
                return jsonify({
                    'error': f'Organization with id {organization_id} not found'
                }), 400
        except (ValueError, TypeError):
            return jsonify({
                'error': 'organization_id must be a valid integer'
            }), 400

    # Get other optional fields
    tags = data.get('tags')
    category = data.get('category')
    networks = data.get('networks')
    zoho_campaign_id = data.get('zoho_campaign_id')

    # Create content asset record
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
    List all content assets with pagination and filtering.

    Query Parameters:
        page: Page number (default: 1)
        per_page: Items per page (default: 20, max: 100)
        status: Filter by status (DRAFT, SUBMITTED, APPROVED, PUBLISHED)
        organization_id: Filter by organization ID
        search: Search in title and description
        sort: Sort field (created_at, title, file_size) with optional :asc/:desc
        category: Filter by category

    Returns:
        200: List of content assets
            {
                "assets": [
                    {
                        "id": 1,
                        "uuid": "uuid-string",
                        "title": "My Video",
                        ...
                    }
                ],
                "total": 42,
                "page": 1,
                "per_page": 20,
                "pages": 3
            }
        400: Invalid parameters
    """
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    # Validate pagination parameters
    if page < 1:
        return jsonify({'error': 'page must be >= 1'}), 400
    if per_page < 1 or per_page > 100:
        return jsonify({'error': 'per_page must be between 1 and 100'}), 400

    # Build base query
    query = ContentAsset.query

    # Apply filters
    status = request.args.get('status')
    if status:
        query = query.filter_by(status=status)

    organization_id = request.args.get('organization_id', type=int)
    if organization_id:
        query = query.filter_by(organization_id=organization_id)

    search = request.args.get('search')
    if search:
        query = query.filter(
            (ContentAsset.title.ilike(f'%{search}%')) |
            (ContentAsset.description.ilike(f'%{search}%'))
        )

    category = request.args.get('category')
    if category:
        query = query.filter_by(category=category)

    # Apply sorting
    sort = request.args.get('sort', 'created_at:desc')
    if sort:
        parts = sort.split(':')
        sort_field = parts[0]
        sort_direction = parts[1] if len(parts) > 1 else 'asc'

        valid_sorts = ['created_at', 'title', 'file_size', 'status']
        if sort_field not in valid_sorts:
            return jsonify({
                'error': f'Invalid sort field. Valid fields: {", ".join(valid_sorts)}'
            }), 400

        if sort_direction.lower() == 'desc':
            query = query.order_by(getattr(ContentAsset, sort_field).desc())
        else:
            query = query.order_by(getattr(ContentAsset, sort_field).asc())

    # Get paginated results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'assets': [asset.to_dict() for asset in pagination.items],
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'pages': pagination.pages
    }), 200


@assets_bp.route('/<int:asset_id>', methods=['GET'])
def get_asset(asset_id):
    """
    Get a specific content asset by ID.

    Args:
        asset_id: The content asset ID (integer)

    Returns:
        200: Content asset data
            { asset data }
        404: Asset not found
    """
    asset = db.session.get(ContentAsset, asset_id)

    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    return jsonify(asset.to_dict()), 200


@assets_bp.route('/uuid/<asset_uuid>', methods=['GET'])
def get_asset_by_uuid(asset_uuid):
    """
    Get a specific content asset by UUID.

    Args:
        asset_uuid: The content asset UUID

    Returns:
        200: Content asset data
            { asset data }
        404: Asset not found
    """
    asset = ContentAsset.query.filter_by(uuid=asset_uuid).first()

    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Include additional metadata for display
    result = asset.to_dict()

    # Add uploader info if available
    if asset.uploader:
        result['uploader_name'] = asset.uploader.name
        result['uploader_email'] = asset.uploader.email

    # Add approver info if available
    if asset.approver:
        result['approver_name'] = asset.approver.name
        result['approver_email'] = asset.approver.email

    # Add tenant info if available
    if asset.tenant:
        result['tenant_name'] = asset.tenant.name
        result['tenant_slug'] = asset.tenant.slug

    return jsonify(result), 200


@assets_bp.route('/<int:asset_id>', methods=['PUT'])
@jwt_required()
def update_asset(asset_id):
    """
    Update a content asset.

    Only the asset owner, organization admin, or super admin can update.

    Args:
        asset_id: The content asset ID (integer)

    Request Body:
        Any of the fields from create_asset endpoint

    Returns:
        200: Asset updated successfully
            { updated asset data }
        400: Invalid data
        401: Unauthorized
        403: Insufficient permissions
        404: Asset not found
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    asset = db.session.get(ContentAsset, asset_id)

    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Check permissions: owner, org admin, or super admin
    can_update = (
        asset.uploaded_by == current_user.id or
        current_user.role == User.ROLE_SUPER_ADMIN or
        (asset.organization_id and current_user.organization_id == asset.organization_id and
         current_user.role == User.ROLE_ADMIN)
    )

    if not can_update:
        return jsonify({'error': 'Insufficient permissions to update this asset'}), 403

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Update allowed fields
    updatable_fields = [
        'title', 'description', 'resolution', 'tags', 'category',
        'networks', 'zoho_campaign_id'
    ]

    for field in updatable_fields:
        if field in data:
            setattr(asset, field, data[field])

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update asset: {str(e)}'
        }), 500

    # Log the update action
    AuditService.log_action(
        db_session=db.session,
        action='content.updated',
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type='content_asset',
        resource_id=asset.id,
        details={
            'asset_uuid': asset.uuid,
            'asset_title': asset.title,
            'updated_fields': list(data.keys())
        }
    )

    return jsonify(asset.to_dict()), 200


@assets_bp.route('/<int:asset_id>', methods=['DELETE'])
@jwt_required()
def delete_asset(asset_id):
    """
    Delete a content asset.

    Only the asset owner, organization admin, or super admin can delete.
    The actual file is not deleted, only the database record.

    Args:
        asset_id: The content asset ID (integer)

    Returns:
        204: Asset deleted successfully
        401: Unauthorized
        403: Insufficient permissions
        404: Asset not found
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    asset = db.session.get(ContentAsset, asset_id)

    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Check permissions: owner, org admin, or super admin
    can_delete = (
        asset.uploaded_by == current_user.id or
        current_user.role == User.ROLE_SUPER_ADMIN or
        (asset.organization_id and current_user.organization_id == asset.organization_id and
         current_user.role == User.ROLE_ADMIN)
    )

    if not can_delete:
        return jsonify({'error': 'Insufficient permissions to delete this asset'}), 403

    try:
        # Log the deletion action
        AuditService.log_action(
            db_session=db.session,
            action='content.deleted',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'asset_uuid': asset.uuid,
                'asset_title': asset.title
            }
        )

        db.session.delete(asset)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to delete asset: {str(e)}'
        }), 500

    return '', 204


@assets_bp.route('/<int:asset_id>/download', methods=['GET'])
def download_asset(asset_id):
    """
    Download the content file for an asset.

    Args:
        asset_id: The content asset ID (integer)

    Returns:
        200: File content with appropriate MIME type
        404: Asset not found
    """
    asset = db.session.get(ContentAsset, asset_id)

    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    file_path = asset.file_path

    # Verify file exists
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found on storage'}), 404

    try:
        return send_file(
            file_path,
            mimetype=get_mime_type(asset.filename),
            as_attachment=True,
            download_name=asset.filename
        )
    except Exception as e:
        return jsonify({
            'error': f'Failed to download file: {str(e)}'
        }), 500


@assets_bp.route('/<int:asset_id>/preview', methods=['GET'])
def preview_asset(asset_id):
    """
    Preview the content file for an asset (inline playback).

    Args:
        asset_id: The content asset ID (integer)

    Returns:
        200: File content with appropriate MIME type for inline playback
        404: Asset not found
    """
    asset = db.session.get(ContentAsset, asset_id)

    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    file_path = asset.file_path

    # Verify file exists
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found on storage'}), 404

    try:
        return send_file(
            file_path,
            mimetype=get_mime_type(asset.filename),
            as_attachment=False
        )
    except Exception as e:
        return jsonify({
            'error': f'Failed to preview file: {str(e)}'
        }), 500


@assets_bp.route('/<int:asset_id>/thumbnail', methods=['GET'])
def get_thumbnail(asset_id):
    """
    Get the thumbnail for a content asset.

    Args:
        asset_id: The content asset ID (integer)

    Returns:
        200: Thumbnail image file
        404: Asset or thumbnail not found
    """
    asset = db.session.get(ContentAsset, asset_id)

    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    if not asset.thumbnail_path:
        return jsonify({'error': 'No thumbnail available'}), 404

    # Verify file exists
    if not os.path.exists(asset.thumbnail_path):
        return jsonify({'error': 'Thumbnail file not found on storage'}), 404

    try:
        return send_file(
            asset.thumbnail_path,
            mimetype='image/jpeg'
        )
    except Exception as e:
        return jsonify({
            'error': f'Failed to get thumbnail: {str(e)}'
        }), 500


@assets_bp.route('/<int:asset_id>/submit', methods=['POST'])
@jwt_required()
def submit_asset(asset_id):
    """
    Submit a DRAFT asset for approval.

    Changes asset status from DRAFT to SUBMITTED.
    Only the asset owner can submit for approval.

    Args:
        asset_id: The content asset ID (integer)

    Returns:
        200: Asset submitted for approval
            { updated asset data }
        401: Unauthorized
        403: Insufficient permissions
        404: Asset not found
        409: Asset not in DRAFT status
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    asset = db.session.get(ContentAsset, asset_id)

    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Check permissions: only owner can submit
    if asset.uploaded_by != current_user.id:
        return jsonify({'error': 'Insufficient permissions to submit this asset'}), 403

    # Check status
    if asset.status != ContentAsset.STATUS_DRAFT:
        return jsonify({
            'error': f'Asset status must be DRAFT to submit. Current status: {asset.status}'
        }), 409

    try:
        asset.status = ContentAsset.STATUS_SUBMITTED
        asset.submitted_at = datetime.now(timezone.utc)
        db.session.commit()

        # Log the submit action
        AuditService.log_action(
            db_session=db.session,
            action='content.submitted',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'asset_uuid': asset.uuid,
                'asset_title': asset.title
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to submit asset: {str(e)}'
        }), 500

    return jsonify(asset.to_dict()), 200


@assets_bp.route('/<int:asset_id>/approve', methods=['POST'])
@jwt_required()
def approve_asset(asset_id):
    """
    Approve a SUBMITTED asset.

    Changes asset status from SUBMITTED to APPROVED.
    Only content managers and admins can approve assets.

    Args:
        asset_id: The content asset ID (integer)

    Returns:
        200: Asset approved
            { updated asset data }
        401: Unauthorized
        403: Insufficient permissions
        404: Asset not found
        409: Asset not in SUBMITTED status
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check permissions
    if not _can_manage_content(current_user):
        return jsonify({'error': 'Insufficient permissions to approve assets'}), 403

    asset = db.session.get(ContentAsset, asset_id)

    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Check status
    if asset.status != ContentAsset.STATUS_SUBMITTED:
        return jsonify({
            'error': f'Asset status must be SUBMITTED to approve. Current status: {asset.status}'
        }), 409

    try:
        asset.status = ContentAsset.STATUS_APPROVED
        asset.approved_at = datetime.now(timezone.utc)
        asset.approved_by = current_user.id
        db.session.commit()

        # Log the approve action
        AuditService.log_action(
            db_session=db.session,
            action='content.approved',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'asset_uuid': asset.uuid,
                'asset_title': asset.title
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to approve asset: {str(e)}'
        }), 500

    return jsonify(asset.to_dict()), 200


@assets_bp.route('/<int:asset_id>/reject', methods=['POST'])
@jwt_required()
def reject_asset(asset_id):
    """
    Reject a SUBMITTED asset.

    Changes asset status from SUBMITTED back to DRAFT.
    Only content managers and admins can reject assets.

    Request Body (optional):
        {
            "reason": "Rejection reason (optional)"
        }

    Args:
        asset_id: The content asset ID (integer)

    Returns:
        200: Asset rejected
            { updated asset data }
        401: Unauthorized
        403: Insufficient permissions
        404: Asset not found
        409: Asset not in SUBMITTED status
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check permissions
    if not _can_manage_content(current_user):
        return jsonify({'error': 'Insufficient permissions to reject assets'}), 403

    asset = db.session.get(ContentAsset, asset_id)

    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Check status
    if asset.status != ContentAsset.STATUS_SUBMITTED:
        return jsonify({
            'error': f'Asset status must be SUBMITTED to reject. Current status: {asset.status}'
        }), 409

    data = request.get_json() or {}
    reason = data.get('reason')

    try:
        asset.status = ContentAsset.STATUS_DRAFT
        asset.rejected_reason = reason
        db.session.commit()

        # Log the reject action
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
                'rejection_reason': reason
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to reject asset: {str(e)}'
        }), 500

    return jsonify(asset.to_dict()), 200


@assets_bp.route('/<int:asset_id>/publish', methods=['POST'])
@jwt_required()
def publish_asset(asset_id):
    """
    Publish an APPROVED asset.

    Changes asset status from APPROVED to PUBLISHED.
    Only content managers and admins can publish assets.

    Args:
        asset_id: The content asset ID (integer)

    Returns:
        200: Asset published
            { updated asset data }
        401: Unauthorized
        403: Insufficient permissions
        404: Asset not found
        409: Asset not in APPROVED status
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check permissions
    if not _can_manage_content(current_user):
        return jsonify({'error': 'Insufficient permissions to publish assets'}), 403

    asset = db.session.get(ContentAsset, asset_id)

    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Check status
    if asset.status != ContentAsset.STATUS_APPROVED:
        return jsonify({
            'error': f'Asset status must be APPROVED to publish. Current status: {asset.status}'
        }), 409

    try:
        asset.status = ContentAsset.STATUS_PUBLISHED
        asset.published_at = datetime.now(timezone.utc)
        db.session.commit()

        # Log the publish action
        AuditService.log_action(
            db_session=db.session,
            action='content.published',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'asset_uuid': asset.uuid,
                'asset_title': asset.title
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to publish asset: {str(e)}'
        }), 500

    return jsonify(asset.to_dict()), 200


# CMS Integration Blueprint for browsing approved assets
approved_assets_bp = Blueprint('approved_assets', __name__)


@approved_assets_bp.route('', methods=['GET'])
def list_approved_assets():
    """
    List approved and published assets for CMS browsing.

    This endpoint is for CMS and public API to browse approved content.
    Only returns APPROVED and PUBLISHED assets.

    Query Parameters:
        page: Page number (default: 1)
        per_page: Items per page (default: 50, max: 100)
        search: Search in title and description
        category: Filter by category
        organization_id: Filter by organization
        sort: Sort field (created_at, title, published_at) with optional :asc/:desc

    Returns:
        200: List of approved/published assets
            {
                "assets": [
                    {
                        "id": 1,
                        "uuid": "uuid-string",
                        "title": "My Video",
                        ...
                    }
                ],
                "total": 42,
                "page": 1,
                "per_page": 50,
                "pages": 1
            }
        400: Invalid parameters
    """
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Validate pagination parameters
    if page < 1:
        return jsonify({'error': 'page must be >= 1'}), 400
    if per_page < 1 or per_page > 100:
        return jsonify({'error': 'per_page must be between 1 and 100'}), 400

    # Build base query for approved/published assets only
    query = ContentAsset.query.filter(
        ContentAsset.status.in_([
            ContentAsset.STATUS_APPROVED,
            ContentAsset.STATUS_PUBLISHED
        ])
    )

    # Apply filters
    search = request.args.get('search')
    if search:
        query = query.filter(
            (ContentAsset.title.ilike(f'%{search}%')) |
            (ContentAsset.description.ilike(f'%{search}%'))
        )

    category = request.args.get('category')
    if category:
        query = query.filter_by(category=category)

    organization_id = request.args.get('organization_id', type=int)
    if organization_id:
        query = query.filter_by(organization_id=organization_id)

    # Apply sorting
    sort = request.args.get('sort', 'published_at:desc')
    if sort:
        parts = sort.split(':')
        sort_field = parts[0]
        sort_direction = parts[1] if len(parts) > 1 else 'asc'

        valid_sorts = ['created_at', 'title', 'published_at']
        if sort_field not in valid_sorts:
            return jsonify({
                'error': f'Invalid sort field. Valid fields: {", ".join(valid_sorts)}'
            }), 400

        if sort_direction.lower() == 'desc':
            query = query.order_by(getattr(ContentAsset, sort_field).desc())
        else:
            query = query.order_by(getattr(ContentAsset, sort_field).asc())

    # Get paginated results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'assets': [asset.to_dict() for asset in pagination.items],
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'pages': pagination.pages
    }), 200