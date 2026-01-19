"""
Content Catalog Approvals Routes.

Blueprint for user and content approval workflow API endpoints:

User Approval Endpoints:
- GET /pending: List all users pending approval
- POST /<id>/approve: Approve a pending user
- POST /<id>/reject: Reject a pending user

Content Approval Endpoints:
- GET /content/pending: List all content assets pending approval
- GET /content/approved: List all approved/published content assets (for CMS integration)

Magic Link Endpoints (no authentication required):
- GET /approve/<token>: Display magic link approval page
- POST /approve/<token>: Process approval/rejection via magic link

All endpoints are prefixed with /api/v1/approvals when registered with the app.
All endpoints except magic link routes require JWT authentication with appropriate permissions.
"""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, render_template
from flask_jwt_extended import get_jwt_identity, jwt_required

from content_catalog.models import db, User, UserApprovalRequest, ContentAsset, ContentApprovalRequest, MagicLinkToken
from content_catalog.services.audit_service import AuditService
from content_catalog.services.content_service import ContentService
from content_catalog.services.approval_service import ApprovalService


# Create approvals blueprint
approvals_bp = Blueprint('approvals', __name__)


def _get_current_user():
    """
    Get the current authenticated user from JWT identity.

    Returns:
        User object or None if not found
    """
    current_user_id = get_jwt_identity()
    return db.session.get(User, current_user_id)


def _can_approve_users(user):
    """
    Check if the user has permission to approve/reject other users.

    Only Super Admins, Admins, and Content Managers can approve users.

    Args:
        user: The User object to check permissions for

    Returns:
        True if user can approve other users, False otherwise
    """
    if not user:
        return False
    return user.role in [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER
    ]


def _can_approve_content(user):
    """
    Check if the user has permission to approve/reject content.

    Only Super Admins, Admins, and Content Managers can approve content.

    Args:
        user: The User object to check permissions for

    Returns:
        True if user can approve content, False otherwise
    """
    if not user:
        return False
    return user.role in [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER
    ]


@approvals_bp.route('/pending', methods=['GET'])
@jwt_required()
def list_pending_users():
    """
    List all users pending approval.

    Returns a paginated list of users with status 'pending' that the
    current user has permission to approve based on role hierarchy.

    Query Parameters:
        role: Filter by role (optional)
        organization_id: Filter by organization ID (optional)
        page: Page number (default: 1)
        per_page: Items per page (default: 20, max: 100)

    Returns:
        200: List of pending users
            {
                "users": [ { user data }, ... ],
                "count": 5,
                "page": 1,
                "per_page": 20,
                "total": 10
            }
        401: Unauthorized (missing or invalid token)
        403: Forbidden (insufficient permissions)
        404: Current user not found
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to view pending approvals
    if not _can_approve_users(current_user):
        return jsonify({'error': 'Insufficient permissions to view pending approvals'}), 403

    # Build query for pending users
    query = User.query.filter_by(status=User.STATUS_PENDING)

    # Filter by role if specified
    role_filter = request.args.get('role')
    if role_filter:
        if role_filter not in User.VALID_ROLES:
            return jsonify({
                'error': f"Invalid role. Must be one of: {', '.join(User.VALID_ROLES)}"
            }), 400
        query = query.filter_by(role=role_filter)

    # Filter by organization if specified
    organization_id = request.args.get('organization_id')
    if organization_id:
        try:
            org_id = int(organization_id)
            query = query.filter_by(organization_id=org_id)
        except ValueError:
            return jsonify({'error': 'organization_id must be an integer'}), 400

    # Only show users that the current user can approve based on role hierarchy
    # Filter to roles that the current user can approve
    approvable_roles = [
        role for role in User.VALID_ROLES
        if current_user.can_approve_role(role)
    ]
    if approvable_roles:
        query = query.filter(User.role.in_(approvable_roles))
    else:
        # User cannot approve anyone, return empty list
        return jsonify({
            'users': [],
            'count': 0,
            'page': 1,
            'per_page': 20,
            'total': 0
        }), 200

    # Pagination parameters
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1

    try:
        per_page = int(request.args.get('per_page', 20))
        if per_page < 1:
            per_page = 20
        if per_page > 100:
            per_page = 100
    except ValueError:
        per_page = 20

    # Get total count before pagination
    total = query.count()

    # Apply pagination and ordering
    users = query.order_by(User.created_at.asc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return jsonify({
        'users': [user.to_dict() for user in users],
        'count': len(users),
        'page': page,
        'per_page': per_page,
        'total': total
    }), 200


@approvals_bp.route('/<int:user_id>/approve', methods=['POST'])
@jwt_required()
def approve_user(user_id):
    """
    Approve a pending user.

    Approves a user that is in pending status, changing their status
    to 'approved' or 'active' based on the request.

    Args:
        user_id: The ID of the user to approve

    Request Body (optional):
        {
            "notes": "Approval notes" (optional),
            "status": "active" or "approved" (optional, defaults to "active")
        }

    Returns:
        200: User approved successfully
            {
                "message": "User approved successfully",
                "user": { user data }
            }
        400: Invalid request data
        401: Unauthorized (missing or invalid token)
        403: Forbidden (insufficient permissions or cannot approve this role)
        404: User not found or current user not found
        409: User is not in pending status
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has general permission to approve users
    if not _can_approve_users(current_user):
        return jsonify({'error': 'Insufficient permissions to approve users'}), 403

    # Find the user to approve
    user = db.session.get(User, user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user is in pending status
    if user.status != User.STATUS_PENDING:
        return jsonify({
            'error': f"Cannot approve user: user status is '{user.status}', not 'pending'"
        }), 409

    # Check if current user can approve this specific role
    if not current_user.can_approve_role(user.role):
        return jsonify({
            'error': f'Insufficient permissions to approve users with role: {user.role}'
        }), 403

    # Parse request body if provided
    data = request.get_json(silent=True) or {}

    # Validate notes if provided
    notes = data.get('notes')
    if notes and (not isinstance(notes, str) or len(notes) > 1000):
        return jsonify({
            'error': 'notes must be a string with max 1000 characters'
        }), 400

    # Determine the new status (default to active)
    new_status = data.get('status', User.STATUS_ACTIVE)
    if new_status not in [User.STATUS_ACTIVE, User.STATUS_APPROVED]:
        return jsonify({
            'error': "status must be 'active' or 'approved'"
        }), 400

    # Update user status
    user.status = new_status
    user.approved_by = current_user.id
    user.approved_at = datetime.now(timezone.utc)

    # Create or update approval request record if exists
    pending_request = UserApprovalRequest.query.filter_by(
        user_id=user_id,
        status=UserApprovalRequest.STATUS_PENDING
    ).first()

    if pending_request:
        pending_request.status = UserApprovalRequest.STATUS_APPROVED
        pending_request.assigned_to = current_user.id
        pending_request.resolved_at = datetime.now(timezone.utc)
        pending_request.notes = notes

    try:
        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='user.approved',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='user',
            resource_id=user.id,
            details={
                'approved_user_id': user.id,
                'approved_user_email': user.email,
                'approved_role': user.role,
                'new_status': new_status,
                'notes': notes
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to approve user: {str(e)}'}), 500

    return jsonify({
        'message': 'User approved successfully',
        'user': user.to_dict()
    }), 200


@approvals_bp.route('/<int:user_id>/reject', methods=['POST'])
@jwt_required()
def reject_user(user_id):
    """
    Reject a pending user.

    Rejects a user that is in pending status, changing their status
    to 'rejected'.

    Args:
        user_id: The ID of the user to reject

    Request Body:
        {
            "reason": "Rejection reason" (required)
        }

    Returns:
        200: User rejected successfully
            {
                "message": "User rejected successfully",
                "user": { user data }
            }
        400: Missing or invalid rejection reason
        401: Unauthorized (missing or invalid token)
        403: Forbidden (insufficient permissions or cannot reject this role)
        404: User not found or current user not found
        409: User is not in pending status
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has general permission to reject users
    if not _can_approve_users(current_user):
        return jsonify({'error': 'Insufficient permissions to reject users'}), 403

    # Find the user to reject
    user = db.session.get(User, user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user is in pending status
    if user.status != User.STATUS_PENDING:
        return jsonify({
            'error': f"Cannot reject user: user status is '{user.status}', not 'pending'"
        }), 409

    # Check if current user can reject this specific role
    if not current_user.can_approve_role(user.role):
        return jsonify({
            'error': f'Insufficient permissions to reject users with role: {user.role}'
        }), 403

    # Parse request body
    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate rejection reason (required)
    reason = data.get('reason')
    if not reason:
        return jsonify({'error': 'reason is required'}), 400

    if not isinstance(reason, str) or len(reason) > 1000:
        return jsonify({
            'error': 'reason must be a string with max 1000 characters'
        }), 400

    reason = reason.strip()
    if not reason:
        return jsonify({'error': 'reason cannot be empty'}), 400

    # Update user status
    user.status = User.STATUS_REJECTED
    user.rejection_reason = reason

    # Update approval request record if exists
    pending_request = UserApprovalRequest.query.filter_by(
        user_id=user_id,
        status=UserApprovalRequest.STATUS_PENDING
    ).first()

    if pending_request:
        pending_request.status = UserApprovalRequest.STATUS_REJECTED
        pending_request.assigned_to = current_user.id
        pending_request.resolved_at = datetime.now(timezone.utc)
        pending_request.notes = reason

    try:
        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='user.rejected',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='user',
            resource_id=user.id,
            details={
                'rejected_user_id': user.id,
                'rejected_user_email': user.email,
                'rejected_role': user.role,
                'reason': reason
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to reject user: {str(e)}'}), 500

    return jsonify({
        'message': 'User rejected successfully',
        'user': user.to_dict()
    }), 200


@approvals_bp.route('/content/pending', methods=['GET'])
@jwt_required()
def list_pending_content_approvals():
    """
    List all content assets pending approval.

    Returns a paginated list of content assets with status 'pending_review'
    that the current user has permission to approve.

    Query Parameters:
        organization_id: Filter by organization ID (optional)
        category: Filter by content category (optional)
        page: Page number (default: 1)
        per_page: Items per page (default: 20, max: 100)

    Returns:
        200: List of pending content assets
            {
                "assets": [ { asset data }, ... ],
                "count": 5,
                "page": 1,
                "per_page": 20,
                "total": 10
            }
        401: Unauthorized (missing or invalid token)
        403: Forbidden (insufficient permissions)
        404: Current user not found
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to view pending content approvals
    if not _can_approve_content(current_user):
        return jsonify({'error': 'Insufficient permissions to view pending content approvals'}), 403

    # Build query for pending content assets
    query = ContentAsset.query.filter_by(status=ContentAsset.STATUS_PENDING_REVIEW)

    # Filter by organization if specified
    organization_id = request.args.get('organization_id')
    if organization_id:
        try:
            org_id = int(organization_id)
            query = query.filter_by(organization_id=org_id)
        except ValueError:
            return jsonify({'error': 'organization_id must be an integer'}), 400

    # Filter by category if specified
    category = request.args.get('category')
    if category:
        query = query.filter_by(category=category)

    # For non-super-admin users, optionally restrict to their organization's content
    # (Super Admins and Admins can see all, Content Managers see their org's content)
    if current_user.role == User.ROLE_CONTENT_MANAGER and current_user.organization_id:
        query = query.filter_by(organization_id=current_user.organization_id)

    # Pagination parameters
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1

    try:
        per_page = int(request.args.get('per_page', 20))
        if per_page < 1:
            per_page = 20
        if per_page > 100:
            per_page = 100
    except ValueError:
        per_page = 20

    # Get total count before pagination
    total = query.count()

    # Apply pagination and ordering (oldest first for approval queue)
    assets = query.order_by(ContentAsset.created_at.asc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return jsonify({
        'assets': [asset.to_dict() for asset in assets],
        'count': len(assets),
        'page': page,
        'per_page': per_page,
        'total': total
    }), 200


@approvals_bp.route('/content/approved', methods=['GET'])
@jwt_required()
def list_approved_content():
    """
    List all approved and published content assets.

    Returns a paginated list of content assets with status 'approved' or 'published'
    that are available for consumption by external systems like the CMS.

    This endpoint is designed for CMS integration to fetch approved content
    for playlist building without needing direct upload capability.

    Query Parameters:
        network_id: Filter by network ID (optional). Matches assets where
                   the networks JSON field contains this ID.
        organization_id: Filter by organization ID (optional)
        category: Filter by content category (optional)
        page: Page number (default: 1)
        per_page: Items per page (default: 20, max: 100)

    Returns:
        200: List of approved content assets
            {
                "assets": [ { asset data }, ... ],
                "count": 5,
                "page": 1,
                "per_page": 20,
                "total": 10
            }
        401: Unauthorized (missing or invalid token)
        404: Current user not found
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Parse network_id filter (string, used for JSON field matching)
    network_id = request.args.get('network_id')

    # Parse organization_id filter
    organization_id = request.args.get('organization_id')
    if organization_id:
        try:
            organization_id = int(organization_id)
        except ValueError:
            return jsonify({'error': 'organization_id must be an integer'}), 400

    # Parse category filter
    category = request.args.get('category')

    # Pagination parameters
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1

    try:
        per_page = int(request.args.get('per_page', 20))
        if per_page < 1:
            per_page = 20
        if per_page > 100:
            per_page = 100
    except ValueError:
        per_page = 20

    # Get approved content using the ContentService
    assets, total = ContentService.get_approved_content(
        db_session=db.session,
        network_id=network_id,
        organization_id=organization_id,
        category=category,
        page=page,
        per_page=per_page
    )

    return jsonify({
        'assets': [asset.to_dict() for asset in assets],
        'count': len(assets),
        'page': page,
        'per_page': per_page,
        'total': total
    }), 200


# =============================================================================
# Magic Link Routes Blueprint
# =============================================================================
# This blueprint handles magic link approval pages that don't require
# JWT authentication. The magic link token itself serves as authentication.

magic_link_bp = Blueprint('magic_link', __name__)


@magic_link_bp.route('/approve/<token>', methods=['GET'])
def magic_link_approval_page(token):
    """
    Display the magic link approval page for one-click content approval.

    This page allows approvers to review and approve/reject content directly
    from an email link without requiring login. The token provides authentication.

    Args:
        token: The magic link token string

    Returns:
        200: Renders the magic_link.html template with asset details
        401: Token is invalid, expired, or already used
        404: Token not found
    """
    # Look up the magic link token
    magic_token = MagicLinkToken.get_by_token(token)

    if not magic_token:
        return render_template(
            'partner/magic_link.html',
            error='Invalid or unknown approval link',
            error_type='not_found',
            token=None,
            asset=None,
            approver=None
        ), 404

    # Check if token is expired (by time)
    if magic_token.is_expired():
        # Mark it as expired if not already
        if magic_token.status == MagicLinkToken.STATUS_PENDING:
            magic_token.mark_expired()
            db.session.commit()

        return render_template(
            'partner/magic_link.html',
            error='This approval link has expired',
            error_type='expired',
            token=magic_token,
            asset=magic_token.asset,
            approver=magic_token.approver,
            expires_at=magic_token.token_expires_at
        ), 401

    # Check if token has already been used
    if magic_token.status == MagicLinkToken.STATUS_USED:
        return render_template(
            'partner/magic_link.html',
            error='This approval link has already been used',
            error_type='already_used',
            token=magic_token,
            asset=magic_token.asset,
            approver=magic_token.approver,
            action_taken=magic_token.action,
            used_at=magic_token.used_at
        ), 401

    # Check if token was manually expired
    if magic_token.status == MagicLinkToken.STATUS_EXPIRED:
        return render_template(
            'partner/magic_link.html',
            error='This approval link is no longer valid',
            error_type='expired',
            token=magic_token,
            asset=magic_token.asset,
            approver=magic_token.approver
        ), 401

    # Token is valid - fetch the asset and approver details
    asset = magic_token.asset
    approver = magic_token.approver

    # Check if asset is still pending review
    if asset.status != ContentAsset.STATUS_PENDING_REVIEW:
        # Asset has already been processed through other means
        return render_template(
            'partner/magic_link.html',
            error=f'This asset has already been {asset.status}',
            error_type='already_processed',
            token=magic_token,
            asset=asset,
            approver=approver,
            asset_status=asset.status
        ), 401

    # Check separation of duties - approver cannot approve their own upload
    is_own_upload = asset.uploaded_by == approver.id

    # Render the approval page
    return render_template(
        'partner/magic_link.html',
        error=None,
        token=magic_token,
        asset=asset,
        approver=approver,
        uploader=asset.uploader,
        organization=asset.organization,
        is_own_upload=is_own_upload,
        expires_at=magic_token.token_expires_at,
        raw_token=token  # Pass the raw token for form submission
    ), 200


@magic_link_bp.route('/approve/<token>', methods=['POST'])
def magic_link_approval_action(token):
    """
    Process approval or rejection via magic link.

    Handles the form submission from the magic link approval page to either
    approve or reject the content asset.

    Args:
        token: The magic link token string

    Form Data:
        action: 'approve' or 'reject' (required)
        reason: Rejection reason (required if action is 'reject')

    Returns:
        200: Action completed successfully (renders success template)
        400: Invalid request data
        401: Token is invalid, expired, or already used
        403: Cannot approve own upload (separation of duties)
        404: Token not found
    """
    # Look up the magic link token
    magic_token = MagicLinkToken.get_by_token(token)

    if not magic_token:
        return render_template(
            'partner/magic_link.html',
            error='Invalid or unknown approval link',
            error_type='not_found',
            token=None,
            asset=None,
            approver=None
        ), 404

    # Validate token is still valid
    if not magic_token.is_valid():
        error_type = 'already_used' if magic_token.status == MagicLinkToken.STATUS_USED else 'expired'
        error_msg = 'This approval link has already been used' if error_type == 'already_used' else 'This approval link has expired'
        return render_template(
            'partner/magic_link.html',
            error=error_msg,
            error_type=error_type,
            token=magic_token,
            asset=magic_token.asset,
            approver=magic_token.approver,
            action_taken=magic_token.action if magic_token.status == MagicLinkToken.STATUS_USED else None,
            used_at=magic_token.used_at
        ), 401

    # Get form data
    action = request.form.get('action')
    reason = request.form.get('reason', '').strip()

    # Validate action
    if action not in ['approve', 'reject']:
        return render_template(
            'partner/magic_link.html',
            error='Invalid action. Please select either Approve or Reject.',
            error_type='invalid_action',
            token=magic_token,
            asset=magic_token.asset,
            approver=magic_token.approver,
            raw_token=token
        ), 400

    # Validate rejection reason if rejecting
    if action == 'reject' and not reason:
        return render_template(
            'partner/magic_link.html',
            error='Please provide a reason for rejection.',
            error_type='missing_reason',
            token=magic_token,
            asset=magic_token.asset,
            approver=magic_token.approver,
            uploader=magic_token.asset.uploader,
            organization=magic_token.asset.organization,
            is_own_upload=magic_token.asset.uploaded_by == magic_token.approver_id,
            expires_at=magic_token.token_expires_at,
            raw_token=token
        ), 400

    asset = magic_token.asset
    approver = magic_token.approver

    # Check if asset is still pending review
    if asset.status != ContentAsset.STATUS_PENDING_REVIEW:
        return render_template(
            'partner/magic_link.html',
            error=f'This asset has already been {asset.status}',
            error_type='already_processed',
            token=magic_token,
            asset=asset,
            approver=approver,
            asset_status=asset.status
        ), 401

    # Check separation of duties - approver cannot approve their own upload
    if asset.uploaded_by == approver.id:
        return render_template(
            'partner/magic_link.html',
            error='You cannot approve your own uploaded content',
            error_type='self_approval',
            token=magic_token,
            asset=asset,
            approver=approver,
            is_own_upload=True
        ), 403

    try:
        if action == 'approve':
            # Approve the content
            result = ApprovalService.approve_content(
                db_session=db.session,
                approver_id=approver.id,
                asset_id=asset.id,
                notes='Approved via magic link'
            )

            if not result['success']:
                return render_template(
                    'partner/magic_link.html',
                    error=result['error'],
                    error_type='approval_failed',
                    token=magic_token,
                    asset=asset,
                    approver=approver,
                    raw_token=token
                ), 400

            # Mark the magic token as used
            magic_token.mark_used(MagicLinkToken.ACTION_APPROVE)

            # Expire any other pending tokens for this asset
            MagicLinkToken.expire_tokens_for_asset(asset.id)

            # Log the action
            AuditService.log_action(
                db_session=db.session,
                action='asset.approved.magic_link',
                user_id=approver.id,
                user_email=approver.email,
                resource_type='content_asset',
                resource_id=asset.id,
                details={
                    'asset_uuid': asset.uuid,
                    'asset_title': asset.title,
                    'magic_token_id': magic_token.id
                }
            )

            db.session.commit()

            return render_template(
                'partner/magic_link.html',
                success=True,
                action_taken='approved',
                token=magic_token,
                asset=asset,
                approver=approver
            ), 200

        else:  # action == 'reject'
            # Reject the content
            result = ApprovalService.reject_content(
                db_session=db.session,
                approver_id=approver.id,
                asset_id=asset.id,
                reason=reason
            )

            if not result['success']:
                return render_template(
                    'partner/magic_link.html',
                    error=result['error'],
                    error_type='rejection_failed',
                    token=magic_token,
                    asset=asset,
                    approver=approver,
                    raw_token=token
                ), 400

            # Mark the magic token as used
            magic_token.mark_used(MagicLinkToken.ACTION_REJECT, reason)

            # Expire any other pending tokens for this asset
            MagicLinkToken.expire_tokens_for_asset(asset.id)

            # Log the action
            AuditService.log_action(
                db_session=db.session,
                action='asset.rejected.magic_link',
                user_id=approver.id,
                user_email=approver.email,
                resource_type='content_asset',
                resource_id=asset.id,
                details={
                    'asset_uuid': asset.uuid,
                    'asset_title': asset.title,
                    'magic_token_id': magic_token.id,
                    'rejection_reason': reason
                }
            )

            db.session.commit()

            return render_template(
                'partner/magic_link.html',
                success=True,
                action_taken='rejected',
                rejection_reason=reason,
                token=magic_token,
                asset=asset,
                approver=approver
            ), 200

    except Exception as e:
        db.session.rollback()
        return render_template(
            'partner/magic_link.html',
            error=f'An error occurred: {str(e)}',
            error_type='server_error',
            token=magic_token,
            asset=asset,
            approver=approver,
            raw_token=token
        ), 500
