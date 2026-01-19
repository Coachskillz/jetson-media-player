"""
Partner Portal Web Routes

Blueprint for partner web page rendering:
- GET /login: Partner login page
- GET /register: Partner registration page (invitation acceptance)
- GET /register/<token>: Registration with invitation token
- GET /: Dashboard (requires auth)
- GET /assets: My assets page (requires auth)
- GET /upload: Content upload page (requires auth)
- GET /approvals: Approval queue page (requires auth + approval permission)
- GET /submissions: Submission tracking page (requires auth)
- GET /analytics: Performance analytics page (requires auth)
- GET /revenue: Revenue tracking page (requires auth)
- GET /profile: Profile management page (requires auth)
- GET /settings: Account settings page (requires auth)
- GET /logout: Logout handler

Partner Portal API Routes (session-based authentication):
- POST /api/approvals/<uuid>/approve: Approve a pending content asset
- POST /api/approvals/<uuid>/reject: Reject a pending content asset
"""

from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, jsonify

from content_catalog.models import db, UserInvitation, User, ContentAsset, AdminSession, ContentApprovalRequest
from content_catalog.services.auth_service import AuthService
from content_catalog.services.audit_service import AuditService
from content_catalog.services.visibility_service import VisibilityService


# Session cookie name for partner portal
PARTNER_SESSION_COOKIE = 'partner_session'


def get_current_partner():
    """
    Get the current authenticated partner user from the session cookie.

    Validates the session token from the cookie and returns the associated user
    if the session is valid and the user has partner or advertiser role.

    Returns:
        User: The authenticated user, or None if not authenticated
    """
    session_token = request.cookies.get(PARTNER_SESSION_COOKIE)
    if not session_token:
        return None

    is_valid, session = AuthService.validate_session(db.session, session_token)
    if not is_valid or not session:
        return None

    user = User.query.get(session.user_id)
    if not user or user.status != User.STATUS_ACTIVE:
        return None

    # Verify user has partner-level access
    partner_roles = [User.ROLE_PARTNER, User.ROLE_ADVERTISER]
    if user.role not in partner_roles:
        return None

    db.session.commit()  # Commit the last_activity update
    return user


# Create partner web blueprint (registered at /partner prefix in app.py)
partner_web_bp = Blueprint(
    'partner',
    __name__,
    template_folder='../templates/partner'
)


@partner_web_bp.route('/login')
def login():
    """
    Partner login page.

    Displays the login form for partner portal authentication.
    If already logged in, redirects to dashboard.

    Returns:
        Rendered login.html template
    """
    return render_template('partner/login.html')


@partner_web_bp.route('/register')
@partner_web_bp.route('/register/<token>')
def register(token=None):
    """
    Partner registration page for invitation acceptance.

    Displays the registration form for new partners who have been invited.
    The token parameter is used to pre-fill invitation details.

    Args:
        token: Optional invitation token from email link

    Returns:
        Rendered register.html template with invitation data if token is valid
    """
    invitation = None
    error = None

    if token:
        # Look up invitation by token
        invitation = UserInvitation.query.filter_by(token=token).first()

        if not invitation:
            error = 'Invalid invitation link. Please contact your administrator.'
        elif invitation.status == UserInvitation.STATUS_ACCEPTED:
            error = 'This invitation has already been used. Please log in instead.'
        elif invitation.status == UserInvitation.STATUS_REVOKED:
            error = 'This invitation has been revoked. Please contact your administrator.'
        elif invitation.is_expired:
            error = 'This invitation has expired. Please request a new invitation.'

    return render_template(
        'partner/register.html',
        invitation=invitation,
        token=token,
        error=error
    )


@partner_web_bp.route('/')
def dashboard():
    """
    Partner dashboard page.

    Displays overview with stats for:
    - Total assets uploaded
    - Pending submissions
    - Published content count
    - Draft content count

    Requires authentication - redirects to login if not authenticated.

    Returns:
        Rendered dashboard.html template with stats
    """
    current_user = get_current_partner()
    if not current_user:
        return redirect(url_for('partner.login'))

    # Get organization-scoped stats for this partner
    org_id = current_user.organization_id

    # Count total assets
    if org_id:
        total_assets = ContentAsset.query.filter_by(
            organization_id=org_id
        ).count()
    else:
        # If no org, count assets uploaded by this user
        total_assets = ContentAsset.query.filter_by(
            uploaded_by=current_user.id
        ).count()

    # Count pending submissions
    if org_id:
        pending_submissions_count = ContentAsset.query.filter_by(
            organization_id=org_id,
            status=ContentAsset.STATUS_PENDING_REVIEW
        ).count()
    else:
        pending_submissions_count = ContentAsset.query.filter_by(
            uploaded_by=current_user.id,
            status=ContentAsset.STATUS_PENDING_REVIEW
        ).count()

    # Count published content
    if org_id:
        published_count = ContentAsset.query.filter_by(
            organization_id=org_id,
            status=ContentAsset.STATUS_PUBLISHED
        ).count()
    else:
        published_count = ContentAsset.query.filter_by(
            uploaded_by=current_user.id,
            status=ContentAsset.STATUS_PUBLISHED
        ).count()

    # Count drafts
    if org_id:
        draft_count = ContentAsset.query.filter_by(
            organization_id=org_id,
            status=ContentAsset.STATUS_DRAFT
        ).count()
    else:
        draft_count = ContentAsset.query.filter_by(
            uploaded_by=current_user.id,
            status=ContentAsset.STATUS_DRAFT
        ).count()

    # Get pending assets for the list (up to 10)
    if org_id:
        pending_assets = ContentAsset.query.filter_by(
            organization_id=org_id,
            status=ContentAsset.STATUS_PENDING_REVIEW
        ).order_by(ContentAsset.created_at.desc()).limit(10).all()
    else:
        pending_assets = ContentAsset.query.filter_by(
            uploaded_by=current_user.id,
            status=ContentAsset.STATUS_PENDING_REVIEW
        ).order_by(ContentAsset.created_at.desc()).limit(10).all()

    return render_template(
        'partner/dashboard.html',
        active_page='dashboard',
        current_user=current_user,
        total_assets=total_assets,
        pending_submissions_count=pending_submissions_count,
        published_count=published_count,
        draft_count=draft_count,
        pending_assets=pending_assets,
        recent_activity=None
    )


@partner_web_bp.route('/assets')
def assets():
    """
    My assets page.

    Lists all content assets visible to the partner based on visibility rules.
    Uses VisibilityService to apply org-type based filtering:
    - SKILLZ users see all assets
    - RETAILER users see tenant assets (non-internal)
    - BRAND users see only their own organization's assets
    - AGENCY users see assets from brands in their allowed_brand_ids

    Supports filtering by status via query parameter.

    Query Parameters:
        status: Filter by status (draft, pending_review, approved, rejected, published, archived)

    Requires authentication - redirects to login if not authenticated.

    Returns:
        Rendered assets.html template with visibility-filtered assets list
    """
    current_user = get_current_partner()
    if not current_user:
        return redirect(url_for('partner.login'))

    # Get filter parameters
    status_filter = request.args.get('status', None)

    # Use VisibilityService to get assets visible to this user
    # Include drafts since partners need to see their own drafts
    visible_assets = VisibilityService.filter_assets_for_user(
        db_session=db.session,
        user_id=current_user.id,
        include_drafts=True
    )

    # Apply status filter if provided
    if status_filter and status_filter in ContentAsset.VALID_STATUSES:
        visible_assets = [a for a in visible_assets if a.status == status_filter]

    # Sort by creation date (newest first)
    visible_assets.sort(key=lambda a: a.created_at or datetime.min, reverse=True)

    # Calculate status counts from visible assets
    all_visible = VisibilityService.filter_assets_for_user(
        db_session=db.session,
        user_id=current_user.id,
        include_drafts=True
    )

    total_count = len(all_visible)
    draft_count = len([a for a in all_visible if a.status == ContentAsset.STATUS_DRAFT])
    pending_count = len([a for a in all_visible if a.status == ContentAsset.STATUS_PENDING_REVIEW])
    approved_count = len([a for a in all_visible if a.status == ContentAsset.STATUS_APPROVED])
    rejected_count = len([a for a in all_visible if a.status == ContentAsset.STATUS_REJECTED])
    published_count = len([a for a in all_visible if a.status == ContentAsset.STATUS_PUBLISHED])

    return render_template(
        'partner/assets.html',
        active_page='assets',
        current_user=current_user,
        pending_submissions_count=pending_count,
        assets=visible_assets,
        status_filter=status_filter,
        total_count=total_count,
        draft_count=draft_count,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        published_count=published_count
    )


@partner_web_bp.route('/upload')
def upload():
    """
    Content upload page.

    Allows partners to upload new content assets with metadata fields.
    Partners can save content as draft or submit for review.

    Requires authentication - redirects to login if not authenticated.

    Returns:
        Rendered upload.html template with upload form
    """
    current_user = get_current_partner()
    if not current_user:
        return redirect(url_for('partner.login'))

    # Get pending submissions count for sidebar badge
    org_id = current_user.organization_id
    if org_id:
        pending_submissions_count = ContentAsset.query.filter_by(
            organization_id=org_id,
            status=ContentAsset.STATUS_PENDING_REVIEW
        ).count()
    else:
        pending_submissions_count = ContentAsset.query.filter_by(
            uploaded_by=current_user.id,
            status=ContentAsset.STATUS_PENDING_REVIEW
        ).count()

    return render_template(
        'partner/upload.html',
        active_page='upload',
        current_user=current_user,
        pending_submissions_count=pending_submissions_count
    )


@partner_web_bp.route('/approvals')
def approvals():
    """
    Approval queue page.

    Shows content assets pending approval for users with approval permissions.
    Allows approvers to approve or reject pending content.

    Requires authentication - redirects to login if not authenticated.
    Shows permission warning if user doesn't have approval permission.

    Returns:
        Rendered approvals.html template with pending approvals list
    """
    current_user = get_current_partner()
    if not current_user:
        return redirect(url_for('partner.login'))

    # Get pending submissions count for sidebar badge
    org_id = current_user.organization_id
    if org_id:
        pending_submissions_count = ContentAsset.query.filter_by(
            organization_id=org_id,
            status=ContentAsset.STATUS_PENDING_REVIEW
        ).count()
    else:
        pending_submissions_count = ContentAsset.query.filter_by(
            uploaded_by=current_user.id,
            status=ContentAsset.STATUS_PENDING_REVIEW
        ).count()

    # Check if user has permission to approve content
    can_approve = current_user.can_approve_assets and current_user.role in [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER
    ]

    pending_approvals = []
    if can_approve:
        # Get pending content assets that this user can approve
        # Exclude assets uploaded by this user (separation of duties)
        query = ContentAsset.query.filter(
            ContentAsset.status == ContentAsset.STATUS_PENDING_REVIEW,
            ContentAsset.uploaded_by != current_user.id  # Exclude own uploads
        )

        # For Content Managers, optionally restrict to their organization's content
        if current_user.role == User.ROLE_CONTENT_MANAGER and current_user.organization_id:
            query = query.filter(ContentAsset.organization_id == current_user.organization_id)

        pending_approvals = query.order_by(ContentAsset.created_at.asc()).all()

    return render_template(
        'partner/approvals.html',
        active_page='approvals',
        current_user=current_user,
        pending_submissions_count=pending_submissions_count,
        can_approve=can_approve,
        pending_approvals=pending_approvals
    )


@partner_web_bp.route('/submissions')
def submissions():
    """
    Submission tracking page.

    Shows status of content submissions awaiting approval.

    Returns:
        Rendered submissions.html template
    """
    # Placeholder - will be implemented with auth check
    return render_template(
        'partner/base.html',
        active_page='submissions',
        current_user=None,
        pending_submissions_count=0
    )


@partner_web_bp.route('/analytics')
def analytics():
    """
    Performance analytics page.

    Displays content performance metrics and analytics.

    Returns:
        Rendered analytics.html template
    """
    # Placeholder - will be implemented with auth check
    return render_template(
        'partner/base.html',
        active_page='analytics',
        current_user=None,
        pending_submissions_count=0
    )


@partner_web_bp.route('/revenue')
def revenue():
    """
    Revenue tracking page.

    Shows revenue information and payment history.

    Returns:
        Rendered revenue.html template
    """
    # Placeholder - will be implemented with auth check
    return render_template(
        'partner/base.html',
        active_page='revenue',
        current_user=None,
        pending_submissions_count=0
    )


@partner_web_bp.route('/profile')
def profile():
    """
    Profile management page.

    Allows partners to view and update their profile.

    Returns:
        Rendered profile.html template
    """
    # Placeholder - will be implemented with auth check
    return render_template(
        'partner/base.html',
        active_page='profile',
        current_user=None,
        pending_submissions_count=0
    )


@partner_web_bp.route('/settings')
def settings():
    """
    Account settings page.

    Allows partners to configure account settings.

    Returns:
        Rendered settings.html template
    """
    # Placeholder - will be implemented with auth check
    return render_template(
        'partner/base.html',
        active_page='settings',
        current_user=None,
        pending_submissions_count=0
    )


@partner_web_bp.route('/logout')
def logout():
    """
    Logout handler.

    Clears the session and redirects to login page.

    Returns:
        Redirect to login page
    """
    # Placeholder - will be implemented with session handling
    return render_template('partner/login.html')


# =============================================================================
# Partner Portal API Routes (Session-based authentication)
# =============================================================================


@partner_web_bp.route('/api/approvals/<asset_uuid>/approve', methods=['POST'])
def api_approve_asset(asset_uuid):
    """
    API endpoint to approve a content asset.

    Approves a pending content asset, changing its status from 'pending_review'
    to 'approved'. Only users with approval permissions can use this endpoint.

    Separation of duties: Users cannot approve their own uploaded content.

    Args:
        asset_uuid: UUID of the asset to approve

    Returns:
        JSON response with approval result or error
    """
    current_user = get_current_partner()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    # Check if user has permission to approve content
    can_approve = current_user.can_approve_assets and current_user.role in [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER
    ]

    if not can_approve:
        return jsonify({'error': 'Insufficient permissions to approve content'}), 403

    # Find the asset by UUID
    asset = ContentAsset.query.filter_by(uuid=asset_uuid).first()
    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Check if asset is pending review
    if asset.status != ContentAsset.STATUS_PENDING_REVIEW:
        return jsonify({
            'error': f"Cannot approve asset: status is '{asset.status}'. Only 'pending_review' assets can be approved."
        }), 409

    # Prevent self-approval (separation of duties)
    if asset.uploaded_by == current_user.id:
        return jsonify({
            'error': 'Users cannot approve their own uploaded content'
        }), 403

    # Parse optional notes from request
    data = request.get_json(silent=True) or {}
    notes = data.get('notes', '')

    # Update asset status
    asset.status = ContentAsset.STATUS_APPROVED
    asset.reviewed_by = current_user.id
    asset.reviewed_at = datetime.now(timezone.utc)
    if notes:
        asset.review_notes = notes

    try:
        # Log the audit event
        AuditService.log_action(
            db_session=db.session,
            action='content.approved',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'asset_uuid': asset.uuid,
                'asset_title': asset.title,
                'notes': notes
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to approve asset: {str(e)}'}), 500

    return jsonify({
        'message': 'Asset approved successfully',
        'asset': asset.to_dict()
    }), 200


@partner_web_bp.route('/api/approvals/<asset_uuid>/reject', methods=['POST'])
def api_reject_asset(asset_uuid):
    """
    API endpoint to reject a content asset.

    Rejects a pending content asset, changing its status from 'pending_review'
    to 'rejected'. Only users with approval permissions can use this endpoint.
    A rejection reason is required.

    Args:
        asset_uuid: UUID of the asset to reject

    Returns:
        JSON response with rejection result or error
    """
    current_user = get_current_partner()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    # Check if user has permission to reject content
    can_approve = current_user.can_approve_assets and current_user.role in [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN,
        User.ROLE_CONTENT_MANAGER
    ]

    if not can_approve:
        return jsonify({'error': 'Insufficient permissions to reject content'}), 403

    # Find the asset by UUID
    asset = ContentAsset.query.filter_by(uuid=asset_uuid).first()
    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Check if asset is pending review
    if asset.status != ContentAsset.STATUS_PENDING_REVIEW:
        return jsonify({
            'error': f"Cannot reject asset: status is '{asset.status}'. Only 'pending_review' assets can be rejected."
        }), 409

    # Parse request body
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate rejection reason (required)
    reason = data.get('reason')
    if not reason:
        return jsonify({'error': 'Rejection reason is required'}), 400

    if not isinstance(reason, str) or len(reason) > 1000:
        return jsonify({
            'error': 'reason must be a string with max 1000 characters'
        }), 400

    reason = reason.strip()
    if not reason:
        return jsonify({'error': 'Rejection reason cannot be empty'}), 400

    # Update asset status
    asset.status = ContentAsset.STATUS_REJECTED
    asset.reviewed_by = current_user.id
    asset.reviewed_at = datetime.now(timezone.utc)
    asset.review_notes = reason

    try:
        # Log the audit event
        AuditService.log_action(
            db_session=db.session,
            action='content.rejected',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'asset_uuid': asset.uuid,
                'asset_title': asset.title,
                'reason': reason
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to reject asset: {str(e)}'}), 500

    return jsonify({
        'message': 'Asset rejected successfully',
        'asset': asset.to_dict()
    }), 200


@partner_web_bp.route('/api/assets/<asset_uuid>/submit', methods=['POST'])
def api_submit_asset(asset_uuid):
    """
    API endpoint to submit a content asset for review.

    Changes the asset status from 'draft' or 'rejected' to 'pending_review'.
    Creates a content approval request for tracking the workflow.

    Args:
        asset_uuid: UUID of the asset to submit

    Request Body (optional):
        {
            "notes": "Submission notes" (optional, max 1000 chars)
        }

    Returns:
        JSON response with submission result or error
    """
    current_user = get_current_partner()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    # Find the asset by UUID
    asset = ContentAsset.query.filter_by(uuid=asset_uuid).first()
    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Verify user can access this asset (visibility check)
    can_view, reason = VisibilityService.can_view_asset(
        db_session=db.session,
        user_id=current_user.id,
        asset_id=asset.id
    )
    if not can_view:
        return jsonify({'error': 'Access denied to this asset'}), 403

    # Check if asset can be submitted for review
    if not asset.can_submit_for_review():
        return jsonify({
            'error': f"Cannot submit asset: status is '{asset.status}'. Only 'draft' or 'rejected' assets can be submitted for review."
        }), 409

    # Parse request body if provided
    data = request.get_json(silent=True) or {}

    # Validate notes if provided
    notes = data.get('notes')
    if notes and (not isinstance(notes, str) or len(notes) > 1000):
        return jsonify({
            'error': 'notes must be a string with max 1000 characters'
        }), 400

    # Update asset status
    previous_status = asset.status
    asset.status = ContentAsset.STATUS_PENDING_REVIEW

    # Create content approval request for tracking
    approval_request = ContentApprovalRequest(
        asset_id=asset.id,
        requested_by=current_user.id,
        status=ContentApprovalRequest.STATUS_PENDING,
        notes=notes
    )

    try:
        db.session.add(approval_request)

        # Log the audit event
        AuditService.log_action(
            db_session=db.session,
            action='content.submitted',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'asset_uuid': asset.uuid,
                'asset_title': asset.title,
                'previous_status': previous_status,
                'new_status': asset.status,
                'notes': notes
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to submit asset: {str(e)}'}), 500

    return jsonify({
        'message': 'Asset submitted for review',
        'asset': asset.to_dict()
    }), 200
