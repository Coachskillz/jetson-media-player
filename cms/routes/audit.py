"""
CMS Audit Logs Routes

Blueprint for audit log viewing API endpoints:
- GET /: List audit logs with filtering and pagination
- GET /<id>: Get a specific audit log detail
- GET /logins: Login history (auth-related actions)
- GET /export: Export audit logs as CSV
- GET /summary: Dashboard summary statistics
- GET /users/<id>/activity: Get a specific user's activity

All endpoints are prefixed with /api/v1/audit-logs when registered with the app.
All endpoints require authentication and admin+ role.
"""

import csv
import io
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify, Response

from cms.models import db, AuditLog, User
from cms.utils.auth import login_required, get_current_user
from cms.utils.permissions import require_role


# Create audit blueprint
audit_bp = Blueprint('audit', __name__)


@audit_bp.route('', methods=['GET'])
@login_required
@require_role('admin')
def list_audit_logs():
    """
    List audit logs with filtering and pagination.

    Query Parameters:
        page: Page number (default: 1)
        per_page: Items per page (default: 50, max: 100)
        user_email: Filter by user email (partial match)
        user_id: Filter by exact user ID
        action: Filter by action name (partial match)
        action_category: Filter by action category
        resource_type: Filter by resource type
        resource_id: Filter by resource ID
        start_date: Filter logs after this date (ISO 8601)
        end_date: Filter logs before this date (ISO 8601)
        ip_address: Filter by IP address (partial match)

    Returns:
        200: Paginated list of audit logs
            {
                "audit_logs": [ { audit log data }, ... ],
                "pagination": {
                    "page": 1,
                    "per_page": 50,
                    "total": 150,
                    "pages": 3,
                    "has_next": true,
                    "has_prev": false
                }
            }
    """
    # Parse pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Validate pagination
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 50
    if per_page > 100:
        per_page = 100

    # Build query with filters
    query = AuditLog.query

    # Filter by user email (partial match)
    user_email = request.args.get('user_email')
    if user_email:
        query = query.filter(AuditLog.user_email.ilike(f'%{user_email}%'))

    # Filter by user ID (exact match)
    user_id = request.args.get('user_id')
    if user_id:
        query = query.filter_by(user_id=user_id)

    # Filter by action (partial match)
    action = request.args.get('action')
    if action:
        query = query.filter(AuditLog.action.ilike(f'%{action}%'))

    # Filter by action category (exact match)
    action_category = request.args.get('action_category')
    if action_category:
        if action_category not in AuditLog.VALID_CATEGORIES:
            return jsonify({
                'error': f'Invalid action_category. Must be one of: {", ".join(AuditLog.VALID_CATEGORIES)}'
            }), 400
        query = query.filter_by(action_category=action_category)

    # Filter by resource type (exact match)
    resource_type = request.args.get('resource_type')
    if resource_type:
        query = query.filter_by(resource_type=resource_type)

    # Filter by resource ID (exact match)
    resource_id = request.args.get('resource_id')
    if resource_id:
        query = query.filter_by(resource_id=resource_id)

    # Filter by IP address (partial match)
    ip_address = request.args.get('ip_address')
    if ip_address:
        query = query.filter(AuditLog.ip_address.ilike(f'%{ip_address}%'))

    # Filter by date range
    start_date = request.args.get('start_date')
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            query = query.filter(AuditLog.created_at >= start_dt)
        except ValueError:
            return jsonify({'error': 'Invalid start_date format. Use ISO 8601.'}), 400

    end_date = request.args.get('end_date')
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            query = query.filter(AuditLog.created_at <= end_dt)
        except ValueError:
            return jsonify({'error': 'Invalid end_date format. Use ISO 8601.'}), 400

    # Order by created_at descending (newest first)
    query = query.order_by(AuditLog.created_at.desc())

    # Execute paginated query
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'audit_logs': [log.to_dict() for log in pagination.items],
        'pagination': {
            'page': pagination.page,
            'per_page': pagination.per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    }), 200


@audit_bp.route('/<log_id>', methods=['GET'])
@login_required
@require_role('admin')
def get_audit_log(log_id):
    """
    Get a specific audit log by ID.

    Args:
        log_id: UUID of the audit log

    Returns:
        200: Audit log details
            {
                "id": "uuid",
                "user_id": "uuid",
                "user_email": "user@example.com",
                "action": "user.create",
                "action_category": "users",
                "resource_type": "user",
                "resource_id": "uuid",
                "resource_name": "New User",
                "details": "{ json details }",
                "ip_address": "192.168.1.1",
                "user_agent": "Mozilla/5.0...",
                "session_id": "uuid",
                "created_at": "2024-01-15T10:00:00Z"
            }
        404: Audit log not found
            {
                "error": "Audit log not found"
            }
    """
    audit_log = db.session.get(AuditLog, log_id)

    if not audit_log:
        return jsonify({'error': 'Audit log not found'}), 404

    return jsonify(audit_log.to_dict()), 200


@audit_bp.route('/logins', methods=['GET'])
@login_required
@require_role('admin')
def list_login_history():
    """
    Get login history (authentication-related actions).

    Filters audit logs for auth category actions like login, logout,
    password changes, and failed login attempts.

    Query Parameters:
        page: Page number (default: 1)
        per_page: Items per page (default: 50, max: 100)
        user_email: Filter by user email (partial match)
        start_date: Filter logs after this date (ISO 8601)
        end_date: Filter logs before this date (ISO 8601)
        success_only: If 'true', only show successful logins

    Returns:
        200: Paginated list of login-related audit logs
            {
                "logins": [ { audit log data }, ... ],
                "pagination": { ... }
            }
    """
    # Parse pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Validate pagination
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 50
    if per_page > 100:
        per_page = 100

    # Build query - filter for auth category
    query = AuditLog.query.filter_by(action_category='auth')

    # Filter by user email
    user_email = request.args.get('user_email')
    if user_email:
        query = query.filter(AuditLog.user_email.ilike(f'%{user_email}%'))

    # Filter by success only
    success_only = request.args.get('success_only')
    if success_only and success_only.lower() == 'true':
        query = query.filter(AuditLog.action == 'login.success')

    # Filter by date range
    start_date = request.args.get('start_date')
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            query = query.filter(AuditLog.created_at >= start_dt)
        except ValueError:
            return jsonify({'error': 'Invalid start_date format. Use ISO 8601.'}), 400

    end_date = request.args.get('end_date')
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            query = query.filter(AuditLog.created_at <= end_dt)
        except ValueError:
            return jsonify({'error': 'Invalid end_date format. Use ISO 8601.'}), 400

    # Order by created_at descending
    query = query.order_by(AuditLog.created_at.desc())

    # Execute paginated query
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'logins': [log.to_dict() for log in pagination.items],
        'pagination': {
            'page': pagination.page,
            'per_page': pagination.per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    }), 200


@audit_bp.route('/export', methods=['GET'])
@login_required
@require_role('admin')
def export_audit_logs():
    """
    Export audit logs as CSV.

    Exports audit logs based on filter criteria. Limited to 10,000 records
    for performance reasons.

    Query Parameters:
        user_email: Filter by user email (partial match)
        action_category: Filter by action category
        resource_type: Filter by resource type
        start_date: Filter logs after this date (ISO 8601)
        end_date: Filter logs before this date (ISO 8601)

    Returns:
        200: CSV file download
        400: Invalid filter parameters
    """
    # Build query with filters
    query = AuditLog.query

    # Filter by user email
    user_email = request.args.get('user_email')
    if user_email:
        query = query.filter(AuditLog.user_email.ilike(f'%{user_email}%'))

    # Filter by action category
    action_category = request.args.get('action_category')
    if action_category:
        if action_category not in AuditLog.VALID_CATEGORIES:
            return jsonify({
                'error': f'Invalid action_category. Must be one of: {", ".join(AuditLog.VALID_CATEGORIES)}'
            }), 400
        query = query.filter_by(action_category=action_category)

    # Filter by resource type
    resource_type = request.args.get('resource_type')
    if resource_type:
        query = query.filter_by(resource_type=resource_type)

    # Filter by date range
    start_date = request.args.get('start_date')
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            query = query.filter(AuditLog.created_at >= start_dt)
        except ValueError:
            return jsonify({'error': 'Invalid start_date format. Use ISO 8601.'}), 400

    end_date = request.args.get('end_date')
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            query = query.filter(AuditLog.created_at <= end_dt)
        except ValueError:
            return jsonify({'error': 'Invalid end_date format. Use ISO 8601.'}), 400

    # Order by created_at descending and limit to 10,000 records
    query = query.order_by(AuditLog.created_at.desc()).limit(10000)

    # Execute query
    audit_logs = query.all()

    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([
        'ID',
        'Timestamp',
        'User Email',
        'User Name',
        'User Role',
        'Action',
        'Category',
        'Resource Type',
        'Resource ID',
        'Resource Name',
        'IP Address',
        'User Agent',
        'Details'
    ])

    # Write data rows
    for log in audit_logs:
        writer.writerow([
            log.id,
            log.created_at.isoformat() if log.created_at else '',
            log.user_email,
            log.user_name or '',
            log.user_role or '',
            log.action,
            log.action_category,
            log.resource_type or '',
            log.resource_id or '',
            log.resource_name or '',
            log.ip_address or '',
            log.user_agent or '',
            log.details or ''
        ])

    # Prepare response
    output.seek(0)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    filename = f'audit_logs_{timestamp}.csv'

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename={filename}'
        }
    )


@audit_bp.route('/summary', methods=['GET'])
@login_required
@require_role('admin')
def get_audit_summary():
    """
    Get summary statistics for the audit logs.

    Provides dashboard-style overview of audit log activity including
    counts by category, recent activity, and login statistics.

    Query Parameters:
        days: Number of days to include (default: 7, max: 30)

    Returns:
        200: Summary statistics
            {
                "period_days": 7,
                "total_actions": 150,
                "by_category": {
                    "auth": 50,
                    "users": 20,
                    "devices": 30,
                    ...
                },
                "by_action": {
                    "login.success": 40,
                    "user.create": 10,
                    ...
                },
                "login_stats": {
                    "successful_logins": 40,
                    "failed_logins": 10,
                    "unique_users": 15
                },
                "recent_activity": [ { last 10 actions }, ... ]
            }
    """
    # Parse days parameter
    days = request.args.get('days', 7, type=int)
    if days < 1:
        days = 1
    if days > 30:
        days = 30

    # Calculate start date
    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    # Base query for the period
    base_query = AuditLog.query.filter(AuditLog.created_at >= start_date)

    # Total actions
    total_actions = base_query.count()

    # Count by category
    by_category = {}
    for category in AuditLog.VALID_CATEGORIES:
        count = base_query.filter_by(action_category=category).count()
        if count > 0:
            by_category[category] = count

    # Count by action (top 20)
    action_counts = db.session.query(
        AuditLog.action,
        db.func.count(AuditLog.id).label('count')
    ).filter(
        AuditLog.created_at >= start_date
    ).group_by(
        AuditLog.action
    ).order_by(
        db.func.count(AuditLog.id).desc()
    ).limit(20).all()

    by_action = {action: count for action, count in action_counts}

    # Login statistics
    auth_query = base_query.filter_by(action_category='auth')
    successful_logins = auth_query.filter_by(action='login.success').count()
    failed_logins = auth_query.filter_by(action='login.failed').count()

    # Unique users who logged in
    unique_users = db.session.query(
        db.func.count(db.func.distinct(AuditLog.user_id))
    ).filter(
        AuditLog.created_at >= start_date,
        AuditLog.action == 'login.success'
    ).scalar() or 0

    login_stats = {
        'successful_logins': successful_logins,
        'failed_logins': failed_logins,
        'unique_users': unique_users
    }

    # Recent activity (last 10 actions)
    recent_logs = AuditLog.query.order_by(
        AuditLog.created_at.desc()
    ).limit(10).all()

    recent_activity = [log.to_dict() for log in recent_logs]

    return jsonify({
        'period_days': days,
        'total_actions': total_actions,
        'by_category': by_category,
        'by_action': by_action,
        'login_stats': login_stats,
        'recent_activity': recent_activity
    }), 200


@audit_bp.route('/users/<user_id>/activity', methods=['GET'])
@login_required
@require_role('admin')
def get_user_activity(user_id):
    """
    Get activity logs for a specific user.

    Returns audit logs for all actions performed by the specified user.

    Args:
        user_id: UUID of the user

    Query Parameters:
        page: Page number (default: 1)
        per_page: Items per page (default: 50, max: 100)
        action_category: Filter by action category
        start_date: Filter logs after this date (ISO 8601)
        end_date: Filter logs before this date (ISO 8601)

    Returns:
        200: Paginated list of user's audit logs
            {
                "user": {
                    "id": "uuid",
                    "email": "user@example.com",
                    "name": "User Name"
                },
                "activity": [ { audit log data }, ... ],
                "pagination": { ... }
            }
        404: User not found
    """
    # Find the user
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Parse pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Validate pagination
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 50
    if per_page > 100:
        per_page = 100

    # Build query for this user's activity
    query = AuditLog.query.filter_by(user_id=user_id)

    # Filter by action category
    action_category = request.args.get('action_category')
    if action_category:
        if action_category not in AuditLog.VALID_CATEGORIES:
            return jsonify({
                'error': f'Invalid action_category. Must be one of: {", ".join(AuditLog.VALID_CATEGORIES)}'
            }), 400
        query = query.filter_by(action_category=action_category)

    # Filter by date range
    start_date = request.args.get('start_date')
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            query = query.filter(AuditLog.created_at >= start_dt)
        except ValueError:
            return jsonify({'error': 'Invalid start_date format. Use ISO 8601.'}), 400

    end_date = request.args.get('end_date')
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            query = query.filter(AuditLog.created_at <= end_dt)
        except ValueError:
            return jsonify({'error': 'Invalid end_date format. Use ISO 8601.'}), 400

    # Order by created_at descending
    query = query.order_by(AuditLog.created_at.desc())

    # Execute paginated query
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'user': {
            'id': user.id,
            'email': user.email,
            'name': user.name
        },
        'activity': [log.to_dict() for log in pagination.items],
        'pagination': {
            'page': pagination.page,
            'per_page': pagination.per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    }), 200
