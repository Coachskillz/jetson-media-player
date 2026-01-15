"""
Loyalty Database Models

SQLAlchemy models for per-network loyalty member enrollment
and database version tracking for FAISS face recognition indexes.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from central_hub.extensions import db


class LoyaltyMember(db.Model):
    """Loyalty member enrolled with face encoding for personalized content.

    Each member belongs to a specific network and can be assigned
    a personalized playlist for targeted content delivery.
    """
    __tablename__ = 'loyalty_members'

    # Primary key - UUID for global uniqueness
    id = db.Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # Network association - required for per-network scoping
    network_id = db.Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True
    )

    # Member identification - unique within network
    member_code = db.Column(
        db.String(50),
        nullable=False,
        index=True
    )

    # Personal information
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(20))

    # Face recognition data
    # 512 bytes = 128 dimensions * 4 bytes (float32)
    face_encoding = db.Column(db.LargeBinary(512), nullable=False)

    # Photo storage path (filesystem)
    photo_path = db.Column(db.String(500))

    # Playlist assignment for personalized content
    assigned_playlist_id = db.Column(db.Integer)

    # Enrollment timestamp
    enrolled_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Last seen tracking
    last_seen_at = db.Column(db.DateTime(timezone=True))
    last_seen_store_id = db.Column(UUID(as_uuid=True))

    # Unique constraint: member_code must be unique within a network
    __table_args__ = (
        UniqueConstraint(
            'network_id', 'member_code',
            name='uq_loyalty_member_network_code'
        ),
    )

    def __repr__(self):
        return f'<LoyaltyMember {self.member_code}: {self.name}>'

    def to_dict(self):
        """Convert member to dictionary for JSON serialization.

        Note: face_encoding is excluded from default serialization
        as it's binary data.
        """
        return {
            'id': str(self.id),
            'network_id': str(self.network_id),
            'member_code': self.member_code,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'photo_path': self.photo_path,
            'assigned_playlist_id': self.assigned_playlist_id,
            'enrolled_at': self.enrolled_at.isoformat() if self.enrolled_at else None,
            'last_seen_at': self.last_seen_at.isoformat() if self.last_seen_at else None,
            'last_seen_store_id': str(self.last_seen_store_id) if self.last_seen_store_id else None,
        }


class LoyaltyDatabaseVersion(db.Model):
    """Version tracking for compiled per-network Loyalty FAISS databases.

    Each network maintains its own versioned FAISS index with
    enrolled member face encodings. Allows for rollback and
    integrity verification.
    """
    __tablename__ = 'loyalty_database_versions'

    # Primary key - UUID
    id = db.Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # Network association - required for per-network databases
    network_id = db.Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True
    )

    # Version number (incrementing per network)
    version = db.Column(db.Integer, nullable=False, index=True)

    # Compilation stats
    record_count = db.Column(db.Integer, nullable=False)

    # File integrity
    file_hash = db.Column(db.String(64), nullable=False)  # SHA256 hex

    # File location
    file_path = db.Column(db.String(500), nullable=False)

    # Timestamp
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    def __repr__(self):
        return f'<LoyaltyDatabaseVersion network={self.network_id} v{self.version}: {self.record_count} records>'

    def to_dict(self):
        """Convert version to dictionary for JSON serialization."""
        return {
            'id': str(self.id),
            'network_id': str(self.network_id),
            'version': self.version,
            'record_count': self.record_count,
            'file_hash': self.file_hash,
            'file_path': self.file_path,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
