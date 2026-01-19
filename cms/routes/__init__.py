"""
CMS Routes Package

Blueprint registration for all API route modules:
- Networks: Network management (top-level organizational units)
- Devices: Device registration and management
- Hubs: Hub registration and manifest delivery
- Content: Media file upload and management
- Thea: Proxy routes for Thea Content Catalog integration
- Playlists: Playlist creation and device assignment
- Layouts: Screen layout management for multi-zone displays
- Web: Web UI page rendering
- Auth: Authentication (login, logout, password management)
- Users: User management and profiles
- Invitations: User invitation system
- Sessions: Session management
- Audit: Audit logging and history
"""

# Import Networks blueprint from its module
from cms.routes.networks import networks_bp

# Import Devices blueprint from its module
from cms.routes.devices import devices_bp

# Import Hubs blueprint from its module
from cms.routes.hubs import hubs_bp

# Import Content blueprint from its module
from cms.routes.content import content_bp

# Import Thea Content Catalog proxy blueprint from its module
from cms.routes.content import thea_bp

# Import Playlists blueprint from its module
from cms.routes.playlists import playlists_bp

# Import Layouts blueprints from its module
from cms.routes.layouts import layouts_bp, layouts_web_bp

# Import Web UI blueprint from its module
from cms.routes.web import web_bp

# Import Auth blueprint from its module
from cms.routes.auth import auth_bp

# Import Users blueprint from its module
from cms.routes.users import users_bp

# Import Invitations blueprint from its module
from cms.routes.invitations import invitations_bp

# Import Sessions blueprint from its module
from cms.routes.sessions import sessions_bp

# Import Audit blueprint from its module
from cms.routes.audit import audit_bp

# Import Catalog Integration blueprint from its module
from cms.routes.catalog_integration import catalog_bp


__all__ = [
    'networks_bp',
    'devices_bp',
    'hubs_bp',
    'content_bp',
    'thea_bp',
    'playlists_bp',
    'layouts_bp',
    'layouts_web_bp',
    'web_bp',
    'auth_bp',
    'users_bp',
    'invitations_bp',
    'sessions_bp',
    'audit_bp',
    'catalog_bp',
]