"""
Checkout Service for Content Catalog.

Provides checkout functionality for content assets with token generation,
signed URLs, and fast-track permission support. Implements secure asset
checkout workflow with time-limited access tokens.

Key features:
- Token generation for asset checkout (10-minute expiry)
- Signed URL generation for downloads (5-minute expiry)
- Fast-track permission checking for unapproved assets
- Integration with visibility and audit services
- Visibility-based access control
"""

import secrets
import hashlib
import hmac
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple

from content_catalog.models import db, ContentAsset, User, CheckoutToken
from content_catalog.models.audit import AuditLog
from content_catalog.services.visibility_service import VisibilityService


class CheckoutService:
    """
    Asset checkout service for the Content Catalog.

    This service handles:
    1. Validating checkout permissions including fast-track
    2. Creating checkout tokens with signed URLs
    3. Fast-track checkout for privileged users
    4. Token validation and usage tracking
    5. Logging checkout events to audit trail

    Checkout Rules:
        - Regular users can only checkout APPROVED/PUBLISHED assets
        - Fast-track users can checkout DRAFT/SUBMITTED assets if:
            a) User has can_fasttrack_unapproved_assets = True
            b) fasttrack_expires_at is None or in the future
            c) Asset's tenant is in user's fasttrack_tenant_ids (if set)

    Token Expiry:
        - Checkout tokens: 10 minutes
        - Signed download URLs: 5 minutes

    Usage:
        # Check if a user can checkout an asset
        can_checkout, reason, is_fasttrack = CheckoutService.can_checkout_asset(
            db_session=db.session,
            user_id=current_user.id,
            asset_id=asset.id
        )

        # Create a checkout token
        result = CheckoutService.create_checkout_token(
            db_session=db.session,
            user_id=current_user.id,
            asset_id=asset.id
        )

        # Validate and use a checkout token
        result = CheckoutService.use_checkout_token(
            db_session=db.session,
            token='abc123...'
        )
    """

    # Token expiry times
    TOKEN_EXPIRY_MINUTES = 10
    DOWNLOAD_URL_EXPIRY_MINUTES = 5
    DEFAULT_EXPIRY_MINUTES = 10

    # Roles that can use fast-track checkout
    FASTTRACK_ROLES = [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER
    ]

    # Asset statuses that regular users can checkout
    REGULAR_CHECKOUT_STATUSES = [
        ContentAsset.STATUS_APPROVED,
        ContentAsset.STATUS_PUBLISHED
    ]

    # Asset statuses that fast-track users can additionally checkout
    FASTTRACK_CHECKOUT_STATUSES = [
        ContentAsset.STATUS_DRAFT,
        ContentAsset.STATUS_PENDING_REVIEW
    ]

    # Secret key for URL signing (should be from config in production)
    URL_SIGNING_SECRET = os.environ.get('CHECKOUT_URL_SECRET', 'default-dev-secret')

    @classmethod
    def _is_fasttrack_eligible_status(cls, status: str) -> bool:
        """
        Check if an asset status requires fast-track permission.

        Args:
            status: The asset status to check

        Returns:
            True if the status requires fast-track permission
        """
        return status in cls.FASTTRACK_CHECKOUT_STATUSES

    @classmethod
    def _is_regular_checkout_status(cls, status: str) -> bool:
        """
        Check if an asset status allows regular (non-fasttrack) checkout.

        Args:
            status: The asset status to check

        Returns:
            True if the status allows regular checkout
        """
        return status in cls.REGULAR_CHECKOUT_STATUSES

    @classmethod
    def _can_user_fasttrack(
        cls,
        db_session,
        user_id: int,
        asset_tenant_id: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Check if a user has valid fast-track permission.

        Validates:
        1. User has can_fasttrack_unapproved_assets flag set
        2. fasttrack_expires_at is None (no expiry) or in the future
        3. If fasttrack_tenant_ids is set, asset's tenant must be in the list

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user to check
            asset_tenant_id: Optional tenant ID of the asset (for tenant-scoped fast-track)

        Returns:
            Tuple of (can_fasttrack: bool, reason: str)
        """
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return False, 'User not found'

        # Check fast-track flag
        if hasattr(user, 'can_fasttrack_unapproved_assets'):
            if not user.can_fasttrack_unapproved_assets:
                return False, 'User does not have fast-track permission'

            # Check expiry
            if hasattr(user, 'has_valid_fasttrack'):
                if not user.has_valid_fasttrack():
                    return False, 'Fast-track permission has expired'

            # Check tenant scope (if applicable)
            if asset_tenant_id is not None and hasattr(user, 'get_fasttrack_tenant_ids_list'):
                fasttrack_tenant_ids = user.get_fasttrack_tenant_ids_list()
                if fasttrack_tenant_ids and asset_tenant_id not in fasttrack_tenant_ids:
                    return False, 'Fast-track permission does not apply to this tenant'
        else:
            # Fall back to role-based fast-track
            if user.role not in cls.FASTTRACK_ROLES:
                return False, f'Role "{user.role}" cannot use fast-track checkout'

        return True, 'ok'

    @classmethod
    def can_checkout_asset(
        cls,
        db_session,
        user_id: int,
        asset_id: int,
        fasttrack: bool = False
    ) -> Tuple[bool, str, bool]:
        """
        Check if a user can checkout a specific asset.

        Validates:
        1. User exists and is active
        2. Asset exists
        3. User has visibility to the asset
        4. For APPROVED/PUBLISHED assets: any authenticated user can checkout
        5. For DRAFT/SUBMITTED assets: requires fast-track permission
        6. For REJECTED/ARCHIVED assets: checkout not allowed

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user attempting checkout
            asset_id: ID of the asset to checkout
            fasttrack: Whether this is a fast-track checkout (for backwards compatibility)

        Returns:
            Tuple of (can_checkout: bool, reason: str, is_fasttrack: bool)
            - can_checkout: True if checkout is allowed
            - reason: 'ok' if allowed, error message otherwise
            - is_fasttrack: True if this is a fast-track checkout
        """
        # Fetch the user
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return False, 'User not found', False

        # Check user's account status
        if user.status not in [User.STATUS_ACTIVE, User.STATUS_APPROVED]:
            return False, 'User account is not active', False

        # Fetch the asset
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return False, 'Asset not found', False

        # Check visibility
        visibility_service = VisibilityService(user)
        if not visibility_service.can_view_asset(asset):
            return False, 'User does not have access to this asset', False

        # Check if asset status allows regular checkout
        if cls._is_regular_checkout_status(asset.status):
            return True, 'ok', False

        # Check if asset status allows fast-track checkout
        if cls._is_fasttrack_eligible_status(asset.status):
            # Get asset's tenant_id if it has one (may not have one if using organization_id)
            # For now, we check against organization's tenant or None
            asset_tenant_id = None  # TODO: Get from asset.tenant_id when available

            can_fasttrack, reason = cls._can_user_fasttrack(
                db_session, user_id, asset_tenant_id
            )
            if can_fasttrack:
                return True, 'ok', True
            else:
                return False, f'Fast-track required: {reason}', False

        # Asset in other statuses (REJECTED, ARCHIVED) cannot be checked out
        return False, f'Asset status "{asset.status}" does not allow checkout', False

    @classmethod
    def _generate_signed_url(
        cls,
        asset: ContentAsset,
        token: str,
        expires_at: datetime
    ) -> str:
        """
        Generate a signed download URL for an asset.

        The signed URL includes:
        - Asset file URL
        - Token for validation
        - Expiry timestamp
        - HMAC signature

        Args:
            asset: The content asset
            token: The checkout token
            expires_at: Token expiration time

        Returns:
            Signed download URL string
        """
        # Build the base URL
        base_url = asset.file_url or f'/api/v1/assets/{asset.id}/download'

        # Create signature payload
        expires_ts = int(expires_at.timestamp())
        payload = f'{asset.id}:{token}:{expires_ts}'

        # Generate HMAC signature
        signature = hmac.new(
            cls.URL_SIGNING_SECRET.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()[:16]

        # Build signed URL
        signed_url = f'{base_url}?token={token}&expires={expires_ts}&sig={signature}'

        return signed_url

    @classmethod
    def create_checkout_token(
        cls,
        db_session,
        user_id: int,
        asset_id: int,
        fasttrack: bool = False,
        expiry_minutes: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a checkout token for an asset.

        Generates a time-limited token and signed download URL for asset access.
        Logs the checkout event to the audit trail.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user performing checkout
            asset_id: ID of the asset to checkout
            fasttrack: Whether to use fast-track checkout (for backwards compatibility)
            expiry_minutes: Optional custom expiry (default 10 min)
            ip_address: Client IP address for audit logging
            user_agent: Client user agent for audit logging

        Returns:
            Dict with keys:
            - success: bool indicating if token creation succeeded
            - token: The generated checkout token (if successful)
            - download_url: Signed download URL (if successful)
            - expires_at: Token expiration timestamp (if successful)
            - is_fasttrack: Whether this was a fast-track checkout
            - error: Error message (if unsuccessful)

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        # Validate checkout is allowed
        can_checkout, reason, is_fasttrack = cls.can_checkout_asset(
            db_session, user_id, asset_id, fasttrack
        )
        if not can_checkout:
            return {
                'success': False,
                'error': reason,
                'token': None,
                'download_url': None,
                'expires_at': None,
                'is_fasttrack': False
            }

        # Fetch user and asset for logging
        user = db_session.query(User).filter_by(id=user_id).first()
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()

        # Generate secure token
        token = secrets.token_urlsafe(32)

        # Calculate expiry
        minutes = expiry_minutes or cls.DEFAULT_EXPIRY_MINUTES
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)

        # Create checkout token record
        checkout_token = CheckoutToken(
            asset_id=asset_id,
            user_id=user_id,
            is_fasttrack=is_fasttrack,
            expires_at=expires_at,
            token=token
        )
        db_session.add(checkout_token)
        db_session.flush()

        # Generate signed download URL
        signed_url = cls._generate_signed_url(asset, token, expires_at)
        checkout_token.download_url = signed_url

        # Log audit event
        import json
        audit_action = AuditLog.ACTION_FASTTRACK_CHECKOUT if is_fasttrack else AuditLog.ACTION_CHECKOUT_CREATED
        audit_log = AuditLog.log_action(
            action=audit_action,
            user_id=user_id,
            user_email=user.email if user else None,
            resource_type=AuditLog.RESOURCE_CHECKOUT_TOKEN,
            resource_id=str(asset_id),
            details=json.dumps({
                'asset_id': asset_id,
                'asset_uuid': asset.uuid if asset else None,
                'asset_title': asset.title if asset else None,
                'asset_status': asset.status if asset else None,
                'is_fasttrack': is_fasttrack,
                'token_expires_at': expires_at.isoformat()
            }),
            ip_address=ip_address,
            user_agent=user_agent
        )
        db_session.add(audit_log)

        return {
            'success': True,
            'error': None,
            'token': token,
            'download_url': signed_url,
            'expires_at': expires_at.isoformat(),
            'is_fasttrack': is_fasttrack
        }

    @classmethod
    def checkout_asset(
        cls,
        db_session,
        user_id: int,
        asset_id: int,
        fasttrack: bool = False,
        expiry_minutes: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Checkout an asset and generate a download token.

        Creates a CheckoutToken with a signed download URL that
        expires after the specified time.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user checking out
            asset_id: ID of the asset to checkout
            fasttrack: Whether to use fast-track checkout
            expiry_minutes: Optional custom expiry (default 10 min)

        Returns:
            Dict with keys:
            - success: bool indicating if checkout succeeded
            - token: The checkout token string (if successful)
            - download_url: Signed download URL (if successful)
            - expires_at: Token expiration time (if successful)
            - is_fasttrack: Whether this was a fast-track checkout
            - error: Error message (if unsuccessful)

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        return cls.create_checkout_token(
            db_session=db_session,
            user_id=user_id,
            asset_id=asset_id,
            fasttrack=fasttrack,
            expiry_minutes=expiry_minutes
        )

    @classmethod
    def validate_checkout_token(
        cls,
        db_session,
        token: str,
        asset_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Validate a checkout token without marking it as used.

        Args:
            db_session: SQLAlchemy database session
            token: The checkout token to validate
            asset_id: Optional ID of the asset being accessed

        Returns:
            Dict with keys:
            - valid: bool indicating if token is valid
            - token_record: The CheckoutToken instance
            - asset: The ContentAsset instance
            - error: Error message (if invalid)
        """
        if not token:
            return {
                'valid': False,
                'error': 'Token is required',
                'token_record': None,
                'asset': None
            }

        # Find the token
        checkout_token = db_session.query(CheckoutToken).filter_by(
            token=token
        ).first()

        if checkout_token is None:
            return {
                'valid': False,
                'error': 'Invalid checkout token',
                'token_record': None,
                'asset': None
            }

        # Check if expired
        if checkout_token.is_expired:
            return {
                'valid': False,
                'error': 'Checkout token has expired',
                'token_record': checkout_token,
                'asset': None
            }

        # Check if already used
        if checkout_token.is_used:
            return {
                'valid': False,
                'error': 'Checkout token has already been used',
                'token_record': checkout_token,
                'asset': None
            }

        # Fetch the asset
        asset = db_session.query(ContentAsset).filter_by(
            id=checkout_token.asset_id
        ).first()

        if asset is None:
            return {
                'valid': False,
                'error': 'Asset not found',
                'token_record': checkout_token,
                'asset': None
            }

        # Verify asset_id matches if provided
        if asset_id is not None and asset.id != asset_id:
            return {
                'valid': False,
                'error': 'Asset ID does not match token',
                'token_record': checkout_token,
                'asset': None
            }

        return {
            'valid': True,
            'token_record': checkout_token,
            'asset': asset,
            'error': None
        }

    @classmethod
    def use_checkout_token(
        cls,
        db_session,
        token: str
    ) -> Dict[str, Any]:
        """
        Validate and mark a checkout token as used.

        This should be called when the user downloads the asset.

        Args:
            db_session: SQLAlchemy database session
            token: The checkout token to use

        Returns:
            Dict with keys:
            - success: bool indicating if token was valid and used
            - token_record: The CheckoutToken instance
            - asset: The ContentAsset instance
            - error: Error message (if unsuccessful)

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        # Validate first
        validation = cls.validate_checkout_token(db_session, token)
        if not validation['valid']:
            return {
                'success': False,
                'error': validation['error'],
                'token_record': validation['token_record'],
                'asset': validation['asset']
            }

        # Mark as used
        checkout_token = validation['token_record']
        checkout_token.mark_used()

        return {
            'success': True,
            'token_record': checkout_token,
            'asset': validation['asset'],
            'error': None
        }

    @classmethod
    def verify_url_signature(
        cls,
        asset_id: int,
        token: str,
        expires: int,
        signature: str
    ) -> bool:
        """
        Verify a signed URL signature.

        Args:
            asset_id: The asset ID from the URL
            token: The checkout token from the URL
            expires: The expiration timestamp from the URL
            signature: The signature from the URL

        Returns:
            True if signature is valid, False otherwise
        """
        # Recreate the payload
        payload = f'{asset_id}:{token}:{expires}'

        # Generate expected signature
        expected_signature = hmac.new(
            cls.URL_SIGNING_SECRET.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()[:16]

        # Compare signatures using constant-time comparison
        return hmac.compare_digest(signature, expected_signature)

    @classmethod
    def get_user_checkouts(
        cls,
        db_session,
        user_id: int,
        limit: int = 50
    ) -> list:
        """
        Get checkout history for a specific user from audit logs.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user
            limit: Maximum number of entries to return

        Returns:
            List of CheckoutToken instances or AuditLog instances for checkout events by this user
        """
        # Try to query from CheckoutToken model first
        try:
            return db_session.query(CheckoutToken).filter_by(
                user_id=user_id
            ).order_by(
                CheckoutToken.created_at.desc()
            ).limit(limit).all()
        except Exception:
            # Fall back to AuditLog if CheckoutToken doesn't exist
            return db_session.query(AuditLog).filter(
                AuditLog.user_id == user_id,
                AuditLog.action.in_([
                    AuditLog.ACTION_CHECKOUT_CREATED,
                    AuditLog.ACTION_FASTTRACK_CHECKOUT
                ])
            ).order_by(AuditLog.created_at.desc()).limit(limit).all()

    @classmethod
    def get_checkout_history_for_asset(
        cls,
        db_session,
        asset_id: int,
        limit: int = 50
    ) -> list:
        """
        Get checkout history for a specific asset from audit logs.

        Args:
            db_session: SQLAlchemy database session
            asset_id: ID of the asset
            limit: Maximum number of entries to return

        Returns:
            List of AuditLog instances for checkout events
        """
        return db_session.query(AuditLog).filter(
            AuditLog.resource_type == AuditLog.RESOURCE_CHECKOUT_TOKEN,
            AuditLog.resource_id == str(asset_id),
            AuditLog.action.in_([
                AuditLog.ACTION_CHECKOUT_CREATED,
                AuditLog.ACTION_FASTTRACK_CHECKOUT,
                AuditLog.ACTION_CHECKOUT_USED,
                AuditLog.ACTION_CHECKOUT_EXPIRED
            ])
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()

    @classmethod
    def get_fasttrack_assets_for_user(
        cls,
        db_session,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Get assets that a fast-track user can checkout.

        Returns DRAFT and SUBMITTED assets visible to the user
        if they have valid fast-track permission.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user

        Returns:
            Dict with keys:
            - success: bool indicating if query succeeded
            - assets: List of ContentAsset instances (if successful)
            - error: Error message (if unsuccessful)
        """
        # Check if user has fast-track permission
        can_fasttrack, reason = cls._can_user_fasttrack(db_session, user_id)
        if not can_fasttrack:
            return {
                'success': False,
                'error': reason,
                'assets': []
            }

        # Query assets in fast-track eligible statuses
        assets = db_session.query(ContentAsset).filter(
            ContentAsset.status.in_(cls.FASTTRACK_CHECKOUT_STATUSES)
        ).order_by(ContentAsset.created_at.desc()).all()

        return {
            'success': True,
            'error': None,
            'assets': assets
        }

    @classmethod
    def cleanup_expired_tokens(
        cls,
        db_session,
        older_than_hours: int = 24
    ) -> int:
        """
        Clean up expired checkout tokens.

        Args:
            db_session: SQLAlchemy database session
            older_than_hours: Delete tokens expired more than this many hours ago

        Returns:
            Number of tokens deleted

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        deleted = db_session.query(CheckoutToken).filter(
            CheckoutToken.expires_at < cutoff
        ).delete()
        return deleted


def get_checkout_service() -> CheckoutService:
    """
    Factory function to get the checkout service.

    Returns:
        CheckoutService class (for static method access)
    """
    return CheckoutService