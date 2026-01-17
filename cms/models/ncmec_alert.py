"""
NCMEC Alert Model.

Stores alerts generated when a potential match is detected against
the NCMEC missing children database.
"""

from datetime import datetime, timezone
from cms.models import db


class NCMECAlert(db.Model):
    """NCMEC detection alert."""
    
    __tablename__ = 'ncmec_alerts'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Device that detected the match
    device_id = db.Column(db.String(50), db.ForeignKey('devices.device_id'), nullable=False)
    
    # NCMEC case information
    ncmec_case_id = db.Column(db.String(100), nullable=False)
    ncmec_child_name = db.Column(db.String(200), nullable=True)
    ncmec_case_photo_path = db.Column(db.String(500), nullable=True)
    
    # Detection information
    captured_image_path = db.Column(db.String(500), nullable=False)
    confidence_score = db.Column(db.Float, nullable=False)
    detected_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    
    # Location info (denormalized for quick access)
    store_name = db.Column(db.String(200), nullable=True)
    store_address = db.Column(db.String(500), nullable=True)
    
    # Status tracking
    status = db.Column(db.String(20), nullable=False, default='pending')
    # Status values: pending, reviewing, confirmed, reported, dismissed
    
    # Review information
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    
    # If reported to authorities
    reported_at = db.Column(db.DateTime, nullable=True)
    reported_to = db.Column(db.String(500), nullable=True)
    report_reference = db.Column(db.String(200), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    device = db.relationship('Device', backref=db.backref('ncmec_alerts', lazy='dynamic'))
    reviewed_by = db.relationship('User', backref=db.backref('reviewed_alerts', lazy='dynamic'))
    
    def to_dict(self):
        """Convert to dictionary."""
        return {
            'id': self.id,
            'device_id': self.device_id,
            'ncmec_case_id': self.ncmec_case_id,
            'ncmec_child_name': self.ncmec_child_name,
            'ncmec_case_photo_path': self.ncmec_case_photo_path,
            'captured_image_path': self.captured_image_path,
            'confidence_score': self.confidence_score,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'store_name': self.store_name,
            'store_address': self.store_address,
            'status': self.status,
            'reviewed_by_id': self.reviewed_by_id,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_notes': self.review_notes,
            'reported_at': self.reported_at.isoformat() if self.reported_at else None,
            'reported_to': self.reported_to,
            'report_reference': self.report_reference,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class NCMECNotificationConfig(db.Model):
    """Configuration for NCMEC alert notifications."""
    
    __tablename__ = 'ncmec_notification_config'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Notification settings
    email_enabled = db.Column(db.Boolean, default=True)
    email_addresses = db.Column(db.Text, nullable=True)  # Comma-separated
    
    sms_enabled = db.Column(db.Boolean, default=False)
    phone_numbers = db.Column(db.Text, nullable=True)  # Comma-separated
    
    # Minimum confidence to trigger notification
    min_confidence_threshold = db.Column(db.Float, default=0.85)
    
    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def get_email_list(self):
        """Get list of email addresses."""
        if not self.email_addresses:
            return []
        return [e.strip() for e in self.email_addresses.split(',') if e.strip()]
    
    def get_phone_list(self):
        """Get list of phone numbers."""
        if not self.phone_numbers:
            return []
        return [p.strip() for p in self.phone_numbers.split(',') if p.strip()]
    
    def to_dict(self):
        """Convert to dictionary."""
        return {
            'id': self.id,
            'email_enabled': self.email_enabled,
            'email_addresses': self.get_email_list(),
            'sms_enabled': self.sms_enabled,
            'phone_numbers': self.get_phone_list(),
            'min_confidence_threshold': self.min_confidence_threshold
        }
