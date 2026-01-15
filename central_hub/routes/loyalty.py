"""
Loyalty Routes Blueprint

REST API endpoints for per-network loyalty member management including
enrollment with face encoding, CRUD operations, database compilation,
and FAISS database download.

Endpoints:
- POST /api/v1/networks/<network_id>/loyalty/enroll - Enroll new member with photo
- GET /api/v1/networks/<network_id>/loyalty/members - List network members
- GET /api/v1/loyalty/members/<id> - Get single member
- PUT /api/v1/loyalty/members/<id> - Update member
- DELETE /api/v1/loyalty/members/<id> - Delete member
- POST /api/v1/networks/<network_id>/loyalty/compile - Trigger database compilation
- GET /api/v1/networks/<network_id>/loyalty/database/latest - Get latest database version
- GET /api/v1/networks/<network_id>/loyalty/database/download - Download compiled FAISS database
"""

import logging
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from central_hub.config import get_config
from central_hub.extensions import db
from central_hub.models.loyalty import LoyaltyMember, LoyaltyDatabaseVersion
from central_hub.services.face_encoder import (
    FaceEncodingError,
    InvalidImageError,
    NoFaceDetectedError,
    extract_encoding,
)
from central_hub.services.database_compiler import (
    get_latest_loyalty_version,
    DatabaseCompilationError,
    EmptyDatabaseError,
)
from central_hub.tasks.compile_loyalty import compile_loyalty_task

logger = logging.getLogger(__name__)

# Create the Loyalty blueprint
loyalty_bp = Blueprint('loyalty', __name__, url_prefix='/api/v1')


def _allowed_image_file(filename):
    """Check if file has allowed image extension."""
    config = get_config()
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in config.ALLOWED_IMAGE_EXTENSIONS


def _save_upload_file(file, member_id, network_id):
    """Save uploaded photo file to uploads directory.

    Args:
        file: FileStorage object from request
        member_id: Loyalty member ID for naming
        network_id: Network ID for directory organization

    Returns:
        Tuple of (file_path, relative_path) or (None, None) on error
    """
    config = get_config()

    # Ensure uploads directory exists (organized by network)
    loyalty_uploads = config.UPLOADS_PATH / 'loyalty' / str(network_id)
    loyalty_uploads.mkdir(parents=True, exist_ok=True)

    # Generate unique filename
    original_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
    filename = f"{member_id}.{original_ext}"
    file_path = loyalty_uploads / filename

    # Save file
    file.save(str(file_path))

    # Return relative path for database storage
    relative_path = f"loyalty/{network_id}/{filename}"
    return str(file_path), relative_path


def _validate_network_id(network_id_str):
    """Validate and parse network ID from URL parameter.

    Args:
        network_id_str: Network ID string from URL

    Returns:
        Tuple of (uuid.UUID, None) on success or (None, error_response) on failure
    """
    try:
        return uuid.UUID(network_id_str), None
    except ValueError:
        return None, (jsonify({"error": "Invalid network ID format"}), 400)


def _validate_member_id(member_id_str):
    """Validate and parse member ID from URL parameter.

    Args:
        member_id_str: Member ID string from URL

    Returns:
        Tuple of (uuid.UUID, None) on success or (None, error_response) on failure
    """
    try:
        return uuid.UUID(member_id_str), None
    except ValueError:
        return None, (jsonify({"error": "Invalid member ID format"}), 400)


# ============= NETWORK-SCOPED ENDPOINTS =============


@loyalty_bp.route('/networks/<network_id>/loyalty/enroll', methods=['POST'])
def enroll_member(network_id):
    """Enroll a new loyalty member with photo for face encoding.

    Args:
        network_id: UUID of the network to enroll member in

    Request:
        multipart/form-data with:
        - photo: Image file (required)
        - member_code: Member identifier (required, unique within network)
        - name: Member's name (required)
        - email: Member's email (optional)
        - phone: Member's phone (optional)
        - assigned_playlist_id: Playlist to assign (optional)

    Returns:
        JSON response with created member data or error
    """
    # Validate network_id
    network_uuid, error = _validate_network_id(network_id)
    if error:
        return error

    # Check for photo file
    if 'photo' not in request.files:
        return jsonify({"error": "Photo file is required"}), 400

    photo = request.files['photo']

    if photo.filename == '':
        return jsonify({"error": "No photo file selected"}), 400

    if not _allowed_image_file(photo.filename):
        config = get_config()
        return jsonify({
            "error": f"Invalid file type. Allowed: {', '.join(config.ALLOWED_IMAGE_EXTENSIONS)}"
        }), 400

    # Get form data
    member_code = request.form.get('member_code')
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    assigned_playlist_id = request.form.get('assigned_playlist_id')

    # Validate required fields
    if not member_code:
        return jsonify({"error": "member_code is required"}), 400

    if not name:
        return jsonify({"error": "name is required"}), 400

    # Check for duplicate member_code within network
    existing = LoyaltyMember.query.filter_by(
        network_id=network_uuid,
        member_code=member_code
    ).first()

    if existing:
        return jsonify({
            "error": f"Member with code '{member_code}' already exists in this network"
        }), 409

    # Generate member ID
    member_id = uuid.uuid4()

    # Save photo file
    file_path, relative_path = _save_upload_file(photo, member_id, network_uuid)

    if not file_path:
        return jsonify({"error": "Failed to save photo file"}), 500

    # Extract face encoding
    try:
        encoding = extract_encoding(file_path)
    except NoFaceDetectedError:
        # Clean up saved file
        Path(file_path).unlink(missing_ok=True)
        return jsonify({"error": "No face detected in uploaded image"}), 400
    except InvalidImageError as e:
        # Clean up saved file
        Path(file_path).unlink(missing_ok=True)
        return jsonify({"error": f"Invalid image: {str(e)}"}), 400
    except FaceEncodingError as e:
        # Clean up saved file
        Path(file_path).unlink(missing_ok=True)
        logger.error(f"Face encoding error during enrollment: {e}")
        return jsonify({"error": "Failed to process face encoding"}), 500

    # Parse assigned_playlist_id if provided
    playlist_id = None
    if assigned_playlist_id:
        try:
            playlist_id = int(assigned_playlist_id)
        except ValueError:
            # Clean up saved file
            Path(file_path).unlink(missing_ok=True)
            return jsonify({"error": "Invalid assigned_playlist_id format"}), 400

    # Create member record
    member = LoyaltyMember(
        id=member_id,
        network_id=network_uuid,
        member_code=member_code,
        name=name,
        email=email,
        phone=phone,
        face_encoding=encoding,
        photo_path=relative_path,
        assigned_playlist_id=playlist_id
    )

    db.session.add(member)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Clean up saved file
        Path(file_path).unlink(missing_ok=True)
        logger.error(f"Database error during enrollment: {e}")
        return jsonify({"error": "Failed to save member record"}), 500

    logger.info(f"Enrolled loyalty member {member.member_code} for network {network_id}")

    return jsonify({
        "status": "ok",
        "member": member.to_dict()
    }), 201


@loyalty_bp.route('/networks/<network_id>/loyalty/members', methods=['GET'])
def list_network_members(network_id):
    """List loyalty members for a specific network with pagination.

    Args:
        network_id: UUID of the network

    Query Parameters:
        page: Page number (default 1)
        per_page: Members per page (default 20, max 100)
        search: Search by name or member_code (optional)

    Returns:
        JSON response with members array and pagination info
    """
    # Validate network_id
    network_uuid, error = _validate_network_id(network_id)
    if error:
        return error

    # Get query parameters
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    search = request.args.get('search')

    # Build query
    query = LoyaltyMember.query.filter_by(network_id=network_uuid)

    # Apply search filter if provided
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                LoyaltyMember.name.ilike(search_pattern),
                LoyaltyMember.member_code.ilike(search_pattern)
            )
        )

    # Order by enrolled_at descending
    query = query.order_by(LoyaltyMember.enrolled_at.desc())

    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "status": "ok",
        "network_id": str(network_uuid),
        "members": [m.to_dict() for m in pagination.items],
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        }
    })


# ============= DIRECT MEMBER ENDPOINTS =============


@loyalty_bp.route('/loyalty/members/<member_id>', methods=['GET'])
def get_member(member_id):
    """Get a single loyalty member by ID.

    Args:
        member_id: UUID of the member

    Returns:
        JSON response with member data or 404 error
    """
    # Validate member_id
    member_uuid, error = _validate_member_id(member_id)
    if error:
        return error

    member = LoyaltyMember.query.get(member_uuid)

    if not member:
        return jsonify({"error": "Member not found"}), 404

    return jsonify({
        "status": "ok",
        "member": member.to_dict()
    })


@loyalty_bp.route('/loyalty/members/<member_id>', methods=['PUT'])
def update_member(member_id):
    """Update an existing loyalty member.

    Args:
        member_id: UUID of the member

    Request Body:
        name: Member's name
        email: Member's email
        phone: Member's phone
        member_code: Member identifier (must be unique within network)
        assigned_playlist_id: Playlist to assign

    Returns:
        JSON response with updated member data or error
    """
    # Validate member_id
    member_uuid, error = _validate_member_id(member_id)
    if error:
        return error

    member = LoyaltyMember.query.get(member_uuid)

    if not member:
        return jsonify({"error": "Member not found"}), 404

    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body is required"}), 400

    # Track if any changes were made
    updated = False

    # Update name
    if 'name' in data:
        if not data['name']:
            return jsonify({"error": "name cannot be empty"}), 400
        member.name = data['name']
        updated = True

    # Update email
    if 'email' in data:
        member.email = data['email']
        updated = True

    # Update phone
    if 'phone' in data:
        member.phone = data['phone']
        updated = True

    # Update member_code (check uniqueness within network)
    if 'member_code' in data:
        new_code = data['member_code']
        if not new_code:
            return jsonify({"error": "member_code cannot be empty"}), 400

        # Check for duplicates (excluding current member)
        existing = LoyaltyMember.query.filter(
            LoyaltyMember.network_id == member.network_id,
            LoyaltyMember.member_code == new_code,
            LoyaltyMember.id != member.id
        ).first()

        if existing:
            return jsonify({
                "error": f"Member with code '{new_code}' already exists in this network"
            }), 409

        member.member_code = new_code
        updated = True

    # Update assigned_playlist_id
    if 'assigned_playlist_id' in data:
        playlist_id = data['assigned_playlist_id']
        if playlist_id is not None:
            try:
                member.assigned_playlist_id = int(playlist_id)
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid assigned_playlist_id format"}), 400
        else:
            member.assigned_playlist_id = None
        updated = True

    if not updated:
        return jsonify({"error": "No valid fields to update"}), 400

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database error during member update: {e}")
        return jsonify({"error": "Failed to update member"}), 500

    logger.info(f"Updated loyalty member {member.member_code}")

    return jsonify({
        "status": "ok",
        "member": member.to_dict()
    })


@loyalty_bp.route('/loyalty/members/<member_id>', methods=['DELETE'])
def delete_member(member_id):
    """Delete a loyalty member.

    Args:
        member_id: UUID of the member

    Returns:
        JSON response confirming deletion or error
    """
    # Validate member_id
    member_uuid, error = _validate_member_id(member_id)
    if error:
        return error

    member = LoyaltyMember.query.get(member_uuid)

    if not member:
        return jsonify({"error": "Member not found"}), 404

    # Store info for logging before deletion
    member_code = member.member_code
    network_id = str(member.network_id)
    photo_path = member.photo_path

    try:
        db.session.delete(member)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database error during member deletion: {e}")
        return jsonify({"error": "Failed to delete member"}), 500

    # Optionally delete photo file (soft delete approach - keep file for audit)
    # If hard delete is needed, uncomment below:
    # if photo_path:
    #     config = get_config()
    #     full_path = config.UPLOADS_PATH / photo_path
    #     Path(full_path).unlink(missing_ok=True)

    logger.info(f"Deleted loyalty member {member_code} from network {network_id}")

    return jsonify({
        "status": "ok",
        "message": f"Member {member_code} deleted successfully"
    })


@loyalty_bp.route('/loyalty/members/<member_id>/photo', methods=['PUT'])
def update_member_photo(member_id):
    """Update a loyalty member's photo and re-extract face encoding.

    Args:
        member_id: UUID of the member

    Request:
        multipart/form-data with:
        - photo: New image file (required)

    Returns:
        JSON response with updated member data or error
    """
    # Validate member_id
    member_uuid, error = _validate_member_id(member_id)
    if error:
        return error

    member = LoyaltyMember.query.get(member_uuid)

    if not member:
        return jsonify({"error": "Member not found"}), 404

    # Check for photo file
    if 'photo' not in request.files:
        return jsonify({"error": "Photo file is required"}), 400

    photo = request.files['photo']

    if photo.filename == '':
        return jsonify({"error": "No photo file selected"}), 400

    if not _allowed_image_file(photo.filename):
        config = get_config()
        return jsonify({
            "error": f"Invalid file type. Allowed: {', '.join(config.ALLOWED_IMAGE_EXTENSIONS)}"
        }), 400

    # Store old photo path for cleanup
    old_photo_path = member.photo_path

    # Save new photo file
    file_path, relative_path = _save_upload_file(photo, member.id, member.network_id)

    if not file_path:
        return jsonify({"error": "Failed to save photo file"}), 500

    # Extract face encoding from new photo
    try:
        encoding = extract_encoding(file_path)
    except NoFaceDetectedError:
        # Clean up saved file
        Path(file_path).unlink(missing_ok=True)
        return jsonify({"error": "No face detected in uploaded image"}), 400
    except InvalidImageError as e:
        # Clean up saved file
        Path(file_path).unlink(missing_ok=True)
        return jsonify({"error": f"Invalid image: {str(e)}"}), 400
    except FaceEncodingError as e:
        # Clean up saved file
        Path(file_path).unlink(missing_ok=True)
        logger.error(f"Face encoding error during photo update: {e}")
        return jsonify({"error": "Failed to process face encoding"}), 500

    # Update member with new encoding and photo path
    member.face_encoding = encoding
    member.photo_path = relative_path

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Clean up saved file
        Path(file_path).unlink(missing_ok=True)
        logger.error(f"Database error during photo update: {e}")
        return jsonify({"error": "Failed to update member photo"}), 500

    # Optionally delete old photo file
    # if old_photo_path and old_photo_path != relative_path:
    #     config = get_config()
    #     old_full_path = config.UPLOADS_PATH / old_photo_path
    #     Path(old_full_path).unlink(missing_ok=True)

    logger.info(f"Updated photo for loyalty member {member.member_code}")

    return jsonify({
        "status": "ok",
        "member": member.to_dict()
    })


# ============= DATABASE COMPILATION & DOWNLOAD ENDPOINTS =============


@loyalty_bp.route('/networks/<network_id>/loyalty/compile', methods=['POST'])
def compile_database(network_id):
    """Trigger loyalty database compilation for a specific network.

    Compiles all loyalty members for the network into a versioned FAISS index
    for distribution to edge devices. Compilation runs asynchronously
    via Celery background task.

    Args:
        network_id: UUID of the network to compile

    Request Body (optional):
        triggered_by: Identifier for who/what triggered compilation

    Returns:
        JSON response with:
        - status: 'ok'
        - message: Status message
        - task_id: Celery task ID for tracking progress
        - network_id: Network ID being compiled

    Errors:
        400: Invalid network ID or no members to compile
        500: Failed to queue compilation task
    """
    # Validate network_id
    network_uuid, error = _validate_network_id(network_id)
    if error:
        return error

    data = request.json or {}
    triggered_by = data.get('triggered_by', 'api')

    # Check if there are members to compile for this network
    member_count = LoyaltyMember.query.filter_by(
        network_id=network_uuid
    ).count()

    if member_count == 0:
        return jsonify({
            "error": f"No loyalty members enrolled in network {network_id}. "
                     "Enroll members before compilation."
        }), 400

    try:
        # Queue the compilation task
        task = compile_loyalty_task.delay(
            network_id=str(network_uuid),
            triggered_by=triggered_by
        )

        logger.info(
            f"Loyalty compilation task queued: task_id={task.id}, "
            f"network_id={network_id}, members={member_count}, "
            f"triggered_by={triggered_by}"
        )

        return jsonify({
            "status": "ok",
            "message": "Loyalty database compilation started",
            "task_id": task.id,
            "network_id": str(network_uuid),
            "member_count": member_count,
        })

    except Exception as e:
        logger.error(f"Failed to queue loyalty compilation task: {e}")
        return jsonify({
            "error": "Failed to start compilation task"
        }), 500


@loyalty_bp.route('/networks/<network_id>/loyalty/database/latest', methods=['GET'])
def get_latest_database(network_id):
    """Get information about the latest loyalty database version for a network.

    Returns metadata about the most recent compiled FAISS database
    including version number, member count, and file hash for
    integrity verification.

    Args:
        network_id: UUID of the network

    Returns:
        JSON response with:
        - status: 'ok'
        - version: Version info dict (id, version, record_count, file_hash, etc.)
        - network_id: Network ID

    Errors:
        400: Invalid network ID format
        404: No compiled database versions exist for this network
    """
    # Validate network_id
    network_uuid, error = _validate_network_id(network_id)
    if error:
        return error

    version_info = get_latest_loyalty_version(network_uuid)

    if not version_info:
        return jsonify({
            "error": f"No compiled loyalty database versions available for network {network_id}. "
                     "Run compilation first."
        }), 404

    return jsonify({
        "status": "ok",
        "network_id": str(network_uuid),
        "version": version_info
    })


@loyalty_bp.route('/networks/<network_id>/loyalty/database/download', methods=['GET'])
def download_database(network_id):
    """Download the latest compiled loyalty FAISS database file for a network.

    Streams the compiled FAISS index file for use on edge devices.
    The file hash can be verified against the value from /database/latest
    to ensure integrity.

    Args:
        network_id: UUID of the network

    Query Parameters:
        version: Optional specific version number to download (default: latest)

    Returns:
        FAISS file as application/octet-stream download

    Errors:
        400: Invalid network ID or version number
        404: No compiled database exists or file not found
    """
    # Validate network_id
    network_uuid, error = _validate_network_id(network_id)
    if error:
        return error

    version_param = request.args.get('version', type=int)

    if version_param is not None:
        # Get specific version
        db_version = LoyaltyDatabaseVersion.query.filter_by(
            network_id=network_uuid,
            version=version_param
        ).first()

        if not db_version:
            return jsonify({
                "error": f"Database version {version_param} not found for network {network_id}"
            }), 404
    else:
        # Get latest version
        db_version = LoyaltyDatabaseVersion.query.filter_by(
            network_id=network_uuid
        ).order_by(
            LoyaltyDatabaseVersion.version.desc()
        ).first()

        if not db_version:
            return jsonify({
                "error": f"No compiled loyalty database versions available for network {network_id}. "
                         "Run compilation first."
            }), 404

    # Check if file exists
    file_path = Path(db_version.file_path)
    if not file_path.exists():
        logger.error(
            f"Loyalty database file not found: {file_path} "
            f"(network={network_id}, version={db_version.version})"
        )
        return jsonify({
            "error": "Database file not found on server"
        }), 404

    # Prepare download filename
    download_filename = f"loyalty_{network_id}_v{db_version.version}.faiss"

    logger.info(
        f"Serving loyalty database download: network={network_id}, "
        f"version={db_version.version}, members={db_version.record_count}, "
        f"hash={db_version.file_hash[:16]}..."
    )

    return send_file(
        file_path,
        mimetype='application/octet-stream',
        as_attachment=True,
        download_name=download_filename
    )


@loyalty_bp.route('/networks/<network_id>/loyalty/database/download/metadata', methods=['GET'])
def download_database_metadata(network_id):
    """Download the metadata JSON for the latest compiled loyalty database.

    Returns the metadata file containing member details for result lookup
    after FAISS similarity search.

    Args:
        network_id: UUID of the network

    Query Parameters:
        version: Optional specific version number to download (default: latest)

    Returns:
        JSON metadata file as download

    Errors:
        400: Invalid network ID or version number
        404: No compiled database exists or metadata file not found
    """
    # Validate network_id
    network_uuid, error = _validate_network_id(network_id)
    if error:
        return error

    version_param = request.args.get('version', type=int)

    if version_param is not None:
        # Get specific version
        db_version = LoyaltyDatabaseVersion.query.filter_by(
            network_id=network_uuid,
            version=version_param
        ).first()

        if not db_version:
            return jsonify({
                "error": f"Database version {version_param} not found for network {network_id}"
            }), 404
    else:
        # Get latest version
        db_version = LoyaltyDatabaseVersion.query.filter_by(
            network_id=network_uuid
        ).order_by(
            LoyaltyDatabaseVersion.version.desc()
        ).first()

        if not db_version:
            return jsonify({
                "error": f"No compiled loyalty database versions available for network {network_id}. "
                         "Run compilation first."
            }), 404

    # Metadata file is alongside FAISS file with .json extension
    faiss_path = Path(db_version.file_path)
    metadata_path = faiss_path.with_suffix('.json')

    if not metadata_path.exists():
        logger.error(
            f"Loyalty metadata file not found: {metadata_path} "
            f"(network={network_id}, version={db_version.version})"
        )
        return jsonify({
            "error": "Metadata file not found on server"
        }), 404

    # Prepare download filename
    download_filename = f"loyalty_{network_id}_v{db_version.version}.json"

    logger.info(
        f"Serving loyalty metadata download: network={network_id}, "
        f"version={db_version.version}"
    )

    return send_file(
        metadata_path,
        mimetype='application/json',
        as_attachment=True,
        download_name=download_filename
    )
