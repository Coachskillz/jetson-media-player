"""
CMS Content Routes

Blueprint for content management API endpoints:
- POST /upload: Upload content file
- GET /download/<content_id>: Download content file
- GET /: List all content
- DELETE /<content_id>: Delete content
"""

from flask import Blueprint

# Create content blueprint
content_bp = Blueprint('content', __name__)


# Route implementations will be added in subtask-3-4
