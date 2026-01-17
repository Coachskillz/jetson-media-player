"""
Partner Portal Web Routes

Blueprint for partner web page rendering:
- GET /login: Partner login page
- GET /register: Partner registration page (invitation acceptance)
- GET /register/<token>: Registration with invitation token
- GET /: Dashboard (requires auth)
- GET /assets: My assets page (requires auth)
- GET /upload: Content upload page (requires auth)
- GET /submissions: Submission tracking page (requires auth)
- GET /analytics: Performance analytics page (requires auth)
- GET /revenue: Revenue tracking page (requires auth)
- GET /profile: Profile management page (requires auth)
- GET /settings: Account settings page (requires auth)
- GET /logout: Logout handler
"""

from flask import Blueprint, render_template, request, redirect, url_for

from content_catalog.models import db, UserInvitation, User, ContentAsset, AdminSession
from content_catalog.services.auth_service import AuthService


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

    Lists all content assets uploaded by the partner/organization with filtering.
    Supports filtering by status via query parameter.

    Query Parameters:
        status: Filter by status (draft, pending_review, approved, rejected, published, archived)

    Requires authentication - redirects to login if not authenticated.

    Returns:
        Rendered assets.html template with assets list
    """
    current_user = get_current_partner()
    if not current_user:
        return redirect(url_for('partner.login'))

    # Get organization-scoped assets for this partner
    org_id = current_user.organization_id

    # Get filter parameters
    status_filter = request.args.get('status', None)

    # Base query - scoped to organization or user
    if org_id:
        query = ContentAsset.query.filter_by(organization_id=org_id)
    else:
        # If no org, get assets uploaded by this user
        query = ContentAsset.query.filter_by(uploaded_by=current_user.id)

    # Apply status filter if provided
    if status_filter and status_filter in ContentAsset.VALID_STATUSES:
        query = query.filter_by(status=status_filter)

    # Get assets ordered by creation date (newest first)
    all_assets = query.order_by(ContentAsset.created_at.desc()).all()

    # Get status counts for filter badges
    if org_id:
        base_query = ContentAsset.query.filter_by(organization_id=org_id)
    else:
        base_query = ContentAsset.query.filter_by(uploaded_by=current_user.id)

    total_count = base_query.count()
    draft_count = base_query.filter_by(status=ContentAsset.STATUS_DRAFT).count()
    pending_count = base_query.filter_by(status=ContentAsset.STATUS_PENDING_REVIEW).count()
    approved_count = base_query.filter_by(status=ContentAsset.STATUS_APPROVED).count()
    rejected_count = base_query.filter_by(status=ContentAsset.STATUS_REJECTED).count()
    published_count = base_query.filter_by(status=ContentAsset.STATUS_PUBLISHED).count()

    return render_template(
        'partner/assets.html',
        active_page='assets',
        current_user=current_user,
        pending_submissions_count=pending_count,
        assets=all_assets,
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
