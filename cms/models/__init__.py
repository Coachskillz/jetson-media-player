"""
CMS Models Package.

SQLAlchemy models for the Content Management System including:
- Networks (organizational units)
- Hubs (physical locations)
- Devices (individual screens)
- Content (media files)
- Playlists (scheduled sequences)
- Device Assignments (device-to-playlist mappings)
"""

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.

    All models should inherit from db.Model which uses this Base class.
    This provides the foundation for declarative model definitions.
    """
    pass


# SQLAlchemy database instance
# Initialize with model_class=Base for proper declarative base setup
db = SQLAlchemy(model_class=Base)


# Import models after db is defined to avoid circular imports
from cms.models.network import Network
from cms.models.hub import Hub
from cms.models.device import Device
from cms.models.content import Content
from cms.models.playlist import Playlist, PlaylistItem
from cms.models.device_assignment import DeviceAssignment

__all__ = [
    'db',
    'Base',
    'Network',
    'Hub',
    'Device',
    'Content',
    'Playlist',
    'PlaylistItem',
    'DeviceAssignment',
]
