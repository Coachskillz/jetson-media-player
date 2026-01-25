"""
Admin Portal Web Routes

Blueprint for admin web page rendering with session-based authentication.
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import (jsonify, 
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
        
        # Redirect based on user type
        next_url = session.pop('next_url', None)
        
        # Check if retailer user (has tenant_ids but not admin role)
        tenant_ids = user.get_tenant_ids_list()
        is_retailer = tenant_ids and user.role in ['retailer_viewer', 'retailer_uploader', 'retailer_approver', 'retailer_admin']
        
        if is_retailer and not next_url:
            return redirect(url_for('admin.retailer_dashboard'))
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
    # Redirect retailer users to their dashboard
    user_id = session.get("user_id")
    if user_id:
        user = User.query.get(user_id)
        if user and user.role in ["retailer_viewer", "retailer_uploader", "retailer_approver", "retailer_admin"]:
            return redirect(url_for("admin.retailer_dashboard"))
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
        'pending': ContentAsset.query.filter_by(status=ContentAsset.STATUS_PENDING_REVIEW).count(),
        'approved': ContentAsset.query.filter_by(status=ContentAsset.STATUS_APPROVED).count(),
        'published': ContentAsset.query.filter_by(status=ContentAsset.STATUS_PUBLISHED).count(),
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


@admin_web_bp.route('/approved-assets')
@login_required
def approved_assets():
    """Approved assets page with folder organization by network/tenant."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search = request.args.get('search', '')
    tenant_filter = request.args.get('tenant', '')
    synced_filter = request.args.get('synced', '')

    # Only show APPROVED and PUBLISHED assets
    query = ContentAsset.query.filter(
        ContentAsset.status.in_([ContentAsset.STATUS_APPROVED, ContentAsset.STATUS_PUBLISHED])
    )

    # Filter by tenant
    if tenant_filter:
        query = query.filter_by(tenant_id=tenant_filter)

    # Filter by sync status
    if synced_filter == 'true':
        query = query.filter_by(synced_to_cms=True)
    elif synced_filter == 'false':
        query = query.filter_by(synced_to_cms=False)

    if search:
        query = query.filter(
            or_(
                ContentAsset.title.ilike(f'%{search}%'),
                ContentAsset.description.ilike(f'%{search}%')
            )
        )

    query = query.order_by(ContentAsset.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Get all tenants for folder sidebar
    tenants = Tenant.query.filter_by(is_active=True).order_by(Tenant.name).all()

    # Get asset counts per tenant for folder sidebar
    from sqlalchemy import func
    tenant_counts = db.session.query(
        ContentAsset.tenant_id,
        func.count(ContentAsset.id)
    ).filter(
        ContentAsset.status.in_([ContentAsset.STATUS_APPROVED, ContentAsset.STATUS_PUBLISHED])
    ).group_by(ContentAsset.tenant_id).all()

    tenant_asset_counts = {str(tid): count for tid, count in tenant_counts if tid}

    # Get current tenant if filtered
    current_tenant = None
    if tenant_filter:
        current_tenant = Tenant.query.get(tenant_filter)

    # Base stats
    base_query = ContentAsset.query.filter(
        ContentAsset.status.in_([ContentAsset.STATUS_APPROVED, ContentAsset.STATUS_PUBLISHED])
    )
    if tenant_filter:
        base_query = base_query.filter_by(tenant_id=tenant_filter)

    stats = {
        'total': base_query.count(),
        'approved': base_query.filter(ContentAsset.status == ContentAsset.STATUS_APPROVED).count(),
        'published': base_query.filter(ContentAsset.status == ContentAsset.STATUS_PUBLISHED).count(),
        'synced': base_query.filter(ContentAsset.synced_to_cms == True).count(),
        'not_synced': base_query.filter(ContentAsset.synced_to_cms == False).count(),
    }

    return render_template(
        'admin/approved_assets.html',
        active_page='approved_assets',
        current_user=g.current_user,
        pending_approvals_count=_get_pending_approvals_count(),
        assets=pagination.items,
        pagination=pagination,
        stats=stats,
        search=search,
        tenant_filter=tenant_filter,
        tenants=tenants,
        tenant_asset_counts=tenant_asset_counts,
        current_tenant=current_tenant
    )

@admin_web_bp.route('/assets/upload', methods=['POST'])
@login_required
def upload_asset():
    """Handle single file upload from web form (legacy)."""
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


@admin_web_bp.route('/assets/upload-multi', methods=['POST'])
@login_required
def upload_assets_multi():
    """Handle multiple file uploads with progress tracking."""
    import re

    # Get files from request
    files = request.files.getlist('files')

    if not files or all(f.filename == '' for f in files):
        return jsonify({'success': False, 'error': 'No files selected'}), 400

    # Handle tenant selection
    tenant_id = request.form.get('tenant_id', '')

    if tenant_id == '__new__':
        new_tenant_name = request.form.get('new_tenant_name', '').strip()
        if not new_tenant_name:
            return jsonify({'success': False, 'error': 'Please provide a name for the new Retail Partner'}), 400

        slug = re.sub(r'[^a-z0-9]+', '-', new_tenant_name.lower()).strip('-')

        existing = Tenant.query.filter_by(slug=slug).first()
        if existing:
            return jsonify({'success': False, 'error': f'Retail Partner "{new_tenant_name}" already exists'}), 400

        new_tenant = Tenant(name=new_tenant_name, slug=slug, is_active=True)
        db.session.add(new_tenant)
        db.session.flush()
        tenant_id = new_tenant.id
    elif not tenant_id:
        return jsonify({'success': False, 'error': 'Please select a Retail Partner'}), 400

    description = request.form.get('description', '').strip()
    category = request.form.get('category', '').strip()

    # Get upload path
    uploads_path = current_app.config.get('UPLOADS_PATH')
    if not uploads_path:
        uploads_path = Path(current_app.config.get('BASE_DIR', os.getcwd())) / 'uploads'
    uploads_path = Path(uploads_path)
    uploads_path.mkdir(parents=True, exist_ok=True)

    uploaded_assets = []
    failed_files = []

    for file in files:
        if file.filename == '':
            continue

        if not allowed_file(file.filename):
            failed_files.append({'name': file.filename, 'error': 'File type not allowed'})
            continue

        original_filename = secure_filename(file.filename)
        file_ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
        unique_filename = f"{uuid.uuid4()}.{file_ext}" if file_ext else str(uuid.uuid4())
        file_path = uploads_path / unique_filename

        # Determine content type
        video_exts = {'mp4', 'mov', 'avi', 'mkv', 'webm'}
        image_exts = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
        if file_ext in video_exts:
            content_type = f'video/{file_ext}'
        elif file_ext in image_exts:
            content_type = f'image/{file_ext}'
        else:
            content_type = 'application/octet-stream'

        try:
            file.save(str(file_path))
            file_size = os.path.getsize(str(file_path))

            # Extract video duration if it's a video file
            duration = None
            if file_ext in video_exts:
                # Try ffprobe first
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

                # Fallback to cv2 if ffprobe failed
                if duration is None:
                    try:
                        import cv2
                        video = cv2.VideoCapture(str(file_path))
                        fps = video.get(cv2.CAP_PROP_FPS)
                        frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)
                        video.release()
                        if fps > 0 and frame_count > 0:
                            duration = int(frame_count / fps)
                    except Exception as e:
                        current_app.logger.warning(f"Could not extract video duration: {e}")

            # Title from filename (without extension)
            title = original_filename.rsplit('.', 1)[0] if '.' in original_filename else original_filename

            asset = ContentAsset(
                title=title,
                description=description,
                filename=unique_filename,
                original_filename=original_filename,
                file_path=str(file_path),
                file_size=file_size,
                format=file_ext,
                content_type=content_type,
                category=category,
                uploaded_by=g.current_user.id,
                tenant_id=tenant_id,
                status=ContentAsset.STATUS_PENDING_REVIEW,  # Go directly to pending review
                synced_to_cms=False,
                duration=duration
            )

            db.session.add(asset)
            db.session.flush()  # Get the ID for audit log

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
                    'original_filename': original_filename,
                    'file_size': file_size,
                    'tenant_id': tenant_id
                }
            )

            uploaded_assets.append({
                'id': asset.id,
                'uuid': asset.uuid,
                'title': title,
                'filename': unique_filename
            })

        except Exception as e:
            if file_path.exists():
                os.remove(str(file_path))
            failed_files.append({'name': original_filename, 'error': str(e)})

    if uploaded_assets:
        db.session.commit()

    return jsonify({
        'success': True,
        'uploaded_count': len(uploaded_assets),
        'failed_count': len(failed_files),
        'uploaded': uploaded_assets,
        'failed': failed_files
    })
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
    from content_catalog.models import ContentVenueApproval

    active_tab = request.args.get('tab', 'users')

    # Only super_admin can see pending users
    if g.current_user.role == 'super_admin':
        pending_users = User.query.filter_by(status=User.STATUS_PENDING).order_by(
            User.created_at.desc()
        ).all()
    else:
        pending_users = []

    # Filter content by tenant for non-super_admin users
    if g.current_user.role == 'super_admin':
        pending_content = ContentAsset.query.filter_by(
            status=ContentAsset.STATUS_PENDING_REVIEW
        ).order_by(ContentAsset.created_at.desc()).all()
    else:
        # Get user's tenant IDs
        user_tenant_ids = g.current_user.get_tenant_ids_list() or []
        if user_tenant_ids:
            # Find assets that either:
            # 1. Have tenant_id directly set (legacy uploads)
            # 2. Have ContentVenueApproval records with pending_skillz status for user's tenants
            from sqlalchemy import or_

            # Get asset IDs from ContentVenueApproval records
            approval_asset_ids = db.session.query(ContentVenueApproval.content_asset_id).filter(
                ContentVenueApproval.tenant_id.in_(user_tenant_ids),
                ContentVenueApproval.status == ContentVenueApproval.STATUS_PENDING_SKILLZ
            ).subquery()

            pending_content = ContentAsset.query.filter(
                ContentAsset.status == ContentAsset.STATUS_PENDING_REVIEW,
                or_(
                    ContentAsset.tenant_id.in_(user_tenant_ids),
                    ContentAsset.id.in_(approval_asset_ids)
                )
            ).order_by(ContentAsset.created_at.desc()).all()
        else:
            pending_content = []

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
    from content_catalog.models import UserInvitation, Organization, Tenant

    # Get all invitations ordered by creation date (newest first)
    invitations_list = UserInvitation.query.order_by(
        UserInvitation.created_at.desc()
    ).all()

    # Get all organizations for the dropdown
    organizations = Organization.query.order_by(Organization.name).all()

    # Get all tenants/networks for the dropdown
    tenants = Tenant.query.filter_by(is_active=True).order_by(Tenant.name).all()

    return render_template(
        'admin/invitations.html',
        active_page='invitations',
        current_user=g.current_user,
        pending_approvals_count=_get_pending_approvals_count(),
        invitations=invitations_list,
        organizations=organizations,
        tenants=tenants
    )


@admin_web_bp.route('/api/invitations', methods=['POST'])
@login_required
def create_invitation_api():
    """API endpoint to create and send an invitation (session-authenticated)."""
    from datetime import timedelta
    from content_catalog.models import UserInvitation, Organization
    from content_catalog.services.auth_service import AuthService
    from content_catalog.services.email_service import EmailService

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate email
    email = data.get('email')
    if not email:
        return jsonify({'error': 'email is required'}), 400
    email = email.lower().strip()

    # Check if user already exists
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({'error': 'A user with this email already exists'}), 409

    # Check for existing pending invitation
    existing_invitation = UserInvitation.query.filter_by(
        email=email,
        status=UserInvitation.STATUS_PENDING
    ).first()
    if existing_invitation and existing_invitation.is_valid():
        return jsonify({'error': 'A pending invitation already exists for this email'}), 409

    # Validate role
    role = data.get('role')
    if not role:
        return jsonify({'error': 'role is required'}), 400
    if role not in User.VALID_ROLES:
        return jsonify({'error': f'Invalid role. Must be one of: {", ".join(User.VALID_ROLES)}'}), 400

    # Check if current user can invite this role
    current_user = g.current_user
    if not current_user.can_approve_role(role):
        return jsonify({'error': f'Insufficient permissions to invite users with role: {role}'}), 403

    # Validate organization_id if provided
    organization_id = data.get('organization_id')
    organization = None
    if organization_id:
        try:
            org_id = int(organization_id)
            organization = db.session.get(Organization, org_id)
            if not organization:
                return jsonify({'error': f'Organization with id {org_id} not found'}), 400
            organization_id = org_id
        except (ValueError, TypeError):
            return jsonify({'error': 'organization_id must be an integer'}), 400

    # Validate tenant_ids if provided
    tenant_ids = data.get('tenant_ids', [])
    if tenant_ids:
        from content_catalog.models import Tenant
        if not isinstance(tenant_ids, list):
            return jsonify({'error': 'tenant_ids must be a list'}), 400
        # Verify all tenants exist
        valid_tenant_ids = []
        for tid in tenant_ids:
            try:
                tid = int(tid)
                tenant = db.session.get(Tenant, tid)
                if not tenant:
                    return jsonify({'error': f'Tenant with id {tid} not found'}), 400
                valid_tenant_ids.append(tid)
            except (ValueError, TypeError):
                return jsonify({'error': f'Invalid tenant_id: {tid}'}), 400
        tenant_ids = valid_tenant_ids

    # Generate token and create invitation
    token = AuthService.generate_invitation_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=48)

    invitation = UserInvitation(
        email=email,
        role=role,
        organization_id=organization_id,
        invited_by=current_user.id,
        token=token,
        status=UserInvitation.STATUS_PENDING,
        expires_at=expires_at
    )

    # Set tenant_ids if provided
    if tenant_ids:
        invitation.set_tenant_ids_list(tenant_ids)

    try:
        db.session.add(invitation)

        AuditService.log_action(
            db_session=db.session,
            action='invitation.created',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='invitation',
            resource_id=None,
            details={
                'invited_email': email,
                'invited_role': role,
                'organization_id': organization_id
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to create invitation: {str(e)}'}), 500

    # Send invitation email
    organization_name = organization.name if organization else None
    email_sent = EmailService.send_invitation(
        to_email=email,
        inviter_name=current_user.name,
        invitation_token=token,
        role=role,
        organization_name=organization_name
    )

    response = invitation.to_dict()
    response['email_sent'] = email_sent
    response['registration_link'] = f'/partner/register/{token}'

    return jsonify(response), 201


@admin_web_bp.route('/api/invitations/<int:invitation_id>/resend', methods=['POST'])
@login_required
def resend_invitation_api(invitation_id):
    """API endpoint to resend an invitation email (session-authenticated)."""
    from content_catalog.models import UserInvitation
    from content_catalog.services.email_service import EmailService

    invitation = db.session.get(UserInvitation, invitation_id)
    if not invitation:
        return jsonify({'error': 'Invitation not found'}), 404

    if invitation.status != UserInvitation.STATUS_PENDING:
        return jsonify({'error': 'Only pending invitations can be resent'}), 400

    if invitation.is_expired():
        return jsonify({'error': 'Invitation has expired. Please create a new one.'}), 400

    # Get organization name if exists
    organization_name = invitation.organization.name if invitation.organization else None

    # Resend the email
    email_sent = EmailService.send_invitation(
        to_email=invitation.email,
        inviter_name=g.current_user.name,
        invitation_token=invitation.token,
        role=invitation.role,
        organization_name=organization_name
    )

    if email_sent:
        AuditService.log_action(
            db_session=db.session,
            action='invitation.resent',
            user_id=g.current_user.id,
            user_email=g.current_user.email,
            resource_type='invitation',
            resource_id=invitation.id,
            details={'invited_email': invitation.email}
        )
        db.session.commit()
        return jsonify({'message': 'Invitation resent successfully'}), 200
    else:
        return jsonify({'message': 'Email service not configured. Use Copy Link instead.', 'warning': True}), 200


@admin_web_bp.route('/api/invitations/<int:invitation_id>', methods=['DELETE'])
@login_required
def delete_invitation_api(invitation_id):
    """API endpoint to delete an invitation (session-authenticated)."""
    from content_catalog.models import UserInvitation

    invitation = db.session.get(UserInvitation, invitation_id)
    if not invitation:
        return jsonify({'error': 'Invitation not found'}), 404

    invited_email = invitation.email

    try:
        db.session.delete(invitation)

        AuditService.log_action(
            db_session=db.session,
            action='invitation.deleted',
            user_id=g.current_user.id,
            user_email=g.current_user.email,
            resource_type='invitation',
            resource_id=invitation_id,
            details={'invited_email': invited_email}
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete invitation: {str(e)}'}), 500

    return jsonify({'message': 'Invitation deleted successfully'}), 200


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


# ============================================================================
# Retail Partners Routes
# ============================================================================

@admin_web_bp.route('/retail-partners')
@login_required
def retail_partners():
    """Retail Partners management page."""
    status_filter = request.args.get('status', '')
    search_query = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20

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

    partners = []
    for tenant in tenants_list:
        asset_count = ContentAsset.query.filter_by(tenant_id=tenant.id).count()
        partners.append(type('Partner', (), {
            'id': tenant.id, 'uuid': tenant.uuid, 'name': tenant.name,
            'slug': tenant.slug, 'description': tenant.description,
            'is_active': tenant.is_active, 'created_at': tenant.created_at,
            'asset_count': asset_count
        })())

    stats = {
        'total_partners': Tenant.query.count(),
        'active_partners': Tenant.query.filter_by(is_active=True).count(),
        'total_locations': 0,
        'total_assets': ContentAsset.query.count(),
    }

    return render_template(
        'admin/retail_partners.html',
        active_page='retail_partners',
        current_user=g.current_user,
        pending_approvals_count=_get_pending_approvals_count(),
        partners=partners, stats=stats, page=page, per_page=per_page,
        total=total, total_pages=total_pages,
        status_filter=status_filter, search_query=search_query
    )


@admin_web_bp.route('/retail-partners', methods=['POST'])
@login_required
def create_retail_partner():
    """Create a new retail partner."""
    import re
    from flask import jsonify
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400
    
    name = data.get('name', '').strip()
    slug = data.get('slug', '').strip().lower()
    
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if not slug or not re.match(r'^[a-z0-9-]+$', slug):
        return jsonify({'error': 'Valid slug is required'}), 400
    if Tenant.query.filter_by(slug=slug).first():
        return jsonify({'error': 'Slug already exists'}), 409
    
    tenant = Tenant(name=name, slug=slug, description=data.get('description'), is_active=True)
    db.session.add(tenant)
    db.session.commit()
    return jsonify({'success': True}), 201


@admin_web_bp.route('/retail-partners/<partner_uuid>', methods=['PUT'])
@login_required
def update_retail_partner(partner_uuid):
    """Update a retail partner."""
    import re
    from flask import jsonify
    tenant = Tenant.query.filter_by(uuid=partner_uuid).first()
    if not tenant:
        return jsonify({'error': 'Partner not found'}), 404
    
    data = request.get_json()
    if 'name' in data:
        tenant.name = data['name'].strip()
    if 'slug' in data:
        slug = data['slug'].strip().lower()
        existing = Tenant.query.filter_by(slug=slug).first()
        if existing and existing.id != tenant.id:
            return jsonify({'error': 'Slug already exists'}), 409
        tenant.slug = slug
    if 'description' in data:
        tenant.description = data.get('description')
    if 'is_active' in data:
        tenant.is_active = bool(data['is_active'])
    
    db.session.commit()
    return jsonify({'success': True}), 200


@admin_web_bp.route('/retail-partners/<partner_uuid>/users')
@login_required
def retail_partner_users(partner_uuid):
    """Manage users for a specific retail partner."""
    from content_catalog.models import Tenant, User
    
    partner = Tenant.query.filter_by(uuid=partner_uuid).first()
    if not partner:
        flash('Retail partner not found', 'error')
        return redirect(url_for('admin.retail_partners'))
    
    # Get users that have this tenant in their tenant_ids
    all_users = User.query.filter(User.status == User.STATUS_ACTIVE).all()
    partner_users = []
    for user in all_users:
        tenant_ids = user.get_tenant_ids_list()
        if partner.id in tenant_ids or str(partner.id) in tenant_ids:
            partner_users.append(user)
    
    return render_template('admin/retail_partner_users.html',
        partner=partner,
        users=partner_users,
        active_page='retail_partners'
    )


@admin_web_bp.route('/retail-partners/<partner_uuid>/users', methods=['POST'])
@login_required
def add_retail_partner_user(partner_uuid):
    """Add a new user to a retail partner."""
    from content_catalog.models import Tenant, User
    from werkzeug.security import generate_password_hash
    import uuid
    
    partner = Tenant.query.filter_by(uuid=partner_uuid).first()
    if not partner:
        return jsonify({'error': 'Partner not found'}), 404
    
    data = request.get_json()
    
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    role = data.get('role', 'retailer_admin')
    
    if not name or not email or not password:
        return jsonify({'error': 'Name, email, and password are required'}), 400
    
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    
    # Check for existing user
    existing = User.query.filter_by(email=email).first()
    if existing:
        return jsonify({'error': 'A user with this email already exists'}), 409
    
    # Create user
    user = User(
        # uuid auto-generated
        name=name,
        email=email,
        password_hash=AuthService.hash_password(password),
        role=role,
        status=User.STATUS_ACTIVE,
        created_at=datetime.now(timezone.utc)
    )
    user.set_tenant_ids_list([partner.id])
    
    db.session.add(user)
    db.session.commit()
    
    return jsonify({'success': True, 'user': {'id': user.id, 'name': user.name, 'email': user.email}})


@admin_web_bp.route('/retail-partners/<partner_uuid>/users/<int:user_id>', methods=['DELETE'])
@login_required
def remove_retail_partner_user(partner_uuid, user_id):
    """Remove a user from a retail partner (removes tenant from their list)."""
    from content_catalog.models import Tenant, User
    
    partner = Tenant.query.filter_by(uuid=partner_uuid).first()
    if not partner:
        return jsonify({'error': 'Partner not found'}), 404
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Remove this tenant from user's tenant_ids
    tenant_ids = user.get_tenant_ids_list()
    tenant_ids = [t for t in tenant_ids if t != partner.id and str(t) != str(partner.id)]
    user.set_tenant_ids_list(tenant_ids)
    
    db.session.commit()
    
    return jsonify({'success': True})


# ============ RETAILER DASHBOARD ============

@admin_web_bp.route('/retailer/dashboard')
@login_required
def retailer_dashboard():
    """Dashboard for retailer users - shows only their tenant's assets."""
    from content_catalog.models import Tenant, ContentAsset, ContentVenueApproval

    user_id = session.get('user_id')
    user = User.query.get(user_id)

    # Get user's tenant IDs
    tenant_ids = user.get_tenant_ids_list()
    if not tenant_ids:
        flash('You are not assigned to any retail partner', 'error')
        return redirect(url_for('admin.dashboard'))

    # For now, use the first tenant (or could let them switch)
    tenant_id = tenant_ids[0]
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        flash('Retail partner not found', 'error')
        return redirect(url_for('admin.dashboard'))

    # Get tab filter
    tab = request.args.get('tab', 'all')

    # Base query - only this tenant's assets
    query = ContentAsset.query.filter_by(tenant_id=tenant.id)

    if tab == 'pending':
        query = query.filter_by(status='PENDING_REVIEW')
    elif tab == 'approved':
        query = query.filter_by(status='APPROVED')
    elif tab == 'published':
        query = query.filter_by(status='PUBLISHED')
    elif tab == 'venue_pending':
        # Get assets with pending venue approval
        pending_approval_ids = [a.content_asset_id for a in
            ContentVenueApproval.query.filter_by(
                tenant_id=tenant.id,
                status=ContentVenueApproval.STATUS_PENDING_VENUE
            ).all()]
        query = ContentAsset.query.filter(ContentAsset.id.in_(pending_approval_ids))

    assets = query.order_by(ContentAsset.created_at.desc()).limit(100).all()

    # Get pending assets separately for the dashboard section (uploaded by retailer)
    pending_assets = ContentAsset.query.filter_by(tenant_id=tenant.id, status='PENDING_REVIEW').order_by(ContentAsset.created_at.desc()).all()

    # Get pending VENUE approvals (content Skillz approved, waiting for this venue)
    pending_venue_approvals = ContentVenueApproval.query.filter_by(
        tenant_id=tenant.id,
        status=ContentVenueApproval.STATUS_PENDING_VENUE
    ).order_by(ContentVenueApproval.created_at.desc()).all()

    # Get users for this tenant
    all_users = User.query.filter(User.status == User.STATUS_ACTIVE).all()
    tenant_users = [u for u in all_users if tenant.id in u.get_tenant_ids_list() or str(tenant.id) in [str(t) for t in u.get_tenant_ids_list()]]

    # Stats
    stats = {
        'total': ContentAsset.query.filter_by(tenant_id=tenant.id).count(),
        'pending': ContentAsset.query.filter_by(tenant_id=tenant.id, status='PENDING_REVIEW').count(),
        'venue_pending': len(pending_venue_approvals),
        'approved': ContentAsset.query.filter_by(tenant_id=tenant.id, status='APPROVED').count(),
        'published': ContentAsset.query.filter_by(tenant_id=tenant.id, status='PUBLISHED').count(),
    }

    # Check permissions based on role
    can_upload = user.role in ['retailer_uploader', 'retailer_approver', 'retailer_admin', 'super_admin', 'admin']
    can_approve = user.role in ['retailer_approver', 'retailer_admin', 'super_admin', 'admin']
    can_manage_users = user.role in ['retailer_admin', 'super_admin', 'admin']

    return render_template('admin/retailer_dashboard.html',
        user=user,
        retailer=tenant,
        assets=assets,
        pending_assets=pending_assets,
        pending_venue_approvals=pending_venue_approvals,
        users=tenant_users,
        stats=stats,
        tab=tab,
        can_upload=can_upload,
        can_approve=can_approve,
        can_manage_users=can_manage_users,
        active_page='retailer_dashboard'
    )
@admin_web_bp.route("/retailer/upload", methods=["POST"])
@login_required
def retailer_upload():
    """Handle asset upload from retailer user."""
    from content_catalog.models import Tenant, ContentAsset
    from werkzeug.utils import secure_filename
    import uuid as uuid_module
    import os
    
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    tenant_ids = user.get_tenant_ids_list()
    if not tenant_ids:
        flash('You are not assigned to any retail partner', 'error')
        return redirect(url_for('admin.retailer_dashboard'))
    
    tenant_id = tenant_ids[0]
    tenant = Tenant.query.get(tenant_id)
    
    if 'file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('admin.retailer_dashboard'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('admin.retailer_dashboard'))
    
    # Validate extension
    allowed = {'mp4', 'mov', 'avi', 'webm', 'jpg', 'jpeg', 'png', 'gif', 'webp'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed:
        flash('File type not allowed', 'error')
        return redirect(url_for('admin.retailer_dashboard'))
    
    # Save file
    unique_filename = f"{uuid_module.uuid4()}.{ext}"
    upload_dir = os.path.join(current_app.root_path, 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, unique_filename)
    file.save(file_path)
    
    # Determine content type
    content_type = 'video/' + ext if ext in {'mp4', 'mov', 'avi', 'webm'} else 'image/' + ext
    
    # Create asset
    title = request.form.get('title', '').strip() or file.filename.rsplit('.', 1)[0]
    
    asset = ContentAsset(
        uuid=str(uuid_module.uuid4()),
        title=title,
        description=request.form.get('description', '').strip(),
        file_path=unique_filename,
        original_filename=secure_filename(file.filename),
        content_type=content_type,
        file_size=os.path.getsize(file_path),
        category=request.form.get('category', 'advertisement'),
        status='PENDING_REVIEW',
        tenant_id=tenant.id,
        uploaded_by=user.id,
        created_at=datetime.now(timezone.utc)
    )
    
    db.session.add(asset)
    db.session.commit()
    
    flash(f'"{title}" uploaded and pending approval', 'success')
    return redirect(url_for('admin.retailer_dashboard'))




@admin_web_bp.route('/api/tenants', methods=['GET'])
@login_required
def get_tenants_for_approval():
    """Get list of tenants for the approval modal."""
    tenants = Tenant.query.filter_by(is_active=True).order_by(Tenant.name).all()
    return jsonify({
        'tenants': [t.to_dict() for t in tenants]
    })



@admin_web_bp.route('/content/<int:asset_id>/approve-for-venues', methods=['POST'])
@login_required
def approve_content_for_venues(asset_id):
    """
    Approve content for specific venues with optional override.
    
    This is the main Skillz admin approval endpoint that:
    1. Creates ContentVenueApproval records for each target venue
    2. Checks each venue's requires_content_approval setting
    3. Auto-transfers to CMS if venue doesn't require approval or override is set
    4. Queues for venue approval if required
    """
    from content_catalog.models import ContentAsset, Tenant, ContentVenueApproval
    from content_catalog.services.cms_transfer_service import CMSTransferService
    
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Check permissions - only admins and super_admin can approve
    if user.role not in ['admin', 'super_admin', 'content_manager']:
        return jsonify({'error': 'Permission denied'}), 403
    
    # Get the asset
    asset = ContentAsset.query.get(asset_id)
    if not asset:
        return jsonify({'error': 'Asset not found'}), 404
    
    # Get request data
    data = request.get_json() or {}
    target_venue_ids = data.get('target_venue_ids', [])
    override_venue_approval = data.get('override_venue_approval', False)

    if not target_venue_ids:
        return jsonify({'error': 'No venues selected'}), 400

    # Update asset status to approved (Skillz has approved)
    asset.status = ContentAsset.STATUS_APPROVED
    # Store approved venue/network slugs on the asset for CMS sync
    import json
    existing_networks = json.loads(asset.networks) if asset.networks else []
    # Get slugs for the selected venues
    venue_slugs = []
    for vid in target_venue_ids:
        t = Tenant.query.get(vid)
        if t and t.slug:
            venue_slugs.append(t.slug)
    new_networks = list(set(existing_networks + venue_slugs))
    asset.networks = json.dumps(new_networks)
    asset.approved_by_user_id = user.id
    asset.approved_at = datetime.now(timezone.utc)
    
    auto_transferred = 0
    pending_venue_approval = 0
    transfer_results = []
    
    for venue_id in target_venue_ids:
        tenant = Tenant.query.get(venue_id)
        if not tenant:
            continue
        
        # Check if approval record already exists
        existing = ContentVenueApproval.query.filter_by(
            content_asset_id=asset.id,
            tenant_id=tenant.id
        ).first()
        
        if existing:
            # Update existing record
            approval = existing
        else:
            # Create new approval record
            approval = ContentVenueApproval(
                content_asset_id=asset.id,
                tenant_id=tenant.id
            )
            db.session.add(approval)
        
        # Skillz approval
        approval.skillz_approved = True
        approval.skillz_approved_by_id = user.id
        approval.skillz_approved_at = datetime.now(timezone.utc)

        # Auto-transfer to CMS if:
        # 1. Override checkbox is checked, OR
        # 2. Venue doesn't require content approval
        should_auto_approve = override_venue_approval or not tenant.requires_content_approval

        if should_auto_approve:
            approval.venue_approved = True
            approval.auto_approved = True
            approval.venue_approved_at = datetime.now(timezone.utc)
            approval.status = ContentVenueApproval.STATUS_APPROVED
            
            # Commit so the approval record has an ID before transfer
            db.session.commit()

            # Transfer to CMS
            result = CMSTransferService.transfer_to_cms(asset, tenant)
            transfer_results.append({
                'venue': tenant.name,
                'result': result
            })

            if result.get('success'):
                auto_transferred += 1
                # Update asset sync status
                asset.synced_to_cms = True
                asset.synced_at = datetime.now(timezone.utc)
                asset.cms_content_id = result.get('cms_content_id')
            else:
                # Log the error but continue
                print(f"Transfer failed for {tenant.name}: {result.get('error')}")
        else:
            approval.status = ContentVenueApproval.STATUS_PENDING_VENUE
            pending_venue_approval += 1
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Content approved for venues',
        'auto_transferred': auto_transferred,
        'pending_venue_approval': pending_venue_approval,
        'transfer_results': transfer_results
    })

@admin_web_bp.route('/retailer/assets/<asset_uuid>/approve', methods=['POST'])
@login_required
def retailer_approve_asset(asset_uuid):
    """Approve an asset and auto-sync to CMS."""
    from content_catalog.models import ContentAsset
    from content_catalog.services.cms_transfer_service import CMSTransferService

    user_id = session.get('user_id')
    user = User.query.get(user_id)

    if user.role not in ['retailer_approver', 'retailer_admin', 'super_admin', 'admin']:
        return jsonify({'error': 'Permission denied'}), 403

    asset = ContentAsset.query.filter_by(uuid=asset_uuid).first()
    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Verify user has access to this tenant
    tenant_ids = user.get_tenant_ids_list()
    if asset.tenant_id not in tenant_ids and str(asset.tenant_id) not in [str(t) for t in tenant_ids]:
        return jsonify({'error': 'Access denied'}), 403

    # Update approval status
    asset.status = ContentAsset.STATUS_APPROVED
    asset.approved_by_user_id = user.id
    asset.approved_at = datetime.now(timezone.utc)

    # Auto-sync to CMS
    sync_result = None
    if asset.tenant_id:
        tenant = Tenant.query.get(asset.tenant_id)
        if tenant:
            sync_result = CMSTransferService.transfer_to_cms(asset, tenant)
            if sync_result.get('success'):
                asset.synced_to_cms = True
                asset.synced_at = datetime.now(timezone.utc)
                asset.cms_content_id = sync_result.get('cms_content_id')

    # Log the approval
    AuditService.log_action(
        db_session=db.session,
        action='content.approved',
        user_id=user.id,
        user_email=user.email,
        resource_type='content_asset',
        resource_id=asset.id,
        details={
            'synced_to_cms': asset.synced_to_cms,
            'cms_content_id': asset.cms_content_id
        }
    )

    db.session.commit()

    return jsonify({
        'success': True,
        'synced_to_cms': asset.synced_to_cms,
        'sync_result': sync_result
    })


@admin_web_bp.route('/retailer/assets/<asset_uuid>/reject', methods=['POST'])
@login_required
def retailer_reject_asset(asset_uuid):
    """Reject an asset (retailer endpoint using UUID)."""
    from content_catalog.models import ContentAsset

    user_id = session.get('user_id')
    user = User.query.get(user_id)

    if user.role not in ['retailer_approver', 'retailer_admin', 'super_admin', 'admin']:
        return jsonify({'error': 'Permission denied'}), 403

    asset = ContentAsset.query.filter_by(uuid=asset_uuid).first()
    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Skip tenant check for super_admin and admin
    if user.role not in ['super_admin', 'admin']:
        tenant_ids = user.get_tenant_ids_list()
        if asset.tenant_id not in tenant_ids and str(asset.tenant_id) not in [str(t) for t in tenant_ids]:
            return jsonify({'error': 'Access denied'}), 403

    data = request.get_json() or {}
    asset.status = ContentAsset.STATUS_REJECTED
    asset.rejection_reason = data.get('reason', '')
    asset.reviewed_by = user.id
    asset.reviewed_at = datetime.now(timezone.utc)

    AuditService.log_action(
        db_session=db.session,
        action='content.rejected',
        user_id=user.id,
        user_email=user.email,
        resource_type='content_asset',
        resource_id=asset.id,
        details={
            'title': asset.title,
            'reason': asset.rejection_reason
        }
    )

    db.session.commit()
    return jsonify({'success': True})


@admin_web_bp.route('/venue-approval/<int:approval_id>/approve', methods=['POST'])
@login_required
def venue_approve_content(approval_id):
    """
    Venue approves pending content - triggers CMS sync.

    This is called when a venue/retailer approves content that was
    previously approved by Skillz but pending their approval.
    """
    from content_catalog.models import ContentVenueApproval
    from content_catalog.services.cms_transfer_service import CMSTransferService

    approval = ContentVenueApproval.query.get(approval_id)
    if not approval:
        return jsonify({'error': 'Approval record not found'}), 404

    # Check user has permission (is associated with this tenant)
    user = g.current_user
    if user.role not in ['super_admin', 'admin']:
        user_tenant_ids = user.get_tenant_ids_list()
        if approval.tenant_id not in user_tenant_ids and str(approval.tenant_id) not in [str(t) for t in user_tenant_ids]:
            return jsonify({'error': 'Access denied'}), 403

    # Update approval status
    approval.venue_approved = True
    approval.venue_approved_by_id = user.id
    approval.venue_approved_at = datetime.now(timezone.utc)
    approval.status = ContentVenueApproval.STATUS_APPROVED

    # Now sync to CMS
    asset = approval.content_asset
    tenant = approval.tenant
    sync_result = None

    if asset and tenant:
        sync_result = CMSTransferService.transfer_to_cms(asset, tenant)
        if sync_result.get('success'):
            asset.synced_to_cms = True
            asset.synced_at = datetime.now(timezone.utc)
            asset.cms_content_id = sync_result.get('cms_content_id')

    AuditService.log_action(
        db_session=db.session,
        action='content.venue_approved',
        user_id=user.id,
        user_email=user.email,
        resource_type='content_venue_approval',
        resource_id=approval.id,
        details={
            'asset_id': asset.id if asset else None,
            'asset_title': asset.title if asset else None,
            'tenant_id': tenant.id if tenant else None,
            'synced_to_cms': asset.synced_to_cms if asset else False
        }
    )

    db.session.commit()

    return jsonify({
        'success': True,
        'synced_to_cms': asset.synced_to_cms if asset else False,
        'cms_content_id': asset.cms_content_id if asset else None
    })


@admin_web_bp.route('/venue-approval/<int:approval_id>/reject', methods=['POST'])
@login_required
def venue_reject_content(approval_id):
    """Venue rejects pending content."""
    from content_catalog.models import ContentVenueApproval

    approval = ContentVenueApproval.query.get(approval_id)
    if not approval:
        return jsonify({'error': 'Approval record not found'}), 404

    # Check user has permission
    user = g.current_user
    if user.role not in ['super_admin', 'admin']:
        user_tenant_ids = user.get_tenant_ids_list()
        if approval.tenant_id not in user_tenant_ids and str(approval.tenant_id) not in [str(t) for t in user_tenant_ids]:
            return jsonify({'error': 'Access denied'}), 403

    data = request.get_json() or {}
    reason = data.get('reason', '')

    approval.venue_approved = False
    approval.status = ContentVenueApproval.STATUS_REJECTED_VENUE
    approval.venue_rejection_reason = reason

    AuditService.log_action(
        db_session=db.session,
        action='content.venue_rejected',
        user_id=user.id,
        user_email=user.email,
        resource_type='content_venue_approval',
        resource_id=approval.id,
        details={
            'asset_id': approval.content_asset_id,
            'reason': reason
        }
    )

    db.session.commit()
    return jsonify({'success': True})


@admin_web_bp.route('/content/<int:asset_id>/reject', methods=['POST'])
@login_required
def reject_content(asset_id):
    """Reject content from approvals page (using integer ID)."""
    asset = ContentAsset.query.get(asset_id)
    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    data = request.get_json() or {}
    reason = data.get('reason', '')

    asset.status = ContentAsset.STATUS_REJECTED
    asset.rejection_reason = reason
    asset.reviewed_by = g.current_user.id
    asset.reviewed_at = datetime.now(timezone.utc)

    AuditService.log_action(
        db_session=db.session,
        action='content.rejected',
        user_id=g.current_user.id,
        user_email=g.current_user.email,
        resource_type='content_asset',
        resource_id=asset.id,
        details={
            'title': asset.title,
            'reason': reason
        }
    )

    db.session.commit()
    return jsonify({'success': True})


@admin_web_bp.route('/content/<int:asset_id>/approve', methods=['POST'])
@login_required
def approve_content(asset_id):
    """
    Approve content from approvals page (using integer ID).

    This is Skillz approval (stage 1 of two-stage workflow).

    Workflow:
    1. Find any existing ContentVenueApproval records (created during upload)
    2. Update them from 'pending_skillz' to 'pending_venue'
    3. If no records exist (legacy), check asset.tenant_id and create if needed
    4. If venue doesn't require approval, auto-sync to CMS
    """
    from content_catalog.services.cms_transfer_service import CMSTransferService
    from content_catalog.models import ContentVenueApproval

    asset = ContentAsset.query.get(asset_id)
    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    asset.status = ContentAsset.STATUS_APPROVED
    asset.approved_by_user_id = g.current_user.id
    asset.approved_at = datetime.now(timezone.utc)

    sync_results = []
    pending_venue_count = 0
    synced_count = 0

    # First, check for existing ContentVenueApproval records (created during upload)
    existing_approvals = ContentVenueApproval.query.filter_by(
        content_asset_id=asset.id,
        status=ContentVenueApproval.STATUS_PENDING_SKILLZ
    ).all()

    if existing_approvals:
        # Update existing approval records (two-stage workflow)
        for approval in existing_approvals:
            tenant = approval.tenant

            # Mark as Skillz approved
            approval.skillz_approved = True
            approval.skillz_approved_by_id = g.current_user.id
            approval.skillz_approved_at = datetime.now(timezone.utc)

            # Check if venue requires approval
            if tenant and tenant.requires_content_approval:
                # Move to pending venue approval
                approval.status = ContentVenueApproval.STATUS_PENDING_VENUE
                pending_venue_count += 1
            else:
                # Auto-approve and sync to CMS
                approval.venue_approved = True
                approval.auto_approved = True
                approval.venue_approved_at = datetime.now(timezone.utc)
                approval.status = ContentVenueApproval.STATUS_APPROVED

                # Sync to CMS
                if tenant:
                    result = CMSTransferService.transfer_to_cms(asset, tenant)
                    sync_results.append({'tenant': tenant.name, 'result': result})
                    if result.get('success'):
                        asset.synced_to_cms = True
                        asset.synced_at = datetime.now(timezone.utc)
                        asset.cms_content_id = result.get('cms_content_id')
                        synced_count += 1
    elif asset.tenant_id:
        # Legacy flow: No existing approvals, use asset.tenant_id
        tenant = Tenant.query.get(asset.tenant_id)
        if tenant:
            # Check if venue requires content approval
            if tenant.requires_content_approval:
                # Create pending venue approval
                approval = ContentVenueApproval(
                    content_asset_id=asset.id,
                    tenant_id=tenant.id,
                    skillz_approved=True,
                    skillz_approved_by_id=g.current_user.id,
                    skillz_approved_at=datetime.now(timezone.utc),
                    venue_approved=False,
                    auto_approved=False,
                    status=ContentVenueApproval.STATUS_PENDING_VENUE
                )
                db.session.add(approval)
                pending_venue_count = 1
            else:
                # Venue doesn't require approval - auto-sync to CMS
                result = CMSTransferService.transfer_to_cms(asset, tenant)
                sync_results.append({'tenant': tenant.name, 'result': result})
                if result.get('success'):
                    asset.synced_to_cms = True
                    asset.synced_at = datetime.now(timezone.utc)
                    asset.cms_content_id = result.get('cms_content_id')
                    synced_count = 1

    AuditService.log_action(
        db_session=db.session,
        action='content.approved',
        user_id=g.current_user.id,
        user_email=g.current_user.email,
        resource_type='content_asset',
        resource_id=asset.id,
        details={
            'title': asset.title,
            'synced_to_cms': asset.synced_to_cms,
            'pending_venue_count': pending_venue_count,
            'synced_count': synced_count
        }
    )

    db.session.commit()
    return jsonify({
        'success': True,
        'synced_to_cms': asset.synced_to_cms,
        'pending_venue_approval': pending_venue_count > 0,
        'pending_venue_count': pending_venue_count,
        'synced_count': synced_count
    })


# ============================================================================
# CMS Sync API Endpoints
# ============================================================================

@admin_web_bp.route('/api/assets/<asset_uuid>/sync-to-cms', methods=['POST'])
@login_required
def sync_asset_to_cms(asset_uuid):
    """Manually sync an approved asset to CMS."""
    from content_catalog.services.cms_transfer_service import CMSTransferService

    asset = ContentAsset.query.filter_by(uuid=asset_uuid).first()
    if not asset:
        return jsonify({'success': False, 'error': 'Asset not found'}), 404

    if asset.status not in [ContentAsset.STATUS_APPROVED, ContentAsset.STATUS_PUBLISHED]:
        return jsonify({'success': False, 'error': 'Asset must be approved first'}), 400

    if asset.synced_to_cms:
        return jsonify({'success': False, 'error': 'Asset already synced to CMS'}), 400

    # Get tenant for sync
    tenant = Tenant.query.get(asset.tenant_id) if asset.tenant_id else None
    if not tenant:
        return jsonify({'success': False, 'error': 'Asset has no assigned network/tenant'}), 400

    # Perform sync
    result = CMSTransferService.transfer_to_cms(asset, tenant)

    if result.get('success'):
        # Update asset sync status
        asset.synced_to_cms = True
        asset.synced_at = datetime.now(timezone.utc)
        asset.cms_content_id = result.get('cms_content_id')

        AuditService.log_action(
            db_session=db.session,
            action='content.synced_to_cms',
            user_id=g.current_user.id,
            user_email=g.current_user.email,
            resource_type='content_asset',
            resource_id=asset.id,
            details={
                'cms_content_id': result.get('cms_content_id'),
                'network_id': result.get('network_id')
            }
        )

        db.session.commit()
        return jsonify({'success': True, 'cms_content_id': result.get('cms_content_id')})
    else:
        return jsonify({'success': False, 'error': result.get('error', 'Unknown error')}), 500


@admin_web_bp.route('/api/assets/bulk-approve', methods=['POST'])
@login_required
def bulk_approve_assets():
    """Bulk approve multiple assets - handles two-stage workflow."""
    from content_catalog.services.cms_transfer_service import CMSTransferService
    from content_catalog.models import ContentVenueApproval

    data = request.get_json() or {}
    asset_ids = data.get('asset_ids', [])
    auto_sync = data.get('auto_sync', True)

    if not asset_ids:
        return jsonify({'success': False, 'error': 'No assets specified'}), 400

    approved_count = 0
    synced_count = 0
    pending_venue_count = 0
    errors = []

    for asset_id in asset_ids:
        asset = ContentAsset.query.get(asset_id)
        if not asset:
            errors.append({'id': asset_id, 'error': 'Not found'})
            continue

        # Approve the asset
        asset.status = ContentAsset.STATUS_APPROVED
        asset.approved_by_user_id = g.current_user.id
        asset.approved_at = datetime.now(timezone.utc)
        approved_count += 1

        # First, check for existing ContentVenueApproval records (two-stage workflow)
        existing_approvals = ContentVenueApproval.query.filter_by(
            content_asset_id=asset.id,
            status=ContentVenueApproval.STATUS_PENDING_SKILLZ
        ).all()

        if existing_approvals:
            # Update existing approval records
            for approval in existing_approvals:
                tenant = approval.tenant

                # Mark as Skillz approved
                approval.skillz_approved = True
                approval.skillz_approved_by_id = g.current_user.id
                approval.skillz_approved_at = datetime.now(timezone.utc)

                # Check if venue requires approval
                if tenant and tenant.requires_content_approval:
                    approval.status = ContentVenueApproval.STATUS_PENDING_VENUE
                    pending_venue_count += 1
                else:
                    # Auto-approve and sync to CMS
                    approval.venue_approved = True
                    approval.auto_approved = True
                    approval.venue_approved_at = datetime.now(timezone.utc)
                    approval.status = ContentVenueApproval.STATUS_APPROVED

                    if auto_sync and tenant:
                        result = CMSTransferService.transfer_to_cms(asset, tenant)
                        if result.get('success'):
                            asset.synced_to_cms = True
                            asset.synced_at = datetime.now(timezone.utc)
                            asset.cms_content_id = result.get('cms_content_id')
                            synced_count += 1
                        else:
                            errors.append({'id': asset_id, 'error': f"Sync failed: {result.get('error')}"})
        elif auto_sync and asset.tenant_id:
            # Legacy flow: No existing approvals, use asset.tenant_id
            tenant = Tenant.query.get(asset.tenant_id)
            if tenant:
                if tenant.requires_content_approval:
                    # Create pending venue approval
                    approval = ContentVenueApproval(
                        content_asset_id=asset.id,
                        tenant_id=tenant.id,
                        skillz_approved=True,
                        skillz_approved_by_id=g.current_user.id,
                        skillz_approved_at=datetime.now(timezone.utc),
                        venue_approved=False,
                        auto_approved=False,
                        status=ContentVenueApproval.STATUS_PENDING_VENUE
                    )
                    db.session.add(approval)
                    pending_venue_count += 1
                else:
                    # Venue doesn't require approval - sync to CMS
                    result = CMSTransferService.transfer_to_cms(asset, tenant)
                    if result.get('success'):
                        asset.synced_to_cms = True
                        asset.synced_at = datetime.now(timezone.utc)
                        asset.cms_content_id = result.get('cms_content_id')
                        synced_count += 1
                    else:
                        errors.append({'id': asset_id, 'error': f"Sync failed: {result.get('error')}"})

    db.session.commit()

    return jsonify({
        'success': True,
        'approved_count': approved_count,
        'synced_count': synced_count,
        'pending_venue_count': pending_venue_count,
        'errors': errors
    })
