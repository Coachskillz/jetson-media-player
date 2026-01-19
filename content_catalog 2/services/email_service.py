"""
Email Service for Content Catalog.

Provides email notification functionality for user invitations,
password resets, approval workflows, and general system notifications
using Flask-Mail.

Key features:
- User invitation emails with registration links
- Password reset emails with secure tokens
- Approval request emails with magic links
- Asset approved/rejected/revoked notification emails
- General notification emails for system events
- Template-based HTML and plain text emails
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from flask import current_app, render_template

logger = logging.getLogger(__name__)


class EmailService:
    """
    Email service for sending notifications via Flask-Mail.

    This service handles:
    1. Sending user invitation emails with registration links
    2. Sending password reset emails with secure tokens
    3. Sending approval request emails with magic links
    4. Sending asset approved/rejected/revoked notification emails
    5. Sending general notification emails

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

        # Send an approval request email with magic link
        success = EmailService.send_approval_request(
            to_email='approver@example.com',
            approver_name='Jane Approver',
            uploader_name='John Uploader',
            asset=content_asset,
            magic_link='http://localhost:5003/approve/token123',
            expires_at=datetime.utcnow() + timedelta(minutes=30)
        )

        # Send asset approved notification
        success = EmailService.send_asset_approved(
            to_email='uploader@example.com',
            uploader_name='John Uploader',
            approver_name='Jane Approver',
            asset=content_asset
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
    APPROVAL_REQUEST_SUBJECT = 'Content Approval Request - Skillz Media Content Catalog'
    ASSET_APPROVED_SUBJECT = 'Your Content Has Been Approved - Skillz Media Content Catalog'
    ASSET_REJECTED_SUBJECT = 'Your Content Has Been Rejected - Skillz Media Content Catalog'
    ASSET_REVOKED_SUBJECT = 'Your Content Has Been Revoked - Skillz Media Content Catalog'

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
    def send_approval_request(
        cls,
        to_email: str,
        approver_name: str,
        uploader_name: str,
        asset: Any,
        magic_link: str,
        expires_at: Optional[datetime] = None,
        submitted_at: Optional[datetime] = None
    ) -> bool:
        """
        Send an approval request email with a magic link.

        Sends an email to the designated approver with details about the
        asset requiring approval and a secure magic link for review.

        Args:
            to_email: Approver's email address
            approver_name: Name of the approver
            uploader_name: Name of the user who uploaded the asset
            asset: ContentAsset object or dict with asset details
            magic_link: Secure one-time-use approval link
            expires_at: When the magic link expires (optional)
            submitted_at: When the asset was submitted (optional, defaults to now)

        Returns:
            True if the email was sent successfully, False otherwise
        """
        try:
            from flask_mail import Message

            from content_catalog.app import mail

            # Prepare template context
            if submitted_at is None:
                submitted_at = datetime.utcnow()

            # Format datetime for display
            submitted_at_str = submitted_at.strftime('%B %d, %Y at %I:%M %p UTC')
            expires_at_str = None
            if expires_at:
                expires_at_str = expires_at.strftime('%B %d, %Y at %I:%M %p UTC')

            # Prepare asset data for template
            asset_data = cls._prepare_asset_data(asset)

            # Render HTML template
            html_body = render_template(
                'email/approval_request.html',
                asset=asset_data,
                approver_name=approver_name,
                uploader_name=uploader_name,
                magic_link=magic_link,
                expires_at=expires_at_str,
                submitted_at=submitted_at_str,
                current_year=datetime.utcnow().year
            )

            # Create and send message
            msg = Message(
                subject=cls.APPROVAL_REQUEST_SUBJECT,
                recipients=[to_email],
                html=html_body
            )

            mail.send(msg)
            logger.info(f'Approval request email sent to {to_email} for asset {asset_data.get("uuid", "unknown")}')
            return True

        except Exception as e:
            logger.error(f'Failed to send approval request email to {to_email}: {str(e)}')
            return False

    @classmethod
    def send_asset_approved(
        cls,
        to_email: str,
        uploader_name: str,
        approver_name: str,
        asset: Any,
        approved_at: Optional[datetime] = None,
        asset_url: Optional[str] = None
    ) -> bool:
        """
        Send an asset approved notification email.

        Notifies the uploader that their asset has been approved
        and is now available for distribution.

        Args:
            to_email: Uploader's email address
            uploader_name: Name of the uploader
            approver_name: Name of the approver who approved the asset
            asset: ContentAsset object or dict with asset details
            approved_at: When the asset was approved (optional, defaults to now)
            asset_url: URL to view the asset in the catalog (optional)

        Returns:
            True if the email was sent successfully, False otherwise
        """
        try:
            from flask_mail import Message

            from content_catalog.app import mail

            # Prepare template context
            if approved_at is None:
                approved_at = datetime.utcnow()

            approved_at_str = approved_at.strftime('%B %d, %Y at %I:%M %p UTC')

            # Prepare asset data for template
            asset_data = cls._prepare_asset_data(asset)

            # Render HTML template
            html_body = render_template(
                'email/asset_approved.html',
                asset=asset_data,
                uploader_name=uploader_name,
                approver_name=approver_name,
                approved_at=approved_at_str,
                asset_url=asset_url,
                current_year=datetime.utcnow().year
            )

            # Create and send message
            msg = Message(
                subject=cls.ASSET_APPROVED_SUBJECT,
                recipients=[to_email],
                html=html_body
            )

            mail.send(msg)
            logger.info(f'Asset approved email sent to {to_email} for asset {asset_data.get("uuid", "unknown")}')
            return True

        except Exception as e:
            logger.error(f'Failed to send asset approved email to {to_email}: {str(e)}')
            return False

    @classmethod
    def send_asset_rejected(
        cls,
        to_email: str,
        uploader_name: str,
        reviewer_name: str,
        asset: Any,
        rejection_reason: str,
        rejected_at: Optional[datetime] = None,
        upload_url: Optional[str] = None
    ) -> bool:
        """
        Send an asset rejected notification email.

        Notifies the uploader that their asset has been rejected
        with the reason for rejection.

        Args:
            to_email: Uploader's email address
            uploader_name: Name of the uploader
            reviewer_name: Name of the reviewer who rejected the asset
            asset: ContentAsset object or dict with asset details
            rejection_reason: Explanation for why the asset was rejected
            rejected_at: When the asset was rejected (optional, defaults to now)
            upload_url: URL to submit a new upload (optional)

        Returns:
            True if the email was sent successfully, False otherwise
        """
        try:
            from flask_mail import Message

            from content_catalog.app import mail

            # Prepare template context
            if rejected_at is None:
                rejected_at = datetime.utcnow()

            rejected_at_str = rejected_at.strftime('%B %d, %Y at %I:%M %p UTC')

            # Prepare asset data for template
            asset_data = cls._prepare_asset_data(asset)

            # Render HTML template
            html_body = render_template(
                'email/asset_rejected.html',
                asset=asset_data,
                uploader_name=uploader_name,
                reviewer_name=reviewer_name,
                rejection_reason=rejection_reason,
                rejected_at=rejected_at_str,
                upload_url=upload_url,
                current_year=datetime.utcnow().year
            )

            # Create and send message
            msg = Message(
                subject=cls.ASSET_REJECTED_SUBJECT,
                recipients=[to_email],
                html=html_body
            )

            mail.send(msg)
            logger.info(f'Asset rejected email sent to {to_email} for asset {asset_data.get("uuid", "unknown")}')
            return True

        except Exception as e:
            logger.error(f'Failed to send asset rejected email to {to_email}: {str(e)}')
            return False

    @classmethod
    def send_asset_revoked(
        cls,
        to_email: str,
        owner_name: str,
        revoker_name: str,
        asset: Any,
        revocation_reason: Optional[str] = None,
        revoked_at: Optional[datetime] = None,
        admin_contact_url: Optional[str] = None
    ) -> bool:
        """
        Send an asset revoked notification email.

        Notifies the asset owner that their previously approved asset
        has had its approval revoked and is no longer available.

        Args:
            to_email: Owner's email address
            owner_name: Name of the asset owner
            revoker_name: Name of the user who revoked the asset
            asset: ContentAsset object or dict with asset details
            revocation_reason: Explanation for why the asset was revoked (optional)
            revoked_at: When the asset was revoked (optional, defaults to now)
            admin_contact_url: URL to contact administrator (optional)

        Returns:
            True if the email was sent successfully, False otherwise
        """
        try:
            from flask_mail import Message

            from content_catalog.app import mail

            # Prepare template context
            if revoked_at is None:
                revoked_at = datetime.utcnow()

            revoked_at_str = revoked_at.strftime('%B %d, %Y at %I:%M %p UTC')

            # Prepare asset data for template
            asset_data = cls._prepare_asset_data(asset)

            # Render HTML template
            html_body = render_template(
                'email/asset_revoked.html',
                asset=asset_data,
                owner_name=owner_name,
                revoker_name=revoker_name,
                revocation_reason=revocation_reason,
                revoked_at=revoked_at_str,
                admin_contact_url=admin_contact_url,
                current_year=datetime.utcnow().year
            )

            # Create and send message
            msg = Message(
                subject=cls.ASSET_REVOKED_SUBJECT,
                recipients=[to_email],
                html=html_body
            )

            mail.send(msg)
            logger.info(f'Asset revoked email sent to {to_email} for asset {asset_data.get("uuid", "unknown")}')
            return True

        except Exception as e:
            logger.error(f'Failed to send asset revoked email to {to_email}: {str(e)}')
            return False

    @classmethod
    def _prepare_asset_data(cls, asset: Any) -> Dict[str, Any]:
        """
        Prepare asset data for email templates.

        Converts ContentAsset model or dict to a consistent dictionary
        format for use in email templates.

        Args:
            asset: ContentAsset object or dict with asset details

        Returns:
            Dictionary with asset data suitable for templates
        """
        # If it's already a dict, use it directly
        if isinstance(asset, dict):
            return asset

        # If it's a model with to_dict method, use that
        if hasattr(asset, 'to_dict'):
            return asset.to_dict()

        # Otherwise, extract common attributes
        asset_data = {}
        for attr in ['uuid', 'title', 'description', 'filename', 'format',
                     'file_size', 'category', 'state', 'created_at']:
            if hasattr(asset, attr):
                value = getattr(asset, attr)
                # Handle datetime objects
                if isinstance(value, datetime):
                    value = value.isoformat()
                asset_data[attr] = value

        # Handle category relationship if present
        if hasattr(asset, 'category') and asset.category:
            if hasattr(asset.category, 'name'):
                asset_data['category'] = asset.category.name

        return asset_data

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
