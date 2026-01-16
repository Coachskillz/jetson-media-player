"""
CMS Routes Package

Blueprint registration for all API route modules:
- Devices: Device registration and management
- Hubs: Hub registration and manifest delivery
- Content: Media file upload and management
- Playlists: Playlist creation and device assignment
- Web: Web UI page rendering
"""

# Import Devices blueprint from its module
from cms.routes.devices import devices_bp

# Import Hubs blueprint from its module
from cms.routes.hubs import hubs_bp

# Import Content blueprint from its module
from cms.routes.content import content_bp

# Import Playlists blueprint from its module
from cms.routes.playlists import playlists_bp

# Import Web UI blueprint from its module
from cms.routes.web import web_bp


__all__ = [
    'devices_bp',
    'hubs_bp',
    'content_bp',
    'playlists_bp',
    'web_bp',
]
