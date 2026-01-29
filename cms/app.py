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

# Optional security extensions (graceful fallback if not installed)
try:
    from flask_talisman import Talisman
    TALISMAN_AVAILABLE = True
except ImportError:
    TALISMAN_AVAILABLE = False

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    LIMITER_AVAILABLE = True
except ImportError:
    LIMITER_AVAILABLE = False

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

    # Initialize security extensions in production
    _init_security(app, config_class)

    # Initialize Flask-Login
    from flask_login import LoginManager
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "web.login"
    
    @login_manager.user_loader
    def load_user(user_id):
        from cms.models.user import User
        return User.query.get(user_id)

    # Create database tables and seed default data
    with app.app_context():
        db.create_all()
        _run_migrations(app)
        _seed_default_users(app)
        _seed_demo_content(app)

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


def _init_security(app: Flask, config_class) -> None:
    """
    Initialize security extensions for the application.

    In production, enables:
    - Flask-Talisman for security headers (HSTS, CSP, X-Frame-Options, etc.)
    - Flask-Limiter for rate limiting API endpoints

    Args:
        app: Flask application instance.
        config_class: Configuration class being used.
    """
    is_production = config_class.__name__ == 'ProductionConfig'

    # Initialize Talisman for security headers (production only)
    if TALISMAN_AVAILABLE and is_production:
        Talisman(
            app,
            force_https=True,
            strict_transport_security=True,
            strict_transport_security_max_age=31536000,  # 1 year
            content_security_policy={
                'default-src': "'self'",
                'script-src': ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
                'style-src': ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
                'font-src': ["'self'", "https://fonts.gstatic.com"],
                'img-src': ["'self'", "data:", "https:"],
            },
            frame_options='DENY',
            content_type_options=True,
            xss_protection=True,
        )
        app.logger.info('Security headers enabled (Flask-Talisman)')
    elif not TALISMAN_AVAILABLE:
        app.logger.warning('Flask-Talisman not installed, security headers disabled')

    # Initialize rate limiter
    if LIMITER_AVAILABLE:
        limiter = Limiter(
            key_func=get_remote_address,
            app=app,
            default_limits=["200 per day", "50 per hour"],
            storage_uri="memory://",
        )
        # Store limiter on app for route-specific limits
        app.limiter = limiter
        app.logger.info('Rate limiting enabled (Flask-Limiter)')
    else:
        app.logger.warning('Flask-Limiter not installed, rate limiting disabled')


def _run_migrations(app: Flask) -> None:
    """Run lightweight schema migrations to add missing columns."""
    from sqlalchemy import text, inspect
    inspector = inspect(db.engine)

    if 'playlist_items' not in inspector.get_table_names():
        return

    columns = [c['name'] for c in inspector.get_columns('playlist_items')]
    if 'synced_content_id' in columns:
        return  # Already migrated

    app.logger.info('Migration: Rebuilding playlist_items table for synced content support')
    db_url = str(db.engine.url)
    is_postgres = 'postgresql' in db_url or 'postgres' in db_url

    try:
        if is_postgres:
            db.session.execute(text(
                'ALTER TABLE playlist_items ADD COLUMN synced_content_id VARCHAR(36)'
            ))
            db.session.execute(text(
                'ALTER TABLE playlist_items ALTER COLUMN content_id DROP NOT NULL'
            ))
            db.session.commit()
        else:
            # SQLite: must recreate table to change NOT NULL constraint
            db.session.execute(text(
                'CREATE TABLE playlist_items_new ('
                '  id VARCHAR(36) PRIMARY KEY,'
                '  playlist_id VARCHAR(36) NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,'
                '  content_id VARCHAR(36) REFERENCES content(id) ON DELETE CASCADE,'
                '  synced_content_id VARCHAR(36) REFERENCES synced_content(id) ON DELETE CASCADE,'
                '  position INTEGER NOT NULL DEFAULT 0,'
                '  duration_override INTEGER,'
                '  created_at DATETIME'
                ')'
            ))
            db.session.execute(text(
                'INSERT INTO playlist_items_new (id, playlist_id, content_id, position, duration_override, created_at) '
                'SELECT id, playlist_id, content_id, position, duration_override, created_at FROM playlist_items'
            ))
            db.session.execute(text('DROP TABLE playlist_items'))
            db.session.execute(text('ALTER TABLE playlist_items_new RENAME TO playlist_items'))
            db.session.execute(text('CREATE INDEX ix_playlist_items_playlist_id ON playlist_items(playlist_id)'))
            db.session.execute(text('CREATE INDEX ix_playlist_items_content_id ON playlist_items(content_id)'))
            db.session.execute(text('CREATE INDEX ix_playlist_items_synced_content_id ON playlist_items(synced_content_id)'))
            db.session.commit()

        app.logger.info('Migration: playlist_items table updated successfully')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Migration: playlist_items rebuild failed: {e}')


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


def _seed_demo_content(app: Flask) -> None:
    """
    Seed demo networks, content, folder, and playlist on first run.

    Copies sample media from the media/ directory into cms/uploads/
    and creates corresponding database records. Idempotent.
    """
    import shutil
    import uuid as _uuid
    from pathlib import Path
    from datetime import timezone

    try:
        from cms.models import Content, Network
        from cms.models.playlist import Playlist, PlaylistItem
        from cms.models.folder import Folder
        from cms.models.device import Device
    except ImportError:
        app.logger.debug('Models not available yet, skipping demo content seeding')
        return

    # Media files with metadata
    media_items = [
        {'filename': 'bus_ad._4.mp4', 'title': 'Bus Ad', 'duration': 22, 'size': 7101354, 'mime': 'video/mp4'},
        {'filename': '8517AleveAleveArthritisPiggybackConnectedTVC15s16915MIAV1096000HInnovid.MP4', 'title': 'Aleve Arthritis Ad', 'duration': 15, 'size': 7999657, 'mime': 'video/mp4'},
        {'filename': 'social_coachskillz_the_word_look_in_a_dynamic_font_with_eyeballs_in__a79139cb-e492-4549-ba6c-6a5db23cf569_2.mp4', 'title': 'Coach Skillz Promo', 'duration': 5, 'size': 5704195, 'mime': 'video/mp4'},
    ]

    networks_data = [
        {'name': 'High Octane Network', 'slug': 'high-octane'},
        {'name': 'On The Wave TV', 'slug': 'on-the-wave'},
    ]

    # --- Networks ---
    network_ids = {}
    for nd in networks_data:
        existing = Network.query.filter_by(slug=nd['slug']).first()
        if existing:
            network_ids[nd['slug']] = existing.id
        else:
            net = Network(id=str(_uuid.uuid4()), name=nd['name'], slug=nd['slug'])
            db.session.add(net)
            db.session.flush()
            network_ids[nd['slug']] = net.id
            app.logger.info(f"Seeded network: {nd['name']}")

    ho_id = network_ids.get('high-octane')

    # --- Folder ---
    folder = Folder.query.filter_by(name='Ads').first()
    if not folder:
        folder = Folder(id=str(_uuid.uuid4()), name='Ads', icon='🎬', network_id=ho_id)
        db.session.add(folder)
        db.session.flush()
        app.logger.info("Seeded folder: Ads")

    # --- Content ---
    # Resolve paths
    base_dir = Path(app.config.get('BASE_DIR', os.path.dirname(os.path.abspath(__file__))))
    media_dir = base_dir.parent / 'media'
    uploads_dir = Path(app.config.get('UPLOADS_PATH', base_dir / 'uploads'))
    uploads_dir.mkdir(parents=True, exist_ok=True)

    content_ids = []
    for item in media_items:
        existing = Content.query.filter_by(original_name=item['filename']).first()
        if existing:
            content_ids.append(existing.id)
            continue

        # Copy media file if available
        src = media_dir / item['filename']
        dest = uploads_dir / item['filename']
        if src.exists() and not dest.exists():
            shutil.copy2(str(src), str(dest))
            app.logger.info(f"Copied media: {item['filename']}")

        content = Content(
            id=str(_uuid.uuid4()),
            filename=item['filename'],
            original_name=item['filename'],
            mime_type=item['mime'],
            file_size=item['size'],
            duration=item['duration'],
            status='approved',
            network_id=ho_id,
            folder_id=folder.id,
            source='upload',
        )
        db.session.add(content)
        db.session.flush()
        content_ids.append(content.id)
        app.logger.info(f"Seeded content: {item['title']} ({item['duration']}s)")

    # --- Playlist ---
    if not Playlist.query.filter_by(name='Demo Playlist').first():
        playlist = Playlist(
            id=str(_uuid.uuid4()),
            name='Demo Playlist',
            description='Sample playlist with 3 video ads',
            network_id=ho_id,
            trigger_type='manual',
            loop_mode='continuous',
            priority='normal',
            is_active=True,
            sync_status='draft',
            version=1,
        )
        db.session.add(playlist)
        db.session.flush()

        for pos, cid in enumerate(content_ids):
            pi = PlaylistItem(
                id=str(_uuid.uuid4()),
                playlist_id=playlist.id,
                content_id=cid,
                position=pos,
            )
            db.session.add(pi)

        app.logger.info(f"Seeded playlist: Demo Playlist ({len(content_ids)} items)")

    # --- Device (skillz-desktop) ---
    if not Device.query.filter_by(device_id='SKZ-D-0001').first():
        device = Device(
            id=str(_uuid.uuid4()),
            device_id='SKZ-D-0001',
            hardware_id='jetson-ad71ccc73a85',
            mode='direct',
            connection_mode='direct',
            network_id=ho_id,
            name='skillz-desktop',
            status='active',
            store_name='test',
            screen_location='test',
            store_address='1234',
            store_city='minneapolis',
            store_state='MN',
            store_zipcode='55426',
            manager_name='john doe',
            store_phone='3145551212',
        )
        db.session.add(device)
        app.logger.info("Seeded device: skillz-desktop (SKZ-D-0001)")

    try:
        db.session.commit()
        app.logger.info("Demo content seeding complete")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to seed demo content: {e}")


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
