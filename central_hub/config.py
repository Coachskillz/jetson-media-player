"""
Central Hub Configuration Module

Configuration settings for database, Redis, Celery, and external services.
All sensitive values are loaded from environment variables.
"""

import os
from pathlib import Path


class Config:
    """Base configuration class with default settings."""

    # Flask Settings
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Database Settings (PostgreSQL)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'postgresql://postgres:dev@localhost:5432/central_hub'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # Redis Settings (for Celery)
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

    # Celery Settings
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', REDIS_URL)
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', REDIS_URL)
    CELERY_TASK_SERIALIZER = 'json'
    CELERY_RESULT_SERIALIZER = 'json'
    CELERY_ACCEPT_CONTENT = ['json']
    CELERY_TIMEZONE = 'UTC'
    CELERY_TASK_TRACK_STARTED = True
    CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes max per task

    # File Storage Paths
    BASE_DIR = Path(__file__).parent.resolve()
    DATABASES_PATH = Path(os.environ.get('DATABASES_PATH', BASE_DIR / 'databases'))
    UPLOADS_PATH = Path(os.environ.get('UPLOADS_PATH', BASE_DIR / 'uploads'))

    # Upload Constraints
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB max upload size
    ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png'}

    # SendGrid Settings (Email)
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY', '')
    SENDGRID_FROM_EMAIL = os.environ.get('SENDGRID_FROM_EMAIL', 'alerts@skillzmedia.com')

    # Twilio Settings (SMS)
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
    TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER', '')

    # Face Recognition Settings
    FACE_ENCODING_NUM_JITTERS = 10  # Balance of speed/accuracy
    FACE_ENCODING_DIMENSIONS = 128  # dlib face_recognition default
    FACE_ENCODING_BYTES = 512  # 128 * 4 bytes (float32)

    # Database Compilation Settings
    DATABASE_VERSIONS_TO_KEEP = 5  # Keep last 5 versions for rollback

    # Notification Settings
    NOTIFICATION_MAX_RETRIES = 3
    NOTIFICATION_RETRY_BACKOFF = 60  # Base seconds for exponential backoff

    @classmethod
    def init_app(cls, app):
        """Initialize application with this configuration."""
        # Ensure storage directories exist
        cls.DATABASES_PATH.mkdir(parents=True, exist_ok=True)
        cls.UPLOADS_PATH.mkdir(parents=True, exist_ok=True)


class DevelopmentConfig(Config):
    """Development configuration with debug enabled."""

    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """Testing configuration with test database."""

    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'TEST_DATABASE_URL',
        'postgresql://postgres:dev@localhost:5432/central_hub_test'
    )
    # Use eager execution for tests
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True


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
            'DATABASE_URL',
            'REDIS_URL',
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
