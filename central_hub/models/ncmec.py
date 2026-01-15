"""
NCMEC Database Models

SQLAlchemy models for NCMEC (National Center for Missing & Exploited Children)
records and database version tracking.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import UUID

from central_hub.extensions import db


class NCMECStatus(enum.Enum):
    """Status enum for NCMEC records."""
    ACTIVE = 'active'
    RESOLVED = 'resolved'


class NCMECRecord(db.Model):
    """NCMEC record for a missing child with face encoding.

    Stores case information and facial encoding for face recognition
    matching on distributed screens.
    """
    __tablename__ = 'ncmec_records'

    # Primary key - UUID for global uniqueness
    id = db.Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # Case identification - unique NCMEC case number
    case_id = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
        index=True
    )

    # Personal information
    name = db.Column(db.String(255), nullable=False)
    age_when_missing = db.Column(db.Integer)
    missing_since = db.Column(db.Date)
    last_known_location = db.Column(db.Text)

    # Face recognition data
    # 512 bytes = 128 dimensions * 4 bytes (float32)
    face_encoding = db.Column(db.LargeBinary(512), nullable=False)

    # Photo storage path (filesystem)
    photo_path = db.Column(db.String(500))

    # Record status (active/resolved)
    status = db.Column(
        db.String(20),
        default=NCMECStatus.ACTIVE.value,
        nullable=False,
        index=True
    )

    # Timestamps
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'resolved')",
            name='check_ncmec_status'
        ),
    )

    def __repr__(self):
        return f'<NCMECRecord {self.case_id}: {self.name}>'

    def to_dict(self):
        """Convert record to dictionary for JSON serialization.

        Note: face_encoding is excluded from default serialization
        as it's binary data.
        """
        return {
            'id': str(self.id),
            'case_id': self.case_id,
            'name': self.name,
            'age_when_missing': self.age_when_missing,
            'missing_since': self.missing_since.isoformat() if self.missing_since else None,
            'last_known_location': self.last_known_location,
            'photo_path': self.photo_path,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class NCMECDatabaseVersion(db.Model):
    """Version tracking for compiled NCMEC FAISS databases.

    Each compilation creates a new version with its own FAISS index file
    and metadata. Allows for rollback and integrity verification.
    """
    __tablename__ = 'ncmec_database_versions'

    # Primary key - UUID
    id = db.Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # Version number (incrementing)
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
        return f'<NCMECDatabaseVersion v{self.version}: {self.record_count} records>'

    def to_dict(self):
        """Convert version to dictionary for JSON serialization."""
        return {
            'id': str(self.id),
            'version': self.version,
            'record_count': self.record_count,
            'file_hash': self.file_hash,
            'file_path': self.file_path,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
