"""
Content Catalog Configuration Module

Configuration settings for database, uploads, JWT, mail, and server.
All sensitive values are loaded from environment variables.
"""

import os
from pathlib import Path


def get_database_url():
    """Get database URL, handling Railway's postgres:// to postgresql:// conversion."""
    url = os.environ.get('DATABASE_URL')
    if url:
        # Railway uses postgres:// but SQLAlchemy requires postgresql://
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql://', 1)
        return url
    # Fallback to SQLite for development
    base_dir = Path(__file__).parent.resolve()
    db_path = Path(os.environ.get('CONTENT_CATALOG_DATABASE_PATH', base_dir / 'data' / 'content_catalog.db'))
    return f'sqlite:///{db_path}'


class Config:
    """Base configuration class with default settings."""

    # Flask Settings
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Base Directory
    BASE_DIR = Path(__file__).parent.resolve()

    # Database Settings
    DATABASE_PATH = Path(os.environ.get('CONTENT_CATALOG_DATABASE_PATH', BASE_DIR / 'data' / 'content_catalog.db'))
    SQLALCHEMY_DATABASE_URI = get_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Base URL for email links and redirects
    BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5003')

    # File Storage Paths
    UPLOADS_PATH = Path(os.environ.get('CONTENT_CATALOG_UPLOAD_PATH', BASE_DIR / 'uploads'))
    THUMBNAILS_PATH = Path(os.environ.get('CONTENT_CATALOG_THUMBNAILS_PATH', BASE_DIR / 'uploads' / 'thumbnails'))

    # Upload Constraints
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max upload size
    ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
    ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    ALLOWED_EXTENSIONS = ALLOWED_VIDEO_EXTENSIONS | ALLOWED_IMAGE_EXTENSIONS

    # Server Settings
    PORT = int(os.environ.get('CONTENT_CATALOG_PORT', 5003))
    HOST = os.environ.get('CONTENT_CATALOG_HOST', '0.0.0.0')

    # JWT Settings
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'dev-jwt-secret-change-in-production')
    JWT_ACCESS_TOKEN_EXPIRES = int(os.environ.get('JWT_ACCESS_TOKEN_EXPIRES', 3600))  # 1 hour default
    JWT_REFRESH_TOKEN_EXPIRES = int(os.environ.get('JWT_REFRESH_TOKEN_EXPIRES', 86400 * 7))  # 7 days default

    # Mail Settings
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'localhost')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@skillzmedia.com')

    # User Invitation Settings
    INVITATION_EXPIRY_DAYS = int(os.environ.get('INVITATION_EXPIRY_DAYS', 7))

    # Account Lockout Settings
    MAX_LOGIN_ATTEMPTS = int(os.environ.get('MAX_LOGIN_ATTEMPTS', 5))
    LOCKOUT_DURATION_MINUTES = int(os.environ.get('LOCKOUT_DURATION_MINUTES', 15))

    # Password Settings
    PASSWORD_MIN_LENGTH = 8
    PASSWORD_MAX_BYTES = 72  # bcrypt limit

    # Session Settings
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    @classmethod
    def init_app(cls, app):
        """Initialize application with this configuration."""
        # Only create SQLite database directory if using SQLite
        db_url = cls.SQLALCHEMY_DATABASE_URI
        if db_url and db_url.startswith('sqlite'):
            cls.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Ensure upload directories exist
        try:
            cls.UPLOADS_PATH.mkdir(parents=True, exist_ok=True)
            cls.THUMBNAILS_PATH.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            # On Railway, we might not be able to create directories
            # Log warning but don't fail - cloud storage should be used
            app.logger.warning(f"Could not create upload directories: {e}")


class DevelopmentConfig(Config):
    """Development configuration with debug enabled."""

    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """Testing configuration with test database."""

    DEBUG = True
    TESTING = True
    DATABASE_PATH = Path(Config.BASE_DIR / 'data' / 'content_catalog_test.db')
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{DATABASE_PATH}'

    # Faster password hashing for tests (not secure, but fast)
    BCRYPT_LOG_ROUNDS = 4

    # Disable mail sending in tests
    MAIL_SUPPRESS_SEND = True


class ProductionConfig(Config):
    """Production configuration with strict security settings."""

    DEBUG = False
    TESTING = False

    # Secure session cookies in production
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    @classmethod
    def init_app(cls, app):
        """Production-specific initialization."""
        Config.init_app(app)

        # Verify required environment variables are set
        required_vars = [
            'SECRET_KEY',
            'JWT_SECRET_KEY',
            'DATABASE_URL',
        ]
        missing = [var for var in required_vars if not os.environ.get(var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        # Warn if using default secret keys
        if os.environ.get('SECRET_KEY') == 'dev-secret-key-change-in-production':
            raise ValueError("SECRET_KEY must be changed from default in production")
        if os.environ.get('JWT_SECRET_KEY') == 'dev-jwt-secret-change-in-production':
            raise ValueError("JWT_SECRET_KEY must be changed from default in production")


# Configuration mapping by environment name
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}


def get_config(env_name=None):
    """Get configuration class by environment name.

    Args:
        env_name: Environment name ('development', 'testing', 'production').
                  If None, reads from FLASK_ENV environment variable.

    Returns:
        Configuration class for the specified environment.
    """
    if env_name is None:
        env_name = os.environ.get('FLASK_ENV', 'development')
    return config.get(env_name, config['default'])
