"""
Content Catalog Audit Routes.

Blueprint for audit log API endpoints:
- GET /: List all audit logs with optional filtering

All endpoints are prefixed with /admin/api/audit-logs when registered with the app.
All endpoints require JWT authentication and admin permissions.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from content_catalog.models import db, User, AuditLog


# Create audit blueprint
audit_bp = Blueprint('audit', __name__)


def _get_current_user():
    """
    Get the current authenticated user from JWT identity.

    Returns:
        User object or None if not found
    """
    current_user_id = get_jwt_identity()
    return db.session.get(User, current_user_id)


def _can_view_audit_logs(user):
    """
    Check if the user has permission to view audit logs.

    Only Super Admins and Admins can view audit logs.

    Args:
        user: The User object to check permissions for

    Returns:
        True if user can view audit logs, False otherwise
    """
    if not user:
        return False
    return user.role in [
        User.ROLE_SUPER_ADMIN,
        User.ROLE_ADMIN
    ]


@audit_bp.route('', methods=['GET'])
@jwt_required()
def list_audit_logs():
    """
    List all audit logs with optional filtering.

    Returns a paginated list of audit logs with optional filtering by user,
    action type, resource type, date range, or IP address.

    Query Parameters:
        user_id: Filter by user ID who performed the action
        user_email: Filter by user email (partial match)
        action: Filter by action type (e.g., 'user.login', 'content.uploaded')
        resource_type: Filter by resource type (user, organization, content, etc.)
        resource_id: Filter by specific resource ID
        ip_address: Filter by IP address
        start_date: Filter logs from this date (ISO format: YYYY-MM-DD)
        end_date: Filter logs until this date (ISO format: YYYY-MM-DD)
        page: Page number (default: 1)
        per_page: Items per page (default: 50, max: 100)

    Returns:
        200: List of audit logs
            {
                "audit_logs": [ { audit log data }, ... ],
                "count": 50,
                "page": 1,
                "per_page": 50,
                "total": 500
            }
        401: Unauthorized (missing or invalid token)
        403: Forbidden (insufficient permissions)
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user has permission to view audit logs
    if not _can_view_audit_logs(current_user):
        return jsonify({'error': 'Insufficient permissions to view audit logs'}), 403

    # Build query with optional filters
    query = AuditLog.query

    # Filter by user_id
    user_id_filter = request.args.get('user_id')
    if user_id_filter:
        try:
            user_id = int(user_id_filter)
            query = query.filter_by(user_id=user_id)
        except ValueError:
            return jsonify({'error': 'user_id must be an integer'}), 400

    # Filter by user_email (partial match, case-insensitive)
    user_email_filter = request.args.get('user_email')
    if user_email_filter:
        query = query.filter(
            AuditLog.user_email.ilike(f'%{user_email_filter}%')
        )

    # Filter by action
    action_filter = request.args.get('action')
    if action_filter:
        query = query.filter_by(action=action_filter)

    # Filter by resource_type
    resource_type_filter = request.args.get('resource_type')
    if resource_type_filter:
        if resource_type_filter not in AuditLog.VALID_RESOURCE_TYPES:
            return jsonify({
                'error': f"Invalid resource_type. Must be one of: {', '.join(AuditLog.VALID_RESOURCE_TYPES)}"
            }), 400
        query = query.filter_by(resource_type=resource_type_filter)

    # Filter by resource_id
    resource_id_filter = request.args.get('resource_id')
    if resource_id_filter:
        query = query.filter_by(resource_id=str(resource_id_filter))

    # Filter by ip_address
    ip_address_filter = request.args.get('ip_address')
    if ip_address_filter:
        query = query.filter_by(ip_address=ip_address_filter)

    # Filter by date range
    start_date_str = request.args.get('start_date')
    if start_date_str:
        try:
            start_date = datetime.fromisoformat(start_date_str)
            query = query.filter(AuditLog.created_at >= start_date)
        except ValueError:
            return jsonify({
                'error': 'Invalid start_date format. Use ISO format: YYYY-MM-DD'
            }), 400

    end_date_str = request.args.get('end_date')
    if end_date_str:
        try:
            # Add 1 day to include the entire end date
            end_date = datetime.fromisoformat(end_date_str)
            # Set to end of day
            end_date = end_date.replace(hour=23, minute=59, second=59)
            query = query.filter(AuditLog.created_at <= end_date)
        except ValueError:
            return jsonify({
                'error': 'Invalid end_date format. Use ISO format: YYYY-MM-DD'
            }), 400

    # Pagination parameters
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

    # Get total count before pagination
    total = query.count()

    # Apply pagination and ordering (most recent first)
    audit_logs = query.order_by(AuditLog.created_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return jsonify({
        'audit_logs': [log.to_dict() for log in audit_logs],
        'count': len(audit_logs),
        'page': page,
        'per_page': per_page,
        'total': total
    }), 200
