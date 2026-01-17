"""
User Model for Content Catalog Service.

Represents a user with role-based access and hierarchical approval workflows.
Includes security features for authentication, account lockout, and 2FA support.
"""

from datetime import datetime, timezone

from content_catalog.models import db


class User(db.Model):
    """
    SQLAlchemy model representing a user in the Content Catalog system.

    Users have a 6-tier role hierarchy with approval chains:
    - Super Admin: Can manage everything, approve Admins
    - Admin: Can manage users, approve Content Managers/Partners/Advertisers
    - Content Manager: Can manage content, approve content assets
    - Partner: Can upload content, invite Advertisers
    - Advertiser: Can upload content for their campaigns
    - Viewer: Read-only access

    Status Values:
        - 'pending': Awaiting approval after registration
        - 'approved': Approved but may need additional setup
        - 'active': Fully active user
        - 'rejected': Rejected during approval process
        - 'suspended': Temporarily suspended
        - 'deactivated': Permanently deactivated

    Security Features:
        - Password hashing with bcrypt
        - Account lockout after failed login attempts
        - Optional two-factor authentication
        - Session tracking and management

    Attributes:
        id: Unique integer identifier
        email: Unique email address for login
        password_hash: Bcrypt hashed password
        name: User's display name
        phone: Optional phone number
        role: User's role in the hierarchy
        organization_id: Foreign key to organization
        status: Current user status
        invited_by: User ID who sent the invitation
        approved_by: User ID who approved this user
        approved_at: Timestamp when user was approved
        rejection_reason: Reason for rejection if rejected
        failed_login_attempts: Count of consecutive failed logins
        locked_until: Timestamp until which account is locked
        password_changed_at: Last password change timestamp
        two_factor_enabled: Whether 2FA is enabled
        two_factor_secret: Secret key for TOTP 2FA
        zoho_contact_id: External reference to ZOHO CRM contact
        last_login: Timestamp of last successful login
        created_at: Timestamp when user was created
    """

    __tablename__ = 'users'

    # Valid roles in hierarchical order (highest to lowest privilege)
    ROLE_SUPER_ADMIN = 'super_admin'
    ROLE_ADMIN = 'admin'
    ROLE_CONTENT_MANAGER = 'content_manager'
    ROLE_PARTNER = 'partner'
    ROLE_ADVERTISER = 'advertiser'
    ROLE_VIEWER = 'viewer'

    VALID_ROLES = [
        ROLE_SUPER_ADMIN,
        ROLE_ADMIN,
        ROLE_CONTENT_MANAGER,
        ROLE_PARTNER,
        ROLE_ADVERTISER,
        ROLE_VIEWER
    ]

    # Valid status values
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_ACTIVE = 'active'
    STATUS_REJECTED = 'rejected'
    STATUS_SUSPENDED = 'suspended'
    STATUS_DEACTIVATED = 'deactivated'

    VALID_STATUSES = [
        STATUS_PENDING,
        STATUS_APPROVED,
        STATUS_ACTIVE,
        STATUS_REJECTED,
        STATUS_SUSPENDED,
        STATUS_DEACTIVATED
    ]

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Authentication fields
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Profile fields
    name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(50), nullable=True)

    # Role and organization
    role = db.Column(db.String(50), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True, index=True)

    # Status and approval workflow
    status = db.Column(db.String(50), default=STATUS_PENDING, nullable=False)
    invited_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)

    # Security fields
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
    password_changed_at = db.Column(db.DateTime, nullable=True)

    # Two-factor authentication fields
    two_factor_enabled = db.Column(db.Boolean, default=False, nullable=False)
    two_factor_secret = db.Column(db.String(255), nullable=True)

    # External integration
    zoho_contact_id = db.Column(db.String(100), nullable=True)

    # Activity tracking
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    organization = db.relationship(
        'Organization',
        foreign_keys=[organization_id],
        backref=db.backref('users', lazy='dynamic')
    )
    inviter = db.relationship(
        'User',
        foreign_keys=[invited_by],
        remote_side=[id],
        backref=db.backref('invited_users', lazy='dynamic')
    )
    approver = db.relationship(
        'User',
        foreign_keys=[approved_by],
        remote_side=[id],
        backref=db.backref('approved_users', lazy='dynamic')
    )

    def to_dict(self):
        """
        Serialize the user to a dictionary for API responses.

        Note: Sensitive fields (password_hash, two_factor_secret) are excluded.

        Returns:
            Dictionary containing user fields safe for API responses
        """
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'phone': self.phone,
            'role': self.role,
            'organization_id': self.organization_id,
            'status': self.status,
            'invited_by': self.invited_by,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'rejection_reason': self.rejection_reason,
            'two_factor_enabled': self.two_factor_enabled,
            'zoho_contact_id': self.zoho_contact_id,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def is_locked(self):
        """
        Check if the user account is currently locked.

        Returns:
            True if account is locked, False otherwise
        """
        if self.locked_until is None:
            return False
        return datetime.now(timezone.utc) < self.locked_until

    def can_approve_role(self, target_role):
        """
        Check if this user can approve users with the given role.

        Approval hierarchy:
        - Super Admin can approve: Admin, Content Manager, Partner, Advertiser, Viewer
        - Admin can approve: Content Manager, Partner, Advertiser, Viewer
        - Content Manager can approve: Partner, Advertiser, Viewer
        - Partner can approve: Advertiser, Viewer
        - Advertiser can approve: Viewer
        - Viewer cannot approve anyone

        Args:
            target_role: The role of the user to be approved

        Returns:
            True if this user can approve the target role, False otherwise
        """
        if self.role not in self.VALID_ROLES or target_role not in self.VALID_ROLES:
            return False

        my_index = self.VALID_ROLES.index(self.role)
        target_index = self.VALID_ROLES.index(target_role)

        # Can only approve roles with higher index (lower privilege)
        return my_index < target_index

    def __repr__(self):
        """String representation for debugging."""
        return f'<User {self.email}>'


class UserInvitation(db.Model):
    """
    SQLAlchemy model representing a user invitation.

    Invitations are used for token-based user registration. When a user
    is invited, an invitation record is created with a unique token that
    is sent via email. The invitee uses this token to complete registration.

    Status Values:
        - 'pending': Invitation sent, awaiting acceptance
        - 'accepted': Invitation accepted, user registered
        - 'expired': Invitation expired before acceptance
        - 'revoked': Invitation manually revoked by inviter

    Attributes:
        id: Unique integer identifier
        email: Email address the invitation was sent to
        role: Role the user will have upon registration
        organization_id: Organization the user will belong to
        invited_by: User ID who sent the invitation
        token: Unique token for invitation link
        status: Current invitation status
        expires_at: Timestamp when invitation expires
        accepted_at: Timestamp when invitation was accepted
        created_at: Timestamp when invitation was created
    """

    __tablename__ = 'user_invitations'

    # Valid status values
    STATUS_PENDING = 'pending'
    STATUS_ACCEPTED = 'accepted'
    STATUS_EXPIRED = 'expired'
    STATUS_REVOKED = 'revoked'

    VALID_STATUSES = [
        STATUS_PENDING,
        STATUS_ACCEPTED,
        STATUS_EXPIRED,
        STATUS_REVOKED
    ]

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Invitation target
    email = db.Column(db.String(255), nullable=False, index=True)
    role = db.Column(db.String(50), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True, index=True)

    # Invitation source
    invited_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Token and status
    token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    status = db.Column(db.String(50), default=STATUS_PENDING, nullable=False)

    # Timestamps
    expires_at = db.Column(db.DateTime, nullable=False)
    accepted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    organization = db.relationship(
        'Organization',
        foreign_keys=[organization_id],
        backref=db.backref('invitations', lazy='dynamic')
    )
    inviter = db.relationship(
        'User',
        foreign_keys=[invited_by],
        backref=db.backref('sent_invitations', lazy='dynamic')
    )

    def to_dict(self):
        """
        Serialize the invitation to a dictionary for API responses.

        Note: Token is excluded from serialization for security.

        Returns:
            Dictionary containing invitation fields safe for API responses
        """
        return {
            'id': self.id,
            'email': self.email,
            'role': self.role,
            'organization_id': self.organization_id,
            'invited_by': self.invited_by,
            'status': self.status,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'accepted_at': self.accepted_at.isoformat() if self.accepted_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def is_expired(self):
        """
        Check if the invitation has expired.

        Returns:
            True if invitation is expired, False otherwise
        """
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self):
        """
        Check if the invitation is still valid (pending and not expired).

        Returns:
            True if invitation can still be accepted, False otherwise
        """
        return self.status == self.STATUS_PENDING and not self.is_expired()

    def __repr__(self):
        """String representation for debugging."""
        return f'<UserInvitation {self.email}>'


class UserApprovalRequest(db.Model):
    """
    SQLAlchemy model representing a user approval request.

    Tracks the approval workflow for users requesting role changes or
    initial approval. Requests are assigned to approvers who can approve
    or reject based on the role hierarchy.

    Status Values:
        - 'pending': Awaiting review
        - 'approved': Request approved
        - 'rejected': Request rejected

    Attributes:
        id: Unique integer identifier
        user_id: Foreign key to the user being approved
        requested_role: The role being requested
        current_status: The user's current status at time of request
        requested_by: User ID who initiated the request (may differ from user_id)
        assigned_to: User ID of the approver assigned to review
        status: Current request status
        notes: Notes or feedback about the request
        created_at: Timestamp when request was created
        resolved_at: Timestamp when request was resolved (approved/rejected)
    """

    __tablename__ = 'user_approval_requests'

    # Valid status values
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    VALID_STATUSES = [
        STATUS_PENDING,
        STATUS_APPROVED,
        STATUS_REJECTED
    ]

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # User being approved
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )

    # Request details
    requested_role = db.Column(db.String(50), nullable=False)
    current_status = db.Column(db.String(50), nullable=True)

    # Request source and assignment
    requested_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    assigned_to = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )

    # Status and notes
    status = db.Column(db.String(50), default=STATUS_PENDING, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    user = db.relationship(
        'User',
        foreign_keys=[user_id],
        backref=db.backref('approval_requests', lazy='dynamic', cascade='all, delete-orphan')
    )
    requester = db.relationship(
        'User',
        foreign_keys=[requested_by],
        backref=db.backref('initiated_approval_requests', lazy='dynamic')
    )
    assignee = db.relationship(
        'User',
        foreign_keys=[assigned_to],
        backref=db.backref('assigned_approval_requests', lazy='dynamic')
    )

    def to_dict(self):
        """
        Serialize the approval request to a dictionary for API responses.

        Returns:
            Dictionary containing approval request fields
        """
        return {
            'id': self.id,
            'user_id': self.user_id,
            'requested_role': self.requested_role,
            'current_status': self.current_status,
            'requested_by': self.requested_by,
            'assigned_to': self.assigned_to,
            'status': self.status,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None
        }

    def to_dict_with_relations(self):
        """
        Serialize the approval request with related user info.

        Returns:
            Dictionary containing approval request fields with nested user data
        """
        result = self.to_dict()
        result['user'] = self.user.to_dict() if self.user else None
        result['requester'] = self.requester.to_dict() if self.requester else None
        result['assignee'] = self.assignee.to_dict() if self.assignee else None
        return result

    def is_pending(self):
        """
        Check if the request is still pending.

        Returns:
            True if request is pending, False otherwise
        """
        return self.status == self.STATUS_PENDING

    @classmethod
    def get_pending_for_user(cls, user_id):
        """
        Get all pending approval requests for a specific user.

        Args:
            user_id: The user ID to filter by

        Returns:
            list: List of pending UserApprovalRequest instances
        """
        return cls.query.filter_by(
            user_id=user_id,
            status=cls.STATUS_PENDING
        ).all()

    @classmethod
    def get_pending_for_assignee(cls, assignee_id):
        """
        Get all pending approval requests assigned to a specific user.

        Args:
            assignee_id: The assignee user ID to filter by

        Returns:
            list: List of pending UserApprovalRequest instances ordered by creation date
        """
        return cls.query.filter_by(
            assigned_to=assignee_id,
            status=cls.STATUS_PENDING
        ).order_by(cls.created_at.asc()).all()

    def __repr__(self):
        """String representation for debugging."""
        return f'<UserApprovalRequest user={self.user_id} role={self.requested_role} status={self.status}>'


class AdminSession(db.Model):
    """
    SQLAlchemy model representing an admin session.

    Tracks active sessions for authenticated users including session tokens,
    IP addresses, and user agents for security monitoring and session management.

    Status Values:
        - 'active': Session is currently active
        - 'expired': Session has expired
        - 'revoked': Session was manually revoked (logout)

    Attributes:
        id: Unique integer identifier
        user_id: Foreign key to the user who owns this session
        token: Unique session token for authentication
        ip_address: IP address from which the session was created
        user_agent: Browser/client user agent string
        status: Current session status
        expires_at: Timestamp when session expires
        created_at: Timestamp when session was created
        last_activity: Timestamp of last activity in this session
    """

    __tablename__ = 'admin_sessions'

    # Valid status values
    STATUS_ACTIVE = 'active'
    STATUS_EXPIRED = 'expired'
    STATUS_REVOKED = 'revoked'

    VALID_STATUSES = [
        STATUS_ACTIVE,
        STATUS_EXPIRED,
        STATUS_REVOKED
    ]

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Session ownership
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )

    # Session token
    token = db.Column(db.String(255), unique=True, nullable=False, index=True)

    # Client information
    ip_address = db.Column(db.String(45), nullable=True)  # IPv6 can be up to 45 chars
    user_agent = db.Column(db.String(500), nullable=True)

    # Status and expiration
    status = db.Column(db.String(50), default=STATUS_ACTIVE, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_activity = db.Column(db.DateTime, nullable=True)

    # Relationships
    user = db.relationship(
        'User',
        foreign_keys=[user_id],
        backref=db.backref('sessions', lazy='dynamic', cascade='all, delete-orphan')
    )

    def to_dict(self):
        """
        Serialize the session to a dictionary for API responses.

        Note: Token is excluded from serialization for security.

        Returns:
            Dictionary containing session fields safe for API responses
        """
        return {
            'id': self.id,
            'user_id': self.user_id,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'status': self.status,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_activity': self.last_activity.isoformat() if self.last_activity else None
        }

    def is_expired(self):
        """
        Check if the session has expired.

        Returns:
            True if session is expired, False otherwise
        """
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self):
        """
        Check if the session is still valid (active and not expired).

        Returns:
            True if session can still be used, False otherwise
        """
        return self.status == self.STATUS_ACTIVE and not self.is_expired()

    @classmethod
    def get_active_sessions_for_user(cls, user_id):
        """
        Get all active sessions for a specific user.

        Args:
            user_id: The user ID to filter by

        Returns:
            list: List of active AdminSession instances
        """
        return cls.query.filter_by(
            user_id=user_id,
            status=cls.STATUS_ACTIVE
        ).all()

    def __repr__(self):
        """String representation for debugging."""
        return f'<AdminSession user={self.user_id} status={self.status}>'
