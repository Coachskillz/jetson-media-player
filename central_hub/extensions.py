"""
Central Hub Extensions Module

Contains Flask extension instances (SQLAlchemy, Celery, Migrate) that are initialized
in the app factory and shared across the application.
"""

from celery import Celery
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


# SQLAlchemy database instance
# Initialized in app factory with Flask app configuration
db = SQLAlchemy()

# Flask-Migrate instance for database migrations
# Initialized in app factory with Flask app and SQLAlchemy db
migrate = Migrate()


# Celery instance for background task processing
# Configured to work with Flask application context
celery = Celery('central_hub')


def init_celery(app):
    """Initialize Celery with Flask application configuration.

    This function configures Celery to work within Flask's application context,
    ensuring that tasks have access to Flask configuration and extensions.

    Args:
        app: Flask application instance

    Returns:
        Configured Celery instance
    """
    # Update Celery config from Flask config
    celery.conf.update(
        broker_url=app.config.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
        result_backend=app.config.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
        task_serializer=app.config.get('CELERY_TASK_SERIALIZER', 'json'),
        result_serializer=app.config.get('CELERY_RESULT_SERIALIZER', 'json'),
        accept_content=app.config.get('CELERY_ACCEPT_CONTENT', ['json']),
        timezone=app.config.get('CELERY_TIMEZONE', 'UTC'),
        task_track_started=app.config.get('CELERY_TASK_TRACK_STARTED', True),
        task_time_limit=app.config.get('CELERY_TASK_TIME_LIMIT', 30 * 60),
        task_always_eager=app.config.get('CELERY_TASK_ALWAYS_EAGER', False),
        task_eager_propagates=app.config.get('CELERY_TASK_EAGER_PROPAGATES', False),
    )

    class ContextTask(celery.Task):
        """Celery task that runs within Flask application context.

        This ensures that tasks have access to Flask's current_app,
        database connections, and other Flask-managed resources.
        """

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery
