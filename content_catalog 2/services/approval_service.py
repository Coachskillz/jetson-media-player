"""
Approval Service for Content Catalog.

Provides user approval workflow functionality with role hierarchy enforcement.
Ensures that approvers can only approve users with roles lower in the hierarchy
and prevents circular approvals and self-approvals.

Key features:
- Role hierarchy enforcement (Super Admin > Admin > Content Manager > Partner > Advertiser > Viewer)
- Approval permission validation
- Self-approval prevention
- Circular approval detection
- Integration with audit logging
- Email notifications for submit, approve, reject, and revoke actions
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from content_catalog.models.user import User, UserApprovalRequest
from content_catalog.models.content import ContentAsset, ContentApprovalRequest, MagicLinkToken

logger = logging.getLogger(__name__)


class ApprovalService:
    """
    User approval workflow service for the Content Catalog.

    This service handles:
    1. Validating approval permissions based on role hierarchy
    2. Approving and rejecting users with proper audit trails
    3. Preventing invalid approval scenarios (self-approval, circular approval)

    Role Hierarchy (highest to lowest privilege):
        - super_admin: Can approve admin, content_manager, partner, advertiser, viewer
        - admin: Can approve content_manager, partner, advertiser, viewer
        - content_manager: Can approve partner, advertiser, viewer
        - partner: Can approve advertiser, viewer
        - advertiser: Can approve viewer
        - viewer: Cannot approve anyone

    Usage:
        # Check if a user can approve another user
        can_approve, reason = ApprovalService.can_approve_user(
            db_session=db.session,
            approver_id=admin_user.id,
            user_id=pending_user.id
        )

        # Approve a user
        result = ApprovalService.approve_user(
            db_session=db.session,
            approver_id=admin_user.id,
            user_id=pending_user.id,
            notes='Approved after verification'
        )

        # Reject a user
        result = ApprovalService.reject_user(
            db_session=db.session,
            approver_id=admin_user.id,
            user_id=pending_user.id,
            reason='Missing required documentation'
        )
    """

    # Role hierarchy with numeric levels (lower number = higher privilege)
    # This allows easy comparison: approver_level < target_level means can approve
    ROLE_HIERARCHY = {
        User.ROLE_SUPER_ADMIN: 0,
        User.ROLE_ADMIN: 1,
        User.ROLE_CONTENT_MANAGER: 2,
        User.ROLE_PARTNER: 3,
        User.ROLE_ADVERTISER: 4,
        User.ROLE_VIEWER: 5
    }

    # Statuses that can be approved (user must be in one of these states)
    APPROVABLE_STATUSES = [
        User.STATUS_PENDING,
    ]

    @classmethod
    def get_role_level(cls, role: str) -> int:
        """
        Get the hierarchy level for a role.

        Lower numbers indicate higher privilege levels.

        Args:
            role: The role to get the level for

        Returns:
            The hierarchy level (0-5), or -1 if role is invalid
        """
        return cls.ROLE_HIERARCHY.get(role, -1)

    @classmethod
    def can_approve_role(cls, approver_role: str, target_role: str) -> bool:
        """
        Check if one role can approve another role based on hierarchy.

        Args:
            approver_role: The role of the user attempting to approve
            target_role: The role of the user to be approved

        Returns:
            True if the approver role can approve the target role
        """
        approver_level = cls.get_role_level(approver_role)
        target_level = cls.get_role_level(target_role)

        # Invalid roles cannot approve or be approved
        if approver_level < 0 or target_level < 0:
            return False

        # Can only approve roles with higher level numbers (lower privilege)
        return approver_level < target_level

    @classmethod
    def can_approve_user(
        cls,
        db_session,
        approver_id: int,
        user_id: int
    ) -> Tuple[bool, str]:
        """
        Check if an approver can approve a specific user.

        Validates:
        1. Both users exist
        2. Approver is not approving themselves
        3. Target user is in an approvable status
        4. Approver's role is higher in hierarchy than target's role
        5. No circular approval (target didn't previously approve the approver)

        Args:
            db_session: SQLAlchemy database session
            approver_id: ID of the user attempting to approve
            user_id: ID of the user to be approved

        Returns:
            Tuple of (can_approve: bool, reason: str)
            - If can_approve is True, reason will be 'ok'
            - If can_approve is False, reason explains why
        """
        # Fetch both users
        approver = db_session.query(User).filter_by(id=approver_id).first()
        target_user = db_session.query(User).filter_by(id=user_id).first()

        # Validate users exist
        if approver is None:
            return False, 'Approver not found'

        if target_user is None:
            return False, 'User to approve not found'

        # Prevent self-approval
        if approver_id == user_id:
            return False, 'Users cannot approve themselves'

        # Check if target user is in an approvable status
        if target_user.status not in cls.APPROVABLE_STATUSES:
            return False, f'User status "{target_user.status}" is not eligible for approval'

        # Check role hierarchy
        if not cls.can_approve_role(approver.role, target_user.role):
            return False, f'Role "{approver.role}" cannot approve role "{target_user.role}"'

        # Check approver's account status
        if approver.status not in [User.STATUS_ACTIVE, User.STATUS_APPROVED]:
            return False, 'Approver account is not active'

        # Prevent circular approval: target user should not have approved the approver
        if approver.approved_by == user_id:
            return False, 'Circular approval detected: this user previously approved you'

        return True, 'ok'

    @classmethod
    def approve_user(
        cls,
        db_session,
        approver_id: int,
        user_id: int,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Approve a pending user.

        Changes the user's status from 'pending' to 'approved' and records
        the approver information. Also resolves any pending approval requests.

        Args:
            db_session: SQLAlchemy database session
            approver_id: ID of the user performing the approval
            user_id: ID of the user to approve
            notes: Optional notes about the approval decision

        Returns:
            Dict with keys:
            - success: bool indicating if approval succeeded
            - user: The updated User instance (if successful)
            - error: Error message (if unsuccessful)
            - approval_request: The resolved UserApprovalRequest (if one existed)

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        # Validate approval is allowed
        can_approve, reason = cls.can_approve_user(db_session, approver_id, user_id)
        if not can_approve:
            return {
                'success': False,
                'error': reason,
                'user': None,
                'approval_request': None
            }

        # Fetch the user to approve
        user = db_session.query(User).filter_by(id=user_id).first()

        # Update user status
        user.status = User.STATUS_APPROVED
        user.approved_by = approver_id
        user.approved_at = datetime.now(timezone.utc)

        # Find and resolve any pending approval request for this user
        approval_request = db_session.query(UserApprovalRequest).filter_by(
            user_id=user_id,
            status=UserApprovalRequest.STATUS_PENDING
        ).first()

        if approval_request:
            approval_request.status = UserApprovalRequest.STATUS_APPROVED
            approval_request.resolved_at = datetime.now(timezone.utc)
            if notes:
                approval_request.notes = notes

        return {
            'success': True,
            'user': user,
            'error': None,
            'approval_request': approval_request
        }

    @classmethod
    def reject_user(
        cls,
        db_session,
        approver_id: int,
        user_id: int,
        reason: str
    ) -> Dict[str, Any]:
        """
        Reject a pending user.

        Changes the user's status to 'rejected' and records the rejection
        reason and rejector information. Also resolves any pending approval requests.

        Args:
            db_session: SQLAlchemy database session
            approver_id: ID of the user performing the rejection
            user_id: ID of the user to reject
            reason: Required reason for the rejection

        Returns:
            Dict with keys:
            - success: bool indicating if rejection succeeded
            - user: The updated User instance (if successful)
            - error: Error message (if unsuccessful)
            - approval_request: The resolved UserApprovalRequest (if one existed)

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        # Validate that the user performing the action has permission
        # Use the same permission checks as approval
        can_approve, validation_reason = cls.can_approve_user(db_session, approver_id, user_id)
        if not can_approve:
            return {
                'success': False,
                'error': validation_reason,
                'user': None,
                'approval_request': None
            }

        # Validate reason is provided
        if not reason or not reason.strip():
            return {
                'success': False,
                'error': 'Rejection reason is required',
                'user': None,
                'approval_request': None
            }

        # Fetch the user to reject
        user = db_session.query(User).filter_by(id=user_id).first()

        # Update user status
        user.status = User.STATUS_REJECTED
        user.approved_by = approver_id  # Track who made the decision
        user.approved_at = datetime.now(timezone.utc)
        user.rejection_reason = reason.strip()

        # Find and resolve any pending approval request for this user
        approval_request = db_session.query(UserApprovalRequest).filter_by(
            user_id=user_id,
            status=UserApprovalRequest.STATUS_PENDING
        ).first()

        if approval_request:
            approval_request.status = UserApprovalRequest.STATUS_REJECTED
            approval_request.resolved_at = datetime.now(timezone.utc)
            approval_request.notes = reason.strip()

        return {
            'success': True,
            'user': user,
            'error': None,
            'approval_request': approval_request
        }

    @classmethod
    def get_approvable_roles_for_user(cls, db_session, user_id: int) -> list:
        """
        Get the list of roles that a user can approve.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user to check

        Returns:
            List of role strings that the user can approve, or empty list if none
        """
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return []

        user_level = cls.get_role_level(user.role)
        if user_level < 0:
            return []

        # Return all roles with higher level numbers (lower privilege)
        return [
            role for role, level in cls.ROLE_HIERARCHY.items()
            if level > user_level
        ]

    @classmethod
    def get_pending_approvals_for_user(
        cls,
        db_session,
        approver_id: int
    ) -> list:
        """
        Get all pending users that a specific approver can approve.

        Filters users by:
        1. Status is 'pending'
        2. Role is approvable by the approver's role
        3. Not the approver themselves

        Args:
            db_session: SQLAlchemy database session
            approver_id: ID of the potential approver

        Returns:
            List of User instances that can be approved by this user
        """
        approver = db_session.query(User).filter_by(id=approver_id).first()
        if approver is None:
            return []

        # Get roles this user can approve
        approvable_roles = cls.get_approvable_roles_for_user(db_session, approver_id)
        if not approvable_roles:
            return []

        # Query pending users with approvable roles
        pending_users = db_session.query(User).filter(
            User.status == User.STATUS_PENDING,
            User.role.in_(approvable_roles),
            User.id != approver_id
        ).order_by(User.created_at.asc()).all()

        # Filter out any circular approval situations
        result = []
        for user in pending_users:
            # Skip if this user previously approved the approver
            if approver.approved_by != user.id:
                result.append(user)

        return result

    @classmethod
    def create_approval_request(
        cls,
        db_session,
        user_id: int,
        requested_by: Optional[int] = None,
        assigned_to: Optional[int] = None,
        notes: Optional[str] = None
    ) -> UserApprovalRequest:
        """
        Create a new approval request for a user.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user needing approval
            requested_by: ID of the user who initiated the request (optional)
            assigned_to: ID of the user assigned to review (optional)
            notes: Optional notes about the request

        Returns:
            The created UserApprovalRequest instance

        Note:
            The request is added to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            raise ValueError(f'User with id {user_id} not found')

        approval_request = UserApprovalRequest(
            user_id=user_id,
            requested_role=user.role,
            current_status=user.status,
            requested_by=requested_by or user_id,
            assigned_to=assigned_to,
            status=UserApprovalRequest.STATUS_PENDING,
            notes=notes
        )

        db_session.add(approval_request)
        return approval_request

    # ==========================================================================