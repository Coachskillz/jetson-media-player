"""
Test Notifier Service

Tests the notifier service for email/SMS notification dispatch functionality.
Uses stub/mock mode since external services (SendGrid, Twilio) are not configured.
"""

import os
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Set testing environment
os.environ['FLASK_ENV'] = 'testing'


class TestSendEmailNotification:
    """Tests for send_email function."""

    def test_send_email_notification_stub_mode(self, app):
        """Test email notification sends in stub mode (mocked)."""
        from central_hub.services.notifier import send_email

        with app.app_context():
            result = send_email(
                to_email='test@example.com',
                subject='Test Subject',
                body='Test message body',
            )

            # In stub mode, should return success
            assert result.success is True
            assert result.channel == 'email'
            assert result.recipient == 'test@example.com'
            assert result.is_stub is True
            assert result.message_id is not None

    def test_send_email_invalid_recipient(self, app):
        """Test error for invalid email address."""
        from central_hub.services.notifier import (
            send_email,
            InvalidRecipientError
        )

        with app.app_context():
            with pytest.raises(InvalidRecipientError):
                send_email(
                    to_email='invalid-email',  # No @ sign
                    subject='Test',
                    body='Test body',
                )

    def test_send_email_empty_recipient(self, app):
        """Test error for empty recipient."""
        from central_hub.services.notifier import (
            send_email,
            InvalidRecipientError
        )

        with app.app_context():
            with pytest.raises(InvalidRecipientError):
                send_email(
                    to_email='',
                    subject='Test',
                    body='Test body',
                )

    @patch('central_hub.services.notifier._is_sendgrid_configured')
    def test_send_email_with_html_body(self, mock_configured, app):
        """Test email with HTML body."""
        from central_hub.services.notifier import send_email

        mock_configured.return_value = False  # Force stub mode

        with app.app_context():
            result = send_email(
                to_email='test@example.com',
                subject='HTML Test',
                body='Plain text body',
                html_body='<html><body><h1>HTML body</h1></body></html>',
            )

            assert result.success is True
            assert result.is_stub is True


class TestSendSMSNotification:
    """Tests for send_sms function."""

    def test_send_sms_notification_stub_mode(self, app):
        """Test SMS notification sends in stub mode (mocked)."""
        from central_hub.services.notifier import send_sms

        with app.app_context():
            result = send_sms(
                to_phone='+1234567890',
                message='Test SMS message',
            )

            # In stub mode, should return success
            assert result.success is True
            assert result.channel == 'sms'
            assert result.recipient == '+1234567890'
            assert result.is_stub is True
            assert result.message_id is not None

    def test_send_sms_invalid_phone(self, app):
        """Test error for invalid phone number."""
        from central_hub.services.notifier import (
            send_sms,
            InvalidRecipientError
        )

        with app.app_context():
            with pytest.raises(InvalidRecipientError):
                send_sms(
                    to_phone='invalid',  # Too short, no digits
                    message='Test',
                )

    def test_send_sms_various_phone_formats(self, app):
        """Test SMS accepts various phone number formats."""
        from central_hub.services.notifier import send_sms

        valid_phones = [
            '+1234567890',
            '123-456-7890',
            '(123) 456-7890',
            '1234567890',
        ]

        with app.app_context():
            for phone in valid_phones:
                result = send_sms(
                    to_phone=phone,
                    message='Test message',
                )
                assert result.success is True, f"Failed for phone: {phone}"


class TestNotificationRetry:
    """Tests for notification retry functionality."""

    @patch('central_hub.services.notifier._is_sendgrid_configured')
    @patch('central_hub.services.notifier.SendGridAPIClient', create=True)
    def test_notification_retry_on_failure(self, mock_sg_client, mock_configured, app):
        """Test retries on transient failures."""
        from central_hub.services.notifier import send_email, EmailSendError

        # First configure as production mode
        mock_configured.return_value = True

        # Mock SendGrid to raise an exception
        mock_client_instance = MagicMock()
        mock_client_instance.send.side_effect = Exception("Transient network error")
        mock_sg_client.return_value = mock_client_instance

        with app.app_context():
            # In production mode with failure, should raise EmailSendError
            with pytest.raises(EmailSendError):
                send_email(
                    to_email='test@example.com',
                    subject='Test',
                    body='Test body',
                )


class TestWebhookNotification:
    """Tests for webhook notification channel."""

    def test_invalid_channel_error(self, app):
        """Test error for invalid notification channel."""
        from central_hub.services.notifier import send_notification

        with app.app_context():
            with pytest.raises(ValueError) as exc_info:
                send_notification(
                    channel='invalid_channel',
                    recipient='test@example.com',
                    message='Test',
                )

            assert "invalid" in str(exc_info.value).lower()


class TestBulkNotifications:
    """Tests for bulk notification sending."""

    def test_send_bulk_notifications(self, app):
        """Test sending notifications to multiple recipients."""
        from central_hub.services.notifier import send_bulk_notifications

        with app.app_context():
            recipients = [
                'test1@example.com',
                'test2@example.com',
                'test3@example.com',
            ]

            results = send_bulk_notifications(
                channel='email',
                recipients=recipients,
                subject='Bulk Test',
                message='Test message for all recipients',
            )

            assert len(results) == 3
            assert all(r.success for r in results)
            assert all(r.is_stub for r in results)

    def test_send_bulk_notifications_partial_failure(self, app):
        """Test bulk notifications continue on individual failures."""
        from central_hub.services.notifier import send_bulk_notifications

        with app.app_context():
            recipients = [
                'valid@example.com',
                'invalid-email',  # Invalid
                'another@example.com',
            ]

            results = send_bulk_notifications(
                channel='email',
                recipients=recipients,
                subject='Bulk Test',
                message='Test message',
            )

            # Should have 3 results (including the failed one)
            assert len(results) == 3

            # At least one should have failed (the invalid email)
            failed_count = sum(1 for r in results if not r.success)
            assert failed_count >= 1


class TestNotificationStatus:
    """Tests for notification service status."""

    def test_get_notification_status(self, app):
        """Test getting notification service status."""
        from central_hub.services.notifier import get_notification_status

        with app.app_context():
            status = get_notification_status()

            assert 'email' in status
            assert 'sms' in status
            assert 'provider' in status['email']
            assert 'configured' in status['email']
            assert 'mode' in status['email']

            # In test environment, should be in stub mode
            assert status['email']['mode'] == 'stub'
            assert status['sms']['mode'] == 'stub'


class TestUnifiedSendNotification:
    """Tests for unified send_notification interface."""

    def test_send_notification_email_channel(self, app):
        """Test unified interface routes to email correctly."""
        from central_hub.services.notifier import send_notification

        with app.app_context():
            result = send_notification(
                channel='email',
                recipient='test@example.com',
                subject='Test Subject',
                message='Test message',
            )

            assert result.success is True
            assert result.channel == 'email'

    def test_send_notification_sms_channel(self, app):
        """Test unified interface routes to SMS correctly."""
        from central_hub.services.notifier import send_notification

        with app.app_context():
            result = send_notification(
                channel='sms',
                recipient='+1234567890',
                message='Test SMS',
            )

            assert result.success is True
            assert result.channel == 'sms'

    def test_send_notification_default_subject(self, app):
        """Test email with no subject uses default."""
        from central_hub.services.notifier import send_notification

        with app.app_context():
            result = send_notification(
                channel='email',
                recipient='test@example.com',
                message='Test message',
                # No subject provided
            )

            assert result.success is True
