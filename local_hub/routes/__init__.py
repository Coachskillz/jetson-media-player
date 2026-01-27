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

# Cameras blueprint
from routes.cameras import cameras_bp

# Pairing blueprint
from routes.pairing import pairing_bp

# Import route handlers to register them with blueprints
from routes import screens  # noqa: F401, E402
from routes import content  # noqa: F401, E402
from routes import databases  # noqa: F401, E402
from routes import alerts  # noqa: F401, E402
from routes import devices  # noqa: F401, E402

# Export all blueprints
__all__ = ['screens_bp', 'content_bp', 'databases_bp', 'alerts_bp', 'devices_bp', 'cameras_bp', 'pairing_bp']
