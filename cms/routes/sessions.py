"""
CMS Sessions Routes

Blueprint for session management API endpoints:
- GET /: List current user's active sessions
- DELETE /<id>: Revoke a specific session

All endpoints are prefixed with /api/v1/sessions when registered with the app.
"""

from flask import Blueprint, jsonify

from cms.models import db, UserSession
from cms.utils.auth import login_required, get_current_user, get_current_session
from cms.utils.audit import log_action


# Create sessions blueprint
sessions_bp = Blueprint('sessions', __name__)


@sessions_bp.route('', methods=['GET'])
@login_required
def list_sessions():
    """
    List the current user's active sessions.

    Returns all non-expired sessions for the authenticated user,
    including the current session which is marked with is_current flag.

    Returns:
        200: List of sessions
            {
                "sessions": [
                    {
                        "id": "uuid",
                        "user_id": "uuid",
                        "ip_address": "192.168.1.1",
                        "user_agent": "Mozilla/5.0...",
                        "device_info": null,
                        "expires_at": "2024-01-15T18:00:00Z",
                        "last_active": "2024-01-15T10:30:00Z",
                        "created_at": "2024-01-15T10:00:00Z",
                        "is_expired": false,
                        "is_current": true
                    },
                    ...
                ],
                "count": 2
            }
    """
    user = get_current_user()
    current_session = get_current_session()

    # Get all active (non-expired) sessions for the user
    sessions = UserSession.query.filter_by(user_id=user.id).all()

    # Filter out expired sessions and mark current session
    session_list = []
    for session in sessions:
        if not session.is_expired():
            session_data = session.to_dict()
            session_data['is_current'] = (session.id == current_session.id)
            session_list.append(session_data)

    # Sort by last_active descending (most recent first)
    session_list.sort(
        key=lambda s: s.get('last_active') or s.get('created_at') or '',
        reverse=True
    )

    return jsonify({
        'sessions': session_list,
        'count': len(session_list)
    }), 200


@sessions_bp.route('/<session_id>', methods=['DELETE'])
@login_required
def revoke_session(session_id):
    """
    Revoke a specific session.

    Users can only revoke their own sessions. Revoking a session immediately
    invalidates the associated token. If the user revokes their current session,
    they will be logged out.

    Args:
        session_id: UUID of the session to revoke

    Returns:
        200: Session revoked successfully
            {
                "message": "Session revoked successfully",
                "was_current_session": false
            }
        403: Cannot revoke another user's session
            {
                "error": "error message"
            }
        404: Session not found
            {
                "error": "error message"
            }
    """
    user = get_current_user()
    current_session = get_current_session()

    # Find the session
    session = db.session.get(UserSession, session_id)

    if not session:
        return jsonify({'error': 'Session not found'}), 404

    # Verify the session belongs to the current user
    if session.user_id != user.id:
        return jsonify({
            'error': 'You can only revoke your own sessions'
        }), 403

    # Check if this is the current session
    was_current = (session.id == current_session.id)

    # Log the action before deleting
    log_action(
        action='session.revoke',
        action_category='auth',
        resource_type='session',
        resource_id=session_id,
        resource_name=session.ip_address or 'unknown',
        details={
            'was_current_session': was_current,
            'session_ip': session.ip_address,
            'session_user_agent': session.user_agent[:100] if session.user_agent else None,
            'session_created_at': session.created_at.isoformat() if session.created_at else None,
        }
    )

    # Delete the session
    try:
        db.session.delete(session)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to revoke session: {str(e)}'
        }), 500

    return jsonify({
        'message': 'Session revoked successfully',
        'was_current_session': was_current
    }), 200


@sessions_bp.route('/all', methods=['DELETE'])
@login_required
def revoke_all_other_sessions():
    """
    Revoke all sessions except the current one.

    This is useful when a user wants to log out of all other devices
    while staying logged in on the current device.

    Returns:
        200: Sessions revoked successfully
            {
                "message": "X session(s) revoked successfully",
                "revoked_count": 3
            }
    """
    user = get_current_user()
    current_session = get_current_session()

    # Find all other sessions for this user
    other_sessions = UserSession.query.filter(
        UserSession.user_id == user.id,
        UserSession.id != current_session.id
    ).all()

    revoked_count = len(other_sessions)

    if revoked_count > 0:
        # Log the action
        log_action(
            action='session.revoke_all_others',
            action_category='auth',
            resource_type='session',
            resource_id=user.id,
            resource_name=user.email,
            details={
                'revoked_count': revoked_count,
                'session_ids': [s.id for s in other_sessions],
            }
        )

        # Delete all other sessions
        try:
            for session in other_sessions:
                db.session.delete(session)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({
                'error': f'Failed to revoke sessions: {str(e)}'
            }), 500

    return jsonify({
        'message': f'{revoked_count} session(s) revoked successfully',
        'revoked_count': revoked_count
    }), 200
