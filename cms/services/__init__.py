"""
CMS Services Package.

Business logic services for the Content Management System including:
- DeviceIDGenerator: Generates unique device IDs in direct and hub modes
"""

from cms.services.device_id import DeviceIDGenerator

__all__ = [
    'DeviceIDGenerator',
]
