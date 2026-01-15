"""
Notifications Routes Blueprint

REST API endpoints for notification settings management including CRUD
operations for all notification types and a test notification endpoint.

Endpoints:
- GET /api/v1/notification-settings - List all notification settings
- POST /api/v1/notification-settings - Create new notification setting
- GET /api/v1/notification-settings/<id> - Get single setting
- PUT /api/v1/notification-settings/<id> - Update setting
- DELETE /api/v1/notification-settings/<id> - Delete setting
- POST /api/v1/notifications/test - Send test notification
"""

import logging
import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from central_hub.extensions import db
from central_hub.models.notification import NotificationSettings, NotificationChannel
from central_hub.services.notifier import (
    send_notification,
    get_notification_status,
    NotificationError,
    InvalidRecipientError,
)

logger = logging.getLogger(__name__)

# Create the Notifications blueprint
notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/v1')

# Valid notification channels
VALID_CHANNELS = [c.value for c in NotificationChannel]


def _validate_setting_id(setting_id_str):
    """Validate and parse setting ID from URL parameter.

    Args:
        setting_id_str: Setting ID string from URL

    Returns:
        Tuple of (uuid.UUID, None) on success or (None, error_response) on failure
    """
    try:
        return uuid.UUID(setting_id_str), None
    except ValueError:
        return None, (jsonify({"error": "Invalid setting ID format"}), 400)


def _validate_recipients(recipients, channel):
    """Validate recipients structure based on channel.

    Args:
        recipients: Recipients data (should be a dict or list)
        channel: Notification channel type

    Returns:
        Tuple of (True, None) on success or (False, error_message) on failure
    """
    if not recipients:
        return False, "recipients is required"

    if not isinstance(recipients, (dict, list)):
        return False, "recipients must be an object or array"

    # If it's a list, convert to dict format
    if isinstance(recipients, list):
        if not all(isinstance(r, str) for r in recipients):
            return False, "recipients array must contain strings"
        if len(recipients) == 0:
            return False, "recipients array cannot be empty"
        return True, None

    # If it's a dict, validate based on channel
    if channel == 'email':
        emails = recipients.get('emails', [])
        if not isinstance(emails, list) or len(emails) == 0:
            return False, "recipients.emails must be a non-empty array for email channel"
    elif channel == 'sms':
        phones = recipients.get('phones', [])
        if not isinstance(phones, list) or len(phones) == 0:
            return False, "recipients.phones must be a non-empty array for sms channel"
    elif channel == 'webhook':
        urls = recipients.get('urls', [])
        if not isinstance(urls, list) or len(urls) == 0:
            return False, "recipients.urls must be a non-empty array for webhook channel"

    return True, None


@notifications_bp.route('/notification-settings', methods=['GET'])
def list_settings():
    """List all notification settings with optional filtering.

    Query Parameters:
        channel: Filter by channel ('email', 'sms', 'webhook')
        enabled: Filter by enabled status ('true', 'false')
        page: Page number (default 1)
        per_page: Settings per page (default 20, max 100)

    Returns:
        JSON response with settings array and pagination info
    """
    # Get query parameters
    channel = request.args.get('channel')
    enabled = request.args.get('enabled')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)

    # Build query
    query = NotificationSettings.query

    # Apply filters
    if channel:
        if channel not in VALID_CHANNELS:
            return jsonify({
                "error": f"Invalid channel: {channel}. Valid values: {', '.join(VALID_CHANNELS)}"
            }), 400
        query = query.filter_by(channel=channel)

    if enabled is not None:
        if enabled.lower() == 'true':
            query = query.filter_by(enabled=True)
        elif enabled.lower() == 'false':
            query = query.filter_by(enabled=False)
        else:
            return jsonify({"error": "enabled must be 'true' or 'false'"}), 400

    # Order by created_at descending
    query = query.order_by(NotificationSettings.created_at.desc())

    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "status": "ok",
        "settings": [s.to_dict() for s in pagination.items],
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        }
    })


@notifications_bp.route('/notification-settings', methods=['POST'])
def create_setting():
    """Create a new notification setting.

    Request Body:
        name: Setting name/identifier (required, unique)
        channel: Notification channel ('email', 'sms', 'webhook') (required)
        recipients: Recipients configuration (required)
            For email: {"emails": ["admin@example.com"]} or ["admin@example.com"]
            For sms: {"phones": ["+1234567890"]} or ["+1234567890"]
            For webhook: {"urls": ["https://..."]} or ["https://..."]
        delay_minutes: Delay before sending (default 0)
        enabled: Whether setting is active (default true)
        description: Optional description

    Returns:
        JSON response with created setting data

    Errors:
        400: Invalid or missing required fields
        409: Setting name already exists
        500: Server error during creation
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body is required"}), 400

    # Validate required fields
    name = data.get('name')
    channel = data.get('channel')
    recipients = data.get('recipients')

    if not name:
        return jsonify({"error": "name is required"}), 400

    if not name.strip():
        return jsonify({"error": "name cannot be empty"}), 400

    if not channel:
        return jsonify({"error": "channel is required"}), 400

    if channel not in VALID_CHANNELS:
        return jsonify({
            "error": f"Invalid channel: {channel}. Valid values: {', '.join(VALID_CHANNELS)}"
        }), 400

    # Validate recipients
    valid, error_msg = _validate_recipients(recipients, channel)
    if not valid:
        return jsonify({"error": error_msg}), 400

    # Normalize recipients to dict format if it's a list
    if isinstance(recipients, list):
        if channel == 'email':
            recipients = {"emails": recipients}
        elif channel == 'sms':
            recipients = {"phones": recipients}
        elif channel == 'webhook':
            recipients = {"urls": recipients}

    # Validate delay_minutes
    delay_minutes = data.get('delay_minutes', 0)
    if not isinstance(delay_minutes, int) or delay_minutes < 0:
        return jsonify({"error": "delay_minutes must be a non-negative integer"}), 400

    # Check for existing setting with same name
    existing = NotificationSettings.query.filter_by(name=name.strip()).first()
    if existing:
        return jsonify({"error": f"Setting with name '{name}' already exists"}), 409

    # Create new setting
    setting = NotificationSettings(
        name=name.strip(),
        channel=channel,
        recipients=recipients,
        delay_minutes=delay_minutes,
        enabled=data.get('enabled', True),
        description=data.get('description'),
    )

    try:
        db.session.add(setting)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database error creating notification setting: {e}")
        return jsonify({"error": "Failed to create notification setting"}), 500

    logger.info(f"Created notification setting: id={setting.id}, name={setting.name}")

    return jsonify({
        "status": "ok",
        "setting": setting.to_dict()
    }), 201


@notifications_bp.route('/notification-settings/<setting_id>', methods=['GET'])
def get_setting(setting_id):
    """Get a single notification setting by ID.

    Args:
        setting_id: UUID of the setting

    Returns:
        JSON response with setting data or 404 error
    """
    # Validate setting_id
    setting_uuid, error = _validate_setting_id(setting_id)
    if error:
        return error

    setting = NotificationSettings.query.get(setting_uuid)

    if not setting:
        return jsonify({"error": "Notification setting not found"}), 404

    return jsonify({
        "status": "ok",
        "setting": setting.to_dict()
    })


@notifications_bp.route('/notification-settings/<setting_id>', methods=['PUT'])
def update_setting(setting_id):
    """Update an existing notification setting.

    Args:
        setting_id: UUID of the setting

    Request Body:
        name: Setting name/identifier
        channel: Notification channel ('email', 'sms', 'webhook')
        recipients: Recipients configuration
        delay_minutes: Delay before sending
        enabled: Whether setting is active
        description: Optional description

    Returns:
        JSON response with updated setting data or error
    """
    # Validate setting_id
    setting_uuid, error = _validate_setting_id(setting_id)
    if error:
        return error

    setting = NotificationSettings.query.get(setting_uuid)

    if not setting:
        return jsonify({"error": "Notification setting not found"}), 404

    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body is required"}), 400

    # Update name if provided
    if 'name' in data:
        new_name = data['name']
        if not new_name or not new_name.strip():
            return jsonify({"error": "name cannot be empty"}), 400

        # Check for name conflict with other settings
        existing = NotificationSettings.query.filter(
            NotificationSettings.name == new_name.strip(),
            NotificationSettings.id != setting_uuid
        ).first()
        if existing:
            return jsonify({"error": f"Setting with name '{new_name}' already exists"}), 409

        setting.name = new_name.strip()

    # Update channel if provided
    if 'channel' in data:
        new_channel = data['channel']
        if new_channel not in VALID_CHANNELS:
            return jsonify({
                "error": f"Invalid channel: {new_channel}. Valid values: {', '.join(VALID_CHANNELS)}"
            }), 400
        setting.channel = new_channel

    # Update recipients if provided
    if 'recipients' in data:
        recipients = data['recipients']
        channel = data.get('channel', setting.channel)

        valid, error_msg = _validate_recipients(recipients, channel)
        if not valid:
            return jsonify({"error": error_msg}), 400

        # Normalize recipients to dict format if it's a list
        if isinstance(recipients, list):
            if channel == 'email':
                recipients = {"emails": recipients}
            elif channel == 'sms':
                recipients = {"phones": recipients}
            elif channel == 'webhook':
                recipients = {"urls": recipients}

        setting.recipients = recipients

    # Update delay_minutes if provided
    if 'delay_minutes' in data:
        delay_minutes = data['delay_minutes']
        if not isinstance(delay_minutes, int) or delay_minutes < 0:
            return jsonify({"error": "delay_minutes must be a non-negative integer"}), 400
        setting.delay_minutes = delay_minutes

    # Update enabled if provided
    if 'enabled' in data:
        setting.enabled = bool(data['enabled'])

    # Update description if provided
    if 'description' in data:
        setting.description = data['description']

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database error updating notification setting: {e}")
        return jsonify({"error": "Failed to update notification setting"}), 500

    logger.info(f"Updated notification setting: id={setting_id}")

    return jsonify({
        "status": "ok",
        "setting": setting.to_dict()
    })


@notifications_bp.route('/notification-settings/<setting_id>', methods=['DELETE'])
def delete_setting(setting_id):
    """Delete a notification setting.

    Args:
        setting_id: UUID of the setting

    Returns:
        JSON response with success status or error
    """
    # Validate setting_id
    setting_uuid, error = _validate_setting_id(setting_id)
    if error:
        return error

    setting = NotificationSettings.query.get(setting_uuid)

    if not setting:
        return jsonify({"error": "Notification setting not found"}), 404

    try:
        db.session.delete(setting)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database error deleting notification setting: {e}")
        return jsonify({"error": "Failed to delete notification setting"}), 500

    logger.info(f"Deleted notification setting: id={setting_id}")

    return jsonify({
        "status": "ok",
        "message": "Notification setting deleted"
    })


@notifications_bp.route('/notifications/test', methods=['POST'])
def test_notification():
    """Send a test notification.

    Useful for testing notification channel configuration.

    Request Body:
        channel: Notification channel ('email' or 'sms') (required)
        recipient: Single recipient address (required)
        subject: Email subject (required for email, ignored for sms)
        message: Notification message (optional, defaults to test message)

    Returns:
        JSON response with notification result

    Errors:
        400: Invalid or missing required fields
        500: Notification sending failed
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body is required"}), 400

    # Validate required fields
    channel = data.get('channel')
    recipient = data.get('recipient')

    if not channel:
        return jsonify({"error": "channel is required"}), 400

    # Only email and sms are supported for test notifications
    if channel not in ['email', 'sms']:
        return jsonify({
            "error": f"Invalid channel for test: {channel}. Valid values: email, sms"
        }), 400

    if not recipient:
        return jsonify({"error": "recipient is required"}), 400

    # Get subject and message
    subject = data.get('subject')
    if channel == 'email' and not subject:
        subject = "Test Notification from Central Hub"

    message = data.get('message', f"This is a test notification sent at {datetime.now(timezone.utc).isoformat()}")

    try:
        result = send_notification(
            channel=channel,
            recipient=recipient,
            subject=subject,
            message=message,
        )

        logger.info(
            f"Test notification sent: channel={channel}, "
            f"recipient={recipient}, success={result.success}"
        )

        return jsonify({
            "status": "ok",
            "notification": result.to_dict(),
            "service_status": get_notification_status()
        })

    except InvalidRecipientError as e:
        logger.warning(f"Invalid recipient for test notification: {e}")
        return jsonify({"error": str(e)}), 400

    except NotificationError as e:
        logger.error(f"Failed to send test notification: {e}")
        return jsonify({"error": f"Notification failed: {e}"}), 500

    except Exception as e:
        logger.exception(f"Unexpected error sending test notification: {e}")
        return jsonify({"error": "Internal server error"}), 500


@notifications_bp.route('/notifications/status', methods=['GET'])
def notification_status():
    """Get the status of notification services.

    Returns information about configured notification channels
    and whether they are in production or stub mode.

    Returns:
        JSON response with service status
    """
    return jsonify({
        "status": "ok",
        "services": get_notification_status()
    })
