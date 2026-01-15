"""
SQLAlchemy database models for Local Hub Service.

This module provides the database foundation including:
- Base: DeclarativeBase for all models to inherit from
- db: SQLAlchemy instance for database operations

All model classes should inherit from db.Model (which uses Base).

Example:
    from models import db

    class Screen(db.Model):
        __tablename__ = 'screens'
        id = db.Column(db.Integer, primary_key=True)
        # ... additional columns
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


# Models will be imported here as they are created
from models.hub_config import HubConfig
from models.screen import Screen
from models.content import Content
from models.pending_alert import PendingAlert
from models.sync_status import SyncStatus

__all__ = ['db', 'Base', 'HubConfig', 'Screen', 'Content', 'PendingAlert', 'SyncStatus']
