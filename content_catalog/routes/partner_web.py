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

from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, redirect, url_for, jsonify

from sqlalchemy import func

from content_catalog.models import db, UserInvitation, User, ContentAsset, AdminSession, ContentApprovalRequest, Catalog, Category
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


def get_partner_tenants(user):
    """
    Get the tenants/networks associated with a partner user.

    Args:
        user: The User object

    Returns:
        List of Tenant objects the user belongs to
    """
    if not user:
        return []

    from content_catalog.models import Tenant

    tenant_ids = user.get_tenant_ids_list()
    if not tenant_ids:
        return []

    return Tenant.query.filter(Tenant.id.in_(tenant_ids)).all()


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
        elif invitation.is_expired():
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
        partner_tenants=get_partner_tenants(current_user),
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
    folder_filter = request.args.get('folder', '', type=str)

    # Use VisibilityService to get assets visible to this user
    # Include drafts since partners need to see their own drafts
    visible_assets = VisibilityService.filter_assets_for_user(
        db_session=db.session,
        user_id=current_user.id,
        include_drafts=True
    )

    # Apply folder filter
    if folder_filter == 'uncategorized':
        visible_assets = [a for a in visible_assets if a.category_id is None]
    elif folder_filter:
        try:
            fid = int(folder_filter)
            visible_assets = [a for a in visible_assets if a.category_id == fid]
        except (ValueError, TypeError):
            pass

    # Apply status filter if provided
    if status_filter and status_filter in ContentAsset.VALID_STATUSES:
        visible_assets = [a for a in visible_assets if a.status == status_filter]

    # Sort by creation date (newest first)
    visible_assets.sort(key=lambda a: a.created_at or datetime.min, reverse=True)

    # Calculate status counts from visible assets (before folder filter)
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

    # Load folders for sidebar
    default_catalog = Catalog.query.first()
    folders = []
    folder_counts = {}
    uncategorized_count = 0
    if default_catalog:
        folders = Category.query.filter_by(
            catalog_id=default_catalog.id,
            is_active=True,
            parent_id=None
        ).order_by(Category.sort_order.asc(), Category.name.asc()).all()

        # Count assets per folder (scoped to this user's visible assets)
        visible_ids = [a.id for a in all_visible]
        if visible_ids:
            counts = db.session.query(
                ContentAsset.category_id, func.count(ContentAsset.id)
            ).filter(
                ContentAsset.id.in_(visible_ids),
                ContentAsset.category_id.isnot(None)
            ).group_by(ContentAsset.category_id).all()
            folder_counts = {str(cid): cnt for cid, cnt in counts}
            uncategorized_count = len([a for a in all_visible if a.category_id is None])

    return render_template(
        'partner/assets.html',
        active_page='assets',
        current_user=current_user,
        partner_tenants=get_partner_tenants(current_user),
        pending_submissions_count=pending_count,
        assets=visible_assets,
        status_filter=status_filter,
        folder_filter=folder_filter,
        total_count=total_count,
        draft_count=draft_count,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        published_count=published_count,
        folders=folders,
        folder_counts=folder_counts,
        uncategorized_count=uncategorized_count
    )


@partner_web_bp.route('/upload')
def upload():
    """
    Content upload page.

    Allows partners to upload new content assets with metadata fields.
    Network selection depends on user role:
    - Skillz employees (admin, content_manager): All networks, multi-select
    - Advertisers: All networks, multi-select
    - Partners/Retailers: Only their assigned networks

    Requires authentication - redirects to login if not authenticated.

    Returns:
        Rendered upload.html template with upload form
    """
    from content_catalog.models import Tenant

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

    # Determine available networks based on role
    skillz_roles = [User.ROLE_SUPER_ADMIN, User.ROLE_ADMIN, User.ROLE_CONTENT_MANAGER]
    is_skillz = current_user.role in skillz_roles
    is_advertiser = current_user.role == User.ROLE_ADVERTISER

    if is_skillz or is_advertiser:
        # Skillz employees and advertisers can upload to all networks
        available_networks = Tenant.query.filter_by(is_active=True).order_by(Tenant.name).all()
        allow_multi_network = True
    else:
        # Partners can only upload to their assigned networks
        available_networks = get_partner_tenants(current_user)
        allow_multi_network = False

    # Load folders for folder picker
    default_catalog = Catalog.query.first()
    folders = []
    if default_catalog:
        folders = Category.query.filter_by(
            catalog_id=default_catalog.id,
            is_active=True,
            parent_id=None
        ).order_by(Category.sort_order.asc(), Category.name.asc()).all()

    return render_template(
        'partner/upload.html',
        active_page='upload',
        current_user=current_user,
        partner_tenants=get_partner_tenants(current_user),
        available_networks=available_networks,
        allow_multi_network=allow_multi_network,
        is_skillz=is_skillz,
        is_advertiser=is_advertiser,
        pending_submissions_count=pending_submissions_count,
        folders=folders
    )


@partner_web_bp.route('/approvals')
def approvals():
    """
    Approval queue page for venue partners.

    Shows content that has been Skillz-approved and is pending venue approval.
    Partners can approve or reject content for their venues/screens.

    Requires authentication - redirects to login if not authenticated.

    Returns:
        Rendered approvals.html template with pending venue approvals
    """
    from content_catalog.models.content_venue_approval import ContentVenueApproval

    current_user = get_current_partner()
    if not current_user:
        return redirect(url_for('partner.login'))

    # Get user's tenant IDs
    tenant_ids = current_user.get_tenant_ids_list()

    # Count pending venue approvals for badge
    pending_submissions_count = 0
    if tenant_ids:
        pending_submissions_count = ContentVenueApproval.query.filter(
            ContentVenueApproval.tenant_id.in_(tenant_ids),
            ContentVenueApproval.status == ContentVenueApproval.STATUS_PENDING_VENUE
        ).count()

    # Partners can approve content for their venues
    can_approve = len(tenant_ids) > 0

    pending_approvals = []
    if can_approve:
        # Get content pending venue approval for user's tenants
        venue_approvals = ContentVenueApproval.query.filter(
            ContentVenueApproval.tenant_id.in_(tenant_ids),
            ContentVenueApproval.status == ContentVenueApproval.STATUS_PENDING_VENUE
        ).order_by(ContentVenueApproval.created_at.desc()).all()

        # Build list with asset and tenant info
        for approval in venue_approvals:
            pending_approvals.append({
                'approval': approval,
                'asset': approval.content_asset,
                'tenant': approval.tenant
            })

    return render_template(
        'partner/approvals.html',
        active_page='approvals',
        current_user=current_user,
        partner_tenants=get_partner_tenants(current_user),
        pending_submissions_count=pending_submissions_count,
        can_approve=can_approve,
        pending_approvals=pending_approvals,
        tenant_ids=tenant_ids
    )


@partner_web_bp.route('/submissions')
def submissions():
    """
    Submission tracking page.

    Shows status of content submissions awaiting approval.

    Returns:
        Rendered submissions.html template
    """
    current_user = get_current_partner()
    if not current_user:
        return redirect(url_for('partner.login'))

    return render_template(
        'partner/base.html',
        active_page='submissions',
        current_user=current_user,
        partner_tenants=get_partner_tenants(current_user),
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
    current_user = get_current_partner()
    if not current_user:
        return redirect(url_for('partner.login'))

    return render_template(
        'partner/base.html',
        active_page='profile',
        current_user=current_user,
        partner_tenants=get_partner_tenants(current_user),
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
    current_user = get_current_partner()
    if not current_user:
        return redirect(url_for('partner.login'))

    return render_template(
        'partner/base.html',
        active_page='settings',
        current_user=current_user,
        partner_tenants=get_partner_tenants(current_user),
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
    from flask import make_response

    # Get current session and invalidate it
    session_token = request.cookies.get(PARTNER_SESSION_COOKIE)
    if session_token:
        is_valid, session = AuthService.validate_session(db.session, session_token)
        if session:
            session.is_valid = False
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

    # Clear the cookie and redirect to login
    response = make_response(redirect(url_for('partner.login')))
    response.delete_cookie(PARTNER_SESSION_COOKIE)
    return response


# =============================================================================
# Partner Portal API Routes (Session-based authentication)
# =============================================================================


@partner_web_bp.route('/api/login', methods=['POST'])
def api_login():
    """
    API endpoint for partner login.

    Authenticates a user and creates a session cookie.

    Request Body:
        {
            "email": "partner@example.com" (required),
            "password": "password" (required)
        }

    Returns:
        JSON response with login result or error
    """
    from flask import make_response

    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate email
    email = data.get('email')
    if not email:
        return jsonify({'error': 'email is required'}), 400

    if not isinstance(email, str):
        return jsonify({'error': 'email must be a string'}), 400

    email = email.lower().strip()

    # Validate password
    password = data.get('password')
    if not password:
        return jsonify({'error': 'password is required'}), 400

    if not isinstance(password, str):
        return jsonify({'error': 'password must be a string'}), 400

    # Find user by email
    user = User.query.filter_by(email=email).first()

    if not user:
        AuditService.log_action(
            db_session=db.session,
            action='partner.login_failed',
            user_email=email,
            details={'reason': 'user_not_found'}
        )
        db.session.commit()
        return jsonify({'message': 'Invalid email or password'}), 401

    # Check if account is locked
    if user.is_locked():
        AuditService.log_action(
            db_session=db.session,
            action='partner.login_failed',
            user_id=user.id,
            user_email=user.email,
            details={'reason': 'account_locked'}
        )
        db.session.commit()
        return jsonify({'message': 'Account is locked. Please try again later.'}), 401

    # Check user status - only active users can login
    if user.status != User.STATUS_ACTIVE:
        AuditService.log_action(
            db_session=db.session,
            action='partner.login_failed',
            user_id=user.id,
            user_email=user.email,
            details={'reason': f'account_status_{user.status}'}
        )
        db.session.commit()

        if user.status == User.STATUS_PENDING:
            return jsonify({'message': 'Account is pending approval'}), 401
        elif user.status == User.STATUS_SUSPENDED:
            return jsonify({'message': 'Account has been suspended'}), 401
        elif user.status == User.STATUS_DEACTIVATED:
            return jsonify({'message': 'Account has been deactivated'}), 401
        elif user.status == User.STATUS_REJECTED:
            return jsonify({'message': 'Account registration was rejected'}), 401
        else:
            return jsonify({'message': 'Account is not active'}), 401

    # Verify password
    if not AuthService.verify_password(password, user.password_hash):
        # Increment failed login attempts
        user.failed_login_attempts += 1

        # Lock account if max attempts exceeded
        if user.failed_login_attempts >= AuthService.MAX_LOGIN_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=AuthService.LOCKOUT_DURATION_MINUTES
            )

        AuditService.log_action(
            db_session=db.session,
            action='partner.login_failed',
            user_id=user.id,
            user_email=user.email,
            details={
                'reason': 'invalid_password',
                'failed_attempts': user.failed_login_attempts,
                'locked': user.failed_login_attempts >= AuthService.MAX_LOGIN_ATTEMPTS
            }
        )

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        return jsonify({'message': 'Invalid email or password'}), 401

    # Successful login - reset failed attempts and update last login
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.now(timezone.utc)

    # Create session for cookie-based auth
    session = AuthService.create_session(
        db_session=db.session,
        user_id=user.id,
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string if request.user_agent else None
    )

    # Log successful login
    AuditService.log_action(
        db_session=db.session,
        action='partner.login',
        user_id=user.id,
        user_email=user.email,
        details={'method': 'password'}
    )

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Failed to complete login: {str(e)}'}), 500

    # Create response with session cookie
    response = make_response(jsonify({
        'access_token': session.token,
        'user': user.to_dict()
    }))

    # Set session cookie (HttpOnly for security)
    response.set_cookie(
        PARTNER_SESSION_COOKIE,
        session.token,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite='Lax',
        max_age=86400 * 7  # 7 days
    )

    return response, 200


@partner_web_bp.route('/api/upload', methods=['POST'])
def api_upload():
    """
    API endpoint for partner content upload.

    Handles file upload from the partner portal.
    Creates a new content asset with the uploaded file.

    Form Data:
        file: The uploaded file (required)
        title: Content title (required)
        description: Content description (optional)
        action: 'draft' to save as draft, 'submit' to submit for review

    Returns:
        JSON response with upload result or error
    """
    import os
    import uuid as uuid_module
    from pathlib import Path
    from werkzeug.utils import secure_filename
    from flask import current_app

    current_user = get_current_partner()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    # Check for file
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Validate file type
    allowed_extensions = {'mp4', 'avi', 'mov', 'mkv', 'webm', 'jpg', 'jpeg', 'png', 'gif', 'webp'}
    file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if file_ext not in allowed_extensions:
        return jsonify({'error': f'File type not allowed. Supported: {", ".join(allowed_extensions)}'}), 400

    # Get title
    title = request.form.get('title', '').strip()
    if not title:
        title = file.filename.rsplit('.', 1)[0]

    description = request.form.get('description', '').strip()
    category = request.form.get('category', '').strip()
    tags = request.form.get('tags', '').strip()
    action = request.form.get('action', 'draft')
    folder_id = request.form.get('folder_id', '').strip()

    # Get target tenant(s)/network(s)
    # Can be multiple values for advertisers/skillz, single for partners
    tenant_ids_raw = request.form.getlist('tenant_ids')
    if not tenant_ids_raw:
        return jsonify({'error': 'Target network is required'}), 400

    # Parse and validate tenant IDs
    from content_catalog.models import Tenant
    tenant_ids = []
    for tid in tenant_ids_raw:
        try:
            tenant_ids.append(int(tid))
        except (ValueError, TypeError):
            return jsonify({'error': f'Invalid network ID: {tid}'}), 400

    # Check user permissions for these tenants
    skillz_roles = [User.ROLE_SUPER_ADMIN, User.ROLE_ADMIN, User.ROLE_CONTENT_MANAGER]
    is_skillz = current_user.role in skillz_roles
    is_advertiser = current_user.role == User.ROLE_ADVERTISER

    if not is_skillz and not is_advertiser:
        # Partners can only upload to their assigned tenants
        user_tenant_ids = current_user.get_tenant_ids_list()
        for tid in tenant_ids:
            if tid not in user_tenant_ids:
                return jsonify({'error': f'Access denied to network ID: {tid}'}), 403

    # Verify all tenants exist
    tenants = Tenant.query.filter(Tenant.id.in_(tenant_ids)).all()
    if len(tenants) != len(tenant_ids):
        return jsonify({'error': 'One or more networks not found'}), 404

    tenant_names = [t.name for t in tenants]

    # Generate unique filename
    original_filename = secure_filename(file.filename)
    unique_filename = f"{uuid_module.uuid4()}.{file_ext}"

    # Get upload path
    uploads_path = current_app.config.get('UPLOADS_PATH')
    if not uploads_path:
        uploads_path = Path(current_app.config.get('BASE_DIR', os.getcwd())) / 'uploads'

    uploads_path = Path(uploads_path)
    uploads_path.mkdir(parents=True, exist_ok=True)

    file_path = uploads_path / unique_filename

    try:
        file.save(str(file_path))
        file_size = os.path.getsize(str(file_path))

        # Determine status based on action and who is uploading
        if action == 'submit':
            if is_skillz:
                # Skillz uploading → already approved by Skillz
                status = ContentAsset.STATUS_APPROVED
            else:
                # Advertiser/Partner uploading → needs Skillz review
                status = ContentAsset.STATUS_PENDING_REVIEW
        else:
            status = ContentAsset.STATUS_DRAFT

        # Extract video duration if it's a video
        duration = None
        video_exts = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
        if file_ext in video_exts:
            try:
                import subprocess
                result = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                     '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0 and result.stdout.strip():
                    duration = int(float(result.stdout.strip()))
            except Exception:
                pass

        asset = ContentAsset(
            title=title,
            description=description,
            filename=unique_filename,
            original_filename=original_filename,
            file_path=str(file_path),
            file_size=file_size,
            format=file_ext,
            duration=duration,
            category=category if category else None,
            category_id=int(folder_id) if folder_id else None,
            tags=tags if tags else None,
            uploaded_by=current_user.id,
            organization_id=current_user.organization_id,
            status=status
        )

        db.session.add(asset)
        db.session.flush()  # Get the asset ID

        # Create ContentVenueApproval records for each target tenant
        from content_catalog.models.content_venue_approval import ContentVenueApproval
        from datetime import datetime, timezone

        for tenant in tenants:
            # Determine initial status based on who is uploading:
            # - Skillz employees: Skip Skillz approval, go directly to pending_venue
            # - Advertisers/Partners: Need Skillz approval first
            if is_skillz:
                # Skillz uploading → already Skillz-approved, needs venue approval
                venue_approval = ContentVenueApproval(
                    content_asset_id=asset.id,
                    tenant_id=tenant.id,
                    status=ContentVenueApproval.STATUS_PENDING_VENUE,
                    skillz_approved=True,
                    skillz_approved_by_id=current_user.id,
                    skillz_approved_at=datetime.now(timezone.utc)
                )
            else:
                # Advertiser/Partner uploading → needs Skillz approval first
                venue_approval = ContentVenueApproval(
                    content_asset_id=asset.id,
                    tenant_id=tenant.id,
                    status=ContentVenueApproval.STATUS_PENDING_SKILLZ
                )
            db.session.add(venue_approval)

        AuditService.log_action(
            db_session=db.session,
            action='content.uploaded',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'title': title,
                'filename': unique_filename,
                'file_size': file_size,
                'status': status,
                'tenant_ids': tenant_ids,
                'tenant_names': tenant_names
            }
        )

        db.session.commit()

        # Build response message
        if len(tenants) == 1:
            message = f'Content uploaded successfully for {tenant_names[0]}'
        else:
            message = f'Content uploaded successfully for {len(tenants)} networks'

        return jsonify({
            'success': True,
            'message': message,
            'asset': asset.to_dict(),
            'networks': [{'id': t.id, 'name': t.name} for t in tenants]
        }), 201

    except Exception as e:
        db.session.rollback()
        if file_path.exists():
            os.remove(str(file_path))
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500


@partner_web_bp.route('/api/venue-approval/<int:approval_id>/approve', methods=['POST'])
def api_venue_approve(approval_id):
    """
    API endpoint for partners to approve content for their venue.

    This is the second stage of the two-stage approval workflow.
    When approved, content is synced to the CMS for display on screens.

    Args:
        approval_id: ID of the ContentVenueApproval record

    Returns:
        JSON response with approval result or error
    """
    from content_catalog.models.content_venue_approval import ContentVenueApproval
    from content_catalog.services.cms_transfer_service import CMSTransferService

    current_user = get_current_partner()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    # Get the approval record
    approval = db.session.get(ContentVenueApproval, approval_id)
    if not approval:
        return jsonify({'error': 'Approval record not found'}), 404

    # Check if user has access to this tenant
    tenant_ids = current_user.get_tenant_ids_list()
    if approval.tenant_id not in tenant_ids:
        return jsonify({'error': 'Access denied to this venue'}), 403

    # Check if it's pending venue approval
    if approval.status != ContentVenueApproval.STATUS_PENDING_VENUE:
        return jsonify({'error': f"Cannot approve: status is '{approval.status}'"}), 400

    try:
        # Approve the venue approval
        approval.approve_venue(current_user.id)

        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='content.venue_approved',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_venue_approval',
            resource_id=approval.id,
            details={
                'content_asset_id': approval.content_asset_id,
                'tenant_id': approval.tenant_id,
                'asset_title': approval.content_asset.title if approval.content_asset else None
            }
        )

        db.session.commit()

        # Sync to CMS now that it's fully approved
        sync_result = {'synced': False}
        try:
            asset = approval.content_asset
            tenant = approval.tenant
            sync_result = CMSTransferService.transfer_to_cms(asset, tenant)
            if sync_result.get('success'):
                asset.synced_to_cms = True
                if sync_result.get('cms_content_id'):
                    asset.cms_content_id = sync_result.get('cms_content_id')
                db.session.commit()
                sync_result['synced'] = True
        except Exception as sync_error:
            # Log sync error but don't fail the approval
            print(f"CMS sync error: {sync_error}")
            sync_result = {'synced': False, 'error': str(sync_error)}

        return jsonify({
            'success': True,
            'message': 'Content approved for your venue and synced to CMS',
            'approval': approval.to_dict(),
            'cms_sync': sync_result
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to approve: {str(e)}'}), 500


@partner_web_bp.route('/api/venue-approval/<int:approval_id>/reject', methods=['POST'])
def api_venue_reject(approval_id):
    """
    API endpoint for partners to reject content for their venue.

    Args:
        approval_id: ID of the ContentVenueApproval record

    Returns:
        JSON response with rejection result or error
    """
    from content_catalog.models.content_venue_approval import ContentVenueApproval

    current_user = get_current_partner()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    # Get the approval record
    approval = db.session.get(ContentVenueApproval, approval_id)
    if not approval:
        return jsonify({'error': 'Approval record not found'}), 404

    # Check if user has access to this tenant
    tenant_ids = current_user.get_tenant_ids_list()
    if approval.tenant_id not in tenant_ids:
        return jsonify({'error': 'Access denied to this venue'}), 403

    # Check if it's pending venue approval
    if approval.status != ContentVenueApproval.STATUS_PENDING_VENUE:
        return jsonify({'error': f"Cannot reject: status is '{approval.status}'"}), 400

    # Get rejection reason
    data = request.get_json(silent=True) or {}
    reason = data.get('reason', '').strip()

    try:
        # Reject the venue approval
        approval.reject_venue(current_user.id, reason)

        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='content.venue_rejected',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='content_venue_approval',
            resource_id=approval.id,
            details={
                'content_asset_id': approval.content_asset_id,
                'tenant_id': approval.tenant_id,
                'asset_title': approval.content_asset.title if approval.content_asset else None,
                'reason': reason
            }
        )

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Content rejected for your venue',
            'approval': approval.to_dict()
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to reject: {str(e)}'}), 500


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


# =============================================================================
# Partner Folder Management API Routes
# =============================================================================


@partner_web_bp.route('/api/folders', methods=['GET'])
def api_list_folders():
    """List all folders for the partner."""
    current_user = get_current_partner()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    default_catalog = Catalog.query.first()
    if not default_catalog:
        return jsonify({'folders': [], 'count': 0})

    folders = Category.query.filter_by(
        catalog_id=default_catalog.id,
        is_active=True,
        parent_id=None
    ).order_by(Category.sort_order.asc(), Category.name.asc()).all()

    return jsonify({
        'folders': [f.to_dict(include_children=True) for f in folders],
        'count': len(folders)
    })


@partner_web_bp.route('/api/folders', methods=['POST'])
def api_create_folder():
    """Create a new folder."""
    current_user = get_current_partner()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Folder name is required'}), 400

    default_catalog = Catalog.query.first()
    if not default_catalog:
        return jsonify({'error': 'No catalog exists'}), 500

    folder = Category(
        name=name,
        catalog_id=default_catalog.id,
        parent_id=None,
        description=data.get('description', ''),
        sort_order=data.get('sort_order', 0)
    )

    db.session.add(folder)
    db.session.commit()

    AuditService.log_action(
        db_session=db.session,
        action='folder.created',
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type='category',
        resource_id=folder.id,
        details={'name': name}
    )
    db.session.commit()

    return jsonify(folder.to_dict()), 201


@partner_web_bp.route('/api/folders/<int:folder_id>', methods=['PUT'])
def api_update_folder(folder_id):
    """Rename a folder."""
    current_user = get_current_partner()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    folder = db.session.get(Category, folder_id)
    if not folder:
        return jsonify({'error': 'Folder not found'}), 404

    data = request.get_json()
    if 'name' in data:
        folder.name = data['name'].strip()
    if 'description' in data:
        folder.description = data['description']

    db.session.commit()
    return jsonify(folder.to_dict())


@partner_web_bp.route('/api/folders/<int:folder_id>', methods=['DELETE'])
def api_delete_folder(folder_id):
    """Delete a folder. Assets become uncategorized."""
    current_user = get_current_partner()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    folder = db.session.get(Category, folder_id)
    if not folder:
        return jsonify({'error': 'Folder not found'}), 404

    ContentAsset.query.filter_by(category_id=folder_id).update(
        {'category_id': None}, synchronize_session='fetch'
    )
    Category.query.filter_by(parent_id=folder_id).update(
        {'parent_id': None}, synchronize_session='fetch'
    )

    folder_name = folder.name
    db.session.delete(folder)
    db.session.commit()

    AuditService.log_action(
        db_session=db.session,
        action='folder.deleted',
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type='category',
        resource_id=folder_id,
        details={'name': folder_name}
    )
    db.session.commit()

    return jsonify({'success': True, 'message': f'Folder "{folder_name}" deleted'})


@partner_web_bp.route('/api/assets/<int:asset_id>/move', methods=['POST'])
def api_move_asset(asset_id):
    """Move an asset into a folder."""
    current_user = get_current_partner()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    asset = db.session.get(ContentAsset, asset_id)
    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    data = request.get_json() or {}
    folder_id = data.get('folder_id')

    if folder_id:
        folder = db.session.get(Category, int(folder_id))
        if not folder:
            return jsonify({'error': 'Folder not found'}), 404
        asset.category_id = folder.id
    else:
        asset.category_id = None

    db.session.commit()
    return jsonify({'success': True, 'category_id': asset.category_id})
