"""
CMS Authentication Utilities.

Provides authentication decorators and session validation for the CMS API.

Features:
- @login_required decorator for protecting routes
- Session token validation from Authorization header
- Current user retrieval via Flask's g object
- Automatic session activity tracking
- Support for both active and must_change_password states

Usage:
    from cms.utils.auth import login_required, get_current_user

    @blueprint.route('/protected')
    @login_required
    def protected_route():
        user = get_current_user()
        return jsonify({'user': user.to_dict()})
"""

from functools import wraps
from datetime import datetime, timezone

from flask import request, jsonify, g
from flask_login import current_user as flask_login_user

from cms.models import db, User, UserSession


def get_current_user():
    """
    Get the currently authenticated user.

    Returns the user object stored in Flask's g object by the @login_required
    decorator. Returns None if no user is authenticated.

    Returns:
        User object if authenticated, None otherwise
    """
    return getattr(g, 'current_user', None)


def get_current_session():
    """
    Get the current session object.

    Returns the session object stored in Flask's g object by the @login_required
    decorator. Returns None if no session is active.

    Returns:
        UserSession object if authenticated, None otherwise
    """
    return getattr(g, 'current_session', None)


def _extract_token_from_header():
    """
    Extract the bearer token from the Authorization header.

    Supports the format: "Bearer <token>"

    Returns:
        Token string if present and valid format, None otherwise
    """
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return None

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None

    return parts[1]


def _validate_session(token):
    """
    Validate a session token and return the associated user and session.

    Performs the following checks:
    1. Token exists in database
    2. Session has not expired
    3. User exists and is in an allowed state (active or must change password)
    4. User account is not locked

    Also updates the session's last_active timestamp on successful validation.

    Args:
        token: The session token to validate

    Returns:
        Tuple of (User, UserSession) if valid, (None, None) otherwise
    """
    if not token:
        return None, None

    # Find session by token
    session = UserSession.query.filter_by(token=token).first()
    if not session:
        return None, None

    # Check if session has expired
    if session.is_expired():
        # Optionally clean up expired session
        try:
            db.session.delete(session)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return None, None

    # Get the associated user
    user = db.session.get(User, session.user_id)
    if not user:
        return None, None

    # Check user status - allow 'active' users
    # Users with must_change_password=True can still be authenticated
    # (the password change requirement is enforced at the route level)
    if user.status not in ('active',):
        return None, None

    # Check if account is locked
    if user.is_locked():
        return None, None

    # Update session activity
    try:
        session.update_activity()
        db.session.commit()
    except Exception:
        db.session.rollback()

    return user, session


def login_required(f):
    """
    Decorator to require authentication for a route.

    Validates the session token from the Authorization header and
    stores the authenticated user in Flask's g object for access
    by the route handler.

    The decorator checks:
    1. Authorization header is present with Bearer token
    2. Token corresponds to a valid, non-expired session
    3. User is in an active state and not locked

    On failure, returns a 401 Unauthorized response.

    Usage:
        @blueprint.route('/protected')
        @login_required
        def protected_route():
            user = get_current_user()
            # user is guaranteed to be authenticated here
            return jsonify({'message': f'Hello, {user.name}'})

    Args:
        f: The route function to wrap

    Returns:
        Decorated function that enforces authentication
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # First check if user is logged in via Flask-Login session
        if flask_login_user and flask_login_user.is_authenticated:
            g.current_user = flask_login_user
            g.current_session = None
            return f(*args, **kwargs)
        
        # Extract token from Authorization header
        token = _extract_token_from_header()
        if not token:
            return jsonify({
                'error': 'Authentication required',
                'code': 'missing_token'
            }), 401
        
        # Validate the session
        user, session = _validate_session(token)
        if not user:
            return jsonify({
                'error': 'Invalid or expired session',
                'code': 'invalid_session'
            }), 401
        
        # Store user and session in g for access by route
        g.current_user = user
        g.current_session = session
        
        return f(*args, **kwargs)

    return decorated_function

def login_required_allow_password_change(f):
    """
    Decorator that allows users who must change their password.

    Similar to @login_required but specifically for routes that handle
    password changes. Users with must_change_password=True can access
    routes decorated with this.

    Usage:
        @blueprint.route('/auth/password', methods=['PUT'])
        @login_required_allow_password_change
        def change_password():
            # Allows users who need to change their password
            pass

    Args:
        f: The route function to wrap

    Returns:
        Decorated function that enforces authentication
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # First check if user is logged in via Flask-Login session
        if flask_login_user and flask_login_user.is_authenticated:
            g.current_user = flask_login_user
            g.current_session = None
            return f(*args, **kwargs)
        
        # Extract token from Authorization header
        token = _extract_token_from_header()
        if not token:
            return jsonify({
                'error': 'Authentication required',
                'code': 'missing_token'
            }), 401
        
        # Validate the session
        user, session = _validate_session(token)
        if not user:
            return jsonify({
                'error': 'Invalid or expired session',
                'code': 'invalid_session'
            }), 401
        
        # Store user and session in g for access by route
        g.current_user = user
        g.current_session = session
        
        return f(*args, **kwargs)

    return decorated_function

def get_client_ip():
    """
    Get the client's IP address from the request.

    Handles X-Forwarded-For header for proxied requests.

    Returns:
        Client IP address string
    """
    # Check for X-Forwarded-For header (when behind proxy/load balancer)
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        # Take the first IP in the list (client's original IP)
        return forwarded_for.split(',')[0].strip()

    # Fall back to remote_addr
    return request.remote_addr


def get_user_agent():
    """
    Get the client's user agent string from the request.

    Returns:
        User agent string, truncated to 500 characters
    """
    user_agent = request.headers.get('User-Agent', '')
    return user_agent[:500] if user_agent else None


def cleanup_expired_sessions(user_id=None):
    """
    Remove expired sessions from the database.

    Can be called periodically or during login to clean up stale sessions.

    Args:
        user_id: If provided, only clean up sessions for this user.
                 If None, cleans up all expired sessions.

    Returns:
        Number of sessions deleted
    """
    now = datetime.now(timezone.utc)

    query = UserSession.query.filter(UserSession.expires_at < now)
    if user_id:
        query = query.filter_by(user_id=user_id)

    try:
        count = query.delete(synchronize_session=False)
        db.session.commit()
        return count
    except Exception:
        db.session.rollback()
        return 0
