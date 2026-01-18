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
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from content_catalog.models.user import User, UserApprovalRequest
from content_catalog.models.content import ContentAsset, ContentApprovalRequest


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
    # Content Approval Methods
    # ==========================================================================

    # Roles that can approve content (Content Manager and above)
    CONTENT_APPROVER_ROLES = [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER
    ]

    # Roles that can publish content (Content Manager and above)
    CONTENT_PUBLISHER_ROLES = [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER
    ]

    @classmethod
    def can_approve_content(
        cls,
        db_session,
        approver_id: int,
        asset_id: int
    ) -> Tuple[bool, str]:
        """
        Check if a user can approve a specific content asset.

        Validates:
        1. Approver exists and is active
        2. Content asset exists
        3. Content is in pending_review status
        4. Approver has a content approval role (Content Manager or above)
        5. User is not approving their own uploaded content

        Args:
            db_session: SQLAlchemy database session
            approver_id: ID of the user attempting to approve
            asset_id: ID of the content asset to be approved

        Returns:
            Tuple of (can_approve: bool, reason: str)
            - If can_approve is True, reason will be 'ok'
            - If can_approve is False, reason explains why
        """
        # Fetch the approver
        approver = db_session.query(User).filter_by(id=approver_id).first()
        if approver is None:
            return False, 'Approver not found'

        # Check approver's account status
        if approver.status not in [User.STATUS_ACTIVE, User.STATUS_APPROVED]:
            return False, 'Approver account is not active'

        # Check approver has permission to approve content
        if approver.role not in cls.CONTENT_APPROVER_ROLES:
            return False, f'Role "{approver.role}" cannot approve content'

        # Fetch the content asset
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return False, 'Content asset not found'

        # Check content is in pending_review status
        if asset.status != ContentAsset.STATUS_PENDING_REVIEW:
            return False, f'Content status "{asset.status}" is not eligible for approval'

        # Prevent self-approval (user cannot approve their own uploads)
        if asset.uploaded_by == approver_id:
            return False, 'Users cannot approve their own uploaded content'

        return True, 'ok'

    @classmethod
    def approve_content(
        cls,
        db_session,
        approver_id: int,
        asset_id: int,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Approve a content asset pending review.

        Changes the asset's status from 'pending_review' to 'approved' and records
        the reviewer information. Also resolves any pending content approval requests.

        Args:
            db_session: SQLAlchemy database session
            approver_id: ID of the user performing the approval
            asset_id: ID of the content asset to approve
            notes: Optional notes about the approval decision

        Returns:
            Dict with keys:
            - success: bool indicating if approval succeeded
            - asset: The updated ContentAsset instance (if successful)
            - error: Error message (if unsuccessful)
            - approval_request: The resolved ContentApprovalRequest (if one existed)

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        # Validate approval is allowed
        can_approve, reason = cls.can_approve_content(db_session, approver_id, asset_id)
        if not can_approve:
            return {
                'success': False,
                'error': reason,
                'asset': None,
                'approval_request': None
            }

        # Fetch the asset to approve
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()

        # Update asset status
        asset.status = ContentAsset.STATUS_APPROVED
        asset.reviewed_by = approver_id
        asset.reviewed_at = datetime.now(timezone.utc)
        if notes:
            asset.review_notes = notes

        # Find and resolve any pending approval request for this asset
        approval_request = db_session.query(ContentApprovalRequest).filter_by(
            asset_id=asset_id,
            status=ContentApprovalRequest.STATUS_PENDING
        ).first()

        if approval_request:
            approval_request.status = ContentApprovalRequest.STATUS_APPROVED
            approval_request.resolved_at = datetime.now(timezone.utc)
            if notes:
                approval_request.notes = notes

        return {
            'success': True,
            'asset': asset,
            'error': None,
            'approval_request': approval_request
        }

    @classmethod
    def reject_content(
        cls,
        db_session,
        approver_id: int,
        asset_id: int,
        reason: str
    ) -> Dict[str, Any]:
        """
        Reject a content asset pending review.

        Changes the asset's status to 'rejected' and records the rejection
        reason and reviewer information. Also resolves any pending content approval requests.

        Args:
            db_session: SQLAlchemy database session
            approver_id: ID of the user performing the rejection
            asset_id: ID of the content asset to reject
            reason: Required reason for the rejection

        Returns:
            Dict with keys:
            - success: bool indicating if rejection succeeded
            - asset: The updated ContentAsset instance (if successful)
            - error: Error message (if unsuccessful)
            - approval_request: The resolved ContentApprovalRequest (if one existed)

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        # Validate that the user performing the action has permission
        # Use the same permission checks as approval
        can_approve, validation_reason = cls.can_approve_content(db_session, approver_id, asset_id)
        if not can_approve:
            return {
                'success': False,
                'error': validation_reason,
                'asset': None,
                'approval_request': None
            }

        # Validate reason is provided
        if not reason or not reason.strip():
            return {
                'success': False,
                'error': 'Rejection reason is required',
                'asset': None,
                'approval_request': None
            }

        # Fetch the asset to reject
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()

        # Update asset status
        asset.status = ContentAsset.STATUS_REJECTED
        asset.reviewed_by = approver_id
        asset.reviewed_at = datetime.now(timezone.utc)
        asset.review_notes = reason.strip()

        # Find and resolve any pending approval request for this asset
        approval_request = db_session.query(ContentApprovalRequest).filter_by(
            asset_id=asset_id,
            status=ContentApprovalRequest.STATUS_PENDING
        ).first()

        if approval_request:
            approval_request.status = ContentApprovalRequest.STATUS_REJECTED
            approval_request.resolved_at = datetime.now(timezone.utc)
            approval_request.notes = reason.strip()

        return {
            'success': True,
            'asset': asset,
            'error': None,
            'approval_request': approval_request
        }

    @classmethod
    def can_publish_content(
        cls,
        db_session,
        publisher_id: int,
        asset_id: int
    ) -> Tuple[bool, str]:
        """
        Check if a user can publish a specific content asset.

        Validates:
        1. Publisher exists and is active
        2. Content asset exists
        3. Content is in approved status
        4. Publisher has a content publisher role (Content Manager or above)

        Args:
            db_session: SQLAlchemy database session
            publisher_id: ID of the user attempting to publish
            asset_id: ID of the content asset to be published

        Returns:
            Tuple of (can_publish: bool, reason: str)
            - If can_publish is True, reason will be 'ok'
            - If can_publish is False, reason explains why
        """
        # Fetch the publisher
        publisher = db_session.query(User).filter_by(id=publisher_id).first()
        if publisher is None:
            return False, 'Publisher not found'

        # Check publisher's account status
        if publisher.status not in [User.STATUS_ACTIVE, User.STATUS_APPROVED]:
            return False, 'Publisher account is not active'

        # Check publisher has permission to publish content
        if publisher.role not in cls.CONTENT_PUBLISHER_ROLES:
            return False, f'Role "{publisher.role}" cannot publish content'

        # Fetch the content asset
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return False, 'Content asset not found'

        # Check content is in approved status
        if asset.status != ContentAsset.STATUS_APPROVED:
            return False, f'Content status "{asset.status}" is not eligible for publishing'

        return True, 'ok'

    @classmethod
    def publish_content(
        cls,
        db_session,
        publisher_id: int,
        asset_id: int
    ) -> Dict[str, Any]:
        """
        Publish an approved content asset.

        Changes the asset's status from 'approved' to 'published' and records
        the publication timestamp.

        Args:
            db_session: SQLAlchemy database session
            publisher_id: ID of the user performing the publish action
            asset_id: ID of the content asset to publish

        Returns:
            Dict with keys:
            - success: bool indicating if publishing succeeded
            - asset: The updated ContentAsset instance (if successful)
            - error: Error message (if unsuccessful)

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        # Validate publish is allowed
        can_publish, reason = cls.can_publish_content(db_session, publisher_id, asset_id)
        if not can_publish:
            return {
                'success': False,
                'error': reason,
                'asset': None
            }

        # Fetch the asset to publish
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()

        # Update asset status
        asset.status = ContentAsset.STATUS_PUBLISHED
        asset.published_at = datetime.now(timezone.utc)

        return {
            'success': True,
            'asset': asset,
            'error': None
        }

    @classmethod
    def get_pending_content_approvals(
        cls,
        db_session,
        approver_id: int,
        organization_id: Optional[int] = None
    ) -> list:
        """
        Get all content assets pending approval that a specific approver can approve.

        Filters assets by:
        1. Status is 'pending_review'
        2. Approver has permission to approve content
        3. Not the approver's own uploads
        4. Optionally filtered by organization

        Args:
            db_session: SQLAlchemy database session
            approver_id: ID of the potential approver
            organization_id: Optional organization ID to filter by

        Returns:
            List of ContentAsset instances that can be approved by this user
        """
        approver = db_session.query(User).filter_by(id=approver_id).first()
        if approver is None:
            return []

        # Check approver has permission
        if approver.role not in cls.CONTENT_APPROVER_ROLES:
            return []

        # Query pending content assets
        query = db_session.query(ContentAsset).filter(
            ContentAsset.status == ContentAsset.STATUS_PENDING_REVIEW,
            ContentAsset.uploaded_by != approver_id  # Exclude own uploads
        )

        # Filter by organization if specified
        if organization_id:
            query = query.filter(ContentAsset.organization_id == organization_id)

        return query.order_by(ContentAsset.created_at.asc()).all()

    @classmethod
    def create_content_approval_request(
        cls,
        db_session,
        asset_id: int,
        requested_by: Optional[int] = None,
        assigned_to: Optional[int] = None,
        notes: Optional[str] = None
    ) -> ContentApprovalRequest:
        """
        Create a new approval request for a content asset.

        Args:
            db_session: SQLAlchemy database session
            asset_id: ID of the content asset needing approval
            requested_by: ID of the user who initiated the request (optional)
            assigned_to: ID of the user assigned to review (optional)
            notes: Optional notes about the request

        Returns:
            The created ContentApprovalRequest instance

        Raises:
            ValueError: If the content asset does not exist

        Note:
            The request is added to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            raise ValueError(f'Content asset with id {asset_id} not found')

        approval_request = ContentApprovalRequest(
            asset_id=asset_id,
            requested_by=requested_by or asset.uploaded_by,
            assigned_to=assigned_to,
            status=ContentApprovalRequest.STATUS_PENDING,
            notes=notes
        )

        db_session.add(approval_request)
        return approval_request

    @classmethod
    def submit_content_for_approval(
        cls,
        db_session,
        user_id: int,
        asset_id: int,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submit a draft content asset for approval.

        Changes the asset's status from 'draft' to 'pending_review' and creates
        an approval request.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user submitting the content
            asset_id: ID of the content asset to submit
            notes: Optional notes about the submission

        Returns:
            Dict with keys:
            - success: bool indicating if submission succeeded
            - asset: The updated ContentAsset instance (if successful)
            - error: Error message (if unsuccessful)
            - approval_request: The created ContentApprovalRequest

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        # Fetch the user
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return {
                'success': False,
                'error': 'User not found',
                'asset': None,
                'approval_request': None
            }

        # Check user's account status
        if user.status not in [User.STATUS_ACTIVE, User.STATUS_APPROVED]:
            return {
                'success': False,
                'error': 'User account is not active',
                'asset': None,
                'approval_request': None
            }

        # Fetch the content asset
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return {
                'success': False,
                'error': 'Content asset not found',
                'asset': None,
                'approval_request': None
            }

        # Check content is in draft status
        if asset.status != ContentAsset.STATUS_DRAFT:
            return {
                'success': False,
                'error': f'Content status "{asset.status}" cannot be submitted for approval',
                'asset': None,
                'approval_request': None
            }

        # Check user can submit this asset (must be owner or have upload permission)
        if asset.uploaded_by != user_id and user.role not in cls.CONTENT_APPROVER_ROLES:
            return {
                'success': False,
                'error': 'User does not have permission to submit this asset',
                'asset': None,
                'approval_request': None
            }

        # Update asset status
        asset.status = ContentAsset.STATUS_PENDING_REVIEW

        # Create approval request
        approval_request = ContentApprovalRequest(
            asset_id=asset_id,
            requested_by=user_id,
            status=ContentApprovalRequest.STATUS_PENDING,
            notes=notes
        )
        db_session.add(approval_request)

        return {
            'success': True,
            'asset': asset,
            'error': None,
            'approval_request': approval_request
        }

    @classmethod
    def revoke_content(
        cls,
        db_session,
        user_id: int,
        asset_id: int,
        reason: str
    ) -> Dict[str, Any]:
        """
        Revoke a published or approved content asset.

        Changes the asset's status to 'revoked' and records the revocation
        reason. Only users with publisher role can revoke content.

        Args:
            db_session: SQLAlchemy database session
            user_id: ID of the user revoking the content
            asset_id: ID of the content asset to revoke
            reason: Required reason for the revocation

        Returns:
            Dict with keys:
            - success: bool indicating if revocation succeeded
            - asset: The updated ContentAsset instance (if successful)
            - error: Error message (if unsuccessful)

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        # Fetch the user
        user = db_session.query(User).filter_by(id=user_id).first()
        if user is None:
            return {
                'success': False,
                'error': 'User not found',
                'asset': None
            }

        # Check user's account status
        if user.status not in [User.STATUS_ACTIVE, User.STATUS_APPROVED]:
            return {
                'success': False,
                'error': 'User account is not active',
                'asset': None
            }

        # Check user has permission to revoke content
        if user.role not in cls.CONTENT_PUBLISHER_ROLES:
            return {
                'success': False,
                'error': f'Role "{user.role}" cannot revoke content',
                'asset': None
            }

        # Validate reason is provided
        if not reason or not reason.strip():
            return {
                'success': False,
                'error': 'Revocation reason is required',
                'asset': None
            }

        # Fetch the content asset
        asset = db_session.query(ContentAsset).filter_by(id=asset_id).first()
        if asset is None:
            return {
                'success': False,
                'error': 'Content asset not found',
                'asset': None
            }

        # Check content is in a revocable status (approved or published)
        revocable_statuses = [ContentAsset.STATUS_APPROVED, ContentAsset.STATUS_PUBLISHED]
        if asset.status not in revocable_statuses:
            return {
                'success': False,
                'error': f'Content status "{asset.status}" cannot be revoked',
                'asset': None
            }

        # Update asset status
        asset.status = ContentAsset.STATUS_REVOKED
        asset.review_notes = reason.strip()
        asset.reviewed_by = user_id
        asset.reviewed_at = datetime.now(timezone.utc)

        return {
            'success': True,
            'asset': asset,
            'error': None
        }

    @classmethod
    def process_magic_link_approval(
        cls,
        db_session,
        token: str,
        action: str,
        rejection_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a magic link approval or rejection.

        Validates the token and performs the approval/rejection action.

        Args:
            db_session: SQLAlchemy database session
            token: The magic link token
            action: 'approve' or 'reject'
            rejection_reason: Required reason if action is 'reject'

        Returns:
            Dict with keys:
            - success: bool indicating if action succeeded
            - asset: The updated ContentAsset instance (if successful)
            - error: Error message (if unsuccessful)
            - approval_task: The ApprovalTask instance

        Note:
            Changes are made to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        from content_catalog.models.checkout import ApprovalTask

        # Find the approval task by token
        approval_task = db_session.query(ApprovalTask).filter_by(
            review_token=token
        ).first()

        if approval_task is None:
            return {
                'success': False,
                'error': 'Invalid approval token',
                'asset': None,
                'approval_task': None
            }

        # Check token is valid
        if not approval_task.is_token_valid:
            if approval_task.token_used:
                return {
                    'success': False,
                    'error': 'This approval link has already been used',
                    'asset': None,
                    'approval_task': approval_task
                }
            return {
                'success': False,
                'error': 'This approval link has expired',
                'asset': None,
                'approval_task': approval_task
            }

        # Validate action
        if action not in ['approve', 'reject']:
            return {
                'success': False,
                'error': f'Invalid action: {action}',
                'asset': None,
                'approval_task': approval_task
            }

        # For rejection, require a reason
        if action == 'reject' and (not rejection_reason or not rejection_reason.strip()):
            return {
                'success': False,
                'error': 'Rejection reason is required',
                'asset': None,
                'approval_task': approval_task
            }

        # Fetch the asset
        asset = db_session.query(ContentAsset).filter_by(id=approval_task.asset_id).first()
        if asset is None:
            return {
                'success': False,
                'error': 'Content asset not found',
                'asset': None,
                'approval_task': approval_task
            }

        # Check asset is still pending review
        if asset.status != ContentAsset.STATUS_PENDING_REVIEW:
            return {
                'success': False,
                'error': f'Content is no longer pending review (status: {asset.status})',
                'asset': asset,
                'approval_task': approval_task
            }

        # Process the action
        if action == 'approve':
            asset.status = ContentAsset.STATUS_APPROVED
            asset.reviewed_at = datetime.now(timezone.utc)
            if approval_task.intended_approver_id:
                asset.reviewed_by = approval_task.intended_approver_id
            approval_task.complete(ApprovalTask.RESULT_APPROVED)
        else:
            asset.status = ContentAsset.STATUS_REJECTED
            asset.review_notes = rejection_reason.strip()
            asset.reviewed_at = datetime.now(timezone.utc)
            if approval_task.intended_approver_id:
                asset.reviewed_by = approval_task.intended_approver_id
            approval_task.complete(ApprovalTask.RESULT_REJECTED, rejection_reason.strip())

        return {
            'success': True,
            'asset': asset,
            'error': None,
            'approval_task': approval_task
        }

    @classmethod
    def create_magic_link_approval_task(
        cls,
        db_session,
        asset_id: int,
        tenant_id: str,
        intended_approver_id: Optional[int] = None
    ):
        """
        Create a magic link approval task for a content asset.

        Args:
            db_session: SQLAlchemy database session
            asset_id: ID of the content asset needing approval
            tenant_id: Tenant ID for the asset
            intended_approver_id: Optional ID of the intended approver

        Returns:
            The created ApprovalTask instance

        Note:
            The task is added to the session but not committed.
            The caller is responsible for committing the transaction.
        """
        from content_catalog.models.checkout import ApprovalTask

        approval_task = ApprovalTask(
            tenant_id=tenant_id,
            asset_id=asset_id,
            intended_approver_id=intended_approver_id
        )

        db_session.add(approval_task)
        return approval_task
