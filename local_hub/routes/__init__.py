"""
API Route Blueprints for Local Hub Service.
"""

from flask import Blueprint

# Screen management blueprint
screens_bp = Blueprint('screens', __name__, url_prefix='/screens')

# Content management blueprint
content_bp = Blueprint('content', __name__, url_prefix='/content')

# Database management blueprint
databases_bp = Blueprint('databases', __name__, url_prefix='/databases')

# Alerts blueprint
alerts_bp = Blueprint('alerts', __name__, url_prefix='/alerts')

# Devices blueprint
devices_bp = Blueprint('devices', __name__, url_prefix='/devices')

# Locations blueprint
locations_bp = Blueprint('locations', __name__, url_prefix='/locations')

# Cameras blueprint
from routes.cameras import cameras_bp

# Pairing blueprint (for devices pairing to hub)
from routes.pairing import pairing_bp

# Hub pairing blueprint (for hub pairing to CMS)
from routes.hub_pairing import hub_pairing_ui_bp, hub_pairing_api_bp

# Import route handlers to register them with blueprints
from routes import screens  # noqa: F401, E402
from routes import content  # noqa: F401, E402
from routes import databases  # noqa: F401, E402
from routes import alerts  # noqa: F401, E402
from routes import devices  # noqa: F401, E402

# Import locations blueprint from its module
from routes.locations import locations_bp  # noqa: F401, E402

# Export all blueprints
__all__ = [
    'screens_bp', 'content_bp', 'databases_bp', 'alerts_bp', 'devices_bp',
    'locations_bp', 'cameras_bp', 'pairing_bp', 'hub_pairing_ui_bp', 'hub_pairing_api_bp'
]
