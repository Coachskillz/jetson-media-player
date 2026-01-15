"""
Send Notification Celery Task

Provides background task for delayed notification dispatch with retry logic.
The task runs asynchronously to handle delayed notifications for alerts
that don't require immediate dispatch (e.g., loyalty matches).
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from celery.exceptions import MaxRetriesExceededError

from central_hub.extensions import celery
from central_hub.tasks import (
    CriticalTaskWithRetry,
    task_success_result,
    task_error_result,
    QUEUE_HIGH_PRIORITY,
)
from central_hub.services.notifier import (
    send_notification,
    NotificationError,
    InvalidRecipientError,
    NotificationChannel,
)

logger = logging.getLogger(__name__)


@celery.task(
    base=CriticalTaskWithRetry,
    bind=True,
    name='central_hub.tasks.send_notification.send_notification_task',
    queue=QUEUE_HIGH_PRIORITY,
    acks_late=True,  # Acknowledge task after completion for reliability
)
def send_notification_task(
    self,
    channel: str,
    recipient: str,
    subject: Optional[str] = None,
    message: str = "",
    html_body: Optional[str] = None,
    alert_id: Optional[str] = None,
    triggered_by: Optional[str] = None,
) -> Dict:
    """
    Celery task to send a notification in the background.

    Sends notifications via email or SMS with automatic retry logic
    and exponential backoff on failure. Designed for delayed notification
    dispatch where immediate delivery is not required.

    Args:
        channel: Notification channel ('email' or 'sms').
        recipient: Recipient address (email or phone number).
        subject: Subject line (required for email, ignored for SMS).
        message: Message body.
        html_body: Optional HTML body (email only).
        alert_id: Optional alert ID this notification is associated with.
        triggered_by: Optional identifier of who/what triggered the notification
                     (e.g., 'scheduler', 'alert_processor', 'admin:user@example.com')

    Returns:
        Dictionary containing task result:
        - status: 'ok' on success, 'error' on failure
        - channel: Notification channel used
        - recipient: Recipient address
        - message_id: Provider message ID (on success)
        - is_stub: Whether stub mode was used
        - alert_id: Associated alert ID (if provided)
        - triggered_by: Who/what triggered the notification
        - completed_at: ISO timestamp of completion

    Raises:
        Retry: When a retryable error occurs
        MaxRetriesExceededError: When all retries exhausted
    """
    task_id = self.request.id
    started_at = datetime.now(timezone.utc)

    logger.info(
        f"Starting notification task[{task_id}]: channel={channel}, recipient={recipient}",
        extra={
            'task_id': task_id,
            'channel': channel,
            'recipient': recipient,
            'alert_id': alert_id,
            'triggered_by': triggered_by,
            'started_at': started_at.isoformat(),
        }
    )

    # Validate channel
    valid_channels = [NotificationChannel.EMAIL.value, NotificationChannel.SMS.value]
    if channel not in valid_channels:
        error_msg = f"Invalid notification channel: {channel}"
        logger.error(
            f"Notification task[{task_id}] failed: {error_msg}",
            extra={
                'task_id': task_id,
                'error': error_msg,
                'error_type': 'invalid_channel',
            }
        )
        return task_error_result(
            error=error_msg,
            code='INVALID_CHANNEL',
            data={
                'channel': channel,
                'recipient': recipient,
                'alert_id': alert_id,
                'triggered_by': triggered_by,
            }
        )

    try:
        # Execute the notification dispatch
        result = send_notification(
            channel=channel,
            recipient=recipient,
            subject=subject,
            message=message,
            html_body=html_body,
        )

        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()

        if result.success:
            logger.info(
                f"Notification task[{task_id}] completed in {duration:.2f}s: "
                f"channel={channel}, recipient={recipient}, "
                f"message_id={result.message_id}, is_stub={result.is_stub}",
                extra={
                    'task_id': task_id,
                    'channel': channel,
                    'recipient': recipient,
                    'message_id': result.message_id,
                    'is_stub': result.is_stub,
                    'duration_seconds': duration,
                }
            )

            return task_success_result(
                message='Notification sent successfully',
                data={
                    'channel': result.channel,
                    'recipient': result.recipient,
                    'message_id': result.message_id,
                    'is_stub': result.is_stub,
                    'alert_id': alert_id,
                    'triggered_by': triggered_by,
                    'completed_at': completed_at.isoformat(),
                    'duration_seconds': duration,
                }
            )
        else:
            # Result indicates failure but didn't raise - shouldn't happen
            # but handle defensively
            raise NotificationError(result.error or "Unknown notification failure")

    except InvalidRecipientError as e:
        # Invalid recipient is not a retryable error
        logger.warning(
            f"Notification task[{task_id}] failed: {e}",
            extra={
                'task_id': task_id,
                'error': str(e),
                'error_type': 'invalid_recipient',
                'channel': channel,
                'recipient': recipient,
            }
        )
        return task_error_result(
            error=str(e),
            code='INVALID_RECIPIENT',
            data={
                'channel': channel,
                'recipient': recipient,
                'alert_id': alert_id,
                'triggered_by': triggered_by,
            }
        )

    except NotificationError as e:
        # Notification errors may be retryable (e.g., transient API issues)
        retry_count = self.request.retries
        max_retries = self.max_retries

        logger.warning(
            f"Notification task[{task_id}] encountered error: {e} "
            f"(retry {retry_count}/{max_retries})",
            extra={
                'task_id': task_id,
                'error': str(e),
                'channel': channel,
                'recipient': recipient,
                'retry_count': retry_count,
                'max_retries': max_retries,
            }
        )

        try:
            # Retry with exponential backoff
            self.retry_with_backoff(exc=e)
        except MaxRetriesExceededError:
            logger.error(
                f"Notification task[{task_id}] failed after {max_retries} retries",
                extra={
                    'task_id': task_id,
                    'error': str(e),
                    'channel': channel,
                    'recipient': recipient,
                    'final_retry_count': retry_count,
                }
            )
            return task_error_result(
                error=f"Notification failed after {max_retries} retries: {e}",
                code='MAX_RETRIES_EXCEEDED',
                data={
                    'channel': channel,
                    'recipient': recipient,
                    'alert_id': alert_id,
                    'triggered_by': triggered_by,
                }
            )

    except Exception as e:
        # Unexpected errors - log and attempt retry
        retry_count = self.request.retries
        max_retries = self.max_retries

        logger.exception(
            f"Notification task[{task_id}] unexpected error: {e}",
            extra={
                'task_id': task_id,
                'error': str(e),
                'error_type': type(e).__name__,
                'channel': channel,
                'recipient': recipient,
                'retry_count': retry_count,
            }
        )

        try:
            self.retry_with_backoff(exc=e)
        except MaxRetriesExceededError:
            logger.error(
                f"Notification task[{task_id}] failed after {max_retries} retries "
                f"due to unexpected error",
                extra={
                    'task_id': task_id,
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'channel': channel,
                    'recipient': recipient,
                }
            )
            return task_error_result(
                error=f"Unexpected error after {max_retries} retries: {e}",
                code='UNEXPECTED_ERROR',
                data={
                    'channel': channel,
                    'recipient': recipient,
                    'alert_id': alert_id,
                    'triggered_by': triggered_by,
                }
            )


@celery.task(
    base=CriticalTaskWithRetry,
    bind=True,
    name='central_hub.tasks.send_notification.send_bulk_notification_task',
    queue=QUEUE_HIGH_PRIORITY,
    acks_late=True,
)
def send_bulk_notification_task(
    self,
    channel: str,
    recipients: List[str],
    subject: Optional[str] = None,
    message: str = "",
    html_body: Optional[str] = None,
    alert_id: Optional[str] = None,
    triggered_by: Optional[str] = None,
) -> Dict:
    """
    Celery task to send notifications to multiple recipients.

    Sends the same notification to a list of recipients. Each recipient
    is processed individually, allowing partial success when some
    recipients fail.

    Args:
        channel: Notification channel ('email' or 'sms').
        recipients: List of recipient addresses.
        subject: Subject line (required for email, ignored for SMS).
        message: Message body.
        html_body: Optional HTML body (email only).
        alert_id: Optional alert ID this notification is associated with.
        triggered_by: Optional identifier of who/what triggered the notification.

    Returns:
        Dictionary containing task result:
        - status: 'ok' on complete success, 'partial' on partial success, 'error' on failure
        - channel: Notification channel used
        - total_recipients: Number of recipients
        - successful: Number of successful sends
        - failed: Number of failed sends
        - results: List of individual results
        - alert_id: Associated alert ID (if provided)
        - triggered_by: Who/what triggered the notification
        - completed_at: ISO timestamp of completion
    """
    task_id = self.request.id
    started_at = datetime.now(timezone.utc)

    logger.info(
        f"Starting bulk notification task[{task_id}]: "
        f"channel={channel}, recipients_count={len(recipients)}",
        extra={
            'task_id': task_id,
            'channel': channel,
            'recipients_count': len(recipients),
            'alert_id': alert_id,
            'triggered_by': triggered_by,
            'started_at': started_at.isoformat(),
        }
    )

    # Validate channel
    valid_channels = [NotificationChannel.EMAIL.value, NotificationChannel.SMS.value]
    if channel not in valid_channels:
        error_msg = f"Invalid notification channel: {channel}"
        logger.error(
            f"Bulk notification task[{task_id}] failed: {error_msg}",
            extra={
                'task_id': task_id,
                'error': error_msg,
                'error_type': 'invalid_channel',
            }
        )
        return task_error_result(
            error=error_msg,
            code='INVALID_CHANNEL',
            data={
                'channel': channel,
                'recipients_count': len(recipients),
                'alert_id': alert_id,
                'triggered_by': triggered_by,
            }
        )

    if not recipients:
        logger.warning(
            f"Bulk notification task[{task_id}]: empty recipients list",
            extra={
                'task_id': task_id,
                'channel': channel,
            }
        )
        return task_success_result(
            message='No recipients to notify',
            data={
                'channel': channel,
                'total_recipients': 0,
                'successful': 0,
                'failed': 0,
                'results': [],
                'alert_id': alert_id,
                'triggered_by': triggered_by,
                'completed_at': datetime.now(timezone.utc).isoformat(),
            }
        )

    results = []
    successful = 0
    failed = 0

    for recipient in recipients:
        try:
            result = send_notification(
                channel=channel,
                recipient=recipient,
                subject=subject,
                message=message,
                html_body=html_body,
            )

            if result.success:
                successful += 1
                results.append({
                    'recipient': recipient,
                    'success': True,
                    'message_id': result.message_id,
                    'is_stub': result.is_stub,
                })
            else:
                failed += 1
                results.append({
                    'recipient': recipient,
                    'success': False,
                    'error': result.error,
                })

        except InvalidRecipientError as e:
            failed += 1
            results.append({
                'recipient': recipient,
                'success': False,
                'error': str(e),
            })
            logger.warning(
                f"Invalid recipient in bulk notification: {recipient}: {e}"
            )

        except NotificationError as e:
            failed += 1
            results.append({
                'recipient': recipient,
                'success': False,
                'error': str(e),
            })
            logger.warning(
                f"Failed to send notification to {recipient}: {e}"
            )

        except Exception as e:
            failed += 1
            results.append({
                'recipient': recipient,
                'success': False,
                'error': f"Unexpected error: {e}",
            })
            logger.error(
                f"Unexpected error sending notification to {recipient}: {e}"
            )

    completed_at = datetime.now(timezone.utc)
    duration = (completed_at - started_at).total_seconds()

    # Determine overall status
    if failed == 0:
        status = 'ok'
        message_text = 'All notifications sent successfully'
    elif successful == 0:
        status = 'error'
        message_text = 'All notifications failed'
    else:
        status = 'partial'
        message_text = f'{successful} of {len(recipients)} notifications sent successfully'

    logger.info(
        f"Bulk notification task[{task_id}] completed in {duration:.2f}s: "
        f"channel={channel}, successful={successful}, failed={failed}",
        extra={
            'task_id': task_id,
            'channel': channel,
            'successful': successful,
            'failed': failed,
            'total_recipients': len(recipients),
            'duration_seconds': duration,
        }
    )

    result_data = {
        'channel': channel,
        'total_recipients': len(recipients),
        'successful': successful,
        'failed': failed,
        'results': results,
        'alert_id': alert_id,
        'triggered_by': triggered_by,
        'completed_at': completed_at.isoformat(),
        'duration_seconds': duration,
    }

    if status == 'error':
        return task_error_result(
            error=message_text,
            code='ALL_NOTIFICATIONS_FAILED',
            data=result_data,
        )

    # Return success for 'ok' or 'partial' status
    return {
        'status': status,
        'message': message_text,
        **result_data,
    }


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    'send_notification_task',
    'send_bulk_notification_task',
]
