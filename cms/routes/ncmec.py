"""
NCMEC Alert Routes.

Handles NCMEC alert management including:
- Receiving alerts from Jetson devices
- Listing and reviewing alerts
- Confirming/dismissing alerts
- Notification configuration
"""

from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, render_template, current_app
from werkzeug.utils import secure_filename
import os
import uuid

from cms.models import db
from cms.models.ncmec_alert import NCMECAlert, NCMECNotificationConfig
from cms.models.device import Device
from cms.utils.auth import login_required, get_current_user


ncmec_bp = Blueprint('ncmec', __name__, url_prefix='/ncmec')
ncmec_api_bp = Blueprint('ncmec_api', __name__, url_prefix='/api/v1/ncmec')


# =============================================================================
# Web Routes
# =============================================================================

@ncmec_bp.route('/')
@ncmec_bp.route('/alerts')
@login_required
def alerts_list():
    """Display NCMEC alerts list page."""
    return render_template('ncmec/alerts.html')


@ncmec_bp.route('/alerts/<int:alert_id>')
@login_required
def alert_detail(alert_id):
    """Display NCMEC alert detail/review page."""
    alert = NCMECAlert.query.get_or_404(alert_id)
    return render_template('ncmec/alert_detail.html', alert=alert)


@ncmec_bp.route('/settings')
@login_required
def settings():
    """Display NCMEC notification settings page."""
    return render_template('ncmec/settings.html')


# =============================================================================
# API Routes - Alert Management
# =============================================================================

@ncmec_api_bp.route('/alerts', methods=['GET'])
@login_required
def get_alerts():
    """Get all NCMEC alerts with optional filtering."""
    status = request.args.get('status')
    device_id = request.args.get('device_id')
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    query = NCMECAlert.query
    
    if status:
        query = query.filter_by(status=status)
    if device_id:
        query = query.filter_by(device_id=device_id)
    
    # Order by most recent first
    query = query.order_by(NCMECAlert.detected_at.desc())
    
    total = query.count()
    alerts = query.offset(offset).limit(limit).all()
    
    return jsonify({
        'alerts': [a.to_dict() for a in alerts],
        'total': total,
        'limit': limit,
        'offset': offset
    })


@ncmec_api_bp.route('/alerts/<int:alert_id>', methods=['GET'])
@login_required
def get_alert(alert_id):
    """Get a specific NCMEC alert."""
    alert = NCMECAlert.query.get_or_404(alert_id)
    return jsonify(alert.to_dict())


@ncmec_api_bp.route('/alerts/<int:alert_id>/review', methods=['POST'])
@login_required
def review_alert(alert_id):
    """Mark an alert as being reviewed."""
    alert = NCMECAlert.query.get_or_404(alert_id)
    user = get_current_user()
    
    alert.status = 'reviewing'
    alert.reviewed_by_id = user.id
    alert.reviewed_at = datetime.now(timezone.utc)
    
    db.session.commit()
    
    return jsonify({
        'message': 'Alert marked as reviewing',
        'alert': alert.to_dict()
    })


@ncmec_api_bp.route('/alerts/<int:alert_id>/confirm', methods=['POST'])
@login_required
def confirm_alert(alert_id):
    """Confirm an alert and mark as needing to be reported."""
    alert = NCMECAlert.query.get_or_404(alert_id)
    user = get_current_user()
    data = request.get_json() or {}
    
    alert.status = 'confirmed'
    alert.reviewed_by_id = user.id
    alert.reviewed_at = datetime.now(timezone.utc)
    alert.review_notes = data.get('notes', '')
    
    db.session.commit()
    
    return jsonify({
        'message': 'Alert confirmed',
        'alert': alert.to_dict()
    })


@ncmec_api_bp.route('/alerts/<int:alert_id>/report', methods=['POST'])
@login_required
def report_alert(alert_id):
    """Mark an alert as reported to authorities."""
    alert = NCMECAlert.query.get_or_404(alert_id)
    user = get_current_user()
    data = request.get_json() or {}
    
    alert.status = 'reported'
    alert.reported_at = datetime.now(timezone.utc)
    alert.reported_to = data.get('reported_to', '')
    alert.report_reference = data.get('reference', '')
    alert.review_notes = data.get('notes', alert.review_notes)
    
    if not alert.reviewed_by_id:
        alert.reviewed_by_id = user.id
        alert.reviewed_at = datetime.now(timezone.utc)
    
    db.session.commit()
    
    return jsonify({
        'message': 'Alert marked as reported',
        'alert': alert.to_dict()
    })


@ncmec_api_bp.route('/alerts/<int:alert_id>/dismiss', methods=['POST'])
@login_required
def dismiss_alert(alert_id):
    """Dismiss an alert as false positive."""
    alert = NCMECAlert.query.get_or_404(alert_id)
    user = get_current_user()
    data = request.get_json() or {}
    
    alert.status = 'dismissed'
    alert.reviewed_by_id = user.id
    alert.reviewed_at = datetime.now(timezone.utc)
    alert.review_notes = data.get('reason', 'Dismissed as false positive')
    
    db.session.commit()
    
    return jsonify({
        'message': 'Alert dismissed',
        'alert': alert.to_dict()
    })


# =============================================================================
# API Routes - Device Alert Submission (called by Jetson devices)
# =============================================================================

@ncmec_api_bp.route('/alerts', methods=['POST'])
def submit_alert():
    """
    Receive an NCMEC alert from a Jetson device.
    
    This endpoint is called by devices when they detect a potential match.
    It does NOT require user authentication - it uses device authentication.
    """
    # Get device authentication from header
    device_id = request.headers.get('X-Device-ID')
    device_key = request.headers.get('X-Device-Key')
    
    if not device_id:
        return jsonify({'error': 'Device ID required'}), 401
    
    # Verify device exists
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        return jsonify({'error': 'Unknown device'}), 401

    # Verify device_key against stored key
    if device.device_key and device_key != device.device_key:
        current_app.logger.warning(f'Invalid device key for device {device_id}')
        return jsonify({'error': 'Invalid device key'}), 401
    
    # Get alert data
    data = request.form.to_dict() if request.form else request.get_json() or {}
    
    # Handle uploaded image
    captured_image_path = None
    if 'captured_image' in request.files:
        file = request.files['captured_image']
        if file.filename:
            filename = f"ncmec_{device_id}_{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            upload_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'ncmec_captures')
            os.makedirs(upload_dir, exist_ok=True)
            filepath = os.path.join(upload_dir, filename)
            file.save(filepath)
            captured_image_path = f"/uploads/ncmec_captures/{filename}"
    elif data.get('captured_image_base64'):
        # Handle base64 encoded image
        import base64
        img_data = base64.b64decode(data['captured_image_base64'])
        filename = f"ncmec_{device_id}_{uuid.uuid4().hex}.jpg"
        upload_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'ncmec_captures')
        os.makedirs(upload_dir, exist_ok=True)
        filepath = os.path.join(upload_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(img_data)
        captured_image_path = f"/uploads/ncmec_captures/{filename}"
    
    if not captured_image_path:
        return jsonify({'error': 'Captured image required'}), 400
    
    # Create alert
    alert = NCMECAlert(
        device_id=device_id,
        ncmec_case_id=data.get('ncmec_case_id', 'UNKNOWN'),
        ncmec_child_name=data.get('ncmec_child_name'),
        ncmec_case_photo_path=data.get('ncmec_case_photo_path'),
        captured_image_path=captured_image_path,
        confidence_score=float(data.get('confidence_score', 0)),
        detected_at=datetime.now(timezone.utc),
        store_name=device.hub.name if device.hub else None,
        store_address=device.hub.address if device.hub else None,
        status='pending'
    )
    
    db.session.add(alert)
    db.session.commit()
    
    # Send notifications
    _send_alert_notifications(alert)
    
    return jsonify({
        'message': 'Alert received',
        'alert_id': alert.id
    }), 201


def _send_alert_notifications(alert):
    """Send notifications for a new alert."""
    config = NCMECNotificationConfig.query.first()
    if not config:
        return
    
    # Check confidence threshold
    if alert.confidence_score < config.min_confidence_threshold:
        return
    
    # Send email notifications
    if config.email_enabled and config.email_addresses:
        try:
            from cms.services.notification import send_ncmec_alert_email
            for email in config.get_email_list():
                send_ncmec_alert_email(email, alert)
        except Exception as e:
            current_app.logger.error(f"Failed to send NCMEC email notification: {e}")
    
    # Send SMS notifications
    if config.sms_enabled and config.phone_numbers:
        try:
            from cms.services.notification import send_ncmec_alert_sms
            for phone in config.get_phone_list():
                send_ncmec_alert_sms(phone, alert)
        except Exception as e:
            current_app.logger.error(f"Failed to send NCMEC SMS notification: {e}")


# =============================================================================
# API Routes - Notification Settings
# =============================================================================

@ncmec_api_bp.route('/settings', methods=['GET'])
@login_required
def get_settings():
    """Get NCMEC notification settings."""
    config = NCMECNotificationConfig.query.first()
    if not config:
        config = NCMECNotificationConfig()
        db.session.add(config)
        db.session.commit()
    
    return jsonify(config.to_dict())


@ncmec_api_bp.route('/settings', methods=['PUT'])
@login_required
def update_settings():
    """Update NCMEC notification settings."""
    data = request.get_json() or {}
    
    config = NCMECNotificationConfig.query.first()
    if not config:
        config = NCMECNotificationConfig()
        db.session.add(config)
    
    if 'email_enabled' in data:
        config.email_enabled = bool(data['email_enabled'])
    if 'email_addresses' in data:
        if isinstance(data['email_addresses'], list):
            config.email_addresses = ','.join(data['email_addresses'])
        else:
            config.email_addresses = data['email_addresses']
    
    if 'sms_enabled' in data:
        config.sms_enabled = bool(data['sms_enabled'])
    if 'phone_numbers' in data:
        if isinstance(data['phone_numbers'], list):
            config.phone_numbers = ','.join(data['phone_numbers'])
        else:
            config.phone_numbers = data['phone_numbers']
    
    if 'min_confidence_threshold' in data:
        config.min_confidence_threshold = float(data['min_confidence_threshold'])
    
    db.session.commit()
    
    return jsonify({
        'message': 'Settings updated',
        'settings': config.to_dict()
    })


# =============================================================================
# API Routes - Statistics
# =============================================================================

@ncmec_api_bp.route('/stats', methods=['GET'])
@login_required
def get_stats():
    """Get NCMEC alert statistics."""
    total = NCMECAlert.query.count()
    pending = NCMECAlert.query.filter_by(status='pending').count()
    reviewing = NCMECAlert.query.filter_by(status='reviewing').count()
    confirmed = NCMECAlert.query.filter_by(status='confirmed').count()
    reported = NCMECAlert.query.filter_by(status='reported').count()
    dismissed = NCMECAlert.query.filter_by(status='dismissed').count()
    
    return jsonify({
        'total': total,
        'pending': pending,
        'reviewing': reviewing,
        'confirmed': confirmed,
        'reported': reported,
        'dismissed': dismissed
    })
