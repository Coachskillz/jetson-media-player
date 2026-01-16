"""
CMS Invitations Routes

Blueprint for user invitation API endpoints:
- POST /: Send a new invitation
- GET /: List sent invitations
- GET /<token>: Get invitation details by token (public)
- POST /<token>/accept: Accept an invitation (public)
- POST /<id>/revoke: Revoke an invitation

All endpoints are prefixed with /api/v1/invitations when registered with the app.
Most endpoints require authentication and admin or higher role.
Token-based endpoints (get by token, accept) are public for invitation workflow.
"""

from datetime import datetime, timezone, timedelta
import secrets

from flask import Blueprint, request, jsonify

from cms.models import db, User, UserInvitation, Network
from cms.models.user import ROLE_HIERARCHY
from cms.utils.auth import login_required, get_current_user
from cms.utils.permissions import (
    require_role,
    can_manage_role,
    VALID_ROLES,
)
from cms.utils.audit import log_action, log_user_management_action


# Create invitations blueprint
invitations_bp = Blueprint('invitations', __name__)

# Default invitation expiration (7 days)
INVITATION_EXPIRATION_DAYS = 7


def _validate_password(password):
    """
    Validate password meets requirements.

    Requirements:
    - Minimum 12 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - At least one special character

    Args:
        password: Password string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not password or len(password) < 12:
        return False, 'Password must be at least 12 characters long'

    if not any(c.isupper() for c in password):
        return False, 'Password must contain at least one uppercase letter'

    if not any(c.islower() for c in password):
        return False, 'Password must contain at least one lowercase letter'

    if not any(c.isdigit() for c in password):
        return False, 'Password must contain at least one number'

    special_chars = set('!@#$%^&*()_+-=[]{}|;:,.<>?/~`')
    if not any(c in special_chars for c in password):
        return False, 'Password must contain at least one special character'

    return True, None


@invitations_bp.route('', methods=['POST'])
@login_required
@require_role('admin')
def send_invitation():
    """
    Send a new user invitation.

    Creates an invitation that allows a new user to register with the system.
    The invitation includes a unique token and expires after a configurable period.

    Request Body:
        {
            "email": "user@example.com" (required),
            "role": "content_manager" (required),
            "network_id": "uuid-of-network" (required for non-super_admin roles),
            "expires_days": 7 (optional, default 7)
        }

    Returns:
        201: Invitation created successfully
            {
                "message": "Invitation sent successfully",
                "invitation": { invitation data }
            }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
        403: Insufficient permissions to invite with this role
            {
                "error": "error message"
            }
        409: Email already exists or has pending invitation
            {
                "error": "error message"
            }
    """
    current_user = get_current_user()

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate email
    email = data.get('email')
    if not email:
        return jsonify({'error': 'email is required'}), 400

    if not isinstance(email, str) or len(email) > 255:
        return jsonify({
            'error': 'email must be a string with max 255 characters'
        }), 400

    # Normalize email to lowercase
    email = email.lower().strip()

    # Check if email is valid format (basic check)
    if '@' not in email or '.' not in email:
        return jsonify({'error': 'Invalid email format'}), 400

    # Check if user with this email already exists
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({
            'error': 'A user with this email already exists'
        }), 409

    # Check if there's a pending invitation for this email
    existing_invitation = UserInvitation.query.filter_by(
        email=email,
        status='pending'
    ).first()
    if existing_invitation:
        # Check if it's expired
        if existing_invitation.is_expired():
            # Mark as expired
            existing_invitation.status = 'expired'
            db.session.commit()
        else:
            return jsonify({
                'error': 'A pending invitation for this email already exists'
            }), 409

    # Validate role
    role = data.get('role')
    if not role:
        return jsonify({'error': 'role is required'}), 400

    if role not in VALID_ROLES:
        return jsonify({
            'error': f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}"
        }), 400

    # Check if current user can invite with this role
    if not can_manage_role(current_user, role):
        return jsonify({
            'error': f'Cannot invite users with role: {role}'
        }), 403

    # Validate network_id
    network_id = data.get('network_id')

    # Super admin role doesn't require network
    if role == 'super_admin':
        if network_id:
            return jsonify({
                'error': 'super_admin role cannot be assigned to a network'
            }), 400
        network_id = None
    else:
        # All other roles require a network
        if not network_id:
            return jsonify({
                'error': 'network_id is required for non-super_admin roles'
            }), 400

        # Verify network exists
        network = db.session.get(Network, network_id)
        if not network:
            return jsonify({
                'error': f'Network with id {network_id} not found'
            }), 400

        # Non-super admins can only invite to their own network
        if current_user.role != 'super_admin' and current_user.network_id != network_id:
            return jsonify({
                'error': 'Cannot invite users to a different network'
            }), 403

    # Calculate expiration
    expires_days = data.get('expires_days', INVITATION_EXPIRATION_DAYS)
    if not isinstance(expires_days, int) or expires_days < 1 or expires_days > 30:
        return jsonify({
            'error': 'expires_days must be an integer between 1 and 30'
        }), 400

    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    # Create invitation
    invitation = UserInvitation(
        email=email,
        role=role,
        network_id=network_id,
        invited_by=current_user.id,
        token=secrets.token_urlsafe(32),
        status='pending',
        expires_at=expires_at
    )

    try:
        db.session.add(invitation)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create invitation: {str(e)}'
        }), 500

    # Log the action
    log_action(
        action='invitation.send',
        action_category='users',
        resource_type='invitation',
        resource_id=invitation.id,
        resource_name=email,
        details={
            'role': role,
            'network_id': network_id,
            'expires_at': expires_at.isoformat()
        }
    )

    return jsonify({
        'message': 'Invitation sent successfully',
        'invitation': invitation.to_dict()
    }), 201


@invitations_bp.route('', methods=['GET'])
@login_required
@require_role('admin')
def list_invitations():
    """
    List all invitations.

    Returns a list of invitations. Super admins see all invitations,
    regular admins only see invitations they sent.

    Query Parameters:
        status: Filter by status (pending, accepted, expired, revoked)
        email: Search by email (partial match)

    Returns:
        200: List of invitations
            {
                "invitations": [ { invitation data }, ... ],
                "count": 5
            }
        400: Invalid filter value
    """
    current_user = get_current_user()

    # Build query
    query = UserInvitation.query

    # Non-super admins only see their own invitations
    if current_user.role != 'super_admin':
        query = query.filter_by(invited_by=current_user.id)

    # Filter by status
    status_filter = request.args.get('status')
    if status_filter:
        valid_statuses = ['pending', 'accepted', 'expired', 'revoked']
        if status_filter not in valid_statuses:
            return jsonify({
                'error': f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
            }), 400
        query = query.filter_by(status=status_filter)

    # Search by email
    email_search = request.args.get('email')
    if email_search:
        search_pattern = f'%{email_search}%'
        query = query.filter(UserInvitation.email.ilike(search_pattern))

    # Execute query ordered by created_at descending
    invitations = query.order_by(UserInvitation.created_at.desc()).all()

    # Update any expired invitations
    now = datetime.now(timezone.utc)
    for invitation in invitations:
        if invitation.status == 'pending' and invitation.expires_at and invitation.expires_at < now:
            invitation.status = 'expired'

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Build response with inviter info
    invitation_list = []
    for invitation in invitations:
        inv_data = invitation.to_dict()
        # Add inviter info
        if invitation.inviter:
            inv_data['inviter'] = {
                'id': invitation.inviter.id,
                'email': invitation.inviter.email,
                'name': invitation.inviter.name
            }
        # Add network info
        if invitation.network:
            inv_data['network'] = {
                'id': invitation.network.id,
                'name': invitation.network.name
            }
        invitation_list.append(inv_data)

    return jsonify({
        'invitations': invitation_list,
        'count': len(invitation_list)
    }), 200


@invitations_bp.route('/<token>', methods=['GET'])
def get_invitation_by_token(token):
    """
    Get invitation details by token.

    This is a public endpoint used by the invitation acceptance flow.
    Returns limited information for security.

    Args:
        token: Invitation token

    Returns:
        200: Invitation details (limited)
            {
                "email": "user@example.com",
                "role": "content_manager",
                "status": "pending",
                "expires_at": "2024-01-22T10:00:00Z",
                "is_valid": true
            }
        404: Invitation not found or invalid token
    """
    # Find invitation by token
    invitation = UserInvitation.query.filter_by(token=token).first()

    if not invitation:
        return jsonify({'error': 'Invitation not found'}), 404

    # Check if expired and update status
    if invitation.status == 'pending' and invitation.is_expired():
        invitation.status = 'expired'
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Return limited information for security
    response_data = {
        'email': invitation.email,
        'role': invitation.role,
        'status': invitation.status,
        'expires_at': invitation.expires_at.isoformat() if invitation.expires_at else None,
        'is_valid': invitation.is_valid()
    }

    # Add network info if available
    if invitation.network:
        response_data['network'] = {
            'id': invitation.network.id,
            'name': invitation.network.name
        }

    return jsonify(response_data), 200


@invitations_bp.route('/<token>/accept', methods=['POST'])
def accept_invitation(token):
    """
    Accept an invitation and create a user account.

    This is a public endpoint used by invited users to register.
    Creates a new user account with the invited role and network.

    Args:
        token: Invitation token

    Request Body:
        {
            "name": "User Name" (required),
            "password": "SecurePassword123!" (required),
            "phone": "123-456-7890" (optional)
        }

    Returns:
        201: User created successfully
            {
                "message": "Account created successfully",
                "user": { user data }
            }
        400: Missing required field, invalid password, or invitation not valid
            {
                "error": "error message"
            }
        404: Invitation not found
    """
    # Find invitation by token
    invitation = UserInvitation.query.filter_by(token=token).first()

    if not invitation:
        return jsonify({'error': 'Invitation not found'}), 404

    # Check if expired and update status
    if invitation.status == 'pending' and invitation.is_expired():
        invitation.status = 'expired'
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Check if invitation is valid
    if not invitation.is_valid():
        error_msg = 'Invitation has expired' if invitation.is_expired() else f'Invitation is {invitation.status}'
        return jsonify({'error': error_msg}), 400

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate name
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400

    if not isinstance(name, str) or len(name) > 200:
        return jsonify({
            'error': 'name must be a string with max 200 characters'
        }), 400

    # Validate password
    password = data.get('password')
    if not password:
        return jsonify({'error': 'password is required'}), 400

    is_valid, error_msg = _validate_password(password)
    if not is_valid:
        return jsonify({'error': error_msg}), 400

    # Validate phone if provided
    phone = data.get('phone')
    if phone and (not isinstance(phone, str) or len(phone) > 50):
        return jsonify({
            'error': 'phone must be a string with max 50 characters'
        }), 400

    # Check if user with this email already exists (race condition check)
    existing_user = User.query.filter_by(email=invitation.email).first()
    if existing_user:
        return jsonify({
            'error': 'A user with this email already exists'
        }), 400

    # Create new user
    user = User(
        email=invitation.email,
        name=name.strip(),
        phone=phone,
        role=invitation.role,
        network_id=invitation.network_id,
        status='pending',  # Will be approved by admin
        invited_by=invitation.invited_by,
        must_change_password=False  # They just set their password
    )
    user.set_password(password)

    # Update invitation status
    invitation.status = 'accepted'
    invitation.accepted_at = datetime.now(timezone.utc)

    try:
        db.session.add(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create account: {str(e)}'
        }), 500

    # Log the action
    log_user_management_action(
        action='create_from_invitation',
        target_user_id=user.id,
        target_user_email=user.email,
        target_user_name=user.name,
        details={
            'role': user.role,
            'network_id': user.network_id,
            'invitation_id': invitation.id
        }
    )

    return jsonify({
        'message': 'Account created successfully. Please wait for admin approval.',
        'user': user.to_dict()
    }), 201


@invitations_bp.route('/<invitation_id>/revoke', methods=['POST'])
@login_required
@require_role('admin')
def revoke_invitation(invitation_id):
    """
    Revoke an invitation.

    Prevents the invitation from being used. Only pending invitations
    can be revoked.

    Args:
        invitation_id: Invitation UUID

    Request Body (optional):
        {
            "reason": "Revocation reason"
        }

    Returns:
        200: Invitation revoked successfully
            {
                "message": "Invitation revoked successfully",
                "invitation": { invitation data }
            }
        400: Invitation is not pending
            {
                "error": "error message"
            }
        403: Insufficient permissions
            {
                "error": "error message"
            }
        404: Invitation not found
    """
    current_user = get_current_user()

    # Find invitation by ID
    invitation = db.session.get(UserInvitation, invitation_id)

    if not invitation:
        return jsonify({'error': 'Invitation not found'}), 404

    # Check permissions - only the inviter or super_admin can revoke
    if current_user.role != 'super_admin' and invitation.invited_by != current_user.id:
        return jsonify({
            'error': 'Only the inviter or super admin can revoke this invitation'
        }), 403

    # Check if invitation is pending
    if invitation.status != 'pending':
        return jsonify({
            'error': f'Cannot revoke invitation with status: {invitation.status}'
        }), 400

    # Get optional reason
    data = request.get_json(silent=True) or {}
    reason = data.get('reason')

    if reason and (not isinstance(reason, str) or len(reason) > 1000):
        return jsonify({
            'error': 'reason must be a string with max 1000 characters'
        }), 400

    # Revoke the invitation
    invitation.status = 'revoked'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to revoke invitation: {str(e)}'
        }), 500

    # Log the action
    log_action(
        action='invitation.revoke',
        action_category='users',
        resource_type='invitation',
        resource_id=invitation.id,
        resource_name=invitation.email,
        details={
            'reason': reason,
            'role': invitation.role,
            'network_id': invitation.network_id
        }
    )

    return jsonify({
        'message': 'Invitation revoked successfully',
        'invitation': invitation.to_dict()
    }), 200


@invitations_bp.route('/<invitation_id>/resend', methods=['POST'])
@login_required
@require_role('admin')
def resend_invitation(invitation_id):
    """
    Resend an invitation with a new token and expiration.

    Creates a new token and extends the expiration for an existing invitation.
    Only pending or expired invitations can be resent.

    Args:
        invitation_id: Invitation UUID

    Request Body (optional):
        {
            "expires_days": 7
        }

    Returns:
        200: Invitation resent successfully
            {
                "message": "Invitation resent successfully",
                "invitation": { invitation data with new token }
            }
        400: Invitation cannot be resent
            {
                "error": "error message"
            }
        403: Insufficient permissions
            {
                "error": "error message"
            }
        404: Invitation not found
    """
    current_user = get_current_user()

    # Find invitation by ID
    invitation = db.session.get(UserInvitation, invitation_id)

    if not invitation:
        return jsonify({'error': 'Invitation not found'}), 404

    # Check permissions - only the inviter or super_admin can resend
    if current_user.role != 'super_admin' and invitation.invited_by != current_user.id:
        return jsonify({
            'error': 'Only the inviter or super admin can resend this invitation'
        }), 403

    # Check if invitation can be resent
    if invitation.status not in ('pending', 'expired'):
        return jsonify({
            'error': f'Cannot resend invitation with status: {invitation.status}'
        }), 400

    # Check if a user with this email now exists
    existing_user = User.query.filter_by(email=invitation.email).first()
    if existing_user:
        return jsonify({
            'error': 'A user with this email already exists'
        }), 409

    # Get optional expiration days
    data = request.get_json(silent=True) or {}
    expires_days = data.get('expires_days', INVITATION_EXPIRATION_DAYS)

    if not isinstance(expires_days, int) or expires_days < 1 or expires_days > 30:
        return jsonify({
            'error': 'expires_days must be an integer between 1 and 30'
        }), 400

    # Generate new token and expiration
    old_token = invitation.token
    invitation.token = secrets.token_urlsafe(32)
    invitation.expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)
    invitation.status = 'pending'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to resend invitation: {str(e)}'
        }), 500

    # Log the action
    log_action(
        action='invitation.resend',
        action_category='users',
        resource_type='invitation',
        resource_id=invitation.id,
        resource_name=invitation.email,
        details={
            'new_expires_at': invitation.expires_at.isoformat()
        }
    )

    return jsonify({
        'message': 'Invitation resent successfully',
        'invitation': invitation.to_dict()
    }), 200
