"""
Central Hub - Flask Application Factory

Creates and configures the Flask application with database, Celery,
and blueprint registration for NCMEC, Loyalty, Alerts, and Notifications.
"""

from datetime import datetime

from flask import Flask, jsonify

from central_hub.config import get_config
from central_hub.extensions import db, migrate, init_celery


def create_app(config_name=None):
    """Create and configure the Flask application.

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

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    init_celery(app)

    # Import models to register them with SQLAlchemy
    # This ensures Flask-Migrate can detect model changes
    with app.app_context():
        from central_hub import models  # noqa: F401

    # Register blueprints
    register_blueprints(app)

    # Register error handlers
    register_error_handlers(app)

    return app


def register_blueprints(app):
    """Register all route blueprints with the Flask application.

    All blueprints are registered under the /api/v1 prefix.
    Registration order: NCMEC, Loyalty, Alerts, Notifications.

    Args:
        app: Flask application instance.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Import all blueprints from routes package
    from central_hub.routes import ncmec_bp, loyalty_bp, alerts_bp, notifications_bp

    # Register NCMEC blueprint - handles missing children database management
    # Routes: /api/v1/ncmec/records, /api/v1/ncmec/import, /api/v1/ncmec/compile, etc.
    app.register_blueprint(ncmec_bp, url_prefix='/api/v1/ncmec')
    logger.info("Registered NCMEC blueprint at /api/v1/ncmec")

    # Register Loyalty blueprint - handles per-network member enrollment
    # Routes: /api/v1/networks/<id>/loyalty/*, /api/v1/loyalty/members/*
    app.register_blueprint(loyalty_bp, url_prefix='/api/v1')
    logger.info("Registered Loyalty blueprint at /api/v1")

    # Register Alerts blueprint - handles alert ingestion and review workflow
    # Routes: /api/v1/alerts, /api/v1/alerts/<id>, /api/v1/alerts/<id>/review, etc.
    app.register_blueprint(alerts_bp, url_prefix='/api/v1/alerts')
    logger.info("Registered Alerts blueprint at /api/v1/alerts")

    # Register Notifications blueprint - handles notification settings management
    # Routes: /api/v1/notification-settings, /api/v1/notifications/test, etc.
    app.register_blueprint(notifications_bp, url_prefix='/api/v1')
    logger.info("Registered Notifications blueprint at /api/v1")

    # Register health check endpoints
    @app.route('/api/health')
    @app.route('/api/v1/health')
    def health_check():
        """Health check endpoint for monitoring.

        Available at both /api/health and /api/v1/health for compatibility.
        """
        return jsonify({
            "status": "ok",
            "service": "central_hub",
            "timestamp": datetime.now().isoformat()
        })

    @app.route('/api/test')
    def test_api():
        """Test endpoint to verify API is working."""
        return jsonify({
            "status": "ok",
            "message": "Central Hub API is working!",
            "timestamp": datetime.now().isoformat()
        })


def register_error_handlers(app):
    """Register error handlers for common HTTP errors.

    Args:
        app: Flask application instance.
    """
    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({
            "status": "error",
            "error": "Bad Request",
            "message": str(error.description) if hasattr(error, 'description') else "Invalid request"
        }), 400

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            "status": "error",
            "error": "Not Found",
            "message": "The requested resource was not found"
        }), 404

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify({
            "status": "error",
            "error": "File Too Large",
            "message": "File size exceeds the 10MB limit"
        }), 413

    @app.errorhandler(500)
    def internal_server_error(error):
        return jsonify({
            "status": "error",
            "error": "Internal Server Error",
            "message": "An unexpected error occurred"
        }), 500


