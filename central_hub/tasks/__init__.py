"""
Central Hub Celery Tasks Package

Celery configuration and background task definitions for:
- NCMEC database compilation
- Loyalty database compilation
- Delayed notification dispatch

The celery instance is imported from extensions.py and configured
to work with Flask application context. Tasks use a base class
with built-in retry logic and exponential backoff.
"""

import logging
from typing import Any, Dict, Optional

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from central_hub.extensions import celery


logger = logging.getLogger(__name__)


# ============================================================================
# Task Configuration Constants
# ============================================================================

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 60  # Base seconds for exponential backoff
DEFAULT_RETRY_JITTER = True  # Add randomness to prevent thundering herd

# Task queue names for priority routing
QUEUE_HIGH_PRIORITY = 'high_priority'
QUEUE_DEFAULT = 'default'
QUEUE_LOW_PRIORITY = 'low_priority'

# Task time limits (seconds)
TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes soft limit (warning)
TASK_HARD_TIME_LIMIT = 30 * 60  # 30 minutes hard limit (kill)


# ============================================================================
# Base Task Class with Retry Logic
# ============================================================================

class BaseTaskWithRetry(Task):
    """
    Base Celery task class with built-in retry logic and exponential backoff.

    This class provides:
    - Automatic retry on failure with configurable max_retries
    - Exponential backoff with optional jitter
    - Structured logging for task lifecycle events
    - Error handling and result formatting

    Usage:
        @celery.task(base=BaseTaskWithRetry, bind=True)
        def my_task(self, arg1, arg2):
            # Task implementation
            return {'status': 'ok', 'result': 'data'}

    Configuration:
        Override class attributes for task-specific settings:
        - max_retries: Maximum retry attempts (default: 3)
        - retry_backoff: Base seconds for exponential backoff (default: 60)
        - retry_jitter: Add randomness to delay (default: True)
    """

    # Retry configuration (can be overridden per task)
    max_retries = DEFAULT_MAX_RETRIES
    retry_backoff = DEFAULT_RETRY_BACKOFF
    retry_jitter = DEFAULT_RETRY_JITTER

    # Time limits
    soft_time_limit = TASK_SOFT_TIME_LIMIT
    time_limit = TASK_HARD_TIME_LIMIT

    # Task tracking
    track_started = True

    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        """Called when task succeeds.

        Args:
            retval: Return value from the task
            task_id: Unique task identifier
            args: Positional arguments passed to task
            kwargs: Keyword arguments passed to task
        """
        logger.info(
            f"Task {self.name}[{task_id}] succeeded",
            extra={
                'task_id': task_id,
                'task_name': self.name,
                'status': 'success',
            }
        )

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any
    ) -> None:
        """Called when task fails after all retries exhausted.

        Args:
            exc: Exception that caused failure
            task_id: Unique task identifier
            args: Positional arguments passed to task
            kwargs: Keyword arguments passed to task
            einfo: Exception info object
        """
        logger.error(
            f"Task {self.name}[{task_id}] failed: {exc}",
            extra={
                'task_id': task_id,
                'task_name': self.name,
                'status': 'failed',
                'error': str(exc),
            },
            exc_info=True,
        )

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any
    ) -> None:
        """Called when task is being retried.

        Args:
            exc: Exception that caused retry
            task_id: Unique task identifier
            args: Positional arguments passed to task
            kwargs: Keyword arguments passed to task
            einfo: Exception info object
        """
        retry_count = self.request.retries if self.request else 0
        logger.warning(
            f"Task {self.name}[{task_id}] retry {retry_count}/{self.max_retries}: {exc}",
            extra={
                'task_id': task_id,
                'task_name': self.name,
                'status': 'retry',
                'retry_count': retry_count,
                'max_retries': self.max_retries,
                'error': str(exc),
            }
        )

    def retry_with_backoff(
        self,
        exc: Optional[Exception] = None,
        countdown: Optional[int] = None,
        max_retries: Optional[int] = None,
        **kwargs
    ) -> None:
        """Retry task with exponential backoff.

        Calculates delay as: retry_backoff * (2 ** retry_count)
        With jitter: adds random variation to prevent thundering herd

        Args:
            exc: Exception that triggered retry
            countdown: Override calculated countdown (seconds)
            max_retries: Override default max_retries
            **kwargs: Additional arguments for retry()

        Raises:
            MaxRetriesExceededError: When max retries reached
            Retry: Celery retry exception
        """
        retries = self.request.retries if self.request else 0
        max_retries = max_retries if max_retries is not None else self.max_retries

        if countdown is None:
            # Calculate exponential backoff: base * 2^retries
            countdown = self.retry_backoff * (2 ** retries)

            if self.retry_jitter:
                # Add jitter: +-25% variation
                import random
                jitter_range = countdown * 0.25
                countdown = int(countdown + random.uniform(-jitter_range, jitter_range))

        logger.info(
            f"Task {self.name} scheduling retry in {countdown}s (attempt {retries + 1}/{max_retries})"
        )

        raise self.retry(
            exc=exc,
            countdown=countdown,
            max_retries=max_retries,
            **kwargs
        )


class CriticalTaskWithRetry(BaseTaskWithRetry):
    """
    Task base for critical operations requiring more retries.

    Used for high-priority tasks like NCMEC notifications where
    delivery is critical and more retry attempts are warranted.
    """
    max_retries = 5
    retry_backoff = 30  # Shorter initial backoff for urgent tasks


class LongRunningTask(BaseTaskWithRetry):
    """
    Task base for long-running operations.

    Used for database compilation tasks that may take significant time.
    Provides extended time limits and fewer retries.
    """
    max_retries = 2
    soft_time_limit = 55 * 60  # 55 minutes
    time_limit = 60 * 60  # 1 hour


# ============================================================================
# Task Result Helpers
# ============================================================================

def task_success_result(
    message: str = 'Task completed successfully',
    data: Optional[Dict] = None
) -> Dict:
    """Create a standardized success result dictionary.

    Args:
        message: Success message
        data: Optional additional data to include

    Returns:
        Dictionary with status='ok' and provided data
    """
    result = {
        'status': 'ok',
        'message': message,
    }
    if data:
        result.update(data)
    return result


def task_error_result(
    error: str,
    code: Optional[str] = None,
    data: Optional[Dict] = None
) -> Dict:
    """Create a standardized error result dictionary.

    Args:
        error: Error message
        code: Optional error code
        data: Optional additional data to include

    Returns:
        Dictionary with status='error' and error details
    """
    result = {
        'status': 'error',
        'error': error,
    }
    if code:
        result['code'] = code
    if data:
        result.update(data)
    return result


# ============================================================================
# Celery Configuration
# ============================================================================

# Configure task routing for priority queues
celery.conf.task_routes = {
    'central_hub.tasks.send_notification.*': {'queue': QUEUE_HIGH_PRIORITY},
    'central_hub.tasks.compile_ncmec.*': {'queue': QUEUE_DEFAULT},
    'central_hub.tasks.compile_loyalty.*': {'queue': QUEUE_DEFAULT},
}

# Configure task autodiscovery
# Tasks will be discovered when task modules are imported
celery.conf.task_default_queue = QUEUE_DEFAULT


# ============================================================================
# Task Imports (for Celery autodiscovery)
# ============================================================================

# Import tasks to register them with Celery
from central_hub.tasks.compile_ncmec import compile_ncmec_task, check_compilation_status
from central_hub.tasks.compile_loyalty import compile_loyalty_task, check_loyalty_compilation_status
from central_hub.tasks.send_notification import send_notification_task, send_bulk_notification_task


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Celery instance
    'celery',
    # Base task classes
    'BaseTaskWithRetry',
    'CriticalTaskWithRetry',
    'LongRunningTask',
    # Result helpers
    'task_success_result',
    'task_error_result',
    # Constants
    'DEFAULT_MAX_RETRIES',
    'DEFAULT_RETRY_BACKOFF',
    'QUEUE_HIGH_PRIORITY',
    'QUEUE_DEFAULT',
    'QUEUE_LOW_PRIORITY',
    # NCMEC compilation tasks
    'compile_ncmec_task',
    'check_compilation_status',
    # Loyalty compilation tasks
    'compile_loyalty_task',
    'check_loyalty_compilation_status',
    # Notification tasks
    'send_notification_task',
    'send_bulk_notification_task',
]
