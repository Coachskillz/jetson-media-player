"""
Central Hub Routes Package

Blueprint registration for all API route modules:
- NCMEC: Missing children database management
- Loyalty: Per-network member enrollment and management
- Alerts: Alert ingestion and review workflow
- Notifications: Notification settings management
"""

# Import NCMEC blueprint from its module
from central_hub.routes.ncmec import ncmec_bp

# Import Loyalty blueprint from its module
from central_hub.routes.loyalty import loyalty_bp

# Import Alerts blueprint from its module
from central_hub.routes.alerts import alerts_bp

# Import Notifications blueprint from its module
from central_hub.routes.notifications import notifications_bp


__all__ = [
    'ncmec_bp',
    'loyalty_bp',
    'alerts_bp',
    'notifications_bp',
]
