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

from flask import Flask, jsonify, send_from_directory
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

# Test user credentials for development/testing
TEST_USERS = [
    {
        'email': 'manager@skillzmedia.com',
        'password': 'Manager123!',
        'name': 'Content Manager',
        'role': 'content_manager',
        'org_name': 'Skillz Media',
        'org_type': 'SKILLZ',
        'legacy_org_type': 'internal'
    },
    {
        'email': 'retailer@testretailer.com',
        'password': 'Retailer123!',
        'name': 'Test Retailer User',
        'role': 'partner',
        'org_name': 'Test Retailer',
        'org_type': 'RETAILER',
        'legacy_org_type': 'partner'
    },
    {
        'email': 'brand@testbrand.com',
        'password': 'Brand123!',
        'name': 'Test Brand User',
        'role': 'partner',
        'org_name': 'Test Brand',
        'org_type': 'BRAND',
        'legacy_org_type': 'advertiser'
    }
]


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
        # Seed default catalog for folder/category support
        _seed_default_catalog(app)
        # Seed test data (organizations and users) for development/testing
        # Skip in production unless explicitly enabled
        seed_test_data = os.environ.get('SEED_TEST_DATA', 'true').lower() in ('true', '1', 'yes')
        if seed_test_data:
            _seed_test_data(app)
        else:
            app.logger.info('Skipping test data seeding (SEED_TEST_DATA not enabled)')

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

    # Serve uploaded files
    @app.route('/uploads/<path:filename>')
    def serve_upload(filename):
        """Serve uploaded media files.

        Args:
            filename: The filename to serve from the uploads directory.

        Returns:
            The file from the uploads directory.
        """
        uploads_path = app.config.get('UPLOADS_PATH', os.path.join(app.root_path, 'uploads'))
        return send_from_directory(str(uploads_path), filename)

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


def _seed_default_catalog(app: Flask) -> None:
    """
    Seed a default catalog so folders/categories can be created.

    Categories require a parent catalog. This creates a single
    'Content Library' catalog if none exists.
    """
    from content_catalog.models.catalog import Catalog

    existing = Catalog.query.first()
    if existing:
        app.logger.debug('Default catalog already exists, skipping seed')
        return

    try:
        catalog = Catalog(
            name='Content Library',
            description='Default content library for organizing assets into folders',
            is_active=True,
            is_internal_only=False
        )
        db.session.add(catalog)
        db.session.commit()
        app.logger.info(f'Created default catalog: Content Library (id={catalog.id})')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Failed to create default catalog: {e}')


def _seed_test_data(app: Flask) -> None:
    """
    Seed test organizations and users for development/testing.

    Creates test organizations (SKILLZ, RETAILER, BRAND) and corresponding
    test users (manager, retailer, brand) to support development and testing
    of the multi-org-type permission system.

    This function is idempotent - it will not create duplicates if run multiple times.

    Args:
        app: Flask application instance.
    """
    from content_catalog.models.organization import Organization
    from content_catalog.models.user import User
    from content_catalog.services.auth_service import AuthService

    # Track created organizations by name for user assignment
    org_map = {}

    for user_config in TEST_USERS:
        org_name = user_config['org_name']
        org_type = user_config['org_type']
        legacy_org_type = user_config['legacy_org_type']

        # Check if organization exists, create if not
        if org_name not in org_map:
            org = Organization.query.filter_by(name=org_name).first()
            if not org:
                try:
                    org = Organization(
                        name=org_name,
                        type=legacy_org_type,
                        org_type=org_type,
                        status='active',
                        contact_email=f'contact@{org_name.lower().replace(" ", "")}.com'
                    )
                    db.session.add(org)
                    db.session.flush()  # Get the ID
                    app.logger.info(f'Created test organization: {org_name} ({org_type})')
                except Exception as e:
                    app.logger.error(f'Failed to create organization {org_name}: {e}')
                    continue
            org_map[org_name] = org

        # Check if user exists, create if not
        existing_user = User.query.filter_by(email=user_config['email']).first()
        if existing_user:
            app.logger.debug(f"Test user {user_config['email']} already exists, skipping")
            continue

        try:
            password_hash = AuthService.hash_password(user_config['password'])
            org = org_map.get(org_name)

            user = User(
                email=user_config['email'],
                password_hash=password_hash,
                name=user_config['name'],
                role=user_config['role'],
                status=User.STATUS_ACTIVE,
                organization_id=org.id if org else None
            )

            db.session.add(user)
            app.logger.info(f"Created test user: {user_config['email']} ({user_config['role']})")

        except Exception as e:
            app.logger.error(f"Failed to create test user {user_config['email']}: {e}")

    # Commit all changes
    try:
        db.session.commit()
        app.logger.info('Test data seeding completed successfully')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Failed to commit test data: {e}')


def _configure_logging(app: Flask) -> None:
    """
    Configure application logging.

    In production (Railway), logs to stdout for container logging.
    In development, optionally logs to file.

    Args:
        app: Flask application instance.
    """
    import sys

    # Set up log format
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Always log to stdout (required for Railway/container environments)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(log_format)
    app.logger.addHandler(stream_handler)

    # In development, also try to log to file
    if app.config.get('DEBUG', False):
        log_dir = app.config.get('BASE_DIR', os.getcwd())
        if hasattr(log_dir, '__truediv__'):  # Path object
            log_dir = log_dir / 'logs'
        else:
            log_dir = os.path.join(log_dir, 'logs')

        try:
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(str(log_dir), 'content_catalog.log')
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(log_format)
            app.logger.addHandler(file_handler)
        except (OSError, PermissionError):
            # Log path not writable, skip file logging
            pass

    # Set application log level
    log_level = logging.DEBUG if app.config.get('DEBUG', False) else logging.INFO
    app.logger.setLevel(log_level)


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

    # Approved Assets Blueprint (CMS Integration)
    try:
        from content_catalog.routes import approved_assets_bp
        app.register_blueprint(approved_assets_bp, url_prefix='/api/v1/approved-assets')
        app.logger.info('Registered approved_assets blueprint at /api/v1/approved-assets')
    except ImportError:
        app.logger.debug('Approved assets blueprint not available yet')

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

    # Audit Logs Blueprint (legacy endpoint)
    try:
        from content_catalog.routes import audit_bp
        app.register_blueprint(audit_bp, url_prefix='/admin/api/audit-logs')
        app.logger.info('Registered audit blueprint at /admin/api/audit-logs')
    except ImportError:
        app.logger.debug('Audit blueprint not available yet')

    # Audit Admin Blueprint (spec-required endpoint at /admin/api/audit)
    try:
        from content_catalog.routes import audit_admin_bp
        app.register_blueprint(audit_admin_bp, url_prefix='/admin/api')
        app.logger.info('Registered audit_admin blueprint at /admin/api')
    except ImportError:
        app.logger.debug('Audit admin blueprint not available yet')

    # External Catalog API Blueprint
    try:
        from content_catalog.routes import catalog_bp
        app.register_blueprint(catalog_bp, url_prefix='/api/v1/catalog')
        app.logger.info('Registered catalog blueprint at /api/v1/catalog')
    except ImportError:
        app.logger.debug('Catalog blueprint not available yet')

    # Catalogs and Categories Blueprint
    try:
        from content_catalog.routes import catalogs_bp
        app.register_blueprint(catalogs_bp, url_prefix='/api/v1/catalogs')
        app.logger.info('Registered catalogs blueprint at /api/v1/catalogs')
    except ImportError:
        app.logger.debug('Catalogs blueprint not available yet')

    # Tenants Blueprint
    try:
        from content_catalog.routes import tenants_bp
        app.register_blueprint(tenants_bp, url_prefix='/api/v1/tenants')
        app.logger.info('Registered tenants blueprint at /api/v1/tenants')
    except ImportError:
        app.logger.debug('Tenants blueprint not available yet')

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

    # Magic Link Approval Blueprint (no authentication required)
    try:
        from content_catalog.routes import magic_link_bp
        app.register_blueprint(magic_link_bp)
        app.logger.info('Registered magic_link blueprint at /')
    except ImportError:
        app.logger.debug('Magic link blueprint not available yet')


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
