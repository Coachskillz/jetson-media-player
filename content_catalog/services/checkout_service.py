"""
Checkout Service for Content Catalog.

Provides asset checkout functionality with signed download URLs.
Supports both regular checkout (approved assets only) and
fast-track checkout (any asset for privileged users).

Key features:
- Generate time-limited checkout tokens
- Create signed download URLs
- Fast-track support for privileged users
- Visibility-based access control
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
import hashlib
import hmac
import os

from content_catalog.models import db, ContentAsset, User, CheckoutToken
from content_catalog.services.visibility_service import VisibilityService


class CheckoutService:
    """
    Asset checkout service for the Content Catalog.

    This service handles:
    1. Validating checkout permissions
    2. Creating checkout tokens with signed URLs
    3. Fast-track checkout for privileged users
    4. Token validation and usage tracking

    Usage:
        # Regular checkout (approved assets only)
        result = CheckoutService.checkout_asset(
            db_session=db.session,
            user_id=user.id,
            asset_id=asset.id
        )

        # Fast-track checkout (any visible asset)
        result = CheckoutService.checkout_asset(
            db_session=db.session,
            user_id=user.id,
            asset_id=asset.id,
            fasttrack=True
        )

        # Validate and use a checkout token
        result = CheckoutService.use_checkout_token(
            db_session=db.session,
            token='abc123...'
        )
    """

    # Roles that can use fast-track checkout
    FASTTRACK_ROLES = [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER
    ]

    # Default token expiry in minutes
    DEFAULT_EXPIRY_MINUTES = 10

    # Secret key for URL signing (should be from config in production)
    URL_SIGNING_SECRET = os.environ.get('CHECKOUT_URL_SECRET', 'default-dev-secret')

    @classmethod
    def can_checkout_asset(
        cls,
        db_session,
        user_id: int,
        asset_id: int,
        fasttrack: bool = False
    ) -> tuple:
        """
        Check if a user can checkout a specific asset.

        Validates:
        1. User exists and is active
        2. Asset exists
        3. User has visibility to the asset
        4. Asset is approved (unless fasttrack)
        5. User has fasttrack permission (if fasttrack requested)

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user attempting checkout
            asset_id: ID of the asset to checkout
            fasttrack: Whether this is a fast-track checkout

        Returns:
            Tuple of (can_checkout: bool, reason: str)
        """
        # Fetch the user
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return False, 'User not found'

        # Check user's account status
        if user.status not in [User.STATUS_ACTIVE, User.STATUS_APPROVED]:
            return False, 'User account is not active'

        # Fetch the asset
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return False, 'Asset not found'

        # Check visibility
        visibility_service = VisibilityService(user)
        if not visibility_service.can_view_asset(asset):
            return False, 'User does not have access to this asset'

        # For fast-track, check permission
        if fasttrack:
            if user.role not in cls.FASTTRACK_ROLES:
                return False, f'Role "{user.role}" cannot use fast-track checkout'
            # Fast-track allows any visible asset
            return True, 'ok'

        # Regular checkout requires approved status
        if asset.status != ContentAsset.STATUS_APPROVED:
            return False, f'Asset status "{asset.status}" is not available for checkout'

        return True, 'ok'

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
            - error: Error message (if unsuccessful)

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        # Validate checkout is allowed
        can_checkout, reason = cls.can_checkout_asset(
            db_session, user_id, asset_id, fasttrack
        )
        if not can_checkout:
            return {
                'success': False,
                'error': reason,
                'token': None,
                'download_url': None,
                'expires_at': None
            }

        # Fetch the asset
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()

        # Calculate expiry
        minutes = expiry_minutes or cls.DEFAULT_EXPIRY_MINUTES
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)

        # Create checkout token
        checkout_token = CheckoutToken(
            asset_id=asset_id,
            user_id=user_id,
            is_fasttrack=fasttrack,
            expires_at=expires_at
        )
        db_session.add(checkout_token)
        db_session.flush()  # Generate the token string

        # Generate signed URL
        signed_url = cls._generate_signed_url(asset, checkout_token.token, expires_at)
        checkout_token.download_url = signed_url

        return {
            'success': True,
            'token': checkout_token.token,
            'download_url': signed_url,
            'expires_at': expires_at.isoformat(),
            'error': None
        }

    @classmethod
    def validate_checkout_token(
        cls,
        db_session,
        token: str
    ) -> Dict[str, Any]:
        """
        Validate a checkout token without marking it as used.

        Args:
            db_session: SQLAlchemy database session
            token: The checkout token to validate

        Returns:
            Dict with keys:
            - valid: bool indicating if token is valid
            - token_record: The CheckoutToken instance
            - asset: The ContentAsset instance
            - error: Error message (if invalid)
        """
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
    def get_user_checkout_history(
        cls,
        db_session,
        user_id: int,
        limit: int = 50
    ) -> list:
        """
        Get checkout history for a user.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user
            limit: Maximum number of records to return

        Returns:
            List of CheckoutToken instances
        """
        return db_session.query(CheckoutToken).filter_by(
            user_id=user_id
        ).order_by(
            CheckoutToken.created_at.desc()
        ).limit(limit).all()

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
