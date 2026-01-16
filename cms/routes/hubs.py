"""
CMS Hubs Routes

Blueprint for hub management API endpoints:
- POST /register: Register a new hub
- GET /: List all hubs
- GET /<hub_id>/manifest: Get hub content manifest
"""

from flask import Blueprint

# Create hubs blueprint
hubs_bp = Blueprint('hubs', __name__)


# Route implementations will be added in subtask-3-3
