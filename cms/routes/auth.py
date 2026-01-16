"""
CMS Authentication Routes

Blueprint for authentication API endpoints:
- POST /login: Login with email/password
- POST /logout: Logout current session
- GET /me: Get current user info
- PUT /password: Change own password

All endpoints are prefixed with /api/v1/auth when registered with the app.
"""

import re

from flask import Blueprint, request, jsonify

from cms.models import db, User, UserSession
from cms.utils.auth import (
    login_required,
    login_required_allow_password_change,
    get_current_user,
    get_current_session,
    get_client_ip,
    get_user_agent,
    cleanup_expired_sessions,
)
from cms.utils.audit import log_auth_action


# Create auth blueprint
auth_bp = Blueprint('auth', __name__)


# Password validation pattern:
# - Minimum 12 characters
# - At least one uppercase letter
# - At least one lowercase letter
# - At least one number
# - At least one special character
PASSWORD_MIN_LENGTH = 12
PASSWORD_PATTERN = re.compile(
    r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?])'
)


def validate_password(password):
    """
    Validate password meets security requirements.

    Requirements:
    - Minimum 12 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - At least one special character

    Args:
        password: Password string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not password or len(password) < PASSWORD_MIN_LENGTH:
        return False, f'Password must be at least {PASSWORD_MIN_LENGTH} characters'

    if not re.search(r'[a-z]', password):
        return False, 'Password must contain at least one lowercase letter'

    if not re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter'

    if not re.search(r'\d', password):
        return False, 'Password must contain at least one number'

    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]', password):
        return False, 'Password must contain at least one special character'

    return True, None


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Login with email and password.

    Creates a new session upon successful authentication. Supports
    "remember me" functionality for extended session duration.

    Handles account lockout after 5 failed attempts with 15-minute lockout.

    Request Body:
        {
            "email": "user@example.com" (required),
            "password": "password123" (required),
            "remember_me": true (optional, default: false)
        }

    Returns:
        200: Login successful
            {
                "message": "Login successful",
                "user": { user data },
                "session": { session data with token },
                "must_change_password": false
            }
        400: Missing required field
            {
                "error": "email is required"
            }
        401: Invalid credentials or account issue
            {
                "error": "Invalid email or password",
                "code": "invalid_credentials"
            }
        403: Account suspended/deactivated
            {
                "error": "Account suspended",
                "code": "account_suspended",
                "reason": "Violation of terms"
            }
        423: Account locked due to failed attempts
            {
                "error": "Account locked due to too many failed attempts",
                "code": "account_locked",
                "locked_until": "2024-01-15T10:00:00Z"
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

    # Normalize email to lowercase
    email = email.lower().strip()

    # Validate password
    password = data.get('password')
    if not password:
        return jsonify({'error': 'password is required'}), 400

    if not isinstance(password, str):
        return jsonify({'error': 'password must be a string'}), 400

    # Optional remember_me
    remember_me = data.get('remember_me', False)
    if not isinstance(remember_me, bool):
        remember_me = False

    # Find user by email
    user = User.query.filter_by(email=email).first()

    # Log attempt IP for audit
    client_ip = get_client_ip()
    user_agent = get_user_agent()

    if not user:
        # Log failed attempt (no such user)
        log_auth_action(
            action='login',
            user_email=email,
            success=False,
            details={'reason': 'user_not_found'},
        )
        return jsonify({
            'error': 'Invalid email or password',
            'code': 'invalid_credentials'
        }), 401

    # Check if account is locked
    if user.is_locked():
        log_auth_action(
            action='login',
            user_email=email,
            success=False,
            user_id=user.id,
            user_name=user.name,
            user_role=user.role,
            details={'reason': 'account_locked'},
        )
        return jsonify({
            'error': 'Account locked due to too many failed attempts',
            'code': 'account_locked',
            'locked_until': user.locked_until.isoformat() if user.locked_until else None
        }), 423

    # Check account status
    if user.status == 'pending':
        log_auth_action(
            action='login',
            user_email=email,
            success=False,
            user_id=user.id,
            user_name=user.name,
            user_role=user.role,
            details={'reason': 'account_pending'},
        )
        return jsonify({
            'error': 'Account pending approval',
            'code': 'account_pending'
        }), 401

    if user.status == 'rejected':
        log_auth_action(
            action='login',
            user_email=email,
            success=False,
            user_id=user.id,
            user_name=user.name,
            user_role=user.role,
            details={'reason': 'account_rejected'},
        )
        return jsonify({
            'error': 'Account has been rejected',
            'code': 'account_rejected'
        }), 401

    if user.status == 'suspended':
        log_auth_action(
            action='login',
            user_email=email,
            success=False,
            user_id=user.id,
            user_name=user.name,
            user_role=user.role,
            details={'reason': 'account_suspended'},
        )
        return jsonify({
            'error': 'Account suspended',
            'code': 'account_suspended',
            'reason': user.suspended_reason
        }), 403

    if user.status == 'deactivated':
        log_auth_action(
            action='login',
            user_email=email,
            success=False,
            user_id=user.id,
            user_name=user.name,
            user_role=user.role,
            details={'reason': 'account_deactivated'},
        )
        return jsonify({
            'error': 'Account has been deactivated',
            'code': 'account_deactivated'
        }), 403

    # Verify password
    if not user.check_password(password):
        # Record failed attempt
        try:
            user.record_failed_login()
            db.session.commit()
        except Exception:
            db.session.rollback()

        log_auth_action(
            action='login',
            user_email=email,
            success=False,
            user_id=user.id,
            user_name=user.name,
            user_role=user.role,
            details={
                'reason': 'invalid_password',
                'failed_attempts': user.failed_login_attempts
            },
        )

        # Check if just got locked
        if user.is_locked():
            return jsonify({
                'error': 'Account locked due to too many failed attempts',
                'code': 'account_locked',
                'locked_until': user.locked_until.isoformat() if user.locked_until else None
            }), 423

        return jsonify({
            'error': 'Invalid email or password',
            'code': 'invalid_credentials'
        }), 401

    # Clean up any expired sessions for this user
    cleanup_expired_sessions(user_id=user.id)

    # Create new session
    session = UserSession.create_session(
        user_id=user.id,
        ip_address=client_ip,
        user_agent=user_agent,
        remember_me=remember_me
    )

    try:
        # Record successful login
        user.record_successful_login(ip_address=client_ip)
        db.session.add(session)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create session: {str(e)}'
        }), 500

    # Log successful login
    log_auth_action(
        action='login',
        user_email=email,
        success=True,
        user_id=user.id,
        user_name=user.name,
        user_role=user.role,
        details={
            'remember_me': remember_me,
            'session_id': session.id
        },
    )

    return jsonify({
        'message': 'Login successful',
        'user': user.to_dict(),
        'session': session.to_dict(include_token=True),
        'must_change_password': user.must_change_password
    }), 200


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    """
    Logout the current session.

    Deletes the current session, immediately invalidating the token.

    Request Headers:
        Authorization: Bearer <session_token> (required)

    Returns:
        200: Logout successful
            {
                "message": "Logged out successfully"
            }
        401: Not authenticated
            {
                "error": "Authentication required"
            }
    """
    session = get_current_session()
    user = get_current_user()

    try:
        # Delete the current session
        db.session.delete(session)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to logout: {str(e)}'
        }), 500

    # Log logout
    log_auth_action(
        action='logout',
        user_email=user.email,
        success=True,
        user_id=user.id,
        user_name=user.name,
        user_role=user.role,
        details={'session_id': session.id},
    )

    return jsonify({'message': 'Logged out successfully'}), 200


@auth_bp.route('/me', methods=['GET'])
@login_required
def get_me():
    """
    Get current authenticated user information.

    Request Headers:
        Authorization: Bearer <session_token> (required)

    Returns:
        200: User information
            {
                "user": { user data },
                "session": { current session data }
            }
        401: Not authenticated
            {
                "error": "Authentication required"
            }
    """
    user = get_current_user()
    session = get_current_session()

    return jsonify({
        'user': user.to_dict(),
        'session': session.to_dict()
    }), 200


@auth_bp.route('/password', methods=['PUT'])
@login_required_allow_password_change
def change_password():
    """
    Change the current user's password.

    Allows users to change their own password. If the user has
    must_change_password=True, this will clear that flag after
    successful password change.

    Password Requirements:
    - Minimum 12 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - At least one special character

    Request Headers:
        Authorization: Bearer <session_token> (required)

    Request Body:
        {
            "current_password": "old_password" (required),
            "new_password": "new_secure_password" (required)
        }

    Returns:
        200: Password changed successfully
            {
                "message": "Password changed successfully"
            }
        400: Validation error
            {
                "error": "new_password is required"
            }
        401: Current password incorrect
            {
                "error": "Current password is incorrect",
                "code": "invalid_password"
            }
    """
    user = get_current_user()

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate current password
    current_password = data.get('current_password')
    if not current_password:
        return jsonify({'error': 'current_password is required'}), 400

    if not isinstance(current_password, str):
        return jsonify({'error': 'current_password must be a string'}), 400

    # Validate new password
    new_password = data.get('new_password')
    if not new_password:
        return jsonify({'error': 'new_password is required'}), 400

    if not isinstance(new_password, str):
        return jsonify({'error': 'new_password must be a string'}), 400

    # Verify current password
    if not user.check_password(current_password):
        log_auth_action(
            action='password_change',
            user_email=user.email,
            success=False,
            user_id=user.id,
            user_name=user.name,
            user_role=user.role,
            details={'reason': 'invalid_current_password'},
        )
        return jsonify({
            'error': 'Current password is incorrect',
            'code': 'invalid_password'
        }), 401

    # Validate new password requirements
    is_valid, error_message = validate_password(new_password)
    if not is_valid:
        return jsonify({'error': error_message}), 400

    # Check new password is different from current
    if user.check_password(new_password):
        return jsonify({
            'error': 'New password must be different from current password'
        }), 400

    try:
        # Update password
        user.set_password(new_password)

        # Clear must_change_password flag if set
        was_forced = user.must_change_password
        user.must_change_password = False

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to change password: {str(e)}'
        }), 500

    # Log successful password change
    log_auth_action(
        action='password_change',
        user_email=user.email,
        success=True,
        user_id=user.id,
        user_name=user.name,
        user_role=user.role,
        details={'forced_change': was_forced},
    )

    return jsonify({'message': 'Password changed successfully'}), 200
