"""
Content Venue Approval Model for Content Catalog Service.

Tracks the approval status of content assets per venue/tenant.
Enables the two-stage approval workflow:
1. Skillz Media approves content (quality, policy)
2. Venue Partner approves for their screens (if requires_content_approval=TRUE)
"""

from datetime import datetime, timezone
import uuid

from content_catalog.models import db


class ContentVenueApproval(db.Model):
    """
    Tracks approval status of content for each target venue.
    
    A content asset may be targeted at multiple venues. Each venue
    can independently approve or reject the content for their screens.
    
    Status flow:
    - pending_skillz: Uploaded, awaiting Skillz approval
    - pending_venue: Skillz approved, awaiting venue approval
    - approved: Fully approved, ready for CMS
    - rejected_skillz: Rejected by Skillz
    - rejected_venue: Rejected by venue partner
    """
    
    __tablename__ = 'content_venue_approvals'
    
    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    
    # UUID for external API references
    uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
        index=True
    )
    
    # Foreign keys
    content_asset_id = db.Column(
        db.Integer,
        db.ForeignKey('content_assets.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Status
    STATUS_PENDING_SKILLZ = 'pending_skillz'
    STATUS_PENDING_VENUE = 'pending_venue'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED_SKILLZ = 'rejected_skillz'
    STATUS_REJECTED_VENUE = 'rejected_venue'
    
    status = db.Column(
        db.String(20),
        default=STATUS_PENDING_SKILLZ,
        nullable=False,
        index=True
    )
    
    # Skillz approval
    skillz_approved = db.Column(db.Boolean, default=False, nullable=False)
    skillz_approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    skillz_approved_at = db.Column(db.DateTime, nullable=True)
    skillz_rejection_reason = db.Column(db.Text, nullable=True)
    
    # Venue approval
    venue_approved = db.Column(db.Boolean, default=False, nullable=False)
    venue_approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    venue_approved_at = db.Column(db.DateTime, nullable=True)
    venue_rejection_reason = db.Column(db.Text, nullable=True)
    
    # Auto-approved flag (when tenant.requires_content_approval = FALSE)
    auto_approved = db.Column(db.Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    
    # Relationships
    content_asset = db.relationship('ContentAsset', backref='venue_approvals')
    tenant = db.relationship('Tenant', backref='content_approvals')
    skillz_approved_by = db.relationship('User', foreign_keys=[skillz_approved_by_id])
    venue_approved_by = db.relationship('User', foreign_keys=[venue_approved_by_id])
    
    # Unique constraint: one approval record per content per venue
    __table_args__ = (
        db.UniqueConstraint('content_asset_id', 'tenant_id', name='uq_content_venue'),
    )
    
    def to_dict(self):
        """Serialize to dictionary for API responses."""
        return {
            'id': self.id,
            'uuid': self.uuid,
            'content_asset_id': self.content_asset_id,
            'tenant_id': self.tenant_id,
            'status': self.status,
            'skillz_approved': self.skillz_approved,
            'skillz_approved_by_id': self.skillz_approved_by_id,
            'skillz_approved_at': self.skillz_approved_at.isoformat() if self.skillz_approved_at else None,
            'skillz_rejection_reason': self.skillz_rejection_reason,
            'venue_approved': self.venue_approved,
            'venue_approved_by_id': self.venue_approved_by_id,
            'venue_approved_at': self.venue_approved_at.isoformat() if self.venue_approved_at else None,
            'venue_rejection_reason': self.venue_rejection_reason,
            'auto_approved': self.auto_approved,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def is_fully_approved(self):
        """Check if content is fully approved for this venue."""
        return self.skillz_approved and (self.venue_approved or self.auto_approved)
    
    def approve_skillz(self, user_id, auto_approve_venue=False):
        """
        Mark as approved by Skillz.
        
        Args:
            user_id: ID of the Skillz admin approving
            auto_approve_venue: If True, also auto-approve for venue
        """
        self.skillz_approved = True
        self.skillz_approved_by_id = user_id
        self.skillz_approved_at = datetime.now(timezone.utc)
        
        if auto_approve_venue:
            self.venue_approved = True
            self.auto_approved = True
            self.venue_approved_at = datetime.now(timezone.utc)
            self.status = self.STATUS_APPROVED
        else:
            self.status = self.STATUS_PENDING_VENUE
        
        self.updated_at = datetime.now(timezone.utc)
    
    def approve_venue(self, user_id):
        """Mark as approved by venue partner."""
        self.venue_approved = True
        self.venue_approved_by_id = user_id
        self.venue_approved_at = datetime.now(timezone.utc)
        self.status = self.STATUS_APPROVED
        self.updated_at = datetime.now(timezone.utc)
    
    def reject_skillz(self, user_id, reason=None):
        """Mark as rejected by Skillz."""
        self.skillz_approved = False
        self.skillz_approved_by_id = user_id
        self.skillz_approved_at = datetime.now(timezone.utc)
        self.skillz_rejection_reason = reason
        self.status = self.STATUS_REJECTED_SKILLZ
        self.updated_at = datetime.now(timezone.utc)
    
    def reject_venue(self, user_id, reason=None):
        """Mark as rejected by venue partner."""
        self.venue_approved = False
        self.venue_approved_by_id = user_id
        self.venue_approved_at = datetime.now(timezone.utc)
        self.venue_rejection_reason = reason
        self.status = self.STATUS_REJECTED_VENUE
        self.updated_at = datetime.now(timezone.utc)
    
    def __repr__(self):
        return f'<ContentVenueApproval content={self.content_asset_id} tenant={self.tenant_id} status={self.status}>'
