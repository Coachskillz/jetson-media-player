"""
CMS Web UI Routes

Blueprint for web page rendering:
- GET /: Dashboard
- GET /devices: Device management page
- GET /hubs: Hub management page
- GET /content: Content management page
- GET /playlists: Playlist management page
"""

from flask import Blueprint

# Create web blueprint
web_bp = Blueprint('web', __name__)


# Route implementations will be added in subtask-4-1
