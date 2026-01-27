"""
Flask Application Factory for Local Hub Service.

This module provides the create_app() factory function that creates and
configures the Flask application. It initializes:
- SQLAlchemy database connection
- Blueprint registration (when available)
- Background job scheduler (APScheduler)
- Logging configuration
- Automatic pairing flow for unregistered hubs

Usage:
    # Development
    python app.py

    # Production
    gunicorn -w 4 -b 0.0.0.0:5000 'app:create_app()'
"""

import atexit
import logging
import os
import threading
from typing import Optional

from flask import Flask, render_template_string

from config import load_config
from models import db


# Global pairing state (shared across threads)
_pairing_state = {
    'active': False,
    'pairing_code': None,
    'hardware_id': None,
    'hub_name': None,
    'status': 'unknown',
    'error': None,
}


def create_app(config_path: Optional[str] = None) -> Flask:
    """
    Create and configure the Flask application.

    Args:
        config_path: Optional path to configuration file.
                    If None, uses /etc/skillz-hub/config.json

    Returns:
        Configured Flask application instance
    """
    app = Flask(__name__)

    # Load configuration from config file
    config = load_config(config_path)
    storage_path = config.storage_path

    # Ensure storage directories exist
    os.makedirs(storage_path, exist_ok=True)
    os.makedirs(config.content_path, exist_ok=True)
    os.makedirs(config.databases_path, exist_ok=True)
    os.makedirs(config.log_path, exist_ok=True)

    # Database path must be absolute for production reliability
    db_path = config.db_path
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Store hub config in app config for access by routes/services
    app.config['HUB_CONFIG'] = config
    app.config['STORAGE_PATH'] = storage_path
    app.config['CONTENT_PATH'] = config.content_path
    app.config['DATABASES_PATH'] = config.databases_path

    # Initialize extensions
    db.init_app(app)

    # Create database tables
    with app.app_context():
        db.create_all()

    # Configure logging
    _configure_logging(app, config.log_path)

    # Register blueprints (when available)
    _register_blueprints(app)

    # Initialize and start background scheduler
    _init_scheduler(app)

    # Register health check endpoint
    @app.route('/health')
    def health_check():
        """Basic health check endpoint."""
        return {'status': 'healthy', 'service': 'local-hub'}

    # Register pairing screen endpoint
    @app.route('/pairing')
    def pairing_screen():
        """Display pairing code on hub screen."""
        return render_template_string(PAIRING_SCREEN_TEMPLATE, **_pairing_state)

    # Check registration and start pairing if needed
    _check_and_start_pairing(app)

    return app


# HTML template for pairing screen display
PAIRING_SCREEN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Hub Pairing - Skillz Media</title>
    <meta http-equiv="refresh" content="5">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
        }
        .container {
            text-align: center;
            padding: 60px;
            background: rgba(255,255,255,0.1);
            border-radius: 30px;
            backdrop-filter: blur(10px);
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        .logo { font-size: 28px; margin-bottom: 20px; opacity: 0.9; }
        h1 { font-size: 48px; margin-bottom: 30px; }
        .pairing-code {
            font-size: 96px;
            font-family: monospace;
            font-weight: bold;
            letter-spacing: 15px;
            background: white;
            color: #667eea;
            padding: 30px 60px;
            border-radius: 20px;
            margin: 40px 0;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        .hardware-id {
            font-size: 18px;
            opacity: 0.8;
            margin-bottom: 30px;
        }
        .instructions {
            font-size: 24px;
            opacity: 0.9;
            max-width: 500px;
            line-height: 1.6;
        }
        .status {
            margin-top: 40px;
            font-size: 18px;
            opacity: 0.7;
        }
        .status.paired {
            color: #4ade80;
            font-size: 36px;
            opacity: 1;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .waiting { animation: pulse 2s infinite; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">SKILLZ MEDIA</div>
        {% if status == 'paired' %}
            <h1>{{ hub_name or 'Hub Paired!' }}</h1>
            <div class="status paired">Connected to CMS</div>
        {% elif active and pairing_code %}
            <h1>Hub Pairing Required</h1>
            <div class="pairing-code">{{ pairing_code }}</div>
            <div class="hardware-id">Hardware ID: {{ hardware_id }}</div>
            <p class="instructions">
                Enter this code in the CMS admin panel to pair this hub with your account.
            </p>
            <div class="status waiting">Waiting for pairing...</div>
        {% elif error %}
            <h1>Pairing Error</h1>
            <p class="instructions" style="color: #fca5a5;">{{ error }}</p>
            <div class="status">Retrying...</div>
        {% else %}
            <h1>Initializing...</h1>
            <div class="status waiting">Please wait...</div>
        {% endif %}
    </div>
</body>
</html>
'''


def _check_and_start_pairing(app: Flask) -> None:
    """
    Check if hub is registered and start pairing flow if not.

    This function runs after app initialization to check registration
    status. If the hub is not registered, it starts a background thread
    that announces the hub to the CMS and polls for pairing completion.

    Args:
        app: Flask application instance
    """
    global _pairing_state

    def pairing_thread():
        """Background thread for pairing flow."""
        global _pairing_state

        with app.app_context():
            from models.hub_config import HubConfig
            from services.hub_pairing import HubPairingService, get_hardware_id

            hub_config = HubConfig.get_instance()

            if hub_config.is_registered:
                app.logger.info(f'Hub already registered: {hub_config.hub_id}')
                _pairing_state['status'] = 'paired'
                _pairing_state['hub_name'] = hub_config.hub_name
                _pairing_state['active'] = False
                return

            app.logger.info('Hub not registered - starting pairing flow')
            config = app.config['HUB_CONFIG']

            hardware_id = get_hardware_id()
            service = HubPairingService(cms_url=config.cms_url, hardware_id=hardware_id)

            _pairing_state['active'] = True
            _pairing_state['hardware_id'] = hardware_id

            # Announce to CMS
            result = service.announce()

            if result.get('status') == 'already_paired':
                # Store credentials
                HubConfig.update_registration(
                    hub_id=result.get('hub_id'),
                    hub_token=result.get('api_token'),
                    hub_code=result.get('hub_code'),
                    hub_name=result.get('store_name'),
                    network_id=result.get('network_id'),
                    status='active',
                )
                _pairing_state['status'] = 'paired'
                _pairing_state['hub_name'] = result.get('store_name')
                _pairing_state['active'] = False
                app.logger.info(f'Hub already paired as: {result.get("store_name")}')
                return

            if result.get('status') == 'error':
                _pairing_state['error'] = result.get('error')
                app.logger.error(f'Pairing announce failed: {result.get("error")}')
                return

            _pairing_state['pairing_code'] = service.pairing_code
            _pairing_state['status'] = 'pending'

            app.logger.info(f'Pairing code: {service.pairing_code}')
            print(f'\n{"="*60}')
            print(f'  PAIRING CODE: {service.pairing_code}')
            print(f'  Hardware ID:  {hardware_id}')
            print(f'  View at:      http://localhost:{config.port}/pairing')
            print(f'{"="*60}\n')

            # Poll for pairing completion
            def on_status(status):
                global _pairing_state
                if status.get('status') == 'expired':
                    _pairing_state['pairing_code'] = service.pairing_code
                    app.logger.info(f'New pairing code: {service.pairing_code}')

            result = service.wait_for_pairing(on_status=on_status)

            if result.get('status') == 'paired':
                HubConfig.update_registration(
                    hub_id=result.get('hub_id'),
                    hub_token=result.get('api_token'),
                    hub_code=result.get('hub_code'),
                    hub_name=result.get('store_name'),
                    network_id=result.get('network_id'),
                    status='active',
                )
                _pairing_state['status'] = 'paired'
                _pairing_state['hub_name'] = result.get('store_name')
                _pairing_state['active'] = False
                app.logger.info(f'Hub paired as: {result.get("store_name")}')
                print(f'\n{"="*60}')
                print(f'  HUB PAIRED SUCCESSFULLY!')
                print(f'  Store: {result.get("store_name")}')
                print(f'  Hub Code: {result.get("hub_code")}')
                print(f'{"="*60}\n')
            else:
                _pairing_state['error'] = result.get('error', 'Pairing failed')
                app.logger.error(f'Pairing failed: {result}')

    # Start pairing check in background thread
    thread = threading.Thread(target=pairing_thread, daemon=True)
    thread.start()


def _configure_logging(app: Flask, log_path: str) -> None:
    """
    Configure application logging.

    Args:
        app: Flask application instance
        log_path: Directory path for log files
    """
    # Set up file handler if log path is writable
    try:
        log_file = os.path.join(log_path, 'hub.log')
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        app.logger.addHandler(file_handler)
    except (OSError, PermissionError):
        # Log path not writable (dev environment), skip file logging
        pass

    # Set application log level
    app.logger.setLevel(logging.INFO)


def _register_blueprints(app: Flask) -> None:
    """
    Register API blueprints with the application.

    Blueprints are registered with /api/v1 prefix.
    Missing blueprints are silently skipped to allow incremental development.

    Args:
        app: Flask application instance
    """
    # Blueprint imports are inside function to handle missing modules gracefully
    # This allows the app to run before all blueprints are created

    try:
        # Dashboard route (no prefix - serves at /)
        from routes.dashboard import dashboard_bp
        app.register_blueprint(dashboard_bp)
        app.logger.info("Registered dashboard blueprint")

        from routes import screens_bp
        app.register_blueprint(screens_bp, url_prefix='/api/v1')
        app.logger.info('Registered screens blueprint')
    except ImportError:
        pass

    try:
        from routes import content_bp
        app.register_blueprint(content_bp, url_prefix='/api/v1')
        app.logger.info('Registered content blueprint')
    except ImportError:
        pass

    try:
        from routes import databases_bp
        app.register_blueprint(databases_bp, url_prefix='/api/v1')
        app.logger.info('Registered databases blueprint')
    except ImportError:
        pass

    try:
        from routes import alerts_bp
        app.register_blueprint(alerts_bp, url_prefix='/api/v1')
    except ImportError:
        pass

    try:
        from routes import cameras_bp
        app.register_blueprint(cameras_bp, url_prefix='/api/v1/cameras')
        app.logger.info("Registered cameras blueprint")
    except ImportError:
        pass

    try:
        from routes import pairing_bp
        app.register_blueprint(pairing_bp, url_prefix='/api/v1/pairing')
        app.logger.info("Registered pairing blueprint")
    except ImportError:
        pass

    try:
        from routes import devices_bp
        app.register_blueprint(devices_bp, url_prefix='/api/v1/devices')
        app.logger.info("Registered devices blueprint")
    except ImportError:
        pass


def _init_scheduler(app: Flask) -> None:
    """
    Initialize and start the background job scheduler.

    This function sets up APScheduler with all background jobs:
    - Content sync (every 5 minutes)
    - Alert forwarding (every 30 seconds)
    - Screen monitoring (every 30 seconds)
    - HQ heartbeat (every 60 seconds)

    The scheduler is only started if:
    - Not in testing mode (TESTING config is False)
    - Not disabled explicitly (SCHEDULER_ENABLED config is not False)

    Args:
        app: Flask application instance
    """
    # Skip scheduler in testing mode
    if app.config.get('TESTING', False):
        app.logger.info('Scheduler disabled in testing mode')
        return

    # Allow explicit disabling via config
    if app.config.get('SCHEDULER_ENABLED') is False:
        app.logger.info('Scheduler explicitly disabled')
        return

    try:
        from scheduler import init_scheduler, register_jobs, shutdown_scheduler

        # Get database URI for job store
        db_uri = app.config['SQLALCHEMY_DATABASE_URI']

        # Initialize scheduler (don't start yet)
        scheduler = init_scheduler(db_uri=db_uri, start=False)

        # Register all background jobs
        register_jobs(scheduler, app)

        # Start the scheduler
        scheduler.start()
        app.logger.info('Background scheduler started')

        # Register shutdown handler
        atexit.register(lambda: shutdown_scheduler(wait=False))

    except ImportError as e:
        app.logger.warning(f'Scheduler not available: {e}')
    except Exception as e:
        app.logger.error(f'Failed to initialize scheduler: {e}')


if __name__ == '__main__':
    # Development server
    application = create_app()
    config = application.config['HUB_CONFIG']
    application.run(
        host='0.0.0.0',
        port=config.port,
        debug=True
    )
