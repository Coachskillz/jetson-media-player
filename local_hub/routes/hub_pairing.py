"""
Hub Pairing Routes - Web UI and API for pairing local hub with CMS.

This module provides:
- GET /hub/pairing - Interactive pairing screen
- GET /api/v1/hub/status - Get current hub registration status
- POST /api/v1/hub/start-pairing - Manually trigger pairing flow
- GET /api/v1/hub/pairing-poll - Poll for pairing completion
"""

import threading
from flask import Blueprint, jsonify, render_template_string, current_app

from models.hub_config import HubConfig
from services.hub_pairing import HubPairingService, get_hardware_id
from config import get_config


# Blueprint for hub pairing UI (no prefix)
hub_pairing_ui_bp = Blueprint('hub_pairing_ui', __name__)

# Blueprint for hub pairing API
hub_pairing_api_bp = Blueprint('hub_pairing_api', __name__)


# Global pairing state for this module
_pairing_state = {
    'active': False,
    'pairing_code': None,
    'hardware_id': None,
    'status': 'unknown',  # unknown, pending, paired, error
    'error': None,
    'hub_name': None,
    'hub_id': None,
}

_pairing_lock = threading.Lock()
_pairing_thread = None


def get_pairing_state():
    """Get current pairing state."""
    with _pairing_lock:
        return dict(_pairing_state)


def update_pairing_state(**kwargs):
    """Update pairing state."""
    with _pairing_lock:
        _pairing_state.update(kwargs)


# =============================================================================
# API Endpoints
# =============================================================================

@hub_pairing_api_bp.route('/status', methods=['GET'])
def get_hub_status():
    """
    Get current hub registration status.

    Returns:
        200: Hub status
            {
                "registered": true/false,
                "hub_id": "uuid" (if registered),
                "hub_code": "WM" (if registered),
                "hub_name": "Store Name" (if registered),
                "status": "active/pending/unknown"
            }
    """
    hub_config = HubConfig.get_instance()

    if hub_config.is_registered:
        return jsonify({
            'registered': True,
            'hub_id': hub_config.hub_id,
            'hub_code': hub_config.hub_code,
            'hub_name': hub_config.hub_name,
            'network_id': hub_config.network_id,
            'status': hub_config.status or 'active'
        })
    else:
        state = get_pairing_state()
        return jsonify({
            'registered': False,
            'pairing_active': state['active'],
            'pairing_code': state['pairing_code'],
            'hardware_id': state['hardware_id'],
            'status': state['status'],
            'error': state['error']
        })


@hub_pairing_api_bp.route('/start-pairing', methods=['POST'])
def start_pairing():
    """
    Manually start the pairing flow.

    Returns:
        200: Pairing started
            {
                "success": true,
                "pairing_code": "ABC-123",
                "hardware_id": "HUB-XXXXXXXX"
            }
        400: Already registered or pairing in progress
    """
    global _pairing_thread

    hub_config = HubConfig.get_instance()

    if hub_config.is_registered:
        return jsonify({
            'success': False,
            'error': 'Hub is already registered',
            'hub_name': hub_config.hub_name
        }), 400

    state = get_pairing_state()
    if state['active']:
        return jsonify({
            'success': True,
            'message': 'Pairing already in progress',
            'pairing_code': state['pairing_code'],
            'hardware_id': state['hardware_id']
        })

    # Start pairing in background thread
    config = get_config()
    hardware_id = get_hardware_id()

    update_pairing_state(
        active=True,
        hardware_id=hardware_id,
        status='starting',
        error=None
    )

    def pairing_worker():
        try:
            service = HubPairingService(
                cms_url=config.cms_url,
                hardware_id=hardware_id
            )

            # Announce to CMS
            result = service.announce()

            if result.get('status') == 'already_paired':
                # Already paired - store credentials
                HubConfig.update_registration(
                    hub_id=result.get('hub_id'),
                    hub_token=result.get('api_token'),
                    hub_code=result.get('hub_code'),
                    hub_name=result.get('store_name'),
                    network_id=result.get('network_id'),
                    status='active',
                )
                update_pairing_state(
                    active=False,
                    status='paired',
                    hub_name=result.get('store_name'),
                    hub_id=result.get('hub_id')
                )
                current_app.logger.info(f"Hub already paired as: {result.get('store_name')}")
                return

            if result.get('status') == 'error':
                update_pairing_state(
                    active=False,
                    status='error',
                    error=result.get('error', 'Failed to announce to CMS')
                )
                current_app.logger.error(f"Pairing announce failed: {result.get('error')}")
                return

            # Update state with pairing code
            update_pairing_state(
                pairing_code=service.pairing_code,
                status='pending'
            )

            current_app.logger.info(f"Pairing code: {service.pairing_code}")

            # Wait for pairing (polls CMS)
            def on_status(status):
                if status.get('status') == 'expired':
                    new_code = status.get('new_pairing_code') or service.pairing_code
                    update_pairing_state(pairing_code=new_code)
                    current_app.logger.info(f"New pairing code: {new_code}")

            result = service.wait_for_pairing(
                poll_interval=3,
                max_wait=900,
                on_status=on_status
            )

            if result.get('status') == 'paired':
                HubConfig.update_registration(
                    hub_id=result.get('hub_id'),
                    hub_token=result.get('api_token'),
                    hub_code=result.get('hub_code'),
                    hub_name=result.get('store_name'),
                    network_id=result.get('network_id'),
                    status='active',
                    store_address=result.get('store_address'),
                    store_city=result.get('store_city'),
                    store_state=result.get('store_state'),
                    store_zipcode=result.get('store_zipcode'),
                    manager_name=result.get('manager_name'),
                    store_phone=result.get('store_phone'),
                )
                update_pairing_state(
                    active=False,
                    status='paired',
                    hub_name=result.get('store_name'),
                    hub_id=result.get('hub_id')
                )
                current_app.logger.info(f"Hub paired as: {result.get('store_name')}")
            else:
                update_pairing_state(
                    active=False,
                    status='error',
                    error=result.get('error', 'Pairing failed or timed out')
                )

        except Exception as e:
            current_app.logger.error(f"Pairing error: {e}")
            update_pairing_state(
                active=False,
                status='error',
                error=str(e)
            )

    # Need app context for the thread
    app = current_app._get_current_object()

    def run_with_context():
        with app.app_context():
            pairing_worker()

    _pairing_thread = threading.Thread(target=run_with_context, daemon=True)
    _pairing_thread.start()

    # Wait briefly for pairing code to be generated
    import time
    for _ in range(10):
        time.sleep(0.2)
        state = get_pairing_state()
        if state['pairing_code'] or state['status'] in ('error', 'paired'):
            break

    state = get_pairing_state()
    return jsonify({
        'success': True,
        'pairing_code': state['pairing_code'],
        'hardware_id': state['hardware_id'],
        'status': state['status']
    })


@hub_pairing_api_bp.route('/pairing-poll', methods=['GET'])
def poll_pairing_status():
    """
    Poll for pairing status updates.

    Returns:
        200: Current pairing state
    """
    hub_config = HubConfig.get_instance()

    if hub_config.is_registered:
        return jsonify({
            'status': 'paired',
            'hub_id': hub_config.hub_id,
            'hub_code': hub_config.hub_code,
            'hub_name': hub_config.hub_name
        })

    state = get_pairing_state()
    return jsonify({
        'status': state['status'],
        'pairing_code': state['pairing_code'],
        'hardware_id': state['hardware_id'],
        'error': state['error'],
        'active': state['active']
    })


@hub_pairing_api_bp.route('/reset', methods=['POST'])
def reset_hub():
    """
    Reset hub registration (for testing).

    This clears the hub's stored credentials, allowing re-pairing.

    Returns:
        200: Hub reset successfully
    """
    HubConfig.reset_registration()

    update_pairing_state(
        active=False,
        pairing_code=None,
        hardware_id=None,
        status='unknown',
        error=None,
        hub_name=None,
        hub_id=None
    )

    current_app.logger.info("Hub registration reset")

    return jsonify({
        'success': True,
        'message': 'Hub registration cleared. Ready for re-pairing.'
    })


@hub_pairing_api_bp.route('/update-store-info', methods=['POST'])
def update_store_info():
    """
    Receive store info update from CMS.

    Called by CMS when admin updates Hub's store information.

    Request Body:
        {
            "store_name": "Store Name",
            "store_address": "123 Main St",
            "store_city": "Tampa",
            "store_state": "FL",
            "store_zipcode": "33601",
            "manager_name": "John Doe",
            "store_phone": "813-555-1234"
        }

    Returns:
        200: Store info updated
        400: Hub not registered
    """
    from flask import request
    from models import db

    hub_config = HubConfig.get_instance()

    if not hub_config.is_registered:
        return jsonify({
            'success': False,
            'error': 'Hub not registered'
        }), 400

    data = request.get_json() or {}

    # Update store info fields
    if 'store_name' in data:
        hub_config.hub_name = data['store_name']
    if 'store_address' in data:
        hub_config.store_address = data['store_address']
    if 'store_city' in data:
        hub_config.store_city = data['store_city']
    if 'store_state' in data:
        hub_config.store_state = data['store_state']
    if 'store_zipcode' in data:
        hub_config.store_zipcode = data['store_zipcode']
    if 'manager_name' in data:
        hub_config.manager_name = data['manager_name']
    if 'store_phone' in data:
        hub_config.store_phone = data['store_phone']

    db.session.commit()

    current_app.logger.info(f"Store info updated: {hub_config.hub_name}")

    return jsonify({
        'success': True,
        'message': 'Store info updated',
        'hub': hub_config.to_dict()
    })


# =============================================================================
# Pairing Screen UI
# =============================================================================

PAIRING_SCREEN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Hub Pairing - Skillz Media</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1e3a5f 0%, #0d1b2a 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
        }
        .container {
            text-align: center;
            padding: 50px;
            max-width: 600px;
            width: 90%;
        }
        .logo {
            font-size: 14px;
            letter-spacing: 4px;
            opacity: 0.7;
            margin-bottom: 10px;
        }
        h1 {
            font-size: 32px;
            font-weight: 300;
            margin-bottom: 40px;
        }
        .card {
            background: rgba(255,255,255,0.1);
            border-radius: 20px;
            padding: 40px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
        }
        .pairing-code {
            font-size: 72px;
            font-family: 'SF Mono', 'Consolas', monospace;
            font-weight: 700;
            letter-spacing: 8px;
            color: #4ade80;
            margin: 30px 0;
            text-shadow: 0 0 30px rgba(74, 222, 128, 0.5);
        }
        .hardware-id {
            font-size: 13px;
            opacity: 0.5;
            font-family: monospace;
            margin-bottom: 20px;
        }
        .instructions {
            font-size: 16px;
            opacity: 0.8;
            line-height: 1.6;
            margin-bottom: 30px;
        }
        .status {
            display: inline-block;
            padding: 8px 20px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 500;
        }
        .status.waiting {
            background: rgba(251, 191, 36, 0.2);
            color: #fbbf24;
            animation: pulse 2s infinite;
        }
        .status.paired {
            background: rgba(74, 222, 128, 0.2);
            color: #4ade80;
        }
        .status.error {
            background: rgba(248, 113, 113, 0.2);
            color: #f87171;
        }
        .btn {
            display: inline-block;
            padding: 14px 32px;
            font-size: 16px;
            font-weight: 600;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.2s;
            margin: 10px;
        }
        .btn-primary {
            background: #4ade80;
            color: #0d1b2a;
        }
        .btn-primary:hover {
            background: #22c55e;
            transform: translateY(-2px);
        }
        .btn-secondary {
            background: rgba(255,255,255,0.1);
            color: white;
            border: 1px solid rgba(255,255,255,0.2);
        }
        .btn-secondary:hover {
            background: rgba(255,255,255,0.2);
        }
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
        .success-icon {
            font-size: 80px;
            margin-bottom: 20px;
        }
        .hub-name {
            font-size: 28px;
            font-weight: 600;
            color: #4ade80;
            margin: 20px 0;
        }
        .error-message {
            background: rgba(248, 113, 113, 0.1);
            border: 1px solid rgba(248, 113, 113, 0.3);
            border-radius: 10px;
            padding: 15px;
            margin: 20px 0;
            color: #f87171;
        }
        .cms-url {
            font-size: 12px;
            opacity: 0.4;
            margin-top: 30px;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }
        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid rgba(255,255,255,0.3);
            border-top-color: white;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-right: 10px;
            vertical-align: middle;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">SKILLZ MEDIA</div>
        <h1>Local Hub Setup</h1>

        <div class="card" id="content">
            <!-- Content injected by JavaScript -->
            <div class="spinner"></div> Loading...
        </div>

        <div class="cms-url">CMS: {{ cms_url }}</div>
    </div>

    <script>
        const API_BASE = '/api/v1/hub';
        let pollInterval = null;

        async function fetchStatus() {
            try {
                const res = await fetch(API_BASE + '/status');
                return await res.json();
            } catch (e) {
                return { error: 'Failed to connect to hub API' };
            }
        }

        async function startPairing() {
            document.getElementById('content').innerHTML = '<div class="spinner"></div> Starting pairing...';
            try {
                const res = await fetch(API_BASE + '/start-pairing', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    startPolling();
                } else {
                    renderError(data.error || 'Failed to start pairing');
                }
            } catch (e) {
                renderError('Failed to connect to hub API');
            }
        }

        async function resetHub() {
            if (!confirm('Reset hub registration? This will require re-pairing with the CMS.')) return;
            try {
                const res = await fetch(API_BASE + '/reset', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    stopPolling();
                    render();
                } else {
                    alert('Reset failed: ' + (data.error || 'Unknown error'));
                }
            } catch (e) {
                alert('Failed to reset hub');
            }
        }

        function startPolling() {
            if (pollInterval) return;
            pollInterval = setInterval(async () => {
                const status = await fetchPollStatus();
                renderStatus(status);
                if (status.status === 'paired' || status.status === 'error') {
                    stopPolling();
                }
            }, 2000);
        }

        function stopPolling() {
            if (pollInterval) {
                clearInterval(pollInterval);
                pollInterval = null;
            }
        }

        async function fetchPollStatus() {
            try {
                const res = await fetch(API_BASE + '/pairing-poll');
                return await res.json();
            } catch (e) {
                return { status: 'error', error: 'Connection lost' };
            }
        }

        function renderStatus(status) {
            if (status.status === 'paired') {
                renderPaired(status);
            } else if (status.status === 'pending' && status.pairing_code) {
                renderPairingCode(status);
            } else if (status.status === 'error') {
                renderError(status.error);
            } else {
                document.getElementById('content').innerHTML = `
                    <div class="spinner"></div> ${status.status || 'Connecting to CMS...'}
                `;
            }
        }

        function renderPaired(data) {
            document.getElementById('content').innerHTML = `
                <div class="success-icon">&#10004;</div>
                <h2 style="color: #4ade80; margin-bottom: 10px;">Hub Paired Successfully</h2>
                <div class="hub-name">${data.hub_name || data.hub_code || 'Connected'}</div>
                <p class="instructions">This hub is now connected to the CMS and ready to operate.</p>
                <span class="status paired">Connected</span>
                <div style="margin-top: 30px;">
                    <button class="btn btn-secondary" onclick="resetHub()">Reset Hub</button>
                </div>
            `;
        }

        function renderPairingCode(data) {
            document.getElementById('content').innerHTML = `
                <p class="instructions">Enter this code in the CMS admin panel to pair this hub:</p>
                <div class="pairing-code">${data.pairing_code}</div>
                <div class="hardware-id">Hardware ID: ${data.hardware_id}</div>
                <span class="status waiting">Waiting for pairing...</span>
            `;
        }

        function renderError(message) {
            document.getElementById('content').innerHTML = `
                <div class="error-message">${message}</div>
                <button class="btn btn-primary" onclick="startPairing()">Retry Pairing</button>
            `;
        }

        function renderUnregistered(data) {
            let html = `
                <p class="instructions">This hub is not yet paired with the CMS. Click below to start the pairing process.</p>
                <button class="btn btn-primary" onclick="startPairing()">Start Pairing</button>
            `;

            if (data.pairing_active && data.pairing_code) {
                html = `
                    <p class="instructions">Enter this code in the CMS admin panel:</p>
                    <div class="pairing-code">${data.pairing_code}</div>
                    <div class="hardware-id">Hardware ID: ${data.hardware_id}</div>
                    <span class="status waiting">Waiting for pairing...</span>
                `;
                startPolling();
            } else if (data.error) {
                html = `
                    <div class="error-message">${data.error}</div>
                    <button class="btn btn-primary" onclick="startPairing()">Retry Pairing</button>
                `;
            }

            document.getElementById('content').innerHTML = html;
        }

        async function render() {
            const status = await fetchStatus();

            if (status.error && !status.registered) {
                renderError(status.error);
            } else if (status.registered) {
                renderPaired(status);
            } else {
                renderUnregistered(status);
            }
        }

        // Initial render
        render();
    </script>
</body>
</html>
'''


@hub_pairing_ui_bp.route('/hub/pairing')
def pairing_screen():
    """Display the hub pairing screen."""
    config = get_config()
    return render_template_string(PAIRING_SCREEN_TEMPLATE, cms_url=config.cms_url)
