"""
Content Catalog Routes Package.

Blueprint registration for all API route modules:
- Auth: Admin authentication endpoints (login, logout, me)
- Content: Content management and search endpoints
- Partners: Partner portal and organization management
- Users: User management and authentication
- Invitations: User invitation management
- Organizations: Organization management endpoints
- Approvals: User approval workflow endpoints
- Categories: Content categorization
- Collections: Content collection management
- Assets: Content asset management
- Audit: Audit log viewing endpoints
- Admin Web: Admin portal web pages
- Partner Web: Partner portal web pages
"""

# Import blueprints for registration
from content_catalog.routes.auth import auth_bp
from content_catalog.routes.users import users_bp
from content_catalog.routes.invitations import invitations_bp
from content_catalog.routes.organizations import organizations_bp
from content_catalog.routes.approvals import approvals_bp
from content_catalog.routes.assets import assets_bp
from content_catalog.routes.audit import audit_bp
from content_catalog.routes.admin_web import admin_web_bp
from content_catalog.routes.partner_web import partner_web_bp

__all__ = [
    'auth_bp',
    'users_bp',
    'invitations_bp',
    'organizations_bp',
    'approvals_bp',
    'assets_bp',
    'audit_bp',
    'admin_web_bp',
    'partner_web_bp',
]
