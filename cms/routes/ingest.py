"""
Data Ingest Routes for CMS Service.

API endpoints for receiving heartbeats, playback logs, and alerts
from Hubs and direct devices. These endpoints are unauthenticated
as they are called by devices.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime

from cms.models import db
from cms.models.heartbeat import Heartbeat
from cms.models.playback_log import PlaybackLog
from cms.models.alert import Alert

ingest_bp = Blueprint('ingest', __name__, url_prefix='/api/v1')


@ingest_bp.route('/heartbeat', methods=['POST'])
def receive_heartbeat():
    """
    Receive heartbeat from Hub or direct device.

    No authentication required - devices call this endpoint directly.

    Expected JSON body:
    {
        "device_id": "SKZ-H-WM-0001",  # Required
        "hub_id": "HUB-001",           # Optional
        "network_id": "west_marine",   # Optional
        "store_name": "West Marine Tampa",
        "location": "Fishing Counter",
        "current_content": "summer_sale.mp4",
        "ip_address": "192.168.1.100",
        "cpu_temp": 45.5,
        "storage_free_mb": 4096,
        "software_version": "1.2.0",
        "mode": "hub"
    }

    Returns:
        200: Heartbeat received successfully
        400: Missing required device_id
    """
    data = request.json
    if not data or not data.get('device_id'):
        return jsonify({'error': 'device_id required'}), 400

    hb = Heartbeat(
        device_id=data['device_id'],
        hub_id=data.get('hub_id'),
        network_id=data.get('network_id'),
        store_name=data.get('store_name'),
        location=data.get('location'),
        status='online',
        current_content=data.get('current_content'),
        ip_address=data.get('ip_address') or request.remote_addr,
        cpu_temp=data.get('cpu_temp'),
        storage_free_mb=data.get('storage_free_mb'),
        software_version=data.get('software_version'),
        mode=data.get('mode'),
    )
    db.session.add(hb)
    db.session.commit()
    return jsonify({'status': 'ok'}), 200


@ingest_bp.route('/playback/batch', methods=['POST'])
def receive_playback_batch():
    """
    Receive batch of playback logs from Hub or device.

    Sent every 5 minutes with playback events since last batch.

    Expected JSON body:
    {
        "device_id": "SKZ-H-WM-0001",
        "hub_id": "HUB-001",
        "network_id": "west_marine",
        "store_name": "West Marine Tampa",
        "location": "Fishing Counter",
        "plays": [
            {
                "filename": "summer_sale.mp4",
                "started_at": "2026-02-10T12:00:00Z",
                "duration": 30
            },
            {
                "filename": "coca_cola.mp4",
                "started_at": "2026-02-10T12:00:30Z",
                "duration": 15
            }
        ]
    }

    Returns:
        200: Batch received with count of logs created
        400: Missing plays array
    """
    data = request.json
    if not data or not data.get('plays'):
        return jsonify({'error': 'plays array required'}), 400

    count = 0
    for play in data['plays']:
        started = play.get('started_at')
        if isinstance(started, str):
            try:
                # Handle ISO format with or without timezone
                started = started.replace('Z', '+00:00')
                started = datetime.fromisoformat(started)
            except ValueError:
                continue

        if not started:
            continue

        log = PlaybackLog(
            device_id=data.get('device_id', 'unknown'),
            hub_id=data.get('hub_id'),
            network_id=data.get('network_id'),
            store_name=data.get('store_name'),
            location=data.get('location'),
            content_filename=play.get('filename', 'unknown'),
            started_at=started,
            duration_seconds=play.get('duration'),
        )
        db.session.add(log)
        count += 1

    db.session.commit()
    return jsonify({'status': 'ok', 'received': count}), 200


@ingest_bp.route('/alert', methods=['POST'])
def receive_alert():
    """
    Receive an alert from Hub or device.

    Used for NCMEC matches, device offline events, errors, and updates.

    Expected JSON body:
    {
        "device_id": "SKZ-H-WM-0001",
        "hub_id": "HUB-001",
        "network_id": "west_marine",
        "store_name": "West Marine Tampa",
        "alert_type": "ncmec",  # Required: ncmec, offline, error, update
        "severity": "critical", # Optional: info, warning, critical
        "message": "Potential NCMEC match detected",
        "data": {               # Optional additional data
            "confidence": 0.95,
            "image_url": "..."
        }
    }

    Returns:
        200: Alert received with alert_id
        400: Missing alert_type
    """
    data = request.json
    if not data or not data.get('alert_type'):
        return jsonify({'error': 'alert_type required'}), 400

    # Convert data dict to JSON string if present
    data_json = None
    if data.get('data'):
        import json
        data_json = json.dumps(data.get('data'))

    alert = Alert(
        device_id=data.get('device_id'),
        hub_id=data.get('hub_id'),
        network_id=data.get('network_id'),
        store_name=data.get('store_name'),
        alert_type=data['alert_type'],
        severity=data.get('severity', 'info'),
        message=data.get('message'),
        data_json=data_json,
    )
    db.session.add(alert)
    db.session.commit()
    return jsonify({'status': 'ok', 'alert_id': alert.id}), 200


@ingest_bp.route('/alerts/<int:alert_id>/acknowledge', methods=['POST'])
def acknowledge_alert(alert_id):
    """
    Acknowledge an alert.

    Expected JSON body:
    {
        "acknowledged_by": "matt@skillzmedia.com"
    }

    Returns:
        200: Alert acknowledged
        404: Alert not found
    """
    alert = Alert.query.get(alert_id)
    if not alert:
        return jsonify({'error': 'Alert not found'}), 404

    data = request.json or {}
    alert.acknowledged = True
    alert.acknowledged_by = data.get('acknowledged_by', 'unknown')
    db.session.commit()

    return jsonify({'status': 'ok', 'alert': alert.to_dict()}), 200
