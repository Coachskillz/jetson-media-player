"""
NCMEC Routes Blueprint

REST API endpoints for NCMEC (National Center for Missing & Exploited Children)
record management including CRUD operations, CSV/JSON import, photo upload,
database compilation, and FAISS database download.

Endpoints:
- POST /api/v1/ncmec/import - Import records from CSV/JSON
- GET /api/v1/ncmec/records - List records with pagination/filters
- GET /api/v1/ncmec/records/<id> - Get single record
- PUT /api/v1/ncmec/records/<id> - Update record
- DELETE /api/v1/ncmec/records/<id> - Delete record
- POST /api/v1/ncmec/records/<id>/photo - Upload photo for record
- POST /api/v1/ncmec/compile - Trigger database compilation
- GET /api/v1/ncmec/database/latest - Get latest database version info
- GET /api/v1/ncmec/database/download - Download compiled FAISS database
"""

import csv
import io
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from central_hub.config import get_config
from central_hub.extensions import db
from central_hub.models.ncmec import NCMECRecord, NCMECDatabaseVersion, NCMECStatus
from central_hub.services.face_encoder import (
    FaceEncodingError,
    InvalidImageError,
    NoFaceDetectedError,
    extract_encoding,
)
from central_hub.services.database_compiler import (
    get_latest_ncmec_version,
    DatabaseCompilationError,
    EmptyDatabaseError,
)
from central_hub.tasks.compile_ncmec import compile_ncmec_task

logger = logging.getLogger(__name__)

# Create the NCMEC blueprint
ncmec_bp = Blueprint('ncmec', __name__, url_prefix='/api/v1/ncmec')


def _parse_date(date_str):
    """Parse date string to date object.

    Supports ISO format (YYYY-MM-DD) and common variants.

    Args:
        date_str: Date string to parse

    Returns:
        datetime.date object or None if invalid
    """
    if not date_str:
        return None

    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        try:
            return datetime.strptime(date_str, '%m/%d/%Y').date()
        except ValueError:
            return None


def _allowed_image_file(filename):
    """Check if file has allowed image extension."""
    config = get_config()
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in config.ALLOWED_IMAGE_EXTENSIONS


def _save_upload_file(file, record_id):
    """Save uploaded photo file to uploads directory.

    Args:
        file: FileStorage object from request
        record_id: NCMEC record ID for naming

    Returns:
        Tuple of (file_path, relative_path) or (None, None) on error
    """
    config = get_config()

    # Ensure uploads directory exists
    ncmec_uploads = config.UPLOADS_PATH / 'ncmec'
    ncmec_uploads.mkdir(parents=True, exist_ok=True)

    # Generate unique filename
    original_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
    filename = f"{record_id}.{original_ext}"
    file_path = ncmec_uploads / filename

    # Save file
    file.save(str(file_path))

    # Return relative path for database storage
    relative_path = f"ncmec/{filename}"
    return str(file_path), relative_path


@ncmec_bp.route('/records', methods=['GET'])
def list_records():
    """List NCMEC records with optional filtering and pagination.

    Query Parameters:
        status: Filter by status ('active', 'resolved')
        page: Page number (default 1)
        per_page: Records per page (default 20, max 100)

    Returns:
        JSON response with records array and pagination info
    """
    # Get query parameters
    status = request.args.get('status')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)

    # Build query
    query = NCMECRecord.query

    if status:
        if status not in [s.value for s in NCMECStatus]:
            return jsonify({"error": f"Invalid status: {status}"}), 400
        query = query.filter_by(status=status)

    # Order by created_at descending
    query = query.order_by(NCMECRecord.created_at.desc())

    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "status": "ok",
        "records": [r.to_dict() for r in pagination.items],
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        }
    })


@ncmec_bp.route('/records/<record_id>', methods=['GET'])
def get_record(record_id):
    """Get a single NCMEC record by ID.

    Args:
        record_id: UUID of the record

    Returns:
        JSON response with record data or 404 error
    """
    try:
        record_uuid = uuid.UUID(record_id)
    except ValueError:
        return jsonify({"error": "Invalid record ID format"}), 400

    record = NCMECRecord.query.get(record_uuid)

    if not record:
        return jsonify({"error": "Record not found"}), 404

    return jsonify({
        "status": "ok",
        "record": record.to_dict()
    })


@ncmec_bp.route('/records/<record_id>', methods=['PUT'])
def update_record(record_id):
    """Update an existing NCMEC record.

    Args:
        record_id: UUID of the record

    Request Body:
        name: Child's name
        age_when_missing: Age when reported missing
        missing_since: Date reported missing (YYYY-MM-DD)
        last_known_location: Last known location description
        status: Record status ('active', 'resolved')

    Returns:
        JSON response with updated record data or error
    """
    try:
        record_uuid = uuid.UUID(record_id)
    except ValueError:
        return jsonify({"error": "Invalid record ID format"}), 400

    record = NCMECRecord.query.get(record_uuid)

    if not record:
        return jsonify({"error": "Record not found"}), 404

    data = request.json or {}

    # Update fields if provided
    if 'name' in data:
        record.name = data['name']

    if 'age_when_missing' in data:
        record.age_when_missing = data['age_when_missing']

    if 'missing_since' in data:
        parsed_date = _parse_date(data['missing_since'])
        if data['missing_since'] and not parsed_date:
            return jsonify({"error": "Invalid date format for missing_since"}), 400
        record.missing_since = parsed_date

    if 'last_known_location' in data:
        record.last_known_location = data['last_known_location']

    if 'status' in data:
        if data['status'] not in [s.value for s in NCMECStatus]:
            return jsonify({"error": f"Invalid status: {data['status']}"}), 400
        record.status = data['status']

    db.session.commit()

    return jsonify({
        "status": "ok",
        "record": record.to_dict()
    })


@ncmec_bp.route('/records/<record_id>', methods=['DELETE'])
def delete_record(record_id):
    """Delete an NCMEC record.

    Args:
        record_id: UUID of the record

    Returns:
        JSON response confirming deletion or error
    """
    try:
        record_uuid = uuid.UUID(record_id)
    except ValueError:
        return jsonify({"error": "Invalid record ID format"}), 400

    record = NCMECRecord.query.get(record_uuid)

    if not record:
        return jsonify({"error": "Record not found"}), 404

    # Delete associated photo if exists
    if record.photo_path:
        config = get_config()
        photo_full_path = config.UPLOADS_PATH / record.photo_path
        if photo_full_path.exists():
            try:
                os.unlink(str(photo_full_path))
            except OSError as e:
                logger.warning(f"Failed to delete photo file: {e}")

    db.session.delete(record)
    db.session.commit()

    return jsonify({
        "status": "ok",
        "message": "Record deleted successfully",
        "record_id": record_id
    })


@ncmec_bp.route('/records/<record_id>/photo', methods=['POST'])
def upload_photo(record_id):
    """Upload or replace photo for an NCMEC record.

    Extracts face encoding from the uploaded photo and updates the record.

    Args:
        record_id: UUID of the record

    Request:
        Multipart form with 'photo' file field

    Returns:
        JSON response confirming upload or error
    """
    try:
        record_uuid = uuid.UUID(record_id)
    except ValueError:
        return jsonify({"error": "Invalid record ID format"}), 400

    record = NCMECRecord.query.get(record_uuid)

    if not record:
        return jsonify({"error": "Record not found"}), 404

    # Check for file in request
    if 'photo' not in request.files:
        return jsonify({"error": "No photo file provided"}), 400

    file = request.files['photo']

    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    if not _allowed_image_file(file.filename):
        config = get_config()
        allowed = ', '.join(sorted(config.ALLOWED_IMAGE_EXTENSIONS))
        return jsonify({"error": f"File type not allowed. Supported formats: {allowed}"}), 400

    # Delete old photo if exists
    if record.photo_path:
        config = get_config()
        old_photo_path = config.UPLOADS_PATH / record.photo_path
        if old_photo_path.exists():
            try:
                os.unlink(str(old_photo_path))
            except OSError as e:
                logger.warning(f"Failed to delete old photo: {e}")

    # Save new photo
    file_path, relative_path = _save_upload_file(file, str(record.id))

    if not file_path:
        return jsonify({"error": "Failed to save photo file"}), 500

    try:
        # Extract face encoding
        face_encoding = extract_encoding(file_path)

        # Update record
        record.photo_path = relative_path
        record.face_encoding = face_encoding
        db.session.commit()

        return jsonify({
            "status": "ok",
            "message": "Photo uploaded and face encoding extracted successfully",
            "record_id": record_id,
            "photo_path": relative_path
        })

    except NoFaceDetectedError:
        # Clean up saved file
        try:
            os.unlink(file_path)
        except OSError:
            pass
        return jsonify({"error": "No face detected in uploaded image"}), 400

    except InvalidImageError as e:
        # Clean up saved file
        try:
            os.unlink(file_path)
        except OSError:
            pass
        return jsonify({"error": str(e)}), 400

    except FaceEncodingError as e:
        # Clean up saved file
        try:
            os.unlink(file_path)
        except OSError:
            pass
        logger.error(f"Face encoding error: {e}")
        return jsonify({"error": "Failed to extract face encoding"}), 500


@ncmec_bp.route('/import', methods=['POST'])
def import_records():
    """Import NCMEC records from CSV or JSON file.

    CSV format:
        case_id,name,age_when_missing,missing_since,last_known_location

    JSON format:
        [{"case_id": "...", "name": "...", ...}, ...]

    Note: Photos must be uploaded separately after import using the photo endpoint.
    For import, a placeholder face encoding is used (records marked as pending_photo).

    Request:
        Multipart form with 'file' field containing CSV or JSON data

    Returns:
        JSON response with import statistics
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(file.filename)
    file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

    if file_ext not in ('csv', 'json'):
        return jsonify({"error": "File must be CSV or JSON format"}), 400

    # Read file content
    try:
        content = file.read().decode('utf-8')
    except UnicodeDecodeError:
        return jsonify({"error": "File encoding error. Please use UTF-8"}), 400

    records_data = []

    # Parse based on file type
    if file_ext == 'csv':
        try:
            reader = csv.DictReader(io.StringIO(content))
            for row in reader:
                records_data.append({
                    'case_id': row.get('case_id', '').strip(),
                    'name': row.get('name', '').strip(),
                    'age_when_missing': row.get('age_when_missing', '').strip(),
                    'missing_since': row.get('missing_since', '').strip(),
                    'last_known_location': row.get('last_known_location', '').strip(),
                })
        except csv.Error as e:
            return jsonify({"error": f"CSV parsing error: {e}"}), 400

    else:  # JSON
        try:
            data = json.loads(content)
            if not isinstance(data, list):
                return jsonify({"error": "JSON must be an array of records"}), 400
            records_data = data
        except json.JSONDecodeError as e:
            return jsonify({"error": f"JSON parsing error: {e}"}), 400

    if not records_data:
        return jsonify({"error": "No records found in file"}), 400

    # Process records
    imported = 0
    updated = 0
    errors = []

    # Create placeholder encoding for imported records (zeros - will be replaced on photo upload)
    import numpy as np
    placeholder_encoding = np.zeros(128, dtype=np.float32).tobytes()

    for idx, record_data in enumerate(records_data):
        case_id = record_data.get('case_id', '').strip() if isinstance(record_data.get('case_id'), str) else str(record_data.get('case_id', ''))
        name = record_data.get('name', '').strip() if isinstance(record_data.get('name'), str) else str(record_data.get('name', ''))

        if not case_id:
            errors.append(f"Row {idx + 1}: Missing case_id")
            continue

        if not name:
            errors.append(f"Row {idx + 1}: Missing name")
            continue

        # Parse optional fields
        age_when_missing = None
        age_str = record_data.get('age_when_missing')
        if age_str:
            try:
                age_when_missing = int(age_str) if isinstance(age_str, str) else age_str
            except (ValueError, TypeError):
                pass

        missing_since = _parse_date(record_data.get('missing_since'))
        last_known_location = record_data.get('last_known_location', '')
        if isinstance(last_known_location, str):
            last_known_location = last_known_location.strip()

        # Check for existing record (update instead of duplicate)
        existing = NCMECRecord.query.filter_by(case_id=case_id).first()

        if existing:
            # Update existing record
            existing.name = name
            existing.age_when_missing = age_when_missing
            existing.missing_since = missing_since
            existing.last_known_location = last_known_location
            updated += 1
        else:
            # Create new record with placeholder encoding
            new_record = NCMECRecord(
                case_id=case_id,
                name=name,
                age_when_missing=age_when_missing,
                missing_since=missing_since,
                last_known_location=last_known_location,
                face_encoding=placeholder_encoding,
                status=NCMECStatus.ACTIVE.value
            )
            db.session.add(new_record)
            imported += 1

    db.session.commit()

    result = {
        "status": "ok",
        "imported": imported,
        "updated": updated,
        "total_processed": imported + updated,
    }

    if errors:
        result["errors"] = errors[:10]  # Limit to first 10 errors
        if len(errors) > 10:
            result["errors_truncated"] = True
            result["total_errors"] = len(errors)

    return jsonify(result)


@ncmec_bp.route('/compile', methods=['POST'])
def compile_database():
    """Trigger NCMEC database compilation.

    Compiles all active NCMEC records into a versioned FAISS index
    for distribution to edge devices. Compilation runs asynchronously
    via Celery background task.

    Request Body (optional):
        triggered_by: Identifier for who/what triggered compilation

    Returns:
        JSON response with:
        - status: 'ok'
        - message: Status message
        - task_id: Celery task ID for tracking progress

    Errors:
        400: No active records to compile
        500: Failed to queue compilation task
    """
    data = request.json or {}
    triggered_by = data.get('triggered_by', 'api')

    # Check if there are records to compile
    active_count = NCMECRecord.query.filter_by(
        status=NCMECStatus.ACTIVE.value
    ).count()

    if active_count == 0:
        return jsonify({
            "error": "No active NCMEC records to compile. Add records before compilation."
        }), 400

    try:
        # Queue the compilation task
        task = compile_ncmec_task.delay(triggered_by=triggered_by)

        logger.info(
            f"NCMEC compilation task queued: task_id={task.id}, "
            f"active_records={active_count}, triggered_by={triggered_by}"
        )

        return jsonify({
            "status": "ok",
            "message": "NCMEC database compilation started",
            "task_id": task.id,
            "active_records": active_count,
        })

    except Exception as e:
        logger.error(f"Failed to queue NCMEC compilation task: {e}")
        return jsonify({
            "error": "Failed to start compilation task"
        }), 500


@ncmec_bp.route('/database/latest', methods=['GET'])
def get_latest_database():
    """Get information about the latest NCMEC database version.

    Returns metadata about the most recent compiled FAISS database
    including version number, record count, and file hash for
    integrity verification.

    Returns:
        JSON response with:
        - status: 'ok'
        - version: Version info dict (id, version, record_count, file_hash, etc.)

    Errors:
        404: No compiled database versions exist
    """
    version_info = get_latest_ncmec_version()

    if not version_info:
        return jsonify({
            "error": "No compiled NCMEC database versions available. Run compilation first."
        }), 404

    return jsonify({
        "status": "ok",
        "version": version_info
    })


@ncmec_bp.route('/database/download', methods=['GET'])
def download_database():
    """Download the latest compiled NCMEC FAISS database file.

    Streams the compiled FAISS index file for use on edge devices.
    The file hash can be verified against the value from /database/latest
    to ensure integrity.

    Query Parameters:
        version: Optional specific version number to download (default: latest)

    Returns:
        FAISS file as application/octet-stream download

    Errors:
        404: No compiled database exists or file not found
        400: Invalid version number
    """
    version_param = request.args.get('version', type=int)

    if version_param is not None:
        # Get specific version
        db_version = NCMECDatabaseVersion.query.filter_by(
            version=version_param
        ).first()

        if not db_version:
            return jsonify({
                "error": f"Database version {version_param} not found"
            }), 404
    else:
        # Get latest version
        db_version = NCMECDatabaseVersion.query.order_by(
            NCMECDatabaseVersion.version.desc()
        ).first()

        if not db_version:
            return jsonify({
                "error": "No compiled NCMEC database versions available. Run compilation first."
            }), 404

    # Check if file exists
    file_path = Path(db_version.file_path)
    if not file_path.exists():
        logger.error(
            f"NCMEC database file not found: {file_path} "
            f"(version={db_version.version})"
        )
        return jsonify({
            "error": "Database file not found on server"
        }), 404

    # Prepare download filename
    download_filename = f"ncmec_v{db_version.version}.faiss"

    logger.info(
        f"Serving NCMEC database download: version={db_version.version}, "
        f"records={db_version.record_count}, hash={db_version.file_hash[:16]}..."
    )

    return send_file(
        file_path,
        mimetype='application/octet-stream',
        as_attachment=True,
        download_name=download_filename
    )


@ncmec_bp.route('/database/download/metadata', methods=['GET'])
def download_database_metadata():
    """Download the metadata JSON for the latest compiled NCMEC database.

    Returns the metadata file containing record details for result lookup
    after FAISS similarity search.

    Query Parameters:
        version: Optional specific version number to download (default: latest)

    Returns:
        JSON metadata file as download

    Errors:
        404: No compiled database exists or metadata file not found
        400: Invalid version number
    """
    version_param = request.args.get('version', type=int)

    if version_param is not None:
        # Get specific version
        db_version = NCMECDatabaseVersion.query.filter_by(
            version=version_param
        ).first()

        if not db_version:
            return jsonify({
                "error": f"Database version {version_param} not found"
            }), 404
    else:
        # Get latest version
        db_version = NCMECDatabaseVersion.query.order_by(
            NCMECDatabaseVersion.version.desc()
        ).first()

        if not db_version:
            return jsonify({
                "error": "No compiled NCMEC database versions available. Run compilation first."
            }), 404

    # Metadata file is alongside FAISS file with .json extension
    faiss_path = Path(db_version.file_path)
    metadata_path = faiss_path.with_suffix('.json')

    if not metadata_path.exists():
        logger.error(
            f"NCMEC metadata file not found: {metadata_path} "
            f"(version={db_version.version})"
        )
        return jsonify({
            "error": "Metadata file not found on server"
        }), 404

    # Prepare download filename
    download_filename = f"ncmec_v{db_version.version}.json"

    logger.info(
        f"Serving NCMEC metadata download: version={db_version.version}"
    )

    return send_file(
        metadata_path,
        mimetype='application/json',
        as_attachment=True,
        download_name=download_filename
    )
