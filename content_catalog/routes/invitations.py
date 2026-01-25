"""
Content Catalog Invitations Routes.

Blueprint for user invitation API endpoints:
- POST /: Create a new invitation and send email
- POST /<token>/accept: Accept an invitation and create user account

All endpoints are prefixed with /api/v1/invitations when registered with the app.
"""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from content_catalog.models import db, User, UserInvitation, Organization
from content_catalog.services.auth_service import AuthService
from content_catalog.services.audit_service import AuditService
from content_catalog.services.email_service import EmailService


# Create invitations blueprint
invitations_bp = Blueprint('invitations', __name__)

# Invitation expiration period in days
INVITATION_EXPIRY_HOURS = 48


def _get_current_user():
    """
    Get the current authenticated user from JWT identity.

    Returns:
        User object or None if not found
    """
    current_user_id = get_jwt_identity()
    return db.session.get(User, current_user_id)


def _can_invite_role(user, target_role):
    """
    Check if the user has permission to invite users with the given role.

    Uses the hierarchical role system where users can only invite
    users with lower privilege levels.

    Args:
        user: The User object to check permissions for
        target_role: The role being invited

    Returns:
        True if user can invite this role, False otherwise
    """
    if not user:
        return False
    return user.can_approve_role(target_role)


@invitations_bp.route('', methods=['POST'])
@jwt_required()
def create_invitation():
    """
    Create a new invitation and send email.

    Creates an invitation record and sends an email to the invitee
    with a registration link containing a secure token.

    Request Body:
        {
            "email": "newuser@example.com" (required),
            "role": "partner" (required),
            "organization_id": 1 (optional)
        }

    Returns:
        201: Invitation created successfully
            {
                "id": 1,
                "email": "newuser@example.com",
                "role": "partner",
                "organization_id": 1,
                "status": "pending",
                "expires_at": "2024-01-22T10:00:00",
                "created_at": "2024-01-15T10:00:00"
            }
        400: Missing required field or invalid data
        401: Unauthorized (missing or invalid token)
        403: Forbidden (insufficient permissions)
        409: User or pending invitation already exists for email
    """
    current_user = _get_current_user()

    if not current_user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate email
    email = data.get('email')
    if not email:
        return jsonify({'error': 'email is required'}), 400

    if not isinstance(email, str) or len(email) > 255:
        return jsonify({'error': 'email must be a string with max 255 characters'}), 400

    email = email.lower().strip()

    # Check if user already exists with this email
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({'error': 'A user with this email already exists'}), 409

    # Check if there's already a pending invitation for this email
    existing_invitation = UserInvitation.query.filter_by(
        email=email,
        status=UserInvitation.STATUS_PENDING
    ).first()

    if existing_invitation and existing_invitation.is_valid():
        return jsonify({'error': 'A pending invitation already exists for this email'}), 409

    # Validate role
    role = data.get('role')
    if not role:
        return jsonify({'error': 'role is required'}), 400

    if role not in User.VALID_ROLES:
        return jsonify({
            'error': f"Invalid role. Must be one of: {', '.join(User.VALID_ROLES)}"
        }), 400

    # Check if current user can invite this role
    if not _can_invite_role(current_user, role):
        return jsonify({
            'error': f'Insufficient permissions to invite users with role: {role}'
        }), 403

    # Validate organization_id if provided
    organization_id = data.get('organization_id')
    organization = None
    if organization_id:
        try:
            org_id = int(organization_id)
            organization = db.session.get(Organization, org_id)
            if not organization:
                return jsonify({'error': f'Organization with id {org_id} not found'}), 400
            organization_id = org_id
        except (ValueError, TypeError):
            return jsonify({'error': 'organization_id must be an integer'}), 400

    # Generate secure invitation token
    token = AuthService.generate_invitation_token()

    # Calculate expiration date
    expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITATION_EXPIRY_HOURS)

    # Create invitation record
    invitation = UserInvitation(
        email=email,
        role=role,
        organization_id=organization_id,
        invited_by=current_user.id,
        token=token,
        status=UserInvitation.STATUS_PENDING,
        expires_at=expires_at
    )

    try:
        db.session.add(invitation)

        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='invitation.created',
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type='invitation',
            resource_id=None,  # Will be set after commit
            details={
                'invited_email': email,
                'invited_role': role,
                'organization_id': organization_id
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to create invitation: {str(e)}'}), 500

    # Send invitation email
    organization_name = organization.name if organization else None
    email_sent = EmailService.send_invitation(
        to_email=email,
        inviter_name=current_user.name,
        invitation_token=token,
        role=role,
        organization_name=organization_name
    )

    response = invitation.to_dict()
    response['email_sent'] = email_sent

    return jsonify(response), 201


@invitations_bp.route('/<string:token>/accept', methods=['POST'])
def accept_invitation(token):
    """
    Accept an invitation and create user account.

    Validates the invitation token, creates a new user account with the
    provided details, and marks the invitation as accepted.

    Args:
        token: The invitation token from the URL

    Request Body:
        {
            "password": "secure_password" (required),
            "name": "User Name" (required),
            "phone": "+1234567890" (optional)
        }

    Returns:
        201: User created successfully
            {
                "message": "Invitation accepted successfully",
                "user": { user data }
            }
        400: Missing required field, invalid data, or invalid token
        404: Invitation not found
        410: Invitation expired or already used
    """
    # Find invitation by token
    invitation = UserInvitation.query.filter_by(token=token).first()

    if not invitation:
        return jsonify({'error': 'Invitation not found'}), 404

    # Check if invitation is expired
    if invitation.is_expired():
        # Update status if needed
        if invitation.status == UserInvitation.STATUS_PENDING:
            invitation.status = UserInvitation.STATUS_EXPIRED
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return jsonify({'error': 'Invitation has expired'}), 410

    # Check if invitation is still pending
    if invitation.status != UserInvitation.STATUS_PENDING:
        return jsonify({'error': f'Invitation is no longer valid (status: {invitation.status})'}), 410

    data = request.get_json(silent=True)

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate password
    password = data.get('password')
    if not password:
        return jsonify({'error': 'password is required'}), 400

    if not isinstance(password, str) or len(password) < 8:
        return jsonify({'error': 'password must be at least 8 characters'}), 400

    # Validate name
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400

    if not isinstance(name, str) or len(name) > 255:
        return jsonify({'error': 'name must be a string with max 255 characters'}), 400

    # Validate phone if provided
    phone = data.get('phone')
    if phone and (not isinstance(phone, str) or len(phone) > 50):
        return jsonify({'error': 'phone must be a string with max 50 characters'}), 400

    # Check if user already exists (edge case - created after invitation)
    existing_user = User.query.filter_by(email=invitation.email).first()
    if existing_user:
        return jsonify({'error': 'A user with this email already exists'}), 409

    # Hash the password
    password_hash = AuthService.hash_password(password)

    # Create new user
    user = User(
        email=invitation.email,
        password_hash=password_hash,
        name=name,
        role=invitation.role,
        organization_id=invitation.organization_id,
        phone=phone,
        status=User.STATUS_ACTIVE,  # Invited users are active immediately
        invited_by=invitation.invited_by
    )

    # Set tenant_ids from invitation
    invitation_tenant_ids = invitation.get_tenant_ids_list()
    if invitation_tenant_ids:
        user.set_tenant_ids_list(invitation_tenant_ids)

    # Update invitation status
    invitation.status = UserInvitation.STATUS_ACCEPTED
    invitation.accepted_at = datetime.now(timezone.utc)

    try:
        db.session.add(user)

        # Log the action
        AuditService.log_action(
            db_session=db.session,
            action='invitation.accepted',
            user_id=None,  # New user doesn't have ID yet
            user_email=invitation.email,
            resource_type='invitation',
            resource_id=invitation.id,
            details={
                'invitation_id': invitation.id,
                'role': invitation.role,
                'organization_id': invitation.organization_id
            }
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to accept invitation: {str(e)}'}), 500

    return jsonify({
        'message': 'Invitation accepted successfully',
        'user': user.to_dict()
    }), 201
