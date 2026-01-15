"""
Notifier Service

Handles multi-channel notification dispatch for alerts and system events.
Supports email (via SendGrid) and SMS (via Twilio) with configurable
stub/mock modes for development.

In development mode (when API keys are not configured), notifications are
logged but not actually sent, allowing full testing of notification workflows.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from central_hub.config import get_config

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """Base exception for notification errors."""
    pass


class EmailSendError(NotificationError):
    """Raised when email sending fails."""
    pass


class SMSSendError(NotificationError):
    """Raised when SMS sending fails."""
    pass


class InvalidRecipientError(NotificationError):
    """Raised when recipient address/number is invalid."""
    pass


class NotificationChannel(str, Enum):
    """Notification delivery channels."""
    EMAIL = 'email'
    SMS = 'sms'


@dataclass
class NotificationResult:
    """Result of a notification send attempt."""
    success: bool
    channel: str
    recipient: str
    message_id: Optional[str] = None
    error: Optional[str] = None
    timestamp: Optional[datetime] = None
    is_stub: bool = False

    def to_dict(self) -> Dict:
        """Convert result to dictionary."""
        return {
            'success': self.success,
            'channel': self.channel,
            'recipient': self.recipient,
            'message_id': self.message_id,
            'error': self.error,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'is_stub': self.is_stub,
        }


def _is_sendgrid_configured() -> bool:
    """Check if SendGrid is configured with API key."""
    config = get_config()
    return bool(config.SENDGRID_API_KEY)


def _is_twilio_configured() -> bool:
    """Check if Twilio is configured with credentials."""
    config = get_config()
    return bool(
        config.TWILIO_ACCOUNT_SID and
        config.TWILIO_AUTH_TOKEN and
        config.TWILIO_PHONE_NUMBER
    )


def _validate_email(email: str) -> bool:
    """
    Basic email validation.

    Args:
        email: Email address to validate.

    Returns:
        True if email appears valid.
    """
    if not email or not isinstance(email, str):
        return False
    # Basic check for @ and domain
    parts = email.split('@')
    if len(parts) != 2:
        return False
    local, domain = parts
    if not local or not domain:
        return False
    if '.' not in domain:
        return False
    return True


def _validate_phone(phone: str) -> bool:
    """
    Basic phone number validation.

    Args:
        phone: Phone number to validate.

    Returns:
        True if phone appears valid.
    """
    if not phone or not isinstance(phone, str):
        return False
    # Remove common formatting characters
    cleaned = phone.replace('-', '').replace(' ', '').replace('(', '').replace(')', '').replace('+', '')
    # Check it's all digits and reasonable length
    if not cleaned.isdigit():
        return False
    if len(cleaned) < 10 or len(cleaned) > 15:
        return False
    return True


def send_email(
    to_email: str,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
    from_email: Optional[str] = None,
) -> NotificationResult:
    """
    Send an email notification via SendGrid.

    In development mode (without SENDGRID_API_KEY), logs the email
    instead of sending it.

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        body: Plain text email body.
        html_body: Optional HTML email body.
        from_email: Optional sender email (uses config default if not specified).

    Returns:
        NotificationResult with send status.

    Raises:
        InvalidRecipientError: If the email address is invalid.
        EmailSendError: If sending fails (after all retries in production).
    """
    config = get_config()
    timestamp = datetime.now(timezone.utc)

    # Validate recipient
    if not _validate_email(to_email):
        logger.error(f"Invalid email address: {to_email}")
        raise InvalidRecipientError(f"Invalid email address: {to_email}")

    sender_email = from_email or config.SENDGRID_FROM_EMAIL

    # Check if SendGrid is configured
    if not _is_sendgrid_configured():
        # Stub mode - log instead of sending
        logger.info(
            f"[STUB EMAIL] To: {to_email}, From: {sender_email}, "
            f"Subject: {subject}, Body length: {len(body)} chars"
        )
        return NotificationResult(
            success=True,
            channel=NotificationChannel.EMAIL.value,
            recipient=to_email,
            message_id=f"stub-email-{timestamp.timestamp()}",
            timestamp=timestamp,
            is_stub=True,
        )

    # Production mode - send via SendGrid
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content

        message = Mail(
            from_email=Email(sender_email),
            to_emails=To(to_email),
            subject=subject,
        )

        # Add plain text content
        message.add_content(Content("text/plain", body))

        # Add HTML content if provided
        if html_body:
            message.add_content(Content("text/html", html_body))

        sg = SendGridAPIClient(config.SENDGRID_API_KEY)
        response = sg.send(message)

        # Check response status
        if response.status_code in (200, 201, 202):
            message_id = response.headers.get('X-Message-Id', 'unknown')
            logger.info(
                f"Email sent successfully to {to_email}, "
                f"message_id: {message_id}, status: {response.status_code}"
            )
            return NotificationResult(
                success=True,
                channel=NotificationChannel.EMAIL.value,
                recipient=to_email,
                message_id=message_id,
                timestamp=timestamp,
                is_stub=False,
            )
        else:
            error_msg = f"SendGrid returned status {response.status_code}"
            logger.error(f"Email send failed: {error_msg}")
            raise EmailSendError(error_msg)

    except ImportError:
        # SendGrid library not installed - fall back to stub
        logger.warning(
            "SendGrid library not installed, using stub mode. "
            "Install with: pip install sendgrid"
        )
        logger.info(
            f"[STUB EMAIL] To: {to_email}, From: {sender_email}, "
            f"Subject: {subject}, Body length: {len(body)} chars"
        )
        return NotificationResult(
            success=True,
            channel=NotificationChannel.EMAIL.value,
            recipient=to_email,
            message_id=f"stub-email-{timestamp.timestamp()}",
            timestamp=timestamp,
            is_stub=True,
        )

    except EmailSendError:
        raise

    except Exception as e:
        error_msg = f"Failed to send email to {to_email}: {e}"
        logger.error(error_msg)
        raise EmailSendError(error_msg)


def send_sms(
    to_phone: str,
    message: str,
    from_phone: Optional[str] = None,
) -> NotificationResult:
    """
    Send an SMS notification via Twilio.

    In development mode (without Twilio credentials), logs the SMS
    instead of sending it.

    Args:
        to_phone: Recipient phone number (E.164 format preferred, e.g., +1234567890).
        message: SMS message body (max 1600 characters).
        from_phone: Optional sender phone number (uses config default if not specified).

    Returns:
        NotificationResult with send status.

    Raises:
        InvalidRecipientError: If the phone number is invalid.
        SMSSendError: If sending fails (after all retries in production).
    """
    config = get_config()
    timestamp = datetime.now(timezone.utc)

    # Validate recipient
    if not _validate_phone(to_phone):
        logger.error(f"Invalid phone number: {to_phone}")
        raise InvalidRecipientError(f"Invalid phone number: {to_phone}")

    sender_phone = from_phone or config.TWILIO_PHONE_NUMBER

    # Truncate message if too long (SMS limit)
    max_length = 1600
    if len(message) > max_length:
        logger.warning(
            f"SMS message truncated from {len(message)} to {max_length} characters"
        )
        message = message[:max_length - 3] + "..."

    # Check if Twilio is configured
    if not _is_twilio_configured():
        # Stub mode - log instead of sending
        logger.info(
            f"[STUB SMS] To: {to_phone}, From: {sender_phone or 'N/A'}, "
            f"Message: {message[:50]}{'...' if len(message) > 50 else ''}"
        )
        return NotificationResult(
            success=True,
            channel=NotificationChannel.SMS.value,
            recipient=to_phone,
            message_id=f"stub-sms-{timestamp.timestamp()}",
            timestamp=timestamp,
            is_stub=True,
        )

    # Production mode - send via Twilio
    try:
        from twilio.rest import Client

        client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)

        twilio_message = client.messages.create(
            body=message,
            from_=sender_phone,
            to=to_phone,
        )

        logger.info(
            f"SMS sent successfully to {to_phone}, "
            f"sid: {twilio_message.sid}, status: {twilio_message.status}"
        )

        return NotificationResult(
            success=True,
            channel=NotificationChannel.SMS.value,
            recipient=to_phone,
            message_id=twilio_message.sid,
            timestamp=timestamp,
            is_stub=False,
        )

    except ImportError:
        # Twilio library not installed - fall back to stub
        logger.warning(
            "Twilio library not installed, using stub mode. "
            "Install with: pip install twilio"
        )
        logger.info(
            f"[STUB SMS] To: {to_phone}, From: {sender_phone or 'N/A'}, "
            f"Message: {message[:50]}{'...' if len(message) > 50 else ''}"
        )
        return NotificationResult(
            success=True,
            channel=NotificationChannel.SMS.value,
            recipient=to_phone,
            message_id=f"stub-sms-{timestamp.timestamp()}",
            timestamp=timestamp,
            is_stub=True,
        )

    except Exception as e:
        error_msg = f"Failed to send SMS to {to_phone}: {e}"
        logger.error(error_msg)
        raise SMSSendError(error_msg)


def send_notification(
    channel: str,
    recipient: str,
    subject: Optional[str] = None,
    message: str = "",
    html_body: Optional[str] = None,
) -> NotificationResult:
    """
    Send a notification via the specified channel.

    Unified interface for sending notifications across different channels.

    Args:
        channel: Notification channel ('email' or 'sms').
        recipient: Recipient address (email or phone number).
        subject: Subject line (required for email, ignored for SMS).
        message: Message body.
        html_body: Optional HTML body (email only).

    Returns:
        NotificationResult with send status.

    Raises:
        ValueError: If channel is invalid.
        NotificationError: If sending fails.
    """
    if channel == NotificationChannel.EMAIL.value:
        if not subject:
            subject = "Notification"
        return send_email(
            to_email=recipient,
            subject=subject,
            body=message,
            html_body=html_body,
        )
    elif channel == NotificationChannel.SMS.value:
        return send_sms(
            to_phone=recipient,
            message=message,
        )
    else:
        raise ValueError(f"Invalid notification channel: {channel}")


def send_bulk_notifications(
    channel: str,
    recipients: List[str],
    subject: Optional[str] = None,
    message: str = "",
    html_body: Optional[str] = None,
) -> List[NotificationResult]:
    """
    Send notifications to multiple recipients.

    Continues sending even if individual notifications fail.

    Args:
        channel: Notification channel ('email' or 'sms').
        recipients: List of recipient addresses.
        subject: Subject line (required for email, ignored for SMS).
        message: Message body.
        html_body: Optional HTML body (email only).

    Returns:
        List of NotificationResult objects for each recipient.
    """
    results = []

    for recipient in recipients:
        try:
            result = send_notification(
                channel=channel,
                recipient=recipient,
                subject=subject,
                message=message,
                html_body=html_body,
            )
            results.append(result)
        except NotificationError as e:
            # Log failure but continue with other recipients
            logger.error(f"Failed to send {channel} to {recipient}: {e}")
            results.append(NotificationResult(
                success=False,
                channel=channel,
                recipient=recipient,
                error=str(e),
                timestamp=datetime.now(timezone.utc),
            ))
        except Exception as e:
            logger.error(f"Unexpected error sending {channel} to {recipient}: {e}")
            results.append(NotificationResult(
                success=False,
                channel=channel,
                recipient=recipient,
                error=f"Unexpected error: {e}",
                timestamp=datetime.now(timezone.utc),
            ))

    # Log summary
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful
    logger.info(
        f"Bulk notification complete: {successful} successful, {failed} failed "
        f"out of {len(results)} total"
    )

    return results


def get_notification_status() -> Dict:
    """
    Get the current status of notification services.

    Returns:
        Dictionary with service status information.
    """
    return {
        'email': {
            'provider': 'sendgrid',
            'configured': _is_sendgrid_configured(),
            'mode': 'production' if _is_sendgrid_configured() else 'stub',
        },
        'sms': {
            'provider': 'twilio',
            'configured': _is_twilio_configured(),
            'mode': 'production' if _is_twilio_configured() else 'stub',
        },
    }
