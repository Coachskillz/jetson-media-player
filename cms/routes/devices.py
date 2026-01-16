"""
CMS Devices Routes

Blueprint for device management API endpoints:
- POST /register: Register a new device (direct or hub mode)
- POST /pair: Pair device with a hub
- GET /config: Get device configuration
- GET /: List all devices
"""

from flask import Blueprint

# Create devices blueprint
devices_bp = Blueprint('devices', __name__)


# Route implementations will be added in subtask-3-2
