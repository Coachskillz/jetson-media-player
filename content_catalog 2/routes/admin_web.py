"""
Admin Portal Web Routes

Blueprint for admin web page rendering with session-based authentication.
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint, render_template, request, redirect, 
    url_for, session, flash, g, current_app
)
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from content_catalog.models import (
    db, User, Organization, ContentAsset,
    UserApprovalRequest, ContentApprovalRequest, AuditLog, Tenant
)
from content_catalog.services.auth_service import AuthService
from content_catalog.services.audit_service import AuditService


# Create admin web blueprint
admin_web_bp = Blueprint(
    'admin',
    __name__,
    template_folder='../templates/admin'
)


# ============================================================================
# Authentication Helpers
# ============================================================================

def login_required(f):
    """Decorator to require login for web routes."""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        
        if not user_id:
            session['next_url'] = request.url
            return redirect(url_for('admin.login'))
        
        user = db.session.get(User, user_id)
        
        if not user or user.status != User.STATUS_ACTIVE:
            session.clear()
            return redirect(url_for('admin.login'))
        
        g.current_user = user
        return f(*args, **kwargs)
    
    return decorated_function


def _get_pending_approvals_count():
    """Get total count of pending approvals for sidebar badge."""
    return (
        UserApprovalRequest.query.filter_by(
            status=UserApprovalRequest.STATUS_PENDING
        ).count() +
        ContentApprovalRequest.query.filter_by(
            status=ContentApprovalRequest.STATUS_PENDING
        ).count()
    )


def _format_time_ago(dt):
    """Format a datetime as a human-readable 'time ago' string."""
    if dt is None:
        return "Unknown"

    now = datetime.now(timezone.utc)
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


# ============================================================================
# Authentication Routes
# ============================================================================

@admin_web_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Admin login page - handles both display and form submission."""
    
    # If already logged in, redirect to dashboard
    if session.get('user_id'):
        return redirect(url_for('admin.dashboard'))
    
    if request.method == 'POST':
        # Handle form submission
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Email and password are required', 'error')
            return render_template('admin/login.html')
        
        # Find user
        user = User.query.filter_by(email=email).first()
        
        if not user:
            flash('Invalid email or password', 'error')
            return render_template('admin/login.html')
        
        # Check account status
        if user.status != User.STATUS_ACTIVE:
            flash('Account is not active', 'error')
            return render_template('admin/login.html')
        
        # Check if locked
        if user.is_locked():
            flash('Account is locked. Please try again later.', 'error')
            return render_template('admin/login.html')
        
        # Verify password
        if not AuthService.verify_password(password, user.password_hash):
            user.failed_login_attempts += 1
            db.session.commit()
            flash('Invalid email or password', 'error')
            return render_template('admin/login.html')
        
        # Successful login - create session
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login = datetime.now(timezone.utc)
        
        session['user_id'] = user.id
        session['user_email'] = user.email
        session['user_name'] = user.name
        session['user_role'] = user.role
        session.permanent = True
        
        # Log the login
        AuditService.log_action(
            db_session=db.session,
            action='user.login',
            user_id=user.id,
            user_email=user.email,
            resource_type='user',
            resource_id=user.id,
            details={'method': 'web_session'}
        )
        
        db.session.commit()
        
        # Redirect to next URL or dashboard
        next_url = session.pop('next_url', None)
        return redirect(next_url or url_for('admin.dashboard'))
    
    return render_template('admin/login.html')


@admin_web_bp.route('/logout')
def logout():
    """Logout and clear session."""
    user_id = session.get('user_id')
    user_email = session.get('user_email')
    
    if user_id:
        AuditService.log_action(
            db_session=db.session,
            action='user.logout',
            user_id=user_id,
            user_email=user_email,
            resource_type='user',
            resource_id=user_id,
            details={'method': 'web_session'}
        )
        db.session.commit()
    
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('admin.login'))


# ============================================================================
# Dashboard
# ============================================================================

@admin_web_bp.route('/')
@login_required
def dashboard():
    """Admin dashboard page."""
    stats = {
        'total_users': User.query.count(),
        'active_users': User.query.filter_by(status=User.STATUS_ACTIVE).count(),
        'total_organizations': Organization.query.count(),
        'active_organizations': Organization.query.filter_by(status='active').count(),
        'total_assets': ContentAsset.query.count(),
        'published_assets': ContentAsset.query.filter_by(
            status=ContentAsset.STATUS_PUBLISHED
        ).count(),
        'pending_approvals': _get_pending_approvals_count()
    }

    recent_logs = AuditLog.query.order_by(
        AuditLog.created_at.desc()
    ).limit(10).all()

    recent_activity = []
    for log in recent_logs:
        action_descriptions = {
            'user.login': 'User logged in',
            'user.logout': 'User logged out',
            'user.created': 'New user registered',
            'content.uploaded': 'Content uploaded',
            'content.approved': 'Content approved',
        }
        description = action_descriptions.get(log.action, log.action.replace('.', ' ').title())
        recent_activity.append({
            'description': description,
            'time_ago': _format_time_ago(log.created_at),
            'user_email': log.user_email
        })

    return render_template(
        'admin/dashboard.html',
        active_page='dashboard',
        current_user=g.current_user,
        pending_approvals_count=stats['pending_approvals'],
        stats=stats,
        recent_activity=recent_activity,
        pending_users=User.query.filter_by(status=User.STATUS_PENDING).all(),
        pending_content=ContentAsset.query.filter_by(
            status=ContentAsset.STATUS_PENDING_REVIEW
        ).all()
    )


# ============================================================================
# Assets Management
# ============================================================================

def allowed_file(filename):
    """Check if file extension is allowed."""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    allowed = {'mp4', 'mov', 'avi', 'mkv', 'webm', 'jpg', 'jpeg', 'png', 'gif', 'webp'}
    return ext in allowed


@admin_web_bp.route('/assets')
@login_required
def assets():
    """Asset management page with list and upload form."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    tenant_filter = request.args.get('tenant', '')

    query = ContentAsset.query

    # Filter by tenant
    if tenant_filter:
        query = query.filter_by(tenant_id=tenant_filter)

    if search:
        query = query.filter(
            or_(
                ContentAsset.title.ilike(f'%{search}%'),
                ContentAsset.description.ilike(f'%{search}%')
            )
        )

    if status_filter:
        query = query.filter_by(status=status_filter)

    query = query.order_by(ContentAsset.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Get all tenants for filter dropdown
    tenants = Tenant.query.filter_by(is_active=True).order_by(Tenant.name).all()

    stats = {
        'total': ContentAsset.query.count(),
        'draft': ContentAsset.query.filter_by(status=ContentAsset.STATUS_DRAFT).count(),
        'published': ContentAsset.query.filter_by(status=ContentAsset.STATUS_PUBLISHED).count(),
        'pending': ContentAsset.query.filter_by(status=ContentAsset.STATUS_PENDING_REVIEW).count(),
    }

    return render_template(
        'admin/assets.html',
        active_page='assets',
        current_user=g.current_user,
        pending_approvals_count=_get_pending_approvals_count(),
        assets=pagination.items,
        pagination=pagination,
        stats=stats,
        search=search,
        status_filter=status_filter,
        tenant_filter=tenant_filter,
        tenants=tenants
    )
@admin_web_bp.route('/assets/upload', methods=['POST'])
@login_required
def upload_asset():
    """Handle file upload from web form."""
    if 'file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('admin.assets'))

    file = request.files['file']
    
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('admin.assets'))

    if not allowed_file(file.filename):
        flash('File type not allowed. Use: mp4, mov, avi, jpg, jpeg, png, gif', 'error')
        return redirect(url_for('admin.assets'))

    # Handle tenant selection
    tenant_id = request.form.get('tenant_id', '')
    
    if tenant_id == '__new__':
        # Create new tenant
        new_tenant_name = request.form.get('new_tenant_name', '').strip()
        if not new_tenant_name:
            flash('Please provide a name for the new Retail Partner', 'error')
            return redirect(url_for('admin.assets'))
        
        # Generate slug from name
        import re
        slug = re.sub(r'[^a-z0-9]+', '-', new_tenant_name.lower()).strip('-')
        
        # Check if tenant with this slug exists
        existing = Tenant.query.filter_by(slug=slug).first()
        if existing:
            flash(f'Retail Partner "{new_tenant_name}" already exists', 'error')
            return redirect(url_for('admin.assets'))
        
        # Create the tenant
        new_tenant = Tenant(name=new_tenant_name, slug=slug, is_active=True)
        db.session.add(new_tenant)
        db.session.flush()  # Get the ID
        tenant_id = new_tenant.id
    elif not tenant_id:
        flash('Please select a Retail Partner', 'error')
        return redirect(url_for('admin.assets'))

    title = request.form.get('title', '').strip()
    if not title:
        title = file.filename.rsplit('.', 1)[0]

    description = request.form.get('description', '').strip()
    category = request.form.get('category', '').strip()

    # Generate unique filename
    original_filename = secure_filename(file.filename)
    file_ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
    unique_filename = f"{uuid.uuid4()}.{file_ext}" if file_ext else str(uuid.uuid4())

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

        asset = ContentAsset(
            title=title,
            description=description,
            filename=unique_filename,
            file_path=str(file_path),
            file_size=file_size,
            format=file_ext,
            category=category,
            uploaded_by=g.current_user.id,
            tenant_id=tenant_id,
            status=ContentAsset.STATUS_DRAFT
        )

        db.session.add(asset)
        
        AuditService.log_action(
            db_session=db.session,
            action='content.uploaded',
            user_id=g.current_user.id,
            user_email=g.current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'title': title,
                'filename': unique_filename,
                'file_size': file_size,
                'tenant_id': tenant_id
            }
        )
        
        db.session.commit()
        flash(f'Asset "{title}" uploaded successfully!', 'success')

    except Exception as e:
        db.session.rollback()
        if file_path.exists():
            os.remove(str(file_path))
        flash(f'Upload failed: {str(e)}', 'error')

    return redirect(url_for('admin.assets'))
@admin_web_bp.route('/users')
@login_required
def users():
    """User management page."""
    status_filter = request.args.get('status', '')
    role_filter = request.args.get('role', '')
    search_query = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = User.query

    if status_filter and status_filter in User.VALID_STATUSES:
        query = query.filter_by(status=status_filter)

    if role_filter and role_filter in User.VALID_ROLES:
        query = query.filter_by(role=role_filter)

    if search_query:
        query = query.filter(
            or_(
                User.name.ilike(f'%{search_query}%'),
                User.email.ilike(f'%{search_query}%')
            )
        )

    total = query.count()
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    users_list = query.order_by(User.created_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    stats = {
        'total_users': User.query.count(),
        'active_users': User.query.filter_by(status=User.STATUS_ACTIVE).count(),
        'pending_users': User.query.filter_by(status=User.STATUS_PENDING).count(),
        'suspended_users': User.query.filter_by(status=User.STATUS_SUSPENDED).count(),
    }

    return render_template(
        'admin/users.html',
        active_page='users',
        current_user=g.current_user,
        pending_approvals_count=_get_pending_approvals_count(),
        users=users_list,
        stats=stats,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        status_filter=status_filter,
        role_filter=role_filter,
        search_query=search_query,
        valid_statuses=User.VALID_STATUSES,
        valid_roles=User.VALID_ROLES
    )


# ============================================================================
# Other Pages (Placeholders with proper auth)
# ============================================================================

@admin_web_bp.route('/organizations')
@login_required
def organizations():
    """Organization management page."""
    return render_template(
        'admin/base.html',
        active_page='organizations',
        current_user=g.current_user,
        pending_approvals_count=_get_pending_approvals_count()
    )


@admin_web_bp.route('/tenants')
@login_required
def tenants():
    """Tenant management page."""
    status_filter = request.args.get('status', '')
    search_query = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = Tenant.query

    if status_filter == 'active':
        query = query.filter_by(is_active=True)
    elif status_filter == 'inactive':
        query = query.filter_by(is_active=False)

    if search_query:
        query = query.filter(
            or_(
                Tenant.name.ilike(f'%{search_query}%'),
                Tenant.slug.ilike(f'%{search_query}%')
            )
        )

    total = query.count()
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    tenants_list = query.order_by(Tenant.created_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    stats = {
        'total_tenants': Tenant.query.count(),
        'active_tenants': Tenant.query.filter_by(is_active=True).count(),
        'inactive_tenants': Tenant.query.filter_by(is_active=False).count(),
        'total_assets': ContentAsset.query.count(),
    }

    return render_template(
        'admin/tenants.html',
        active_page='tenants',
        current_user=g.current_user,
        pending_approvals_count=_get_pending_approvals_count(),
        tenants=tenants_list,
        stats=stats,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        status_filter=status_filter,
        search_query=search_query
    )


@admin_web_bp.route('/approvals')
@login_required
def approvals():
    """Approval workflow page."""
    active_tab = request.args.get('tab', 'users')
    
    pending_users = User.query.filter_by(status=User.STATUS_PENDING).order_by(
        User.created_at.desc()
    ).all()
    
    pending_content = ContentAsset.query.filter_by(
        status=ContentAsset.STATUS_PENDING_REVIEW
    ).order_by(ContentAsset.created_at.desc()).all()

    return render_template(
        'admin/approvals.html',
        active_page='approvals',
        current_user=g.current_user,
        pending_approvals_count=len(pending_users) + len(pending_content),
        active_tab=active_tab,
        pending_users=pending_users,
        pending_users_count=len(pending_users),
        pending_content=pending_content,
        pending_content_count=len(pending_content),
        recent_approvals=[],
        page=1,
        per_page=20,
        total=len(pending_users) if active_tab == 'users' else len(pending_content),
        total_pages=1
    )


@admin_web_bp.route('/invitations')
@login_required
def invitations():
    """Invitation management page."""
    return render_template(
        'admin/base.html',
        active_page='invitations',
        current_user=g.current_user,
        pending_approvals_count=_get_pending_approvals_count()
    )


@admin_web_bp.route('/audit-logs')
@login_required
def audit_logs():
    """Audit log viewing page."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    query = AuditLog.query.order_by(AuditLog.created_at.desc())
    
    total = query.count()
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    logs_list = query.offset((page - 1) * per_page).limit(per_page).all()

    formatted_logs = []
    for log in logs_list:
        formatted_logs.append({
            'action': log.action,
            'description': log.action.replace('.', ' ').title(),
            'user_email': log.user_email,
            'resource_type': log.resource_type,
            'resource_id': log.resource_id,
            'timestamp': log.created_at,
            'time_ago': _format_time_ago(log.created_at)
        })

    return render_template(
        'admin/audit.html',
        active_page='audit_logs',
        current_user=g.current_user,
        pending_approvals_count=_get_pending_approvals_count(),
        logs=formatted_logs,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        action_filter='',
        user_filter='',
        date_from='',
        date_to=''
    )


@admin_web_bp.route('/settings')
@login_required
def settings():
    """System settings page."""
    settings_config = {
        'cms_endpoint': 'http://192.168.1.111:5002',
        'content_catalog_port': 5003,
        'auto_approve_content': False,
        'require_admin_approval': True,
        'max_upload_size_mb': 500,
        'allowed_file_types': ['mp4', 'mov', 'jpg', 'jpeg', 'png', 'gif'],
        'ncmec_integration_enabled': True,
        'sync_interval_minutes': 15,
    }

    return render_template(
        'admin/settings.html',
        active_page='settings',
        current_user=g.current_user,
        pending_approvals_count=_get_pending_approvals_count(),
        settings=settings_config
    )
