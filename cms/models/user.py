"""
User Model for CMS Service.

Represents a user account in the system with role-based access control,
password management, and status workflow capabilities.

Roles (hierarchical):
- super_admin: Full system access, can manage all users including admins
- admin: Can manage project_managers, content_managers and viewers within their network
- project_manager: Can manage content_managers and viewers within assigned networks
- content_manager: Can manage content and playlists
- viewer: Read-only access

Status workflow:
- pending: Newly invited, awaiting approval
- rejected: Invitation rejected
- active: Normal active account
- suspended: Temporarily disabled (can be reactivated)
- deactivated: Permanently disabled (cannot be reactivated)
"""

from datetime import datetime, timezone
import uuid

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from cms.models import db


# Role hierarchy - higher number means more privileges
ROLE_HIERARCHY = {
    'super_admin': 5,
    'admin': 4,
    'project_manager': 3,
    'content_manager': 2,
    'viewer': 1
}

# Valid statuses for user accounts
USER_STATUSES = ['pending', 'rejected', 'active', 'suspended', 'deactivated']


class User(UserMixin, db.Model):
    """
    SQLAlchemy model representing a user account.

    Users can log in with email/password and perform actions based on their role.
    The system enforces a strict role hierarchy where users can only manage
    other users with lower-level roles.

    Attributes:
        id: Unique UUID identifier (internal database ID)
        email: Unique email address used for login
        password_hash: Hashed password (never store plaintext)
        name: User's display name
        phone: Optional phone number
        role: User's role (super_admin, admin, content_manager, viewer)
        network_id: Foreign key to network (NULL for super_admin = all networks)
        status: Account status (pending, rejected, active, suspended, deactivated)
        invited_by: UUID of user who sent the invitation
        approved_by: UUID of user who approved the account
        approved_at: Timestamp of approval
        rejection_reason: Reason for rejection (if rejected)
        suspended_at: Timestamp when suspended
        suspended_by: UUID of user who suspended
        suspended_reason: Reason for suspension
        deactivated_at: Timestamp when deactivated
        deactivated_by: UUID of user who deactivated
        deactivated_reason: Reason for deactivation
        failed_login_attempts: Counter for lockout mechanism
        locked_until: Timestamp until which account is locked
        password_changed_at: Timestamp of last password change
        must_change_password: Flag for forced password change on login
        last_login: Timestamp of last successful login
        last_login_ip: IP address of last login
        created_at: Timestamp when the user was created
        updated_at: Timestamp of last update
    """

    __tablename__ = 'users'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    role = db.Column(db.String(20), nullable=False)
    network_id = db.Column(db.String(36), db.ForeignKey('networks.id'), nullable=True, index=True)
    # Multiple network access - comma-separated list of network IDs
    # NULL or empty = all networks (for super_admin), otherwise restricted to listed networks
    network_ids = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')

    # Invitation and approval tracking
    invited_by = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True)
    approved_by = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)

    # Suspension tracking
    suspended_at = db.Column(db.DateTime, nullable=True)
    suspended_by = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True)
    suspended_reason = db.Column(db.Text, nullable=True)

    # Deactivation tracking
    deactivated_at = db.Column(db.DateTime, nullable=True)
    deactivated_by = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True)
    deactivated_reason = db.Column(db.Text, nullable=True)

    # Security fields
    failed_login_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    password_changed_at = db.Column(db.DateTime, nullable=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)

    # Login tracking
    last_login = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(45), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    network = db.relationship('Network', backref=db.backref('users', lazy='dynamic'))

    # Self-referential relationships for user management tracking
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
    suspender = db.relationship(
        'User',
        foreign_keys=[suspended_by],
        remote_side=[id],
        backref=db.backref('suspended_users', lazy='dynamic')
    )
    deactivator = db.relationship(
        'User',
        foreign_keys=[deactivated_by],
        remote_side=[id],
        backref=db.backref('deactivated_users', lazy='dynamic')
    )

    def set_password(self, password):
        """
        Hash and store the password.

        Uses werkzeug's generate_password_hash for secure hashing.

        Args:
            password: Plain text password to hash and store
        """
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")
        self.password_changed_at = datetime.now(timezone.utc)

    def check_password(self, password):
        """
        Verify a password against the stored hash.

        Args:
            password: Plain text password to verify

        Returns:
            True if password matches, False otherwise
        """
        return check_password_hash(self.password_hash, password)

    def get_role_level(self):
        """
        Get the numeric level of this user's role.

        Returns:
            Integer representing role privilege level (higher = more privileges)
        """
        return ROLE_HIERARCHY.get(self.role, 0)

    def can_manage_role(self, target_role):
        """
        Check if this user can manage users with the target role.

        Users can only manage users with strictly lower role levels.
        Admins cannot manage other admins (only super_admin can).

        Args:
            target_role: The role to check management permission for

        Returns:
            True if this user can manage users with target_role
        """
        my_level = self.get_role_level()
        target_level = ROLE_HIERARCHY.get(target_role, 0)
        return my_level > target_level

    def can_manage_user(self, target_user):
        """
        Check if this user can manage the target user.

        Enforces role hierarchy and prevents self-management for
        destructive actions.

        Args:
            target_user: The User object to check management permission for

        Returns:
            True if this user can manage the target user
        """
        # Cannot manage yourself
        if self.id == target_user.id:
            return False

        return self.can_manage_role(target_user.role)

    def is_locked(self):
        """
        Check if the account is currently locked due to failed login attempts.

        Returns:
            True if account is locked, False otherwise
        """
        if self.locked_until is None:
            return False
        return datetime.now(timezone.utc) < self.locked_until

    def is_active(self):
        """
        Check if the account is in an active state and can log in.

        Returns:
            True if account status is 'active', False otherwise
        """
        return self.status == 'active'

    def can_login(self):
        """
        Check if the user is eligible to attempt login.

        Returns:
            True if user can attempt login, False otherwise
        """
        return self.is_active() and not self.is_locked()

    def record_failed_login(self, lockout_threshold=5, lockout_minutes=15):
        """
        Record a failed login attempt and lock account if threshold exceeded.

        Args:
            lockout_threshold: Number of failures before lockout (default: 5)
            lockout_minutes: Duration of lockout in minutes (default: 15)
        """
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= lockout_threshold:
            from datetime import timedelta
            self.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)

    def record_successful_login(self, ip_address=None):
        """
        Record a successful login and reset failure counters.

        Args:
            ip_address: IP address of the login request
        """
        self.failed_login_attempts = 0
        self.locked_until = None
        self.last_login = datetime.now(timezone.utc)
        if ip_address:
            self.last_login_ip = ip_address

    def get_network_ids_list(self):
        """
        Get list of network IDs this user has access to.

        Returns:
            List of network ID strings, or empty list for all-access
        """
        if not self.network_ids:
            return []
        return [nid.strip() for nid in self.network_ids.split(',') if nid.strip()]

    def set_network_ids_list(self, network_ids):
        """
        Set the list of network IDs this user has access to.

        Args:
            network_ids: List of network ID strings, or empty/None for all-access
        """
        if not network_ids:
            self.network_ids = None
        else:
            self.network_ids = ','.join(network_ids)

    def has_network_access(self, network_id):
        """
        Check if user has access to a specific network.

        Super admins have access to all networks.
        Users with no network_ids set have access to all networks.
        Otherwise, user must have the network_id in their list.

        Args:
            network_id: Network ID to check access for

        Returns:
            True if user has access to the network
        """
        # Super admins have access to everything
        if self.role == 'super_admin':
            return True

        # No restrictions = access to all
        if not self.network_ids:
            return True

        # Check if network is in user's allowed list
        return network_id in self.get_network_ids_list()

    def has_all_network_access(self):
        """
        Check if user has unrestricted network access.

        Returns:
            True if user can access all networks
        """
        return self.role == 'super_admin' or not self.network_ids

    def to_dict(self, include_sensitive=False):
        """
        Serialize the user to a dictionary for API responses.

        Args:
            include_sensitive: If True, include security-related fields

        Returns:
            Dictionary containing user fields
        """
        result = {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'phone': self.phone,
            'role': self.role,
            'network_id': self.network_id,
            'network_ids': self.get_network_ids_list(),
            'has_all_network_access': self.has_all_network_access(),
            'status': self.status,
            'invited_by': self.invited_by,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'rejection_reason': self.rejection_reason,
            'suspended_at': self.suspended_at.isoformat() if self.suspended_at else None,
            'suspended_by': self.suspended_by,
            'suspended_reason': self.suspended_reason,
            'deactivated_at': self.deactivated_at.isoformat() if self.deactivated_at else None,
            'deactivated_by': self.deactivated_by,
            'deactivated_reason': self.deactivated_reason,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_sensitive:
            result.update({
                'failed_login_attempts': self.failed_login_attempts,
                'locked_until': self.locked_until.isoformat() if self.locked_until else None,
                'password_changed_at': self.password_changed_at.isoformat() if self.password_changed_at else None,
                'must_change_password': self.must_change_password,
                'last_login_ip': self.last_login_ip,
            })

        return result

    def __repr__(self):
        """String representation for debugging."""
        return f'<User {self.email} ({self.role})>'
