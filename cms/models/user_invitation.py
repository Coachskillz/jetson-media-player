"""
UserInvitation Model for CMS Service.

Represents an invitation for a new user to join the system.
Invitations are created by Admins or Super Admins and contain a unique token
that allows the recipient to register and set their password.
"""

from datetime import datetime, timezone
import uuid
import secrets

from cms.models import db


class UserInvitation(db.Model):
    """
    SQLAlchemy model representing a user invitation.

    Invitations are used to onboard new users to the system. An admin creates
    an invitation with a specific role and optionally a network assignment.
    The invitation generates a unique token that can be used to accept the
    invitation and create an account.

    Attributes:
        id: Unique UUID identifier (internal database ID)
        email: Email address of the invited user
        role: Role to be assigned ('super_admin', 'admin', 'content_manager', 'viewer')
        network_id: Foreign key reference to the network (optional, NULL for super_admin)
        invited_by: Foreign key reference to the user who created the invitation
        token: Unique token for accepting the invitation
        status: Current status ('pending', 'accepted', 'expired', 'revoked')
        expires_at: Timestamp when the invitation expires
        accepted_at: Timestamp when the invitation was accepted
        created_at: Timestamp when the invitation was created
    """

    __tablename__ = 'user_invitations'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(255), nullable=False, index=True)
    role = db.Column(db.String(50), nullable=False)
    network_id = db.Column(db.String(36), db.ForeignKey('networks.id'), nullable=True, index=True)
    # Multiple network access - comma-separated list of network IDs
    network_ids = db.Column(db.Text, nullable=True)
    invited_by = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False, index=True)
    token = db.Column(db.String(100), unique=True, nullable=False, index=True, default=lambda: secrets.token_urlsafe(32))
    status = db.Column(db.String(50), nullable=False, default='pending')
    expires_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    network = db.relationship('Network', backref=db.backref('invitations', lazy='dynamic'))
    inviter = db.relationship('User', backref=db.backref('sent_invitations', lazy='dynamic'))

    def to_dict(self):
        """
        Serialize the invitation to a dictionary for API responses.

        Returns:
            Dictionary containing all invitation fields
        """
        return {
            'id': self.id,
            'email': self.email,
            'role': self.role,
            'network_id': self.network_id,
            'network_ids': self.network_ids.split(',') if self.network_ids else [],
            'invited_by': self.invited_by,
            'token': self.token,
            'status': self.status,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'accepted_at': self.accepted_at.isoformat() if self.accepted_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def is_expired(self):
        """
        Check if the invitation has expired.

        Returns:
            True if the invitation has expired, False otherwise
        """
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self):
        """
        Check if the invitation is still valid for acceptance.

        An invitation is valid if it has 'pending' status and has not expired.

        Returns:
            True if the invitation can be accepted, False otherwise
        """
        return self.status == 'pending' and not self.is_expired()

    def __repr__(self):
        """String representation for debugging."""
        return f'<UserInvitation {self.email} ({self.status})>'
