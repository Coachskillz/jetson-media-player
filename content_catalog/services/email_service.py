"""
Email Service for Content Catalog.

Provides email notification functionality for user invitations,
password resets, and general system notifications using Flask-Mail.

Key features:
- User invitation emails with registration links
- Password reset emails with secure tokens
- General notification emails for system events
- Template-based HTML and plain text emails
"""

import logging
from typing import Any, Dict, Optional

from flask import current_app, render_template_string

logger = logging.getLogger(__name__)


class EmailService:
    """
    Email service for sending notifications via Flask-Mail.

    This service handles:
    1. Sending user invitation emails with registration links
    2. Sending password reset emails with secure tokens
    3. Sending general notification emails

    Usage:
        # Send an invitation email
        success = EmailService.send_invitation(
            to_email='newuser@example.com',
            inviter_name='John Admin',
            invitation_token='abc123',
            role='partner',
            organization_name='Partner Corp'
        )

        # Send a password reset email
        success = EmailService.send_password_reset(
            to_email='user@example.com',
            user_name='Jane User',
            reset_token='xyz789'
        )

        # Send a notification
        success = EmailService.send_notification(
            to_email='user@example.com',
            subject='Content Approved',
            body='Your content has been approved and is now published.'
        )
    """

    # Email templates
    INVITATION_SUBJECT = 'You have been invited to join Skillz Media Content Catalog'
    PASSWORD_RESET_SUBJECT = 'Password Reset Request - Skillz Media Content Catalog'

    @classmethod
    def send_invitation(
        cls,
        to_email: str,
        inviter_name: str,
        invitation_token: str,
        role: str,
        organization_name: Optional[str] = None,
        base_url: Optional[str] = None
    ) -> bool:
        """
        Send a user invitation email.

        Creates and sends an invitation email with a registration link
        containing the invitation token.

        Args:
            to_email: Recipient email address
            inviter_name: Name of the user who sent the invitation
            invitation_token: Secure token for the invitation
            role: Role being offered (e.g., 'partner', 'advertiser')
            organization_name: Name of the organization (optional)
            base_url: Base URL for the registration link (optional, uses config default)

        Returns:
            True if the email was sent successfully, False otherwise
        """
        try:
            from flask_mail import Message

            from content_catalog.app import mail

            # Build registration URL
            if base_url is None:
                base_url = cls._get_base_url()
            registration_url = f'{base_url}/register?token={invitation_token}'

            # Build email content
            subject = cls.INVITATION_SUBJECT
            org_text = f' at {organization_name}' if organization_name else ''
            role_display = role.replace('_', ' ').title()

            html_body = cls._render_invitation_html(
                inviter_name=inviter_name,
                role_display=role_display,
                organization_text=org_text,
                registration_url=registration_url
            )

            text_body = cls._render_invitation_text(
                inviter_name=inviter_name,
                role_display=role_display,
                organization_text=org_text,
                registration_url=registration_url
            )

            # Create and send message
            msg = Message(
                subject=subject,
                recipients=[to_email],
                body=text_body,
                html=html_body
            )

            mail.send(msg)
            logger.info(f'Invitation email sent to {to_email}')
            return True

        except Exception as e:
            logger.error(f'Failed to send invitation email to {to_email}: {str(e)}')
            return False

    @classmethod
    def send_password_reset(
        cls,
        to_email: str,
        user_name: str,
        reset_token: str,
        base_url: Optional[str] = None,
        expiry_hours: int = 24
    ) -> bool:
        """
        Send a password reset email.

        Creates and sends a password reset email with a secure reset link.

        Args:
            to_email: Recipient email address
            user_name: Name of the user requesting the reset
            reset_token: Secure token for password reset
            base_url: Base URL for the reset link (optional, uses config default)
            expiry_hours: Hours until the reset link expires (for display purposes)

        Returns:
            True if the email was sent successfully, False otherwise
        """
        try:
            from flask_mail import Message

            from content_catalog.app import mail

            # Build reset URL
            if base_url is None:
                base_url = cls._get_base_url()
            reset_url = f'{base_url}/reset-password?token={reset_token}'

            # Build email content
            subject = cls.PASSWORD_RESET_SUBJECT

            html_body = cls._render_password_reset_html(
                user_name=user_name,
                reset_url=reset_url,
                expiry_hours=expiry_hours
            )

            text_body = cls._render_password_reset_text(
                user_name=user_name,
                reset_url=reset_url,
                expiry_hours=expiry_hours
            )

            # Create and send message
            msg = Message(
                subject=subject,
                recipients=[to_email],
                body=text_body,
                html=html_body
            )

            mail.send(msg)
            logger.info(f'Password reset email sent to {to_email}')
            return True

        except Exception as e:
            logger.error(f'Failed to send password reset email to {to_email}: {str(e)}')
            return False

    @classmethod
    def send_notification(
        cls,
        to_email: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        reply_to: Optional[str] = None
    ) -> bool:
        """
        Send a general notification email.

        Flexible method for sending system notifications with custom content.

        Args:
            to_email: Recipient email address
            subject: Email subject line
            body: Plain text email body
            html_body: HTML email body (optional, uses plain text if not provided)
            reply_to: Reply-to email address (optional)

        Returns:
            True if the email was sent successfully, False otherwise
        """
        try:
            from flask_mail import Message

            from content_catalog.app import mail

            # If no HTML body provided, wrap plain text in basic HTML
            if html_body is None:
                html_body = cls._wrap_plain_text_as_html(body)

            # Create message
            msg = Message(
                subject=subject,
                recipients=[to_email],
                body=body,
                html=html_body
            )

            # Add reply-to if provided
            if reply_to:
                msg.reply_to = reply_to

            mail.send(msg)
            logger.info(f'Notification email sent to {to_email}: {subject}')
            return True

        except Exception as e:
            logger.error(f'Failed to send notification email to {to_email}: {str(e)}')
            return False

    @classmethod
    def send_bulk_notification(
        cls,
        recipients: list,
        subject: str,
        body: str,
        html_body: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a notification to multiple recipients.

        Sends individual emails to each recipient (not CC/BCC) for privacy.

        Args:
            recipients: List of recipient email addresses
            subject: Email subject line
            body: Plain text email body
            html_body: HTML email body (optional)

        Returns:
            Dictionary with 'sent' count and 'failed' list
        """
        results = {
            'sent': 0,
            'failed': []
        }

        for email in recipients:
            success = cls.send_notification(
                to_email=email,
                subject=subject,
                body=body,
                html_body=html_body
            )
            if success:
                results['sent'] += 1
            else:
                results['failed'].append(email)

        return results

    @classmethod
    def _get_base_url(cls) -> str:
        """
        Get the base URL for email links from configuration.

        Returns:
            Base URL string (e.g., 'http://localhost:5003')
        """
        try:
            host = current_app.config.get('HOST', 'localhost')
            port = current_app.config.get('PORT', 5003)

            # Use HTTPS in production, HTTP in development
            protocol = 'https' if not current_app.config.get('DEBUG', True) else 'http'

            # Check for explicit base URL in config
            base_url = current_app.config.get('BASE_URL')
            if base_url:
                return base_url.rstrip('/')

            return f'{protocol}://{host}:{port}'
        except RuntimeError:
            # No app context, return default
            return 'http://localhost:5003'

    @classmethod
    def _render_invitation_html(
        cls,
        inviter_name: str,
        role_display: str,
        organization_text: str,
        registration_url: str
    ) -> str:
        """Render HTML template for invitation email."""
        return f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Invitation to Skillz Media Content Catalog</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #050508 0%, #1a1a2e 100%); padding: 30px; border-radius: 10px;">
        <h1 style="color: #00D4AA; margin: 0 0 20px 0;">You're Invited!</h1>
        <div style="background: rgba(255, 255, 255, 0.05); padding: 25px; border-radius: 8px; border: 1px solid rgba(0, 212, 170, 0.2);">
            <p style="color: #ffffff; margin: 0 0 15px 0;">
                <strong>{inviter_name}</strong> has invited you to join the Skillz Media Content Catalog{organization_text} as a <strong>{role_display}</strong>.
            </p>
            <p style="color: #cccccc; margin: 0 0 25px 0;">
                Click the button below to complete your registration and get started.
            </p>
            <a href="{registration_url}" style="display: inline-block; background: #00D4AA; color: #050508; text-decoration: none; padding: 12px 30px; border-radius: 5px; font-weight: bold;">
                Accept Invitation
            </a>
            <p style="color: #999999; font-size: 12px; margin: 25px 0 0 0;">
                This invitation will expire in 7 days. If you did not expect this invitation, you can safely ignore this email.
            </p>
        </div>
    </div>
    <p style="color: #666; font-size: 12px; text-align: center; margin-top: 20px;">
        Skillz Media Content Catalog
    </p>
</body>
</html>
'''

    @classmethod
    def _render_invitation_text(
        cls,
        inviter_name: str,
        role_display: str,
        organization_text: str,
        registration_url: str
    ) -> str:
        """Render plain text template for invitation email."""
        return f'''You're Invited to Skillz Media Content Catalog!

{inviter_name} has invited you to join the Skillz Media Content Catalog{organization_text} as a {role_display}.

To complete your registration, please visit the following link:

{registration_url}

This invitation will expire in 7 days.

If you did not expect this invitation, you can safely ignore this email.

---
Skillz Media Content Catalog
'''

    @classmethod
    def _render_password_reset_html(
        cls,
        user_name: str,
        reset_url: str,
        expiry_hours: int
    ) -> str:
        """Render HTML template for password reset email."""
        return f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Password Reset - Skillz Media Content Catalog</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #050508 0%, #1a1a2e 100%); padding: 30px; border-radius: 10px;">
        <h1 style="color: #00D4AA; margin: 0 0 20px 0;">Password Reset</h1>
        <div style="background: rgba(255, 255, 255, 0.05); padding: 25px; border-radius: 8px; border: 1px solid rgba(0, 212, 170, 0.2);">
            <p style="color: #ffffff; margin: 0 0 15px 0;">
                Hi <strong>{user_name}</strong>,
            </p>
            <p style="color: #cccccc; margin: 0 0 15px 0;">
                We received a request to reset your password for your Skillz Media Content Catalog account.
            </p>
            <p style="color: #cccccc; margin: 0 0 25px 0;">
                Click the button below to set a new password:
            </p>
            <a href="{reset_url}" style="display: inline-block; background: #00D4AA; color: #050508; text-decoration: none; padding: 12px 30px; border-radius: 5px; font-weight: bold;">
                Reset Password
            </a>
            <p style="color: #999999; font-size: 12px; margin: 25px 0 0 0;">
                This link will expire in {expiry_hours} hours. If you didn't request a password reset, you can safely ignore this email.
            </p>
        </div>
    </div>
    <p style="color: #666; font-size: 12px; text-align: center; margin-top: 20px;">
        Skillz Media Content Catalog
    </p>
</body>
</html>
'''

    @classmethod
    def _render_password_reset_text(
        cls,
        user_name: str,
        reset_url: str,
        expiry_hours: int
    ) -> str:
        """Render plain text template for password reset email."""
        return f'''Password Reset - Skillz Media Content Catalog

Hi {user_name},

We received a request to reset your password for your Skillz Media Content Catalog account.

To reset your password, please visit the following link:

{reset_url}

This link will expire in {expiry_hours} hours.

If you didn't request a password reset, you can safely ignore this email.

---
Skillz Media Content Catalog
'''

    @classmethod
    def _wrap_plain_text_as_html(cls, text: str) -> str:
        """
        Wrap plain text in basic HTML for consistent email rendering.

        Args:
            text: Plain text content

        Returns:
            HTML wrapped content
        """
        # Escape HTML entities and convert newlines to <br>
        import html
        escaped = html.escape(text)
        formatted = escaped.replace('\n', '<br>\n')

        return f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #050508 0%, #1a1a2e 100%); padding: 30px; border-radius: 10px;">
        <div style="background: rgba(255, 255, 255, 0.05); padding: 25px; border-radius: 8px; border: 1px solid rgba(0, 212, 170, 0.2);">
            <p style="color: #ffffff; margin: 0;">
                {formatted}
            </p>
        </div>
    </div>
    <p style="color: #666; font-size: 12px; text-align: center; margin-top: 20px;">
        Skillz Media Content Catalog
    </p>
</body>
</html>
'''
