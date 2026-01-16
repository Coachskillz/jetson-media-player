"""
CMS Utility Functions.

This package contains utility functions and decorators used across the CMS:
- auth: Authentication decorators and session validation
- permissions: Role-based permission checking
- audit: Audit logging helpers
"""

from cms.utils.auth import login_required, get_current_user

__all__ = ['login_required', 'get_current_user']
