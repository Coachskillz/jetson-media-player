"""
Alert Processor Service

Handles incoming alert processing and triggers appropriate notifications.
Supports immediate notifications for critical alerts (NCMEC matches) and
delayed notifications for non-critical alerts based on notification settings.

This service is responsible for:
- Processing incoming alerts from distributed screens
- Determining notification requirements based on alert type
- Dispatching notifications via configured channels
- Logging all notification attempts for auditing
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Union
from uuid import UUID

from central_hub.extensions import db
from central_hub.models.alert import (
    Alert,
    AlertNotificationLog,
    AlertStatus,
    AlertType,
    NotificationStatus,
    NotificationType,
)
from central_hub.models.notification import NotificationSettings
from central_hub.services.notifier import (
    send_notification,
    send_bulk_notifications,
    NotificationError,
    NotificationResult,
    NotificationChannel,
)

logger = logging.getLogger(__name__)


class AlertProcessingError(Exception):
    """Base exception for alert processing errors."""
    pass


class InvalidAlertError(AlertProcessingError):
    """Raised when alert data is invalid."""
    pass


class NotificationDispatchError(AlertProcessingError):
    """Raised when notification dispatch fails."""
    pass


class DuplicateAlertError(AlertProcessingError):
    """Raised when a duplicate alert is detected."""
    pass


class AlertPriority(str, Enum):
    """Priority levels for alerts."""
    CRITICAL = 'critical'
    HIGH = 'high'
    NORMAL = 'normal'
    LOW = 'low'


@dataclass
class AlertProcessingResult:
    """Result of alert processing operation."""
    success: bool
    alert_id: Optional[str] = None
    notifications_sent: int = 0
    notifications_failed: int = 0
    notifications_scheduled: int = 0
    error: Optional[str] = None
    timestamp: Optional[datetime] = None

    def to_dict(self) -> Dict:
        """Convert result to dictionary."""
        return {
            'success': self.success,
            'alert_id': self.alert_id,
            'notifications_sent': self.notifications_sent,
            'notifications_failed': self.notifications_failed,
            'notifications_scheduled': self.notifications_scheduled,
            'error': self.error,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }


def _get_alert_priority(alert_type: str) -> AlertPriority:
    """
    Determine priority level for an alert type.

    Args:
        alert_type: The type of alert.

    Returns:
        AlertPriority indicating urgency level.
    """
    if alert_type == AlertType.NCMEC_MATCH.value:
        return AlertPriority.CRITICAL
    elif alert_type == AlertType.LOYALTY_MATCH.value:
        return AlertPriority.NORMAL
    else:
        return AlertPriority.LOW


def _should_send_immediately(alert_type: str) -> bool:
    """
    Determine if an alert requires immediate notification.

    NCMEC alerts are always sent immediately due to their critical nature.

    Args:
        alert_type: The type of alert.

    Returns:
        True if notification should be sent immediately.
    """
    return alert_type == AlertType.NCMEC_MATCH.value


def _format_alert_subject(alert: Alert) -> str:
    """
    Format email subject line for an alert notification.

    Args:
        alert: The alert to format subject for.

    Returns:
        Formatted subject line string.
    """
    if alert.alert_type == AlertType.NCMEC_MATCH.value:
        return f"[URGENT] NCMEC Alert - Potential Match Detected (Case: {alert.case_id})"
    elif alert.alert_type == AlertType.LOYALTY_MATCH.value:
        return f"Loyalty Member Match Detected"
    else:
        return f"Alert Notification - {alert.alert_type}"


def _format_alert_message(alert: Alert) -> str:
    """
    Format notification message body for an alert.

    Args:
        alert: The alert to format message for.

    Returns:
        Formatted message body string.
    """
    lines = []

    if alert.alert_type == AlertType.NCMEC_MATCH.value:
        lines.append("*** NCMEC ALERT - POTENTIAL MISSING CHILD MATCH ***")
        lines.append("")
        lines.append(f"Case ID: {alert.case_id}")
        lines.append(f"Match Confidence: {alert.confidence * 100:.1f}%")
    elif alert.alert_type == AlertType.LOYALTY_MATCH.value:
        lines.append("Loyalty Member Match Detected")
        lines.append("")
        lines.append(f"Member ID: {alert.member_id}")
        lines.append(f"Match Confidence: {alert.confidence * 100:.1f}%")
    else:
        lines.append(f"Alert Type: {alert.alert_type}")
        lines.append(f"Match Confidence: {alert.confidence * 100:.1f}%")

    lines.append("")
    lines.append(f"Detection Time: {alert.timestamp.isoformat() if alert.timestamp else 'Unknown'}")
    lines.append(f"Received At: {alert.received_at.isoformat() if alert.received_at else 'Unknown'}")

    if alert.store_id:
        lines.append(f"Store ID: {alert.store_id}")
    if alert.screen_id:
        lines.append(f"Screen ID: {alert.screen_id}")

    lines.append("")
    lines.append(f"Alert ID: {alert.id}")
    lines.append("")
    lines.append("Please review this alert in the management dashboard.")

    return "\n".join(lines)


def _get_notification_settings_for_alert(alert_type: str) -> List[NotificationSettings]:
    """
    Get all enabled notification settings applicable to an alert type.

    Args:
        alert_type: The type of alert to get settings for.

    Returns:
        List of applicable NotificationSettings.
    """
    # Map alert types to setting name patterns
    setting_name_patterns = {
        AlertType.NCMEC_MATCH.value: ['ncmec_alert', 'ncmec_match', 'critical_alert'],
        AlertType.LOYALTY_MATCH.value: ['loyalty_alert', 'loyalty_match'],
    }

    patterns = setting_name_patterns.get(alert_type, [])

    if not patterns:
        logger.warning(f"No notification patterns defined for alert type: {alert_type}")
        return []

    # Query for matching settings
    settings = NotificationSettings.query.filter(
        NotificationSettings.enabled == True,
        NotificationSettings.name.in_(patterns)
    ).all()

    return settings


def _check_duplicate_notification(
    alert_id: Union[str, UUID],
    recipient: str,
    notification_type: str,
) -> bool:
    """
    Check if a notification has already been sent for this alert/recipient combination.

    Prevents duplicate notifications from being sent.

    Args:
        alert_id: The alert ID.
        recipient: The notification recipient.
        notification_type: The notification channel type.

    Returns:
        True if a notification has already been sent.
    """
    existing = AlertNotificationLog.query.filter_by(
        alert_id=str(alert_id) if isinstance(alert_id, UUID) else alert_id,
        recipient=recipient,
        notification_type=notification_type,
        status=NotificationStatus.SENT.value,
    ).first()

    return existing is not None


def _log_notification_attempt(
    alert_id: Union[str, UUID],
    notification_type: str,
    recipient: str,
    success: bool,
    error_message: Optional[str] = None,
) -> AlertNotificationLog:
    """
    Log a notification attempt to the database.

    Args:
        alert_id: The alert ID.
        notification_type: The notification channel type.
        recipient: The notification recipient.
        success: Whether the notification was sent successfully.
        error_message: Error message if failed.

    Returns:
        Created AlertNotificationLog record.
    """
    log = AlertNotificationLog(
        alert_id=alert_id if isinstance(alert_id, UUID) else UUID(alert_id),
        notification_type=notification_type,
        recipient=recipient,
        status=NotificationStatus.SENT.value if success else NotificationStatus.FAILED.value,
        error_message=error_message,
        sent_at=datetime.now(timezone.utc),
    )

    db.session.add(log)
    db.session.commit()

    return log


def _dispatch_notification(
    alert: Alert,
    setting: NotificationSettings,
) -> List[NotificationResult]:
    """
    Dispatch notifications for an alert using the given settings.

    Args:
        alert: The alert to notify about.
        setting: The notification settings to use.

    Returns:
        List of NotificationResult objects.
    """
    results = []
    recipients_config = setting.recipients or {}
    channel = setting.channel

    # Get recipients based on channel
    if channel == NotificationChannel.EMAIL.value:
        recipients = recipients_config.get('emails', [])
    elif channel == NotificationChannel.SMS.value:
        recipients = recipients_config.get('phones', [])
    else:
        logger.warning(f"Unsupported notification channel: {channel}")
        return results

    if not recipients:
        logger.warning(
            f"No recipients configured for notification setting '{setting.name}' "
            f"channel '{channel}'"
        )
        return results

    subject = _format_alert_subject(alert)
    message = _format_alert_message(alert)

    for recipient in recipients:
        # Check for duplicate notification
        if _check_duplicate_notification(alert.id, recipient, channel):
            logger.info(
                f"Skipping duplicate notification to {recipient} for alert {alert.id}"
            )
            continue

        try:
            result = send_notification(
                channel=channel,
                recipient=recipient,
                subject=subject,
                message=message,
            )

            # Log the attempt
            _log_notification_attempt(
                alert_id=alert.id,
                notification_type=channel,
                recipient=recipient,
                success=result.success,
                error_message=result.error,
            )

            results.append(result)

            if result.success:
                logger.info(
                    f"Notification sent to {recipient} via {channel} "
                    f"for alert {alert.id}"
                )
            else:
                logger.warning(
                    f"Notification to {recipient} via {channel} failed: {result.error}"
                )

        except NotificationError as e:
            logger.error(f"Failed to send notification to {recipient}: {e}")
            _log_notification_attempt(
                alert_id=alert.id,
                notification_type=channel,
                recipient=recipient,
                success=False,
                error_message=str(e),
            )
            results.append(NotificationResult(
                success=False,
                channel=channel,
                recipient=recipient,
                error=str(e),
                timestamp=datetime.now(timezone.utc),
            ))

        except Exception as e:
            logger.error(f"Unexpected error sending notification to {recipient}: {e}")
            _log_notification_attempt(
                alert_id=alert.id,
                notification_type=channel,
                recipient=recipient,
                success=False,
                error_message=f"Unexpected error: {e}",
            )
            results.append(NotificationResult(
                success=False,
                channel=channel,
                recipient=recipient,
                error=f"Unexpected error: {e}",
                timestamp=datetime.now(timezone.utc),
            ))

    return results


def process_alert(
    alert_data: Dict,
    skip_notifications: bool = False,
) -> AlertProcessingResult:
    """
    Process an incoming alert and trigger appropriate notifications.

    This is the main entry point for alert processing. It validates the alert,
    saves it to the database, and dispatches notifications based on the alert
    type and configured notification settings.

    Args:
        alert_data: Dictionary containing alert information:
            - alert_type: Type of alert (ncmec_match, loyalty_match)
            - confidence: Match confidence score (0.0 to 1.0)
            - timestamp: Detection timestamp (ISO format string or datetime)
            - case_id: NCMEC case ID (for ncmec_match type)
            - member_id: Loyalty member ID (for loyalty_match type)
            - network_id: Optional network ID
            - store_id: Optional store ID
            - screen_id: Optional screen ID
            - captured_image_path: Optional path to captured image
        skip_notifications: If True, skip notification dispatch (useful for testing).

    Returns:
        AlertProcessingResult with processing status and notification counts.

    Raises:
        InvalidAlertError: If alert data is invalid or missing required fields.
        AlertProcessingError: If processing fails due to database or other errors.
    """
    timestamp = datetime.now(timezone.utc)

    # Validate required fields
    alert_type = alert_data.get('alert_type')
    if not alert_type:
        raise InvalidAlertError("Missing required field: alert_type")

    if alert_type not in [t.value for t in AlertType]:
        raise InvalidAlertError(f"Invalid alert_type: {alert_type}")

    confidence = alert_data.get('confidence')
    if confidence is None:
        raise InvalidAlertError("Missing required field: confidence")

    try:
        confidence = float(confidence)
        if not 0.0 <= confidence <= 1.0:
            raise InvalidAlertError("Confidence must be between 0.0 and 1.0")
    except (TypeError, ValueError) as e:
        raise InvalidAlertError(f"Invalid confidence value: {e}")

    detection_timestamp = alert_data.get('timestamp')
    if not detection_timestamp:
        raise InvalidAlertError("Missing required field: timestamp")

    # Parse timestamp if string
    if isinstance(detection_timestamp, str):
        try:
            detection_timestamp = datetime.fromisoformat(
                detection_timestamp.replace('Z', '+00:00')
            )
        except ValueError as e:
            raise InvalidAlertError(f"Invalid timestamp format: {e}")

    # Validate type-specific fields
    if alert_type == AlertType.NCMEC_MATCH.value:
        case_id = alert_data.get('case_id')
        if not case_id:
            raise InvalidAlertError("NCMEC alerts require case_id")
    elif alert_type == AlertType.LOYALTY_MATCH.value:
        member_id = alert_data.get('member_id')
        if not member_id:
            raise InvalidAlertError("Loyalty alerts require member_id")

    try:
        # Create alert record
        alert = Alert(
            alert_type=alert_type,
            confidence=confidence,
            timestamp=detection_timestamp,
            case_id=alert_data.get('case_id'),
            member_id=UUID(alert_data['member_id']) if alert_data.get('member_id') else None,
            network_id=UUID(alert_data['network_id']) if alert_data.get('network_id') else None,
            store_id=UUID(alert_data['store_id']) if alert_data.get('store_id') else None,
            screen_id=UUID(alert_data['screen_id']) if alert_data.get('screen_id') else None,
            captured_image_path=alert_data.get('captured_image_path'),
            status=AlertStatus.NEW.value,
            received_at=timestamp,
        )

        db.session.add(alert)
        db.session.commit()

        logger.info(f"Alert {alert.id} created: type={alert_type}, confidence={confidence}")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to create alert: {e}")
        raise AlertProcessingError(f"Failed to save alert: {e}")

    # Handle notifications
    notifications_sent = 0
    notifications_failed = 0
    notifications_scheduled = 0

    if not skip_notifications:
        # Get notification settings for this alert type
        settings = _get_notification_settings_for_alert(alert_type)

        if not settings:
            logger.info(
                f"No notification settings configured for alert type: {alert_type}"
            )
        else:
            send_immediate = _should_send_immediately(alert_type)

            for setting in settings:
                # Check if we should send immediately or schedule
                if send_immediate or setting.delay_minutes == 0:
                    # Dispatch immediately
                    results = _dispatch_notification(alert, setting)
                    notifications_sent += sum(1 for r in results if r.success)
                    notifications_failed += sum(1 for r in results if not r.success)
                else:
                    # Schedule for delayed delivery (handled by Celery task)
                    # For now, just count as scheduled - actual scheduling
                    # is done by the calling route/task
                    notifications_scheduled += 1
                    logger.info(
                        f"Notification scheduled with {setting.delay_minutes} min delay "
                        f"for alert {alert.id} via setting '{setting.name}'"
                    )

    return AlertProcessingResult(
        success=True,
        alert_id=str(alert.id),
        notifications_sent=notifications_sent,
        notifications_failed=notifications_failed,
        notifications_scheduled=notifications_scheduled,
        timestamp=timestamp,
    )


def get_alert_notification_history(
    alert_id: Union[str, UUID],
) -> List[Dict]:
    """
    Get notification history for a specific alert.

    Args:
        alert_id: The alert ID to get history for.

    Returns:
        List of notification log dictionaries.
    """
    if isinstance(alert_id, str):
        alert_id = UUID(alert_id)

    logs = AlertNotificationLog.query.filter_by(
        alert_id=alert_id
    ).order_by(
        AlertNotificationLog.sent_at.desc()
    ).all()

    return [log.to_dict() for log in logs]


def retry_failed_notifications(
    alert_id: Union[str, UUID],
) -> AlertProcessingResult:
    """
    Retry all failed notifications for an alert.

    Args:
        alert_id: The alert ID to retry notifications for.

    Returns:
        AlertProcessingResult with retry status.
    """
    timestamp = datetime.now(timezone.utc)

    if isinstance(alert_id, str):
        alert_id = UUID(alert_id)

    alert = Alert.query.get(alert_id)
    if not alert:
        raise InvalidAlertError(f"Alert not found: {alert_id}")

    # Get failed notification logs
    failed_logs = AlertNotificationLog.query.filter_by(
        alert_id=alert_id,
        status=NotificationStatus.FAILED.value,
    ).all()

    if not failed_logs:
        logger.info(f"No failed notifications to retry for alert {alert_id}")
        return AlertProcessingResult(
            success=True,
            alert_id=str(alert_id),
            notifications_sent=0,
            notifications_failed=0,
            timestamp=timestamp,
        )

    notifications_sent = 0
    notifications_failed = 0

    subject = _format_alert_subject(alert)
    message = _format_alert_message(alert)

    for log in failed_logs:
        try:
            result = send_notification(
                channel=log.notification_type,
                recipient=log.recipient,
                subject=subject,
                message=message,
            )

            # Create new log entry for the retry
            _log_notification_attempt(
                alert_id=alert_id,
                notification_type=log.notification_type,
                recipient=log.recipient,
                success=result.success,
                error_message=result.error,
            )

            if result.success:
                notifications_sent += 1
                logger.info(
                    f"Retry successful for {log.recipient} via {log.notification_type}"
                )
            else:
                notifications_failed += 1
                logger.warning(
                    f"Retry failed for {log.recipient}: {result.error}"
                )

        except Exception as e:
            notifications_failed += 1
            logger.error(f"Retry failed for {log.recipient}: {e}")
            _log_notification_attempt(
                alert_id=alert_id,
                notification_type=log.notification_type,
                recipient=log.recipient,
                success=False,
                error_message=str(e),
            )

    return AlertProcessingResult(
        success=True,
        alert_id=str(alert_id),
        notifications_sent=notifications_sent,
        notifications_failed=notifications_failed,
        timestamp=timestamp,
    )


def get_alert_processing_status() -> Dict:
    """
    Get the current status of alert processing service.

    Returns:
        Dictionary with service status information.
    """
    # Get recent alert counts
    recent_alerts = Alert.query.filter(
        Alert.status == AlertStatus.NEW.value
    ).count()

    total_alerts = Alert.query.count()

    # Get notification counts
    notifications_sent = AlertNotificationLog.query.filter_by(
        status=NotificationStatus.SENT.value
    ).count()

    notifications_failed = AlertNotificationLog.query.filter_by(
        status=NotificationStatus.FAILED.value
    ).count()

    # Get enabled notification settings count
    enabled_settings = NotificationSettings.query.filter_by(
        enabled=True
    ).count()

    return {
        'status': 'operational',
        'alerts': {
            'total': total_alerts,
            'pending_review': recent_alerts,
        },
        'notifications': {
            'total_sent': notifications_sent,
            'total_failed': notifications_failed,
            'enabled_settings': enabled_settings,
        },
    }
