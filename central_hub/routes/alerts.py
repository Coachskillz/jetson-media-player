"""
Alerts Routes Blueprint

REST API endpoints for alert management including ingestion from distributed
screens, listing with filtering, single alert retrieval, review workflow,
and captured image access.

Endpoints:
- POST /api/v1/alerts - Submit new alert (triggers notifications)
- GET /api/v1/alerts - List alerts with pagination/filters
- GET /api/v1/alerts/<id> - Get single alert
- PUT /api/v1/alerts/<id>/review - Update alert status with review
- GET /api/v1/alerts/<id>/image - Get captured image for alert
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from central_hub.config import get_config
from central_hub.extensions import db
from central_hub.models.alert import (
    Alert,
    AlertNotificationLog,
    AlertStatus,
    AlertType,
)
from central_hub.services.alert_processor import (
    process_alert,
    get_alert_notification_history,
    retry_failed_notifications,
    AlertProcessingError,
    InvalidAlertError,
)

logger = logging.getLogger(__name__)

# Create the Alerts blueprint
alerts_bp = Blueprint('alerts', __name__, url_prefix='/api/v1/alerts')


def _validate_alert_id(alert_id_str):
    """Validate and parse alert ID from URL parameter.

    Args:
        alert_id_str: Alert ID string from URL

    Returns:
        Tuple of (uuid.UUID, None) on success or (None, error_response) on failure
    """
    try:
        return uuid.UUID(alert_id_str), None
    except ValueError:
        return None, (jsonify({"error": "Invalid alert ID format"}), 400)


def _parse_datetime(datetime_str):
    """Parse datetime string to datetime object.

    Supports ISO format with optional timezone.

    Args:
        datetime_str: Datetime string to parse

    Returns:
        datetime object or None if invalid
    """
    if not datetime_str:
        return None

    try:
        # Handle ISO format with Z suffix
        return datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
    except ValueError:
        return None


@alerts_bp.route('', methods=['POST'])
def create_alert():
    """Submit a new alert from a distributed screen.

    Processes the alert, saves it to the database, and automatically
    triggers notifications based on alert type and notification settings.
    NCMEC match alerts trigger immediate notifications.

    Request Body:
        alert_type: Type of alert ('ncmec_match', 'loyalty_match') (required)
        confidence: Match confidence score 0.0 to 1.0 (required)
        timestamp: Detection timestamp in ISO format (required)
        case_id: NCMEC case ID (required for ncmec_match)
        member_id: Loyalty member ID (required for loyalty_match)
        network_id: Network UUID (optional)
        store_id: Store UUID (optional)
        screen_id: Screen UUID (optional)
        captured_image_path: Path to captured image (optional)

    Returns:
        JSON response with:
        - status: 'ok'
        - alert: Created alert data
        - notifications: Notification dispatch summary

    Errors:
        400: Invalid or missing required fields
        500: Server error during processing
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body is required"}), 400

    try:
        # Process the alert through the alert processor service
        # This handles validation, saving, and notification dispatch
        result = process_alert(alert_data=data, skip_notifications=False)

        if result.success:
            # Fetch the created alert for response
            alert = Alert.query.get(uuid.UUID(result.alert_id))

            logger.info(
                f"Alert created: id={result.alert_id}, "
                f"type={data.get('alert_type')}, "
                f"notifications_sent={result.notifications_sent}"
            )

            return jsonify({
                "status": "ok",
                "alert": alert.to_dict() if alert else {"id": result.alert_id},
                "notifications": {
                    "sent": result.notifications_sent,
                    "failed": result.notifications_failed,
                    "scheduled": result.notifications_scheduled,
                }
            }), 201
        else:
            return jsonify({
                "error": result.error or "Alert processing failed"
            }), 500

    except InvalidAlertError as e:
        logger.warning(f"Invalid alert data: {e}")
        return jsonify({"error": str(e)}), 400

    except AlertProcessingError as e:
        logger.error(f"Alert processing error: {e}")
        return jsonify({"error": "Failed to process alert"}), 500

    except Exception as e:
        logger.exception(f"Unexpected error creating alert: {e}")
        return jsonify({"error": "Internal server error"}), 500


@alerts_bp.route('', methods=['GET'])
def list_alerts():
    """List alerts with optional filtering and pagination.

    Query Parameters:
        network_id: Filter by network UUID
        status: Filter by status ('new', 'reviewed', 'escalated', 'resolved', 'false_positive')
        type: Filter by alert type ('ncmec_match', 'loyalty_match')
        since: Filter alerts received after this datetime (ISO format)
        page: Page number (default 1)
        per_page: Alerts per page (default 20, max 100)

    Returns:
        JSON response with alerts array and pagination info
    """
    # Get query parameters
    network_id = request.args.get('network_id')
    status = request.args.get('status')
    alert_type = request.args.get('type')
    since = request.args.get('since')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)

    # Build query
    query = Alert.query

    # Apply filters
    if network_id:
        try:
            network_uuid = uuid.UUID(network_id)
            query = query.filter_by(network_id=network_uuid)
        except ValueError:
            return jsonify({"error": "Invalid network_id format"}), 400

    if status:
        valid_statuses = [s.value for s in AlertStatus]
        if status not in valid_statuses:
            return jsonify({
                "error": f"Invalid status: {status}. Valid values: {', '.join(valid_statuses)}"
            }), 400
        query = query.filter_by(status=status)

    if alert_type:
        valid_types = [t.value for t in AlertType]
        if alert_type not in valid_types:
            return jsonify({
                "error": f"Invalid type: {alert_type}. Valid values: {', '.join(valid_types)}"
            }), 400
        query = query.filter_by(alert_type=alert_type)

    if since:
        since_datetime = _parse_datetime(since)
        if since_datetime:
            query = query.filter(Alert.received_at >= since_datetime)
        else:
            return jsonify({"error": "Invalid since datetime format. Use ISO format."}), 400

    # Order by received_at descending (most recent first)
    query = query.order_by(Alert.received_at.desc())

    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "status": "ok",
        "alerts": [a.to_dict() for a in pagination.items],
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        }
    })


@alerts_bp.route('/<alert_id>', methods=['GET'])
def get_alert(alert_id):
    """Get a single alert by ID.

    Args:
        alert_id: UUID of the alert

    Returns:
        JSON response with alert data or 404 error
    """
    # Validate alert_id
    alert_uuid, error = _validate_alert_id(alert_id)
    if error:
        return error

    alert = Alert.query.get(alert_uuid)

    if not alert:
        return jsonify({"error": "Alert not found"}), 404

    # Include notification history
    notification_history = get_alert_notification_history(alert_uuid)

    return jsonify({
        "status": "ok",
        "alert": alert.to_dict(),
        "notification_history": notification_history
    })


@alerts_bp.route('/<alert_id>/review', methods=['PUT'])
def review_alert(alert_id):
    """Update alert status through review workflow.

    Allows transitioning alert status and recording reviewer information.
    Valid status transitions:
    - new → reviewed, escalated, resolved, false_positive
    - reviewed → escalated, resolved, false_positive
    - escalated → resolved, false_positive

    Args:
        alert_id: UUID of the alert

    Request Body:
        status: New status (required)
        reviewed_by: Reviewer identifier (required)
        notes: Review notes (optional)

    Returns:
        JSON response with updated alert data or error
    """
    # Validate alert_id
    alert_uuid, error = _validate_alert_id(alert_id)
    if error:
        return error

    alert = Alert.query.get(alert_uuid)

    if not alert:
        return jsonify({"error": "Alert not found"}), 404

    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body is required"}), 400

    # Validate required fields
    new_status = data.get('status')
    reviewed_by = data.get('reviewed_by')

    if not new_status:
        return jsonify({"error": "status is required"}), 400

    if not reviewed_by:
        return jsonify({"error": "reviewed_by is required"}), 400

    # Validate status value
    valid_statuses = [s.value for s in AlertStatus]
    if new_status not in valid_statuses:
        return jsonify({
            "error": f"Invalid status: {new_status}. Valid values: {', '.join(valid_statuses)}"
        }), 400

    # Validate status transition
    current_status = alert.status
    valid_transitions = {
        AlertStatus.NEW.value: [
            AlertStatus.REVIEWED.value,
            AlertStatus.ESCALATED.value,
            AlertStatus.RESOLVED.value,
            AlertStatus.FALSE_POSITIVE.value
        ],
        AlertStatus.REVIEWED.value: [
            AlertStatus.ESCALATED.value,
            AlertStatus.RESOLVED.value,
            AlertStatus.FALSE_POSITIVE.value
        ],
        AlertStatus.ESCALATED.value: [
            AlertStatus.RESOLVED.value,
            AlertStatus.FALSE_POSITIVE.value
        ],
        AlertStatus.RESOLVED.value: [],  # Terminal state
        AlertStatus.FALSE_POSITIVE.value: [],  # Terminal state
    }

    allowed = valid_transitions.get(current_status, [])
    if new_status not in allowed and new_status != current_status:
        return jsonify({
            "error": f"Invalid status transition from '{current_status}' to '{new_status}'"
        }), 400

    # Update alert
    alert.status = new_status
    alert.reviewed_by = reviewed_by
    alert.reviewed_at = datetime.now(timezone.utc)

    if 'notes' in data:
        alert.notes = data['notes']

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database error during alert review: {e}")
        return jsonify({"error": "Failed to update alert"}), 500

    logger.info(
        f"Alert reviewed: id={alert_id}, "
        f"status={current_status}→{new_status}, "
        f"reviewed_by={reviewed_by}"
    )

    return jsonify({
        "status": "ok",
        "alert": alert.to_dict()
    })


@alerts_bp.route('/<alert_id>/image', methods=['GET'])
def get_alert_image(alert_id):
    """Get the captured image for an alert.

    Args:
        alert_id: UUID of the alert

    Returns:
        Image file as download or error

    Errors:
        400: Invalid alert ID format
        404: Alert not found or no image available
    """
    # Validate alert_id
    alert_uuid, error = _validate_alert_id(alert_id)
    if error:
        return error

    alert = Alert.query.get(alert_uuid)

    if not alert:
        return jsonify({"error": "Alert not found"}), 404

    if not alert.captured_image_path:
        return jsonify({"error": "No captured image available for this alert"}), 404

    # Get full path to image
    config = get_config()
    image_path = Path(alert.captured_image_path)

    # If relative path, resolve against uploads directory
    if not image_path.is_absolute():
        image_path = config.UPLOADS_PATH / image_path

    if not image_path.exists():
        logger.warning(
            f"Captured image file not found: {image_path} "
            f"(alert_id={alert_id})"
        )
        return jsonify({"error": "Image file not found on server"}), 404

    # Determine mimetype from extension
    extension = image_path.suffix.lower()
    mimetypes = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
    }
    mimetype = mimetypes.get(extension, 'application/octet-stream')

    logger.info(f"Serving captured image for alert {alert_id}")

    return send_file(
        image_path,
        mimetype=mimetype,
        as_attachment=False,
        download_name=f"alert_{alert_id}{extension}"
    )


@alerts_bp.route('/<alert_id>/notifications/retry', methods=['POST'])
def retry_notifications(alert_id):
    """Retry failed notifications for an alert.

    Re-attempts delivery for all notifications that previously failed
    for this alert.

    Args:
        alert_id: UUID of the alert

    Returns:
        JSON response with retry results
    """
    # Validate alert_id
    alert_uuid, error = _validate_alert_id(alert_id)
    if error:
        return error

    alert = Alert.query.get(alert_uuid)

    if not alert:
        return jsonify({"error": "Alert not found"}), 404

    try:
        result = retry_failed_notifications(alert_uuid)

        logger.info(
            f"Notification retry for alert {alert_id}: "
            f"sent={result.notifications_sent}, failed={result.notifications_failed}"
        )

        return jsonify({
            "status": "ok",
            "alert_id": str(alert_uuid),
            "notifications_retried": {
                "sent": result.notifications_sent,
                "failed": result.notifications_failed,
            }
        })

    except InvalidAlertError as e:
        return jsonify({"error": str(e)}), 404

    except Exception as e:
        logger.error(f"Error retrying notifications for alert {alert_id}: {e}")
        return jsonify({"error": "Failed to retry notifications"}), 500
