"""
CMS Models Package.

SQLAlchemy models for the Content Management System including:
- Networks (organizational units)
- Hubs (physical locations)
- Devices (individual screens)
- Content (media files)
- Playlists (scheduled sequences)
- Device Assignments (device-to-playlist mappings)
- Users (authentication and authorization)
- User Sessions (session management)
- User Invitations (user onboarding)
- Audit Logs (activity tracking)
- Screen Layouts (visual screen layout design)
- Screen Layers (layout components)
- Layer Content (content within layout layers)
- Layer Playlist Assignments (playlist assignments to layers)
- Device Layouts (device-specific layout configurations)
- Synced Content (cached content from Content Catalog)
"""

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import DateTime as _SADateTime
from sqlalchemy.types import TypeDecorator


class DateTimeUTC(TypeDecorator):
    """DateTime type that ensures values are always timezone-aware (UTC).

    SQLite stores datetimes as naive strings.  This TypeDecorator adds UTC
    timezone info when reading and strips it when writing, so Python code
    can safely compare with ``datetime.now(timezone.utc)`` without hitting
    "can't compare offset-naive and offset-aware datetimes".
    """

    impl = _SADateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.astimezone(timezone.utc)
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
        return value


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
from cms.models.hub import Hub, PendingHub
from cms.models.device import Device
from cms.models.content import Content, ContentStatus
from cms.models.playlist import Playlist, PlaylistItem, LoopMode, Priority, SyncStatus
from cms.models.device_sync import DevicePlaylistSync, ContentSyncRecord, DeviceSyncStatus
from cms.models.device_assignment import DeviceAssignment
from cms.models.user import User
from cms.models.user_session import UserSession
from cms.models.user_invitation import UserInvitation
from cms.models.audit_log import AuditLog
from cms.models.layout import ScreenLayout, ScreenLayer, LayerContent, LayerPlaylistAssignment, DeviceLayout
from cms.models.synced_content import SyncedContent
from cms.models.folder import Folder

__all__ = [
    'db',
    'Base',
    'Network',
    'Hub',
    'PendingHub',
    'Device',
    'Content',
    'ContentStatus',
    'Playlist',
    'PlaylistItem',
    'LoopMode',
    'Priority',
    'SyncStatus',
    'DevicePlaylistSync',
    'ContentSyncRecord',
    'DeviceSyncStatus',
    'DeviceAssignment',
    'User',
    'UserSession',
    'UserInvitation',
    'AuditLog',
    'ScreenLayout',
    'ScreenLayer',
    'LayerContent',
    'LayerPlaylistAssignment',
    'DeviceLayout',
    'SyncedContent',
    'Folder',
]
# NCMEC Alert models
from cms.models.ncmec_alert import NCMECAlert, NCMECNotificationConfig