"""
Flask Application Factory for CMS Service.

This module provides the create_app() factory function that creates and
configures the Flask application. It initializes:
- SQLAlchemy database connection (SQLite)
- Blueprint registration (when available)
- Error handlers
- Logging configuration

Usage:
    # Development
    python app.py

    # Production
    gunicorn -w 4 -b 0.0.0.0:5002 'cms.app:create_app()'
"""

import logging
import os
from datetime import datetime
from typing import Optional

from flask import Flask, jsonify

from cms.config import get_config
from cms.models import db


def create_app(config_name: Optional[str] = None) -> Flask:
    """
    Create and configure the Flask application.

    Args:
        config_name: Configuration environment name ('development', 'testing', 'production').
                    If None, reads from FLASK_ENV environment variable.

    Returns:
        Configured Flask application instance.
    """
    app = Flask(__name__)

    # Load configuration
    config_class = get_config(config_name)
    app.config.from_object(config_class)
    config_class.init_app(app)

    # Store config class for reference
    app.config['CONFIG_CLASS'] = config_class

    # Initialize extensions
    db.init_app(app)

    # Create database tables
    with app.app_context():
        db.create_all()

    # Configure logging
    _configure_logging(app)

    # Register blueprints
    _register_blueprints(app)

    # Register error handlers
    _register_error_handlers(app)

    # Register health check endpoint
    @app.route('/health')
    @app.route('/api/health')
    @app.route('/api/v1/health')
    def health_check():
        """Health check endpoint for monitoring.

        Available at /health, /api/health, and /api/v1/health for compatibility.
        """
        return jsonify({
            'status': 'healthy',
            'service': 'cms',
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })

    return app


def _configure_logging(app: Flask) -> None:
    """
    Configure application logging.

    Args:
        app: Flask application instance.
    """
    # Get log directory from config
    log_dir = app.config.get('BASE_DIR', os.getcwd())
    if hasattr(log_dir, '__truediv__'):  # Path object
        log_dir = log_dir / 'logs'
    else:
        log_dir = os.path.join(log_dir, 'logs')

    # Set up file handler if log path is writable
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(str(log_dir), 'cms.log')
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

    Blueprints are registered with /api/v1 prefix for API routes.
    Web routes are registered at root.
    Missing blueprints are silently skipped to allow incremental development.

    Args:
        app: Flask application instance.
    """
    # Blueprint imports are inside function to handle missing modules gracefully
    # This allows the app to run before all blueprints are created

    # API Blueprints - registered with /api/v1 prefix
    try:
        from cms.routes import devices_bp
        app.register_blueprint(devices_bp, url_prefix='/api/v1/devices')
        app.logger.info('Registered devices blueprint at /api/v1/devices')
    except ImportError:
        app.logger.debug('Devices blueprint not available yet')

    try:
        from cms.routes import hubs_bp
        app.register_blueprint(hubs_bp, url_prefix='/api/v1/hubs')
        app.logger.info('Registered hubs blueprint at /api/v1/hubs')
    except ImportError:
        app.logger.debug('Hubs blueprint not available yet')

    try:
        from cms.routes import content_bp
        app.register_blueprint(content_bp, url_prefix='/api/v1/content')
        app.logger.info('Registered content blueprint at /api/v1/content')
    except ImportError:
        app.logger.debug('Content blueprint not available yet')

    try:
        from cms.routes import playlists_bp
        app.register_blueprint(playlists_bp, url_prefix='/api/v1/playlists')
        app.logger.info('Registered playlists blueprint at /api/v1/playlists')
    except ImportError:
        app.logger.debug('Playlists blueprint not available yet')

    try:
        from cms.routes import networks_bp
        app.register_blueprint(networks_bp, url_prefix='/api/v1/networks')
        app.logger.info('Registered networks blueprint at /api/v1/networks')
    except ImportError:
        app.logger.debug('Networks blueprint not available yet')

    # Web UI Blueprint - registered at root for page rendering
    try:
        from cms.routes import web_bp
        app.register_blueprint(web_bp)
        app.logger.info('Registered web blueprint at /')
    except ImportError:
        app.logger.debug('Web blueprint not available yet')


def _register_error_handlers(app: Flask) -> None:
    """
    Register error handlers for common HTTP errors.

    Args:
        app: Flask application instance.
    """
    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({
            'status': 'error',
            'error': 'Bad Request',
            'message': str(error.description) if hasattr(error, 'description') else 'Invalid request'
        }), 400

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            'status': 'error',
            'error': 'Not Found',
            'message': 'The requested resource was not found'
        }), 404

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify({
            'status': 'error',
            'error': 'File Too Large',
            'message': 'File size exceeds the maximum allowed limit'
        }), 413

    @app.errorhandler(500)
    def internal_server_error(error):
        return jsonify({
            'status': 'error',
            'error': 'Internal Server Error',
            'message': 'An unexpected error occurred'
        }), 500


if __name__ == '__main__':
    # Development server
    application = create_app()
    config = application.config['CONFIG_CLASS']
    application.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG
    )
