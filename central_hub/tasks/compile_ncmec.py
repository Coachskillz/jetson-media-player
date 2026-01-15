"""
NCMEC Database Compilation Celery Task

Provides background task for compiling NCMEC face recognition database.
The task runs asynchronously to avoid blocking API requests during
compilation of FAISS indexes with version tracking.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from celery.exceptions import MaxRetriesExceededError

from central_hub.extensions import celery
from central_hub.tasks import (
    LongRunningTask,
    task_success_result,
    task_error_result,
    QUEUE_DEFAULT,
)
from central_hub.services.database_compiler import (
    compile_ncmec_database,
    DatabaseCompilationError,
    EmptyDatabaseError,
)

logger = logging.getLogger(__name__)


@celery.task(
    base=LongRunningTask,
    bind=True,
    name='central_hub.tasks.compile_ncmec.compile_ncmec_task',
    queue=QUEUE_DEFAULT,
    acks_late=True,  # Acknowledge task after completion for reliability
)
def compile_ncmec_task(self, triggered_by: Optional[str] = None) -> Dict:
    """
    Celery task to compile NCMEC database in the background.

    Compiles all active NCMEC records into a versioned FAISS index
    for distribution to edge devices. Creates both the index file
    and accompanying metadata JSON.

    Args:
        triggered_by: Optional identifier of who/what triggered the compilation
                     (e.g., 'api', 'scheduler', 'admin:user@example.com')

    Returns:
        Dictionary containing task result:
        - status: 'ok' on success, 'error' on failure
        - version: Database version number (on success)
        - record_count: Number of records compiled (on success)
        - file_hash: SHA256 hash of the compiled file (on success)
        - file_path: Path to the compiled FAISS file (on success)
        - metadata_path: Path to the metadata JSON file (on success)
        - triggered_by: Who/what triggered the compilation
        - completed_at: ISO timestamp of completion

    Raises:
        Retry: When a retryable error occurs
        MaxRetriesExceededError: When all retries exhausted
    """
    task_id = self.request.id
    started_at = datetime.now(timezone.utc)

    logger.info(
        f"Starting NCMEC database compilation task[{task_id}]",
        extra={
            'task_id': task_id,
            'triggered_by': triggered_by,
            'started_at': started_at.isoformat(),
        }
    )

    try:
        # Execute the compilation
        result = compile_ncmec_database()

        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()

        logger.info(
            f"NCMEC database compilation completed in {duration:.2f}s: "
            f"version={result['version']}, records={result['record_count']}",
            extra={
                'task_id': task_id,
                'version': result['version'],
                'record_count': result['record_count'],
                'file_hash': result['file_hash'],
                'duration_seconds': duration,
            }
        )

        return task_success_result(
            message='NCMEC database compilation completed successfully',
            data={
                'version': result['version'],
                'record_count': result['record_count'],
                'file_hash': result['file_hash'],
                'file_path': result['file_path'],
                'metadata_path': result['metadata_path'],
                'triggered_by': triggered_by,
                'completed_at': completed_at.isoformat(),
                'duration_seconds': duration,
            }
        )

    except EmptyDatabaseError as e:
        # Empty database is not a retryable error
        logger.warning(
            f"NCMEC compilation task[{task_id}] failed: {e}",
            extra={
                'task_id': task_id,
                'error': str(e),
                'error_type': 'empty_database',
            }
        )
        return task_error_result(
            error=str(e),
            code='EMPTY_DATABASE',
            data={'triggered_by': triggered_by}
        )

    except DatabaseCompilationError as e:
        # Compilation errors may be retryable (e.g., transient DB issues)
        retry_count = self.request.retries
        max_retries = self.max_retries

        logger.warning(
            f"NCMEC compilation task[{task_id}] encountered error: {e} "
            f"(retry {retry_count}/{max_retries})",
            extra={
                'task_id': task_id,
                'error': str(e),
                'retry_count': retry_count,
                'max_retries': max_retries,
            }
        )

        try:
            # Retry with exponential backoff
            self.retry_with_backoff(exc=e)
        except MaxRetriesExceededError:
            logger.error(
                f"NCMEC compilation task[{task_id}] failed after {max_retries} retries",
                extra={
                    'task_id': task_id,
                    'error': str(e),
                    'final_retry_count': retry_count,
                }
            )
            return task_error_result(
                error=f"Compilation failed after {max_retries} retries: {e}",
                code='MAX_RETRIES_EXCEEDED',
                data={'triggered_by': triggered_by}
            )

    except Exception as e:
        # Unexpected errors - log and attempt retry
        retry_count = self.request.retries
        max_retries = self.max_retries

        logger.exception(
            f"NCMEC compilation task[{task_id}] unexpected error: {e}",
            extra={
                'task_id': task_id,
                'error': str(e),
                'error_type': type(e).__name__,
                'retry_count': retry_count,
            }
        )

        try:
            self.retry_with_backoff(exc=e)
        except MaxRetriesExceededError:
            logger.error(
                f"NCMEC compilation task[{task_id}] failed after {max_retries} retries "
                f"due to unexpected error",
                extra={
                    'task_id': task_id,
                    'error': str(e),
                    'error_type': type(e).__name__,
                }
            )
            return task_error_result(
                error=f"Unexpected error after {max_retries} retries: {e}",
                code='UNEXPECTED_ERROR',
                data={'triggered_by': triggered_by}
            )


@celery.task(
    base=LongRunningTask,
    bind=True,
    name='central_hub.tasks.compile_ncmec.check_compilation_status',
    queue=QUEUE_DEFAULT,
)
def check_compilation_status(self, task_id: str) -> Dict:
    """
    Check the status of a running NCMEC compilation task.

    Args:
        task_id: The Celery task ID to check.

    Returns:
        Dictionary with task status information.
    """
    from celery.result import AsyncResult

    result = AsyncResult(task_id, app=celery)

    status_info = {
        'task_id': task_id,
        'state': result.state,
        'ready': result.ready(),
        'successful': result.successful() if result.ready() else None,
    }

    if result.ready():
        if result.successful():
            status_info['result'] = result.result
        else:
            status_info['error'] = str(result.result) if result.result else 'Unknown error'

    return status_info


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    'compile_ncmec_task',
    'check_compilation_status',
]
