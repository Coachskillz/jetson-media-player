"""
Web Session Authentication Helpers

Provides session-based authentication for admin web routes.
"""

from functools import wraps
from flask import session, redirect, url_for, request, g
from content_catalog.models import db, User


def login_required(f):
    """
    Decorator to require login for web routes.
    
    Checks for user_id in session. If not present, redirects to login.
    Loads the user object into g.current_user for use in the route.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        
        if not user_id:
            # Store the requested URL to redirect back after login
            session['next_url'] = request.url
            return redirect(url_for('admin.login'))
        
        # Load user from database
        user = db.session.get(User, user_id)
        
        if not user:
            # User was deleted, clear session
            session.clear()
            return redirect(url_for('admin.login'))
        
        if user.status != User.STATUS_ACTIVE:
            # User account is no longer active
            session.clear()
            return redirect(url_for('admin.login'))
        
        # Store user in g for access in route
        g.current_user = user
        
        return f(*args, **kwargs)
    
    return decorated_function


def admin_required(f):
    """
    Decorator to require admin role for web routes.
    
    Must be used after @login_required.
    Checks that the user has admin, super_admin, or content_manager role.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = getattr(g, 'current_user', None)
        
        if not user:
            return redirect(url_for('admin.login'))
        
        # Check for admin-level roles
        admin_roles = [
            User.ROLE_SUPER_ADMIN,
            User.ROLE_ADMIN,
            User.ROLE_CONTENT_MANAGER
        ]
        
        if user.role not in admin_roles:
            # Not authorized - could redirect to an error page
            return redirect(url_for('admin.dashboard'))
        
        return f(*args, **kwargs)
    
    return decorated_function


def get_current_user():
    """
    Get the current logged-in user from session.
    
    Returns:
        User object or None
    """
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, user_id)
