"""
Admin Portal Web Routes

Blueprint for admin web page rendering:
- GET /login: Admin login page
- GET /: Dashboard (requires auth)
- GET /users: User management page (requires auth)
- GET /organizations: Organization management page (requires auth)
- GET /assets: Asset management page (requires auth)
- GET /approvals: Approval workflow page (requires auth)
- GET /invitations: Invitation management page (requires auth)
- GET /audit-logs: Audit log viewing page (requires auth)
- GET /settings: System settings page (requires auth)
- GET /logout: Logout handler
"""

from datetime import datetime, timezone

from flask import Blueprint, render_template
from sqlalchemy import or_

from content_catalog.models import (
    db, User, Organization, ContentAsset,
    UserApprovalRequest, ContentApprovalRequest, AuditLog
)


# Create admin web blueprint (registered at /admin prefix in app.py)
admin_web_bp = Blueprint(
    'admin',
    __name__,
    template_folder='../templates/admin'
)


@admin_web_bp.route('/login')
def login():
    """
    Admin login page.

    Displays the login form for admin portal authentication.
    If already logged in, redirects to dashboard.

    Returns:
        Rendered login.html template
    """
    return render_template('admin/login.html')


def _format_time_ago(dt):
    """
    Format a datetime as a human-readable "time ago" string.

    Args:
        dt: datetime object to format

    Returns:
        String like "Just now", "5 minutes ago", "2 hours ago", etc.
    """
    if dt is None:
        return "Unknown"

    now = datetime.now(timezone.utc)
    # Handle naive datetimes by assuming UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    diff = now - dt
    seconds = diff.total_seconds()

    if seconds < 60:
        return "Just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    else:
        return dt.strftime("%b %d, %Y")


@admin_web_bp.route('/')
def dashboard():
    """
    Admin dashboard page.

    Displays system overview with stats for:
    - Total users, organizations, assets
    - Pending approvals count
    - Recent activity summary

    Returns:
        Rendered dashboard.html template with stats
    """
    # Gather stats
    stats = {
        'total_users': User.query.count(),
        'active_users': User.query.filter_by(status=User.STATUS_ACTIVE).count(),
        'total_organizations': Organization.query.count(),
        'active_organizations': Organization.query.filter_by(status='active').count(),
        'total_assets': ContentAsset.query.count(),
        'published_assets': ContentAsset.query.filter_by(
            status=ContentAsset.STATUS_PUBLISHED
        ).count(),
        'pending_approvals': (
            UserApprovalRequest.query.filter_by(
                status=UserApprovalRequest.STATUS_PENDING
            ).count() +
            ContentApprovalRequest.query.filter_by(
                status=ContentApprovalRequest.STATUS_PENDING
            ).count()
        )
    }

    # Get recent activity from audit logs
    recent_logs = AuditLog.query.order_by(
        AuditLog.created_at.desc()
    ).limit(10).all()

    recent_activity = []
    for log in recent_logs:
        # Format action into human-readable description
        action_descriptions = {
            'user.login': 'User logged in',
            'user.logout': 'User logged out',
            'user.created': 'New user registered',
            'user.approved': 'User approved',
            'user.rejected': 'User rejected',
            'user.suspended': 'User suspended',
            'content.uploaded': 'Content uploaded',
            'content.approved': 'Content approved',
            'content.rejected': 'Content rejected',
            'content.deleted': 'Content deleted',
            'organization.created': 'Organization created',
            'invitation.sent': 'Invitation sent',
        }
        description = action_descriptions.get(log.action, log.action.replace('.', ' ').title())

        recent_activity.append({
            'description': description,
            'time_ago': _format_time_ago(log.created_at),
            'user_email': log.user_email
        })

    # Get pending users needing approval
    pending_users = User.query.filter_by(status=User.STATUS_PENDING).all()

    # Get pending content needing review
    pending_content = ContentAsset.query.filter_by(
        status=ContentAsset.STATUS_PENDING_REVIEW
    ).all()

    return render_template(
        'admin/dashboard.html',
        active_page='dashboard',
        current_user=None,
        pending_approvals_count=stats['pending_approvals'],
        stats=stats,
        recent_activity=recent_activity,
        pending_users=pending_users,
        pending_content=pending_content
    )


@admin_web_bp.route('/users')
def users():
    """
    User management page.

    Lists all users with filtering and search capabilities.
    Supports pagination and filtering by status, role, and search term.

    Query Parameters:
        status: Filter by user status (pending, active, suspended, etc.)
        role: Filter by user role (admin, partner, etc.)
        search: Search by name or email
        page: Page number (default: 1)
        per_page: Items per page (default: 20)

    Returns:
        Rendered users.html template with user data
    """
    from flask import request

    # Get filter parameters
    status_filter = request.args.get('status', '')
    role_filter = request.args.get('role', '')
    search_query = request.args.get('search', '').strip()

    # Get pagination parameters
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

    # Build query
    query = User.query

    # Apply status filter
    if status_filter and status_filter in User.VALID_STATUSES:
        query = query.filter_by(status=status_filter)

    # Apply role filter
    if role_filter and role_filter in User.VALID_ROLES:
        query = query.filter_by(role=role_filter)

    # Apply search filter (name or email)
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            or_(
                User.name.ilike(search_pattern),
                User.email.ilike(search_pattern)
            )
        )

    # Get total count before pagination
    total = query.count()

    # Calculate total pages
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    # Apply ordering and pagination
    users_list = query.order_by(User.created_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    # Gather stats
    stats = {
        'total_users': User.query.count(),
        'active_users': User.query.filter_by(status=User.STATUS_ACTIVE).count(),
        'pending_users': User.query.filter_by(status=User.STATUS_PENDING).count(),
        'suspended_users': User.query.filter_by(status=User.STATUS_SUSPENDED).count(),
    }

    # Get pending approvals count for badge
    pending_approvals = (
        UserApprovalRequest.query.filter_by(
            status=UserApprovalRequest.STATUS_PENDING
        ).count() +
        ContentApprovalRequest.query.filter_by(
            status=ContentApprovalRequest.STATUS_PENDING
        ).count()
    )

    return render_template(
        'admin/users.html',
        active_page='users',
        current_user=None,
        pending_approvals_count=pending_approvals,
        users=users_list,
        stats=stats,
        # Pagination info
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        # Current filters
        status_filter=status_filter,
        role_filter=role_filter,
        search_query=search_query,
        # Available options
        valid_statuses=User.VALID_STATUSES,
        valid_roles=User.VALID_ROLES
    )


@admin_web_bp.route('/organizations')
def organizations():
    """
    Organization management page.

    Lists all organizations with their details.

    Returns:
        Rendered organizations.html template
    """
    # Placeholder - will be implemented with auth check
    return render_template(
        'admin/base.html',
        active_page='organizations',
        current_user=None,
        pending_approvals_count=0
    )


@admin_web_bp.route('/assets')
def assets():
    """
    Asset management page.

    Lists all content assets with preview capabilities.

    Returns:
        Rendered assets.html template
    """
    # Placeholder - will be implemented with auth check
    return render_template(
        'admin/base.html',
        active_page='assets',
        current_user=None,
        pending_approvals_count=0
    )


@admin_web_bp.route('/approvals')
def approvals():
    """
    Approval workflow page.

    Shows pending user and content approvals.

    Returns:
        Rendered approvals.html template
    """
    # Placeholder - will be implemented with auth check
    return render_template(
        'admin/base.html',
        active_page='approvals',
        current_user=None,
        pending_approvals_count=0
    )


@admin_web_bp.route('/invitations')
def invitations():
    """
    Invitation management page.

    Lists all sent invitations and allows creating new ones.

    Returns:
        Rendered invitations.html template
    """
    # Placeholder - will be implemented with auth check
    return render_template(
        'admin/base.html',
        active_page='invitations',
        current_user=None,
        pending_approvals_count=0
    )


@admin_web_bp.route('/audit-logs')
def audit_logs():
    """
    Audit log viewing page.

    Displays system audit logs with filtering by action, user, and date range.

    Query Parameters:
        action: Filter by action type (e.g., 'user.login', 'content.uploaded')
        user: Filter by user email (search pattern)
        date_from: Filter logs from this date (YYYY-MM-DD)
        date_to: Filter logs to this date (YYYY-MM-DD)
        page: Page number (default: 1)
        per_page: Items per page (default: 50)

    Returns:
        Rendered audit.html template with log data
    """
    from flask import request
    from datetime import datetime as dt

    # Get filter parameters
    action_filter = request.args.get('action', '')
    user_filter = request.args.get('user', '').strip()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    # Get pagination parameters
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1

    try:
        per_page = int(request.args.get('per_page', 50))
        if per_page < 1:
            per_page = 50
        if per_page > 100:
            per_page = 100
    except ValueError:
        per_page = 50

    # Build query
    query = AuditLog.query

    # Apply action filter
    if action_filter:
        query = query.filter_by(action=action_filter)

    # Apply user filter (search by email)
    if user_filter:
        search_pattern = f'%{user_filter}%'
        query = query.filter(AuditLog.user_email.ilike(search_pattern))

    # Apply date range filters
    if date_from:
        try:
            from_date = dt.strptime(date_from, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            query = query.filter(AuditLog.created_at >= from_date)
        except ValueError:
            pass  # Invalid date format, ignore filter

    if date_to:
        try:
            # Include the entire end date by adding one day
            to_date = dt.strptime(date_to, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            query = query.filter(AuditLog.created_at <= to_date)
        except ValueError:
            pass  # Invalid date format, ignore filter

    # Get total count before pagination
    total = query.count()

    # Calculate total pages
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    # Apply ordering and pagination
    logs_list = query.order_by(AuditLog.created_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    # Get distinct actions for filter dropdown
    action_types = db.session.query(AuditLog.action).distinct().order_by(
        AuditLog.action
    ).all()
    action_types = [a[0] for a in action_types]

    # Gather stats
    stats = {
        'total_logs': AuditLog.query.count(),
        'logs_today': AuditLog.query.filter(
            AuditLog.created_at >= datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        ).count(),
        'unique_users': db.session.query(AuditLog.user_email).distinct().count(),
        'login_attempts': AuditLog.query.filter(
            or_(
                AuditLog.action == 'user.login',
                AuditLog.action == 'user.login_failed'
            )
        ).count()
    }

    # Format logs for display
    formatted_logs = []
    for log in logs_list:
        # Format action into human-readable description
        action_descriptions = {
            'user.login': 'User logged in',
            'user.logout': 'User logged out',
            'user.login_failed': 'Failed login attempt',
            'user.created': 'User created',
            'user.updated': 'User updated',
            'user.approved': 'User approved',
            'user.rejected': 'User rejected',
            'user.suspended': 'User suspended',
            'user.deactivated': 'User deactivated',
            'content.uploaded': 'Content uploaded',
            'content.approved': 'Content approved',
            'content.rejected': 'Content rejected',
            'content.deleted': 'Content deleted',
            'organization.created': 'Organization created',
            'organization.updated': 'Organization updated',
            'invitation.sent': 'Invitation sent',
            'invitation.revoked': 'Invitation revoked',
            'session.created': 'Session created',
            'session.revoked': 'Session revoked',
            'password.changed': 'Password changed',
            'password.reset_requested': 'Password reset requested',
            '2fa.enabled': '2FA enabled',
            '2fa.disabled': '2FA disabled',
        }
        description = action_descriptions.get(
            log.action, log.action.replace('.', ' ').title()
        )

        formatted_logs.append({
            'id': log.id,
            'user_email': log.user_email or 'System',
            'action': log.action,
            'description': description,
            'resource_type': log.resource_type,
            'resource_id': log.resource_id,
            'details': log.details,
            'ip_address': log.ip_address or '-',
            'user_agent': log.user_agent,
            'time_ago': _format_time_ago(log.created_at),
            'timestamp': log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else 'Unknown'
        })

    # Get pending approvals count for badge
    pending_approvals = (
        UserApprovalRequest.query.filter_by(
            status=UserApprovalRequest.STATUS_PENDING
        ).count() +
        ContentApprovalRequest.query.filter_by(
            status=ContentApprovalRequest.STATUS_PENDING
        ).count()
    )

    return render_template(
        'admin/audit.html',
        active_page='audit_logs',
        current_user=None,
        pending_approvals_count=pending_approvals,
        logs=formatted_logs,
        stats=stats,
        # Pagination info
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        # Current filters
        action_filter=action_filter,
        user_filter=user_filter,
        date_from=date_from,
        date_to=date_to,
        # Available options
        action_types=action_types
    )


@admin_web_bp.route('/settings')
def settings():
    """
    System settings page.

    Allows configuration of system-wide settings.

    Returns:
        Rendered settings.html template
    """
    # Placeholder - will be implemented with auth check
    return render_template(
        'admin/base.html',
        active_page='settings',
        current_user=None,
        pending_approvals_count=0
    )


@admin_web_bp.route('/logout')
def logout():
    """
    Logout handler.

    Clears the session and redirects to login page.

    Returns:
        Redirect to login page
    """
    # Placeholder - will be implemented with session handling
    return render_template('admin/login.html')
