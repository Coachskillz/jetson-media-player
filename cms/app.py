"""
Flask Application Factory for CMS Service.

This module provides the create_app() factory function that creates and
configures the Flask application. It initializes:
- SQLAlchemy database connection (SQLite)
- Blueprint registration (when available)
- Error handlers
- Logging configuration
- Default user seeding (Super Admin and Admin)

Usage:
    # Development
    python app.py

    # Production
    gunicorn -w 4 -b 0.0.0.0:5002 'cms.app:create_app()'
"""

import logging
import os
import secrets
from datetime import datetime
from typing import Optional

from flask import Flask, jsonify
from flask_migrate import Migrate

from cms.config import get_config
from cms.models import db

# Global migrate instance
migrate = Migrate()


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
    migrate.init_app(app, db)

    # Initialize Flask-Login
    from flask_login import LoginManager
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "web.login_page"
    
    @login_manager.user_loader
    def load_user(user_id):
        from cms.models.user import User
        return User.query.get(user_id)

    # Create database tables and seed default users
    with app.app_context():
        db.create_all()
        _seed_default_users(app)

    # Configure logging
    _configure_logging(app)

    # Register blueprints
    _register_blueprints(app)

    # Register error handlers
    _register_error_handlers(app)

    # Register template context processor for current_user
    _register_context_processors(app)

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


def _seed_default_users(app: Flask) -> None:
    """
    Seed default user accounts on first run.

    Creates two default accounts if they don't exist:
    - Matt Skillman (mattskillz@skillzmedia.com) - Super Admin
    - Susan Croom (Susan.croom@skillzmedia.com) - Admin

    Both accounts are created with:
    - must_change_password=True (force password change on first login)
    - status='active' (ready to use immediately)
    - Randomly generated temporary passwords (logged at INFO level)

    Args:
        app: Flask application instance.
    """
    try:
        from cms.models import User
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('User model not available yet, skipping user seeding')
        return

    # Default accounts to create
    default_users = [
        {
            'email': 'mattskillz@skillzmedia.com',
            'name': 'Matt Skillman',
            'role': 'super_admin',
            'phone': None,
        },
        {
            'email': 'Susan.croom@skillzmedia.com',
            'name': 'Susan Croom',
            'role': 'admin',
            'phone': None,
        },
    ]

    for user_data in default_users:
        # Check if user already exists
        existing_user = User.query.filter_by(email=user_data['email']).first()
        if existing_user:
            app.logger.debug(f"User {user_data['email']} already exists, skipping")
            continue

        # Generate a secure temporary password
        temp_password = secrets.token_urlsafe(16)

        # Create the user
        user = User(
            email=user_data['email'],
            name=user_data['name'],
            role=user_data['role'],
            phone=user_data['phone'],
            status='active',
            must_change_password=True,
        )
        user.set_password(temp_password)

        db.session.add(user)
        app.logger.info(
            f"Created default {user_data['role']} user: {user_data['email']} "
            f"(temporary password: {temp_password})"
        )

    # Commit all new users
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to seed default users: {e}")


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
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('Devices blueprint not available yet')

    try:
        from cms.routes import hubs_bp
        app.register_blueprint(hubs_bp, url_prefix='/api/v1/hubs')
        app.logger.info('Registered hubs blueprint at /api/v1/hubs')
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('Hubs blueprint not available yet')

    try:
        from cms.routes import content_bp
        app.register_blueprint(content_bp, url_prefix='/api/v1/content')
        app.logger.info('Registered content blueprint at /api/v1/content')
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('Content blueprint not available yet')

    # Thea Content Catalog proxy blueprint
    try:
        from cms.routes import thea_bp
        app.register_blueprint(thea_bp, url_prefix='/api/v1/thea')
        app.logger.info('Registered thea blueprint at /api/v1/thea')
    except ImportError:
        app.logger.debug('Thea blueprint not available yet')

    # Content Catalog integration blueprint
    try:
        from cms.routes import catalog_bp
        app.register_blueprint(catalog_bp, url_prefix='/api/v1/catalog')
        app.logger.info('Registered catalog blueprint at /api/v1/catalog')
    except ImportError:
        app.logger.debug('Catalog blueprint not available yet')

    try:
        from cms.routes import playlists_bp
        app.register_blueprint(playlists_bp, url_prefix='/api/v1/playlists')
        app.logger.info('Registered playlists blueprint at /api/v1/playlists')
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('Playlists blueprint not available yet')

    try:
        from cms.routes import networks_bp
        app.register_blueprint(networks_bp, url_prefix='/api/v1/networks')
        app.logger.info('Registered networks blueprint at /api/v1/networks')
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('Networks blueprint not available yet')

    try:
        from cms.routes import layouts_bp
        app.register_blueprint(layouts_bp, url_prefix='/api/v1/layouts')
        app.logger.info('Registered layouts blueprint at /api/v1/layouts')
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('Layouts blueprint not available yet')

    # Authentication Blueprint - login, logout, password management
    try:
        from cms.routes import auth_bp
        app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
        app.logger.info('Registered auth blueprint at /api/v1/auth')
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('Auth blueprint not available yet')

    # Users Blueprint - user management (CRUD, approve, suspend, deactivate)
    try:
        from cms.routes import users_bp
        app.register_blueprint(users_bp, url_prefix='/api/v1/users')
        app.logger.info('Registered users blueprint at /api/v1/users')
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('Users blueprint not available yet')

    # Invitations Blueprint - user invitation system
    try:
        from cms.routes import invitations_bp
        app.register_blueprint(invitations_bp, url_prefix='/api/v1/invitations')
        app.logger.info('Registered invitations blueprint at /api/v1/invitations')
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('Invitations blueprint not available yet')

    # Sessions Blueprint - session management (list, revoke)
    try:
        from cms.routes import sessions_bp
        app.register_blueprint(sessions_bp, url_prefix='/api/v1/sessions')
        app.logger.info('Registered sessions blueprint at /api/v1/sessions')
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('Sessions blueprint not available yet')

    # Audit Blueprint - audit log viewing and export
    try:
        from cms.routes import audit_bp
        app.register_blueprint(audit_bp, url_prefix='/api/v1/audit-logs')
        app.logger.info('Registered audit blueprint at /api/v1/audit-logs')
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('Audit blueprint not available yet')

    # Web UI Blueprints - registered at root for page rendering
    try:
        from cms.routes import web_bp
        app.register_blueprint(web_bp)
        app.logger.info('Registered web blueprint at /')
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")
        app.logger.debug('Web blueprint not available yet')

    try:
        from cms.routes import layouts_web_bp
        app.register_blueprint(layouts_web_bp)
        app.logger.info('Registered layouts web blueprint at /')
    except ImportError:
        app.logger.debug("Layouts web blueprint not available yet")

    # NCMEC Alert routes
    try:
        from cms.routes.ncmec import ncmec_bp, ncmec_api_bp
        app.register_blueprint(ncmec_bp)
        app.register_blueprint(ncmec_api_bp)
        app.logger.info("Registered NCMEC blueprints")
    except ImportError as e:
        app.logger.warning(f"Could not import NCMEC routes: {e}")
    # Locations routes
    try:
        from cms.routes.locations import locations_bp
        app.register_blueprint(locations_bp, url_prefix='/api/locations')
        app.logger.info('Registered locations blueprint at /api/locations')
    except ImportError:
        app.logger.debug("Locations blueprint not available yet")



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


def _register_context_processors(app: Flask) -> None:
    """
    Register template context processors.

    Context processors inject variables into all templates automatically.
    This is used to make the current_user available in all templates.

    Args:
        app: Flask application instance.
    """
    @app.context_processor
    def inject_current_user():
        """
        Inject current_user into all templates.

        Retrieves the current user from Flask's g object if available.
        This is set by the @login_required decorator in auth utils.

        Returns:
            Dict with current_user key (may be None if not authenticated)
        """
        from flask import g
        current_user = getattr(g, 'current_user', None)
        return {'current_user': current_user, 'user': current_user}


if __name__ == '__main__':
    # Development server
    application = create_app()
    config = application.config['CONFIG_CLASS']
    application.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG
    )
