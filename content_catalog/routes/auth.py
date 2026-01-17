"""
Content Catalog Authentication Routes.

Blueprint for admin authentication API endpoints:
- POST /login: Authenticate admin user and return JWT token
- POST /logout: Invalidate current session
- GET /me: Get current authenticated user information

All endpoints are prefixed with /admin/api when registered with the app.
"""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    get_jwt_identity,
    jwt_required,
)

from content_catalog.models import db, User
from content_catalog.services.auth_service import AuthService
from content_catalog.services.audit_service import AuditService


# Create auth blueprint
auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Authenticate a user and return a JWT access token.

    Validates user credentials, checks account status and lockout,
    and issues a JWT token on successful authentication.

    Request Body:
        {
            "email": "user@example.com" (required),
            "password": "user_password" (required)
        }

    Returns:
        200: Successful authentication
            {
                "access_token": "jwt_token_string",
                "user": { user data }
            }
        400: Missing required field
            {
                "error": "error message"
            }
        401: Invalid credentials or account issues
            {
                "error": "error message"
            }
    """
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
        # Log failed login attempt (user not found)
        AuditService.log_action(
            db_session=db.session,
            action='user.login_failed',
            user_email=email,
            details={'reason': 'user_not_found'}
        )
        db.session.commit()
        return jsonify({'error': 'Invalid email or password'}), 401

    # Check if account is locked
    if user.is_locked():
        AuditService.log_action(
            db_session=db.session,
            action='user.login_failed',
            user_id=user.id,
            user_email=user.email,
            resource_type='user',
            resource_id=user.id,
            details={'reason': 'account_locked'}
        )
        db.session.commit()
        return jsonify({'error': 'Account is locked. Please try again later.'}), 401

    # Check user status - only active users can login
    if user.status != User.STATUS_ACTIVE:
        AuditService.log_action(
            db_session=db.session,
            action='user.login_failed',
            user_id=user.id,
            user_email=user.email,
            resource_type='user',
            resource_id=user.id,
            details={'reason': f'account_status_{user.status}'}
        )
        db.session.commit()

        if user.status == User.STATUS_PENDING:
            return jsonify({'error': 'Account is pending approval'}), 401
        elif user.status == User.STATUS_SUSPENDED:
            return jsonify({'error': 'Account has been suspended'}), 401
        elif user.status == User.STATUS_DEACTIVATED:
            return jsonify({'error': 'Account has been deactivated'}), 401
        elif user.status == User.STATUS_REJECTED:
            return jsonify({'error': 'Account registration was rejected'}), 401
        else:
            return jsonify({'error': 'Account is not active'}), 401

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
            action='user.login_failed',
            user_id=user.id,
            user_email=user.email,
            resource_type='user',
            resource_id=user.id,
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

        return jsonify({'error': 'Invalid email or password'}), 401

    # Successful login - reset failed attempts and update last login
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.now(timezone.utc)

    # Create JWT access token with user ID as identity
    access_token = create_access_token(identity=user.id)

    # Create session record for tracking
    AuthService.create_session(
        db_session=db.session,
        user_id=user.id,
        ip_address=_get_client_ip(),
        user_agent=_get_user_agent()
    )

    # Log successful login
    AuditService.log_action(
        db_session=db.session,
        action='user.login',
        user_id=user.id,
        user_email=user.email,
        resource_type='user',
        resource_id=user.id,
        details={'method': 'password'}
    )

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to complete login: {str(e)}'}), 500

    return jsonify({
        'access_token': access_token,
        'user': user.to_dict()
    }), 200


@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """
    Logout the current user and invalidate their session.

    Requires a valid JWT token in the Authorization header.

    Returns:
        200: Successful logout
            {
                "message": "Logged out successfully"
            }
        401: Unauthorized (missing or invalid token)
            {
                "error": "Unauthorized"
            }
    """
    current_user_id = get_jwt_identity()

    # Find user for audit log
    user = db.session.get(User, current_user_id)
    user_email = user.email if user else None

    # Invalidate all active sessions for this user
    # (Note: In a production system, you might want to only invalidate the current session)
    sessions_invalidated = AuthService.invalidate_all_user_sessions(
        db_session=db.session,
        user_id=current_user_id
    )

    # Log logout action
    AuditService.log_action(
        db_session=db.session,
        action='user.logout',
        user_id=current_user_id,
        user_email=user_email,
        resource_type='user',
        resource_id=current_user_id,
        details={'sessions_invalidated': sessions_invalidated}
    )

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to complete logout: {str(e)}'}), 500

    return jsonify({'message': 'Logged out successfully'}), 200


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """
    Get the current authenticated user's information.

    Requires a valid JWT token in the Authorization header.

    Returns:
        200: Current user data
            {
                "id": 1,
                "email": "user@example.com",
                "name": "User Name",
                "role": "admin",
                ...
            }
        401: Unauthorized (missing or invalid token)
            {
                "error": "Unauthorized"
            }
        404: User not found (token valid but user deleted)
            {
                "error": "User not found"
            }
    """
    current_user_id = get_jwt_identity()

    user = db.session.get(User, current_user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Check if user account is still active
    if user.status != User.STATUS_ACTIVE:
        return jsonify({'error': 'Account is not active'}), 401

    return jsonify(user.to_dict()), 200


def _get_client_ip():
    """
    Extract the client IP address from the Flask request.

    Handles proxy headers (X-Forwarded-For, X-Real-IP) for proper
    IP extraction when behind reverse proxies or load balancers.

    Returns:
        The client IP address, or None if not available
    """
    # Check for proxy headers first (common in production)
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()

    # Check X-Real-IP (common with nginx)
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return real_ip.strip()

    # Fall back to remote_addr
    return request.remote_addr


def _get_user_agent():
    """
    Extract the user agent string from the Flask request.

    Returns:
        The user agent string, or None if not available
    """
    if request.user_agent:
        return request.user_agent.string
    return None
