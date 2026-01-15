"""
Alert ingestion API endpoints.

This module provides REST API endpoints for receiving alerts from Jetson screens:
- POST /alerts - Ingest a new alert from a screen

All endpoints are prefixed with /api/v1 when registered with the app.

CRITICAL: Alerts must NEVER be lost. All incoming alerts are immediately
persisted to the database before any processing or forwarding attempt.
"""

from flask import jsonify, request

from models import db, PendingAlert, Screen
from routes import alerts_bp


# Valid alert types that can be ingested
VALID_ALERT_TYPES = [
    'ncmec_match',      # Missing child face match
    'face_match',       # General face recognition match
    'loyalty_match',    # Loyalty program member match
    'system_error',     # Screen system error
    'hardware_error',   # Hardware malfunction
    'connectivity',     # Network connectivity issue
    'camera_error',     # Camera malfunction
    'storage_warning',  # Low storage warning
    'test'              # Test alerts for verification
]


@alerts_bp.route('', methods=['POST'])
def ingest_alert():
    """
    Ingest a new alert from a Jetson screen.

    Jetson screens send alerts to this endpoint when they detect
    events that need to be forwarded to HQ (e.g., NCMEC face matches,
    system errors, etc.). Alerts are immediately persisted to ensure
    they are never lost.

    Request Body:
        {
            "screen_id": 1,
            "alert_type": "ncmec_match",
            "data": {
                "match_confidence": 0.95,
                "timestamp": "2024-01-15T12:00:00Z",
                ... additional alert-specific data
            }
        }

    Returns:
        201: Alert created and queued for forwarding
            {
                "success": true,
                "message": "Alert received and queued",
                "alert_id": 123
            }
        400: Invalid request body or missing required fields
            {
                "success": false,
                "error": "screen_id is required"
            }
        404: Screen not found
            {
                "success": false,
                "error": "Screen not found"
            }
    """
    data = request.get_json()

    if not data:
        return jsonify({
            'success': False,
            'error': 'Request body is required'
        }), 400

    # Validate screen_id
    screen_id = data.get('screen_id')
    if screen_id is None:
        return jsonify({
            'success': False,
            'error': 'screen_id is required'
        }), 400

    if not isinstance(screen_id, int) or screen_id < 1:
        return jsonify({
            'success': False,
            'error': 'screen_id must be a positive integer'
        }), 400

    # Validate alert_type
    alert_type = data.get('alert_type')
    if not alert_type:
        return jsonify({
            'success': False,
            'error': 'alert_type is required'
        }), 400

    if not isinstance(alert_type, str) or len(alert_type) > 64:
        return jsonify({
            'success': False,
            'error': 'alert_type must be a string with max 64 characters'
        }), 400

    if alert_type not in VALID_ALERT_TYPES:
        return jsonify({
            'success': False,
            'error': f'alert_type must be one of: {", ".join(VALID_ALERT_TYPES)}'
        }), 400

    # Verify screen exists
    screen = db.session.get(Screen, screen_id)
    if not screen:
        return jsonify({
            'success': False,
            'error': 'Screen not found'
        }), 404

    # Extract optional payload data
    payload_data = data.get('data', {})
    if not isinstance(payload_data, dict):
        return jsonify({
            'success': False,
            'error': 'data must be an object'
        }), 400

    # CRITICAL: Persist alert immediately to ensure it's never lost
    alert = PendingAlert.create_alert(
        screen_id=screen_id,
        alert_type=alert_type,
        payload_dict=payload_data
    )

    return jsonify({
        'success': True,
        'message': 'Alert received and queued',
        'alert_id': alert.id
    }), 201


@alerts_bp.route('', methods=['GET'])
def list_alerts():
    """
    List all pending alerts awaiting forwarding to HQ.

    Returns a list of alerts that haven't been successfully
    forwarded to HQ yet, useful for monitoring and debugging.

    Query Parameters:
        screen_id: Filter alerts by screen ID
        status: Filter by status (pending, failed, sending)

    Returns:
        200: List of alerts
            {
                "success": true,
                "alerts": [ { alert data }, ... ],
                "count": 5
            }
    """
    screen_id = request.args.get('screen_id', type=int)
    status = request.args.get('status')

    if screen_id:
        alerts = PendingAlert.get_by_screen(screen_id, include_sent=False)
    else:
        alerts = PendingAlert.get_all_pending()

    # Apply status filter if provided
    if status:
        alerts = [a for a in alerts if a.status == status]

    return jsonify({
        'success': True,
        'alerts': [alert.to_dict() for alert in alerts],
        'count': len(alerts)
    }), 200


@alerts_bp.route('/count', methods=['GET'])
def get_pending_count():
    """
    Get count of pending alerts.

    Returns the total number of alerts awaiting forwarding to HQ.
    Useful for monitoring and dashboard displays.

    Returns:
        200: Alert count
            {
                "success": true,
                "pending_count": 5
            }
    """
    count = PendingAlert.get_pending_count()

    return jsonify({
        'success': True,
        'pending_count': count
    }), 200


@alerts_bp.route('/<int:alert_id>', methods=['GET'])
def get_alert(alert_id):
    """
    Get details for a specific alert.

    Args:
        alert_id: Alert ID

    Returns:
        200: Alert details
            {
                "success": true,
                "alert": { alert data }
            }
        404: Alert not found
            {
                "success": false,
                "error": "Alert not found"
            }
    """
    alert = db.session.get(PendingAlert, alert_id)

    if not alert:
        return jsonify({
            'success': False,
            'error': 'Alert not found'
        }), 404

    return jsonify({
        'success': True,
        'alert': alert.to_dict()
    }), 200
