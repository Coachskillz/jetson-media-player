"""
API Route Blueprints for Local Hub Service.

This module defines and exports Flask blueprints for the local hub API:
- screens_bp: Screen/device management endpoints
- content_bp: Content management endpoints
- databases_bp: Database sync and management endpoints
- alerts_bp: Alert system endpoints
- devices_bp: Device relay endpoints (proxy to cloud API)

Each blueprint is registered with the /api/v1 prefix by the app factory.
"""

from flask import Blueprint

# Screen management blueprint
# Handles device registration, heartbeat, and configuration
screens_bp = Blueprint('screens', __name__, url_prefix='/screens')

# Content management blueprint
# Handles content listing, downloads, and sync
content_bp = Blueprint('content', __name__, url_prefix='/content')

# Database management blueprint
# Handles database sync and version management
databases_bp = Blueprint('databases', __name__, url_prefix='/databases')

# Alerts blueprint
# Handles alert retrieval and acknowledgment
alerts_bp = Blueprint('alerts', __name__, url_prefix='/alerts')

# Devices blueprint
# Handles device relay endpoints (proxy to cloud API)
devices_bp = Blueprint('devices', __name__, url_prefix='/devices')

# Import route handlers to register them with blueprints
# These imports must come AFTER blueprint definitions to avoid circular imports
from routes import screens  # noqa: F401, E402
from routes import content  # noqa: F401, E402
from routes import databases  # noqa: F401, E402
from routes import alerts  # noqa: F401, E402
from routes import devices  # noqa: F401, E402

# Export all blueprints
__all__ = ['screens_bp', 'content_bp', 'databases_bp', 'alerts_bp', 'devices_bp']
