"""
Checkout and Approval Task Models for Content Catalog Service.

CheckoutToken: Short-lived tokens for downloading approved assets
ApprovalTask: Tracks pending approval requests with magic links
"""

from datetime import datetime, timezone, timedelta
import uuid
import secrets

from content_catalog.models import db


class CheckoutToken(db.Model):
    """
    SQLAlchemy model for asset checkout tokens.

    Checkout tokens provide time-limited access to download assets.
    They support both regular checkout (approved assets only) and
    fast-track checkout (any asset for privileged users).

    Token Lifecycle:
    1. User requests checkout for an asset
    2. System generates token with signed download URL
    3. User downloads asset within expiry window (default 10 min)
    4. Token is marked as used

    Attributes:
        id: UUID primary key
        asset_id: Foreign key to content asset
        user_id: Foreign key to user who requested checkout
        token: Random token string for URL
        download_url: Signed URL for file download
        is_fasttrack: Whether this is a fast-track checkout
        expires_at: Token expiration timestamp
        used_at: Timestamp when token was used
        created_at: Timestamp when token was created
    """

    __tablename__ = 'checkout_tokens'

    # Default expiry in minutes
    DEFAULT_EXPIRY_MINUTES = 10

    # Primary key (UUID)
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Asset reference (using integer ID from ContentAsset)
    asset_id = db.Column(db.Integer, db.ForeignKey('content_assets.id'), nullable=False, index=True)

    # User who checked out
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Token for URL
    token = db.Column(db.String(64), unique=True, nullable=False, index=True,
                      default=lambda: secrets.token_urlsafe(32))

    # Download URL (signed)
    download_url = db.Column(db.String(2000), nullable=True)

    # Fast-track flag
    is_fasttrack = db.Column(db.Boolean, default=False, nullable=False)

    # Expiry and usage
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    asset = db.relationship('ContentAsset', backref=db.backref('checkout_tokens', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('checkout_tokens', lazy='dynamic'))

    def __init__(self, **kwargs):
        """Initialize with default expiry if not provided."""
        if 'expires_at' not in kwargs:
            kwargs['expires_at'] = datetime.now(timezone.utc) + timedelta(minutes=self.DEFAULT_EXPIRY_MINUTES)
        super().__init__(**kwargs)

    @property
    def is_expired(self):
        """Check if token has expired."""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_used(self):
        """Check if token has been used."""
        return self.used_at is not None

    @property
    def is_valid(self):
        """Check if token is still valid (not expired and not used)."""
        return not self.is_expired and not self.is_used

    def mark_used(self):
        """Mark token as used."""
        self.used_at = datetime.now(timezone.utc)

    def to_dict(self):
        """Serialize to dictionary."""
        return {
            'id': self.id,
            'asset_id': self.asset_id,
            'user_id': self.user_id,
            'token': self.token,
            'download_url': self.download_url,
            'is_fasttrack': self.is_fasttrack,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'used_at': self.used_at.isoformat() if self.used_at else None,
            'is_valid': self.is_valid,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ApprovalTask(db.Model):
    """
    SQLAlchemy model for asset approval tasks.

    Approval tasks track pending approvals and support magic link
    review (email-based approval without login).

    Task Lifecycle:
    1. Asset submitted for approval
    2. ApprovalTask created with magic link token
    3. Email sent to intended approver
    4. Approver clicks link and reviews
    5. Task completed (approved/rejected)

    Attributes:
        id: UUID primary key
        tenant_id: Foreign key to tenant
        asset_id: Foreign key to content asset
        status: Task status (pending/completed/expired)
        intended_approver_id: User expected to approve
        review_token: Magic link token
        token_expires_at: Token expiration
        token_used: Whether token has been used
        completed_at: When task was completed
        result: Approval result (approved/rejected)
        rejection_reason: Reason if rejected
        created_at: Timestamp when task was created
    """

    __tablename__ = 'approval_tasks'

    # Status constants
    STATUS_PENDING = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_EXPIRED = 'expired'

    VALID_STATUSES = [STATUS_PENDING, STATUS_COMPLETED, STATUS_EXPIRED]

    # Result constants
    RESULT_APPROVED = 'approved'
    RESULT_REJECTED = 'rejected'

    # Default token expiry in minutes
    DEFAULT_TOKEN_EXPIRY_MINUTES = 30

    # Primary key (UUID)
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Tenant
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)

    # Asset reference
    asset_id = db.Column(db.Integer, db.ForeignKey('content_assets.id'), nullable=False, index=True)

    # Task status
    status = db.Column(db.String(20), default=STATUS_PENDING, nullable=False, index=True)

    # Intended approver
    intended_approver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    # Magic link token
    review_token = db.Column(db.String(64), unique=True, nullable=False, index=True,
                             default=lambda: secrets.token_urlsafe(32))
    token_expires_at = db.Column(db.DateTime, nullable=False)
    token_used = db.Column(db.Boolean, default=False, nullable=False)

    # Completion
    completed_at = db.Column(db.DateTime, nullable=True)
    result = db.Column(db.String(20), nullable=True)  # approved/rejected
    rejection_reason = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    asset = db.relationship('ContentAsset', backref=db.backref('approval_tasks', lazy='dynamic'))
    intended_approver = db.relationship('User', backref=db.backref('approval_tasks', lazy='dynamic'))

    def __init__(self, **kwargs):
        """Initialize with default token expiry if not provided."""
        if 'token_expires_at' not in kwargs:
            kwargs['token_expires_at'] = datetime.now(timezone.utc) + timedelta(
                minutes=self.DEFAULT_TOKEN_EXPIRY_MINUTES
            )
        super().__init__(**kwargs)

    @property
    def is_token_expired(self):
        """Check if magic link token has expired."""
        return datetime.now(timezone.utc) > self.token_expires_at

    @property
    def is_token_valid(self):
        """Check if magic link token is still valid."""
        return not self.is_token_expired and not self.token_used

    def complete(self, result: str, rejection_reason: str = None):
        """
        Mark task as completed.

        Args:
            result: 'approved' or 'rejected'
            rejection_reason: Reason for rejection (if rejected)
        """
        self.status = self.STATUS_COMPLETED
        self.completed_at = datetime.now(timezone.utc)
        self.result = result
        self.rejection_reason = rejection_reason
        self.token_used = True

    def expire(self):
        """Mark task as expired."""
        self.status = self.STATUS_EXPIRED

    def to_dict(self):
        """Serialize to dictionary."""
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'asset_id': self.asset_id,
            'status': self.status,
            'intended_approver_id': self.intended_approver_id,
            'token_expires_at': self.token_expires_at.isoformat() if self.token_expires_at else None,
            'is_token_valid': self.is_token_valid,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'result': self.result,
            'rejection_reason': self.rejection_reason,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
