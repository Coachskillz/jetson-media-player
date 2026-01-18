"""
Content Catalog Models Package.

SQLAlchemy models for the Content Catalog service including:
- Organizations (partner companies)
- Users (with role-based access and hierarchical approval)
- User Invitations (token-based registration)
- User Approval Requests (approval workflow tracking)
- Admin Sessions (session management)
- Audit Logs (compliance and security tracking)
- Content Assets (media files with metadata)
- Content Approval Requests (content workflow tracking)
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
# Models will be imported here as they are created:
from content_catalog.models.tenant import Tenant
from content_catalog.models.catalog import Catalog
from content_catalog.models.category import Category
from content_catalog.models.organization import Organization
from content_catalog.models.user import User, UserInvitation, UserApprovalRequest, AdminSession
from content_catalog.models.audit import AuditLog
from content_catalog.models.content import ContentAsset, ContentApprovalRequest
from content_catalog.models.checkout import CheckoutToken, ApprovalTask

__all__ = [
    'db',
    'Base',
    'Tenant',
    'Catalog',
    'Category',
    'Organization',
    'User',
    'UserInvitation',
    'UserApprovalRequest',
    'AdminSession',
    'AuditLog',
    'ContentAsset',
    'ContentApprovalRequest',
    'CheckoutToken',
    'ApprovalTask',
]
