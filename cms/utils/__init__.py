"""
CMS Utility Functions.

This package contains utility functions and decorators used across the CMS:
- auth: Authentication decorators and session validation
- permissions: Role-based permission checking
- audit: Audit logging helpers
"""

from cms.utils.auth import login_required, get_current_user
from cms.utils.permissions import (
    has_permission,
    require_role,
    require_admin,
    require_super_admin,
    require_content_manager,
    ROLE_HIERARCHY,
    can_manage_role,
    can_manage_user,
)

__all__ = [
    # Auth
    'login_required',
    'get_current_user',
    # Permissions
    'has_permission',
    'require_role',
    'require_admin',
    'require_super_admin',
    'require_content_manager',
    'ROLE_HIERARCHY',
    'can_manage_role',
    'can_manage_user',
]
