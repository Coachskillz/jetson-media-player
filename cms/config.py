"""
CMS Configuration Module

Configuration settings for database, uploads, and server.
All sensitive values are loaded from environment variables.
"""

import os
from pathlib import Path


class Config:
    """Base configuration class with default settings."""

    # Flask Settings
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Base Directory
    BASE_DIR = Path(__file__).parent.resolve()

    # Database Settings (SQLite)
    DATABASE_PATH = Path(os.environ.get('CMS_DATABASE_PATH', BASE_DIR / 'data' / 'cms.db'))
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{DATABASE_PATH}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # File Storage Paths
    UPLOADS_PATH = Path(os.environ.get('CMS_UPLOAD_PATH', BASE_DIR / 'uploads'))

    # Upload Constraints
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max upload size
    ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
    ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    ALLOWED_EXTENSIONS = ALLOWED_VIDEO_EXTENSIONS | ALLOWED_IMAGE_EXTENSIONS

    # Server Settings
    PORT = int(os.environ.get('CMS_PORT', 5002))
    HOST = os.environ.get('CMS_HOST', '0.0.0.0')

    # Device ID Settings
    DEVICE_ID_PREFIX_DIRECT = 'SKZ-D'
    DEVICE_ID_PREFIX_HUB = 'SKZ-H'

    @classmethod
    def init_app(cls, app):
        """Initialize application with this configuration."""
        # Ensure storage directories exist
        cls.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.UPLOADS_PATH.mkdir(parents=True, exist_ok=True)


class DevelopmentConfig(Config):
    """Development configuration with debug enabled."""

    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """Testing configuration with test database."""

    DEBUG = True
    TESTING = True
    DATABASE_PATH = Path(Config.BASE_DIR / 'data' / 'cms_test.db')
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{DATABASE_PATH}'


class ProductionConfig(Config):
    """Production configuration with strict security settings."""

    DEBUG = False
    TESTING = False

    @classmethod
    def init_app(cls, app):
        """Production-specific initialization."""
        Config.init_app(app)

        # Verify required environment variables are set
        required_vars = [
            'SECRET_KEY',
        ]
        missing = [var for var in required_vars if not os.environ.get(var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


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
