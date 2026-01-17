"""
User Service for Content Catalog.

Provides user management functionality including CRUD operations,
role and status management, and list filtering capabilities.

Key features:
- User creation with password hashing and role assignment
- User retrieval by ID, email, or various criteria
- User updates with validation and audit integration
- User listing with filtering, pagination, and sorting
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from content_catalog.services.auth_service import AuthService


class UserService:
    """
    User management service for the Content Catalog.

    This service handles:
    1. Creating users with proper password hashing
    2. Retrieving users by various criteria
    3. Updating user information and status
    4. Listing users with filtering and pagination

    Usage:
        # Create a new user
        user = UserService.create_user(
            db_session=db.session,
            email='user@example.com',
            password='secure_password',
            name='John Doe',
            role='partner',
            organization_id=1
        )

        # Get user by ID
        user = UserService.get_user(db.session, user_id=1)

        # Update user
        user = UserService.update_user(
            db.session,
            user_id=1,
            name='Updated Name',
            phone='555-1234'
        )

        # List users with filters
        users, total = UserService.list_users(
            db.session,
            role='partner',
            status='active',
            page=1,
            per_page=20
        )
    """

    # Default pagination settings
    DEFAULT_PAGE = 1
    DEFAULT_PER_PAGE = 20
    MAX_PER_PAGE = 100

    @classmethod
    def create_user(
        cls,
        db_session,
        email: str,
        password: str,
        name: str,
        role: str,
        organization_id: Optional[int] = None,
        phone: Optional[str] = None,
        invited_by: Optional[int] = None,
        status: Optional[str] = None,
        zoho_contact_id: Optional[str] = None
    ):
        """
        Create a new user with the given details.

        Creates a user record with a hashed password. The user starts
        with 'pending' status by default unless explicitly specified.

        Args:
            db_session: SQLAlchemy database session
            email: Unique email address for the user
            password: Plaintext password (will be hashed)
            name: User's display name
            role: User's role (must be a valid role from User.VALID_ROLES)
            organization_id: Optional organization ID the user belongs to
            phone: Optional phone number
            invited_by: Optional user ID of the inviter
            status: Optional initial status (defaults to 'pending')
            zoho_contact_id: Optional ZOHO CRM contact ID

        Returns:
            User: The created user instance

        Raises:
            ValueError: If email already exists, role is invalid,
                        or password exceeds bcrypt's 72-byte limit

        Note:
            The user is added to the database session but not committed.
            The caller is responsible for committing the transaction.
        """
        from content_catalog.models.user import User

        # Validate email uniqueness
        existing_user = db_session.query(User).filter_by(email=email).first()
        if existing_user is not None:
            raise ValueError(f"User with email '{email}' already exists")

        # Validate role
        if role not in User.VALID_ROLES:
            raise ValueError(
                f"Invalid role '{role}'. Must be one of: {', '.join(User.VALID_ROLES)}"
            )

        # Validate status if provided
        if status is not None and status not in User.VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {', '.join(User.VALID_STATUSES)}"
            )

        # Hash the password (this will raise ValueError if password is too long)
        password_hash = AuthService.hash_password(password)

        # Create the user
        user = User(
            email=email,
            password_hash=password_hash,
            name=name,
            role=role,
            organization_id=organization_id,
            phone=phone,
            invited_by=invited_by,
            status=status or User.STATUS_PENDING,
            zoho_contact_id=zoho_contact_id,
            password_changed_at=datetime.now(timezone.utc)
        )

        db_session.add(user)
        return user

    @classmethod
    def get_user(cls, db_session, user_id: int) -> Optional['User']:
        """
        Get a user by their ID.

        Args:
            db_session: SQLAlchemy database session
            user_id: The user's unique identifier

        Returns:
            User: The user instance if found, None otherwise
        """
        from content_catalog.models.user import User

        return db_session.query(User).filter_by(id=user_id).first()

    @classmethod
    def get_user_by_email(cls, db_session, email: str) -> Optional['User']:
        """
        Get a user by their email address.

        Args:
            db_session: SQLAlchemy database session
            email: The user's email address

        Returns:
            User: The user instance if found, None otherwise
        """
        from content_catalog.models.user import User

        return db_session.query(User).filter_by(email=email).first()

    @classmethod
    def update_user(
        cls,
        db_session,
        user_id: int,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        role: Optional[str] = None,
        organization_id: Optional[int] = None,
        status: Optional[str] = None,
        zoho_contact_id: Optional[str] = None,
        password: Optional[str] = None,
        two_factor_enabled: Optional[bool] = None,
        two_factor_secret: Optional[str] = None
    ) -> Optional['User']:
        """
        Update a user's information.

        Only provided fields will be updated. None values for optional
        parameters mean "don't update this field".

        Args:
            db_session: SQLAlchemy database session
            user_id: The user's unique identifier
            name: New display name (optional)
            phone: New phone number (optional)
            role: New role (optional, must be valid)
            organization_id: New organization ID (optional)
            status: New status (optional, must be valid)
            zoho_contact_id: New ZOHO CRM contact ID (optional)
            password: New password (optional, will be hashed)
            two_factor_enabled: Enable/disable 2FA (optional)
            two_factor_secret: New 2FA secret (optional)

        Returns:
            User: The updated user instance, or None if user not found

        Raises:
            ValueError: If role or status is invalid, or password exceeds limit

        Note:
            Changes are made to the user but not committed.
            The caller is responsible for committing the transaction.
        """
        from content_catalog.models.user import User

        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return None

        # Update name if provided
        if name is not None:
            user.name = name

        # Update phone if provided
        if phone is not None:
            user.phone = phone

        # Update role if provided (with validation)
        if role is not None:
            if role not in User.VALID_ROLES:
                raise ValueError(
                    f"Invalid role '{role}'. Must be one of: {', '.join(User.VALID_ROLES)}"
                )
            user.role = role

        # Update organization_id if provided
        if organization_id is not None:
            user.organization_id = organization_id

        # Update status if provided (with validation)
        if status is not None:
            if status not in User.VALID_STATUSES:
                raise ValueError(
                    f"Invalid status '{status}'. Must be one of: {', '.join(User.VALID_STATUSES)}"
                )
            user.status = status

        # Update zoho_contact_id if provided
        if zoho_contact_id is not None:
            user.zoho_contact_id = zoho_contact_id

        # Update password if provided
        if password is not None:
            user.password_hash = AuthService.hash_password(password)
            user.password_changed_at = datetime.now(timezone.utc)

        # Update 2FA settings if provided
        if two_factor_enabled is not None:
            user.two_factor_enabled = two_factor_enabled

        if two_factor_secret is not None:
            user.two_factor_secret = two_factor_secret

        return user

    @classmethod
    def list_users(
        cls,
        db_session,
        role: Optional[str] = None,
        status: Optional[str] = None,
        organization_id: Optional[int] = None,
        search: Optional[str] = None,
        page: int = DEFAULT_PAGE,
        per_page: int = DEFAULT_PER_PAGE,
        sort_by: str = 'created_at',
        sort_order: str = 'desc'
    ) -> Tuple[List['User'], int]:
        """
        List users with optional filtering, pagination, and sorting.

        Args:
            db_session: SQLAlchemy database session
            role: Filter by role (optional)
            status: Filter by status (optional)
            organization_id: Filter by organization (optional)
            search: Search term for name or email (optional)
            page: Page number (1-indexed, default 1)
            per_page: Results per page (default 20, max 100)
            sort_by: Field to sort by (default 'created_at')
            sort_order: Sort order 'asc' or 'desc' (default 'desc')

        Returns:
            Tuple of (list of User instances, total count)

        Example:
            users, total = UserService.list_users(
                db.session,
                role='partner',
                status='active',
                page=2,
                per_page=10
            )
        """
        from content_catalog.models.user import User

        # Build the base query
        query = db_session.query(User)

        # Apply filters
        if role is not None:
            query = query.filter(User.role == role)

        if status is not None:
            query = query.filter(User.status == status)

        if organization_id is not None:
            query = query.filter(User.organization_id == organization_id)

        if search is not None:
            search_pattern = f'%{search}%'
            query = query.filter(
                (User.name.ilike(search_pattern)) |
                (User.email.ilike(search_pattern))
            )

        # Get total count before pagination
        total = query.count()

        # Apply sorting
        sort_column = getattr(User, sort_by, User.created_at)
        if sort_order.lower() == 'asc':
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

        # Apply pagination
        per_page = min(per_page, cls.MAX_PER_PAGE)
        offset = (page - 1) * per_page
        users = query.offset(offset).limit(per_page).all()

        return users, total

    @classmethod
    def get_users_by_role(cls, db_session, role: str) -> List['User']:
        """
        Get all users with a specific role.

        Args:
            db_session: SQLAlchemy database session
            role: The role to filter by

        Returns:
            list: List of User instances with the specified role
        """
        from content_catalog.models.user import User

        return db_session.query(User).filter_by(role=role).all()

    @classmethod
    def get_users_by_status(cls, db_session, status: str) -> List['User']:
        """
        Get all users with a specific status.

        Args:
            db_session: SQLAlchemy database session
            status: The status to filter by

        Returns:
            list: List of User instances with the specified status
        """
        from content_catalog.models.user import User

        return db_session.query(User).filter_by(status=status).all()

    @classmethod
    def get_organization_users(cls, db_session, organization_id: int) -> List['User']:
        """
        Get all users belonging to a specific organization.

        Args:
            db_session: SQLAlchemy database session
            organization_id: The organization ID to filter by

        Returns:
            list: List of User instances belonging to the organization
        """
        from content_catalog.models.user import User

        return db_session.query(User).filter_by(
            organization_id=organization_id
        ).order_by(User.created_at.desc()).all()

    @classmethod
    def get_pending_users(cls, db_session) -> List['User']:
        """
        Get all users with pending status awaiting approval.

        Args:
            db_session: SQLAlchemy database session

        Returns:
            list: List of User instances with pending status
        """
        from content_catalog.models.user import User

        return db_session.query(User).filter_by(
            status=User.STATUS_PENDING
        ).order_by(User.created_at.asc()).all()

    @classmethod
    def approve_user(
        cls,
        db_session,
        user_id: int,
        approved_by: int
    ) -> Optional['User']:
        """
        Approve a pending user.

        Changes the user's status from 'pending' to 'approved' and records
        the approver information.

        Args:
            db_session: SQLAlchemy database session
            user_id: The user ID to approve
            approved_by: The user ID of the approver

        Returns:
            User: The updated user instance, or None if user not found

        Note:
            Does not validate approval hierarchy - caller should verify
            that the approver has permission to approve the user's role.
        """
        from content_catalog.models.user import User

        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return None

        user.status = User.STATUS_APPROVED
        user.approved_by = approved_by
        user.approved_at = datetime.now(timezone.utc)

        return user

    @classmethod
    def reject_user(
        cls,
        db_session,
        user_id: int,
        rejected_by: int,
        reason: str
    ) -> Optional['User']:
        """
        Reject a pending user.

        Changes the user's status to 'rejected' and records the rejection
        reason and rejector information.

        Args:
            db_session: SQLAlchemy database session
            user_id: The user ID to reject
            rejected_by: The user ID of the rejector
            reason: The reason for rejection

        Returns:
            User: The updated user instance, or None if user not found
        """
        from content_catalog.models.user import User

        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return None

        user.status = User.STATUS_REJECTED
        user.approved_by = rejected_by  # Using approved_by field to track who made the decision
        user.approved_at = datetime.now(timezone.utc)
        user.rejection_reason = reason

        return user

    @classmethod
    def suspend_user(cls, db_session, user_id: int) -> Optional['User']:
        """
        Suspend a user account.

        Args:
            db_session: SQLAlchemy database session
            user_id: The user ID to suspend

        Returns:
            User: The updated user instance, or None if user not found
        """
        from content_catalog.models.user import User

        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return None

        user.status = User.STATUS_SUSPENDED

        return user

    @classmethod
    def activate_user(cls, db_session, user_id: int) -> Optional['User']:
        """
        Activate an approved user account.

        Changes the user's status from 'approved' to 'active'.

        Args:
            db_session: SQLAlchemy database session
            user_id: The user ID to activate

        Returns:
            User: The updated user instance, or None if user not found
        """
        from content_catalog.models.user import User

        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return None

        user.status = User.STATUS_ACTIVE

        return user

    @classmethod
    def reactivate_user(cls, db_session, user_id: int) -> Optional['User']:
        """
        Reactivate a suspended or deactivated user account.

        Changes the user's status to 'active', typically used after suspension.

        Args:
            db_session: SQLAlchemy database session
            user_id: The user ID to reactivate

        Returns:
            User: The updated user instance, or None if user not found
        """
        from content_catalog.models.user import User

        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return None

        user.status = User.STATUS_ACTIVE

        return user

    @classmethod
    def deactivate_user(cls, db_session, user_id: int) -> Optional['User']:
        """
        Deactivate a user account.

        Args:
            db_session: SQLAlchemy database session
            user_id: The user ID to deactivate

        Returns:
            User: The updated user instance, or None if user not found
        """
        from content_catalog.models.user import User

        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return None

        user.status = User.STATUS_DEACTIVATED

        return user

    @classmethod
    def record_login(cls, db_session, user_id: int) -> Optional['User']:
        """
        Record a successful login for a user.

        Updates the last_login timestamp and resets failed login attempts.

        Args:
            db_session: SQLAlchemy database session
            user_id: The user ID who logged in

        Returns:
            User: The updated user instance, or None if user not found
        """
        from content_catalog.models.user import User

        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return None

        user.last_login = datetime.now(timezone.utc)
        user.failed_login_attempts = 0
        user.locked_until = None

        return user

    @classmethod
    def record_failed_login(cls, db_session, user_id: int) -> Tuple[Optional['User'], bool]:
        """
        Record a failed login attempt for a user.

        Increments the failed login counter and locks the account if the
        maximum number of attempts is exceeded.

        Args:
            db_session: SQLAlchemy database session
            user_id: The user ID who attempted login

        Returns:
            Tuple of (User instance or None, is_locked boolean)
        """
        from datetime import timedelta

        from content_catalog.models.user import User

        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return None, False

        user.failed_login_attempts += 1

        # Check if account should be locked
        is_locked = False
        if user.failed_login_attempts >= AuthService.MAX_LOGIN_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=AuthService.LOCKOUT_DURATION_MINUTES
            )
            is_locked = True

        return user, is_locked
