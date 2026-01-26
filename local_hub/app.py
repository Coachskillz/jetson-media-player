"""
Flask Application Factory for Local Hub Service.

This module provides the create_app() factory function that creates and
configures the Flask application. It initializes:
- SQLAlchemy database connection
- Blueprint registration (when available)
- Background job scheduler (APScheduler)
- Logging configuration

Usage:
    # Development
    python app.py

    # Production
    gunicorn -w 4 -b 0.0.0.0:5000 'app:create_app()'
"""

import atexit
import logging
import os
from typing import Optional

from flask import Flask

from config import load_config
from models import db


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

    return app


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
