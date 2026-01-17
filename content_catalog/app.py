"""
Flask Application Factory for Content Catalog Service.

This module provides the create_app() factory function that creates and
configures the Flask application. It initializes:
- SQLAlchemy database connection (SQLite)
- Flask-JWT-Extended for authentication
- Flask-Mail for email notifications
- Blueprint registration (when available)
- Error handlers
- Logging configuration

Usage:
    # Development
    python app.py

    # Production
    gunicorn -w 4 -b 0.0.0.0:5003 'content_catalog.app:create_app()'
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from flask import Flask, jsonify
from flask_jwt_extended import JWTManager
from flask_mail import Mail

from content_catalog.config import get_config
from content_catalog.models import db


# Initialize extensions outside of create_app for import access
jwt = JWTManager()
mail = Mail()


# Default Super Admin credentials (should be changed on first login)
DEFAULT_SUPER_ADMIN_EMAIL = 'admin@skillzmedia.com'
DEFAULT_SUPER_ADMIN_PASSWORD = 'Admin123!'  # Must be changed on first login
DEFAULT_SUPER_ADMIN_NAME = 'System Administrator'


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

    # Configure JWT token expiration from config
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(
        seconds=app.config.get('JWT_ACCESS_TOKEN_EXPIRES', 3600)
    )
    app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(
        seconds=app.config.get('JWT_REFRESH_TOKEN_EXPIRES', 86400 * 7)
    )

    # Initialize extensions
    db.init_app(app)
    jwt.init_app(app)
    mail.init_app(app)

    # Create database tables
    with app.app_context():
        db.create_all()
        # Seed Super Admin user for initial system setup
        _seed_super_admin(app)

    # Configure logging
    _configure_logging(app)

    # Register blueprints
    _register_blueprints(app)

    # Register error handlers
    _register_error_handlers(app)

    # Register JWT error handlers
    _register_jwt_handlers(app)

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
            'service': 'content_catalog',
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })

    return app


def _seed_super_admin(app: Flask) -> None:
    """
    Seed the initial Super Admin user for system setup.

    Creates a default Super Admin user if no Super Admin exists in the database.
    This is required for initial system bootstrap - the first user needs to
    exist so they can create additional users via the invitation system.

    The default credentials should be changed immediately after first login.

    Args:
        app: Flask application instance.
    """
    from content_catalog.models.user import User
    from content_catalog.services.auth_service import AuthService

    # Check if any Super Admin already exists
    existing_super_admin = User.query.filter_by(
        role=User.ROLE_SUPER_ADMIN
    ).first()

    if existing_super_admin:
        app.logger.debug('Super Admin user already exists, skipping seed')
        return

    # Create the default Super Admin user
    try:
        password_hash = AuthService.hash_password(DEFAULT_SUPER_ADMIN_PASSWORD)

        super_admin = User(
            email=DEFAULT_SUPER_ADMIN_EMAIL,
            password_hash=password_hash,
            name=DEFAULT_SUPER_ADMIN_NAME,
            role=User.ROLE_SUPER_ADMIN,
            status=User.STATUS_ACTIVE,  # Active immediately, no approval needed
            organization_id=None  # Super Admin doesn't need an organization
        )

        db.session.add(super_admin)
        db.session.commit()

        app.logger.info(
            f'Created default Super Admin user: {DEFAULT_SUPER_ADMIN_EMAIL}'
        )
        app.logger.warning(
            'IMPORTANT: Change the default Super Admin password immediately!'
        )

    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Failed to create Super Admin user: {e}')


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
        log_file = os.path.join(str(log_dir), 'content_catalog.log')
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

    Blueprints are registered with appropriate URL prefixes:
    - /admin/api for admin authentication and operations
    - /api/v1 for general API routes
    - /admin and /partner for web portal routes

    Missing blueprints are silently skipped to allow incremental development.

    Args:
        app: Flask application instance.
    """
    # Blueprint imports are inside function to handle missing modules gracefully
    # This allows the app to run before all blueprints are created

    # Admin Authentication Blueprint
    try:
        from content_catalog.routes import auth_bp
        app.register_blueprint(auth_bp, url_prefix='/admin/api')
        app.logger.info('Registered auth blueprint at /admin/api')
    except ImportError:
        app.logger.debug('Auth blueprint not available yet')

    # User Management Blueprint
    try:
        from content_catalog.routes import users_bp
        app.register_blueprint(users_bp, url_prefix='/api/v1/users')
        app.logger.info('Registered users blueprint at /api/v1/users')
    except ImportError:
        app.logger.debug('Users blueprint not available yet')

    # Organization Management Blueprint
    try:
        from content_catalog.routes import organizations_bp
        app.register_blueprint(organizations_bp, url_prefix='/api/v1/organizations')
        app.logger.info('Registered organizations blueprint at /api/v1/organizations')
    except ImportError:
        app.logger.debug('Organizations blueprint not available yet')

    # Content Assets Blueprint
    try:
        from content_catalog.routes import assets_bp
        app.register_blueprint(assets_bp, url_prefix='/api/v1/assets')
        app.logger.info('Registered assets blueprint at /api/v1/assets')
    except ImportError:
        app.logger.debug('Assets blueprint not available yet')

    # Invitations Blueprint
    try:
        from content_catalog.routes import invitations_bp
        app.register_blueprint(invitations_bp, url_prefix='/api/v1/invitations')
        app.logger.info('Registered invitations blueprint at /api/v1/invitations')
    except ImportError:
        app.logger.debug('Invitations blueprint not available yet')

    # Approvals Blueprint
    try:
        from content_catalog.routes import approvals_bp
        app.register_blueprint(approvals_bp, url_prefix='/api/v1/approvals')
        app.logger.info('Registered approvals blueprint at /api/v1/approvals')
    except ImportError:
        app.logger.debug('Approvals blueprint not available yet')

    # Audit Logs Blueprint
    try:
        from content_catalog.routes import audit_bp
        app.register_blueprint(audit_bp, url_prefix='/admin/api/audit-logs')
        app.logger.info('Registered audit blueprint at /admin/api/audit-logs')
    except ImportError:
        app.logger.debug('Audit blueprint not available yet')

    # External Catalog API Blueprint
    try:
        from content_catalog.routes import catalog_bp
        app.register_blueprint(catalog_bp, url_prefix='/api/v1/catalog')
        app.logger.info('Registered catalog blueprint at /api/v1/catalog')
    except ImportError:
        app.logger.debug('Catalog blueprint not available yet')

    # Admin Portal Web Blueprint
    try:
        from content_catalog.routes import admin_web_bp
        app.register_blueprint(admin_web_bp, url_prefix='/admin')
        app.logger.info('Registered admin web blueprint at /admin')
    except ImportError:
        app.logger.debug('Admin web blueprint not available yet')

    # Partner Portal Web Blueprint
    try:
        from content_catalog.routes import partner_web_bp
        app.register_blueprint(partner_web_bp, url_prefix='/partner')
        app.logger.info('Registered partner web blueprint at /partner')
    except ImportError:
        app.logger.debug('Partner web blueprint not available yet')


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

    @app.errorhandler(405)
    def method_not_allowed(error):
        return jsonify({
            'status': 'error',
            'error': 'Method Not Allowed',
            'message': 'The method is not allowed for this resource'
        }), 405

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify({
            'status': 'error',
            'error': 'File Too Large',
            'message': 'File size exceeds the maximum allowed limit'
        }), 413

    @app.errorhandler(422)
    def unprocessable_entity(error):
        return jsonify({
            'status': 'error',
            'error': 'Unprocessable Entity',
            'message': str(error.description) if hasattr(error, 'description') else 'Request could not be processed'
        }), 422

    @app.errorhandler(500)
    def internal_server_error(error):
        return jsonify({
            'status': 'error',
            'error': 'Internal Server Error',
            'message': 'An unexpected error occurred'
        }), 500


def _register_jwt_handlers(app: Flask) -> None:
    """
    Register JWT-specific error handlers.

    Args:
        app: Flask application instance.
    """
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({
            'status': 'error',
            'error': 'Token Expired',
            'message': 'The access token has expired'
        }), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(error_string):
        return jsonify({
            'status': 'error',
            'error': 'Invalid Token',
            'message': 'The access token is invalid'
        }), 401

    @jwt.unauthorized_loader
    def missing_token_callback(error_string):
        return jsonify({
            'status': 'error',
            'error': 'Unauthorized',
            'message': 'Access token is missing'
        }), 401

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        return jsonify({
            'status': 'error',
            'error': 'Token Revoked',
            'message': 'The access token has been revoked'
        }), 401


if __name__ == '__main__':
    # Development server
    application = create_app()
    config = application.config['CONFIG_CLASS']
    application.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG
    )
