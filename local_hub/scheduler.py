"""
Background Job Scheduler for Local Hub Service.

This module provides APScheduler-based background job scheduling for the hub.
It uses BackgroundScheduler (NOT BlockingScheduler) to run alongside the Flask
web server, and SQLAlchemyJobStore for job persistence across restarts.

Key jobs scheduled:
- Content sync: Syncs content manifest from HQ (every 5 minutes)
- Playlist sync: Syncs playlist data from HQ (every 5 minutes)
- Alert forwarding: Forwards pending alerts to HQ (every 30 seconds)
- Screen monitoring: Checks screen heartbeats for offline detection (every 30 seconds)
- HQ heartbeat: Reports hub status to HQ (every 60 seconds)
- Heartbeat batch: Forwards queued device heartbeats to HQ (every 60 seconds)

Example:
    from scheduler import init_scheduler
    from config import load_config

    config = load_config()
    scheduler = init_scheduler(
        db_uri='sqlite:////var/skillz-hub/hub.db',
        config=config,
    )

    # Scheduler is now running background jobs
"""

import logging
from typing import Any, Callable, Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobEvent

from config import HubConfig


logger = logging.getLogger(__name__)


# Global scheduler instance
_scheduler: Optional[BackgroundScheduler] = None


def init_scheduler(
    db_uri: str,
    config: Optional[HubConfig] = None,
    start: bool = False,
) -> BackgroundScheduler:
    """
    Initialize the background job scheduler.

    This function creates and configures an APScheduler BackgroundScheduler
    with SQLAlchemyJobStore for job persistence. Jobs are NOT added here -
    they are added separately by register_jobs().

    Args:
        db_uri: SQLAlchemy database URI (e.g., 'sqlite:////var/skillz-hub/hub.db')
        config: Optional HubConfig instance for configuration values
        start: Whether to start the scheduler immediately (default: False)

    Returns:
        Configured BackgroundScheduler instance

    Note:
        Use BackgroundScheduler (NOT BlockingScheduler) with Flask.
        BlockingScheduler will block the web server.
    """
    global _scheduler

    # Check if scheduler already exists
    if _scheduler is not None and _scheduler.running:
        logger.warning("Scheduler already initialized and running")
        return _scheduler

    logger.info(f"Initializing scheduler with db_uri: {db_uri}")

    # Configure job stores - use SQLAlchemy for persistence
    jobstores = {
        'default': SQLAlchemyJobStore(url=db_uri)
    }

    # Configure executors - use thread pool for concurrent job execution
    executors = {
        'default': ThreadPoolExecutor(max_workers=4)
    }

    # Configure job defaults
    job_defaults = {
        'coalesce': True,  # Combine missed jobs into single execution
        'max_instances': 1,  # Only one instance of each job at a time
        'misfire_grace_time': 60,  # Grace time for missed jobs (seconds)
    }

    # Create scheduler
    scheduler = BackgroundScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone='UTC',
    )

    # Add event listeners for logging
    scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)

    # Start scheduler if requested
    if start:
        scheduler.start()
        logger.info("Scheduler started")

    _scheduler = scheduler
    return scheduler


def get_scheduler() -> Optional[BackgroundScheduler]:
    """
    Get the global scheduler instance.

    Returns:
        BackgroundScheduler instance if initialized, None otherwise
    """
    return _scheduler


def shutdown_scheduler(wait: bool = True) -> None:
    """
    Shutdown the scheduler gracefully.

    Args:
        wait: Whether to wait for running jobs to complete (default: True)
    """
    global _scheduler

    if _scheduler is not None:
        logger.info("Shutting down scheduler...")
        _scheduler.shutdown(wait=wait)
        _scheduler = None
        logger.info("Scheduler shutdown complete")


def _on_job_executed(event: JobEvent) -> None:
    """
    Callback for successful job execution.

    Args:
        event: APScheduler job event
    """
    logger.debug(f"Job '{event.job_id}' executed successfully")


def _on_job_error(event: JobEvent) -> None:
    """
    Callback for job execution errors.

    Args:
        event: APScheduler job event
    """
    logger.error(
        f"Job '{event.job_id}' failed with exception: {event.exception}",
        exc_info=event.traceback,
    )


def add_job(
    scheduler: BackgroundScheduler,
    func: Callable,
    job_id: str,
    trigger: str = 'interval',
    replace_existing: bool = True,
    **trigger_args: Any,
) -> None:
    """
    Add a job to the scheduler with standard settings.

    This is a helper function that applies common settings like
    replace_existing=True to avoid duplicate jobs.

    Args:
        scheduler: BackgroundScheduler instance
        func: Function to execute
        job_id: Unique identifier for the job
        trigger: Trigger type ('interval', 'cron', etc.)
        replace_existing: Replace job if it already exists (default: True)
        **trigger_args: Additional trigger arguments (seconds, minutes, etc.)

    Example:
        add_job(scheduler, sync_content, 'content_sync', minutes=5)
        add_job(scheduler, forward_alerts, 'alert_forward', seconds=30)
    """
    scheduler.add_job(
        func,
        trigger=trigger,
        id=job_id,
        replace_existing=replace_existing,
        **trigger_args,
    )
    logger.info(f"Added job '{job_id}' with trigger '{trigger}': {trigger_args}")


def list_jobs(scheduler: Optional[BackgroundScheduler] = None) -> Dict[str, Any]:
    """
    List all scheduled jobs.

    Args:
        scheduler: BackgroundScheduler instance (uses global if not provided)

    Returns:
        Dictionary with job information
    """
    sched = scheduler or _scheduler

    if sched is None:
        return {'error': 'Scheduler not initialized', 'jobs': []}

    jobs = []
    for job in sched.get_jobs():
        jobs.append({
            'id': job.id,
            'name': job.name,
            'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
            'trigger': str(job.trigger),
        })

    return {
        'running': sched.running,
        'job_count': len(jobs),
        'jobs': jobs,
    }


def pause_job(job_id: str, scheduler: Optional[BackgroundScheduler] = None) -> bool:
    """
    Pause a scheduled job.

    Args:
        job_id: Job identifier
        scheduler: BackgroundScheduler instance (uses global if not provided)

    Returns:
        True if job was paused successfully
    """
    sched = scheduler or _scheduler

    if sched is None:
        logger.error("Cannot pause job: scheduler not initialized")
        return False

    try:
        sched.pause_job(job_id)
        logger.info(f"Paused job '{job_id}'")
        return True
    except Exception as e:
        logger.error(f"Failed to pause job '{job_id}': {e}")
        return False


def resume_job(job_id: str, scheduler: Optional[BackgroundScheduler] = None) -> bool:
    """
    Resume a paused job.

    Args:
        job_id: Job identifier
        scheduler: BackgroundScheduler instance (uses global if not provided)

    Returns:
        True if job was resumed successfully
    """
    sched = scheduler or _scheduler

    if sched is None:
        logger.error("Cannot resume job: scheduler not initialized")
        return False

    try:
        sched.resume_job(job_id)
        logger.info(f"Resumed job '{job_id}'")
        return True
    except Exception as e:
        logger.error(f"Failed to resume job '{job_id}': {e}")
        return False


def remove_job(job_id: str, scheduler: Optional[BackgroundScheduler] = None) -> bool:
    """
    Remove a job from the scheduler.

    Args:
        job_id: Job identifier
        scheduler: BackgroundScheduler instance (uses global if not provided)

    Returns:
        True if job was removed successfully
    """
    sched = scheduler or _scheduler

    if sched is None:
        logger.error("Cannot remove job: scheduler not initialized")
        return False

    try:
        sched.remove_job(job_id)
        logger.info(f"Removed job '{job_id}'")
        return True
    except Exception as e:
        logger.error(f"Failed to remove job '{job_id}': {e}")
        return False


def run_job_now(job_id: str, scheduler: Optional[BackgroundScheduler] = None) -> bool:
    """
    Run a job immediately (in addition to its scheduled runs).

    Args:
        job_id: Job identifier
        scheduler: BackgroundScheduler instance (uses global if not provided)

    Returns:
        True if job was triggered successfully
    """
    sched = scheduler or _scheduler

    if sched is None:
        logger.error("Cannot run job: scheduler not initialized")
        return False

    try:
        job = sched.get_job(job_id)
        if job is None:
            logger.error(f"Job not found: {job_id}")
            return False

        # Modify the job to run immediately
        job.modify(next_run_time=None)
        sched.modify_job(job_id, next_run_time=None)
        logger.info(f"Triggered immediate run of job '{job_id}'")
        return True
    except Exception as e:
        logger.error(f"Failed to trigger job '{job_id}': {e}")
        return False


def is_scheduler_running(scheduler: Optional[BackgroundScheduler] = None) -> bool:
    """
    Check if the scheduler is running.

    Args:
        scheduler: BackgroundScheduler instance (uses global if not provided)

    Returns:
        True if scheduler is running
    """
    sched = scheduler or _scheduler
    return sched is not None and sched.running


# Job interval constants (in seconds)
CONTENT_SYNC_INTERVAL_MINUTES = 5
PLAYLIST_SYNC_INTERVAL_MINUTES = 5
ALERT_FORWARD_INTERVAL_SECONDS = 30
SCREEN_MONITOR_INTERVAL_SECONDS = 30
HQ_HEARTBEAT_INTERVAL_SECONDS = 60
HEARTBEAT_BATCH_INTERVAL_SECONDS = 60


def register_jobs(scheduler: BackgroundScheduler, app: Any) -> None:
    """
    Register all background jobs with the scheduler.

    This function registers the following jobs:
    - content_sync: Syncs content manifest from HQ (every 5 minutes)
    - playlist_sync: Syncs playlist data from HQ (every 5 minutes)
    - alert_forward: Forwards pending alerts to HQ (every 30 seconds)
    - screen_monitor: Checks screen heartbeats for offline detection (every 30 seconds)
    - hq_heartbeat: Reports hub status to HQ (every 60 seconds)
    - heartbeat_batch: Forwards queued device heartbeats to HQ (every 60 seconds)

    All jobs run within the Flask application context to ensure proper
    database access through Flask-SQLAlchemy.

    Args:
        scheduler: BackgroundScheduler instance (should be initialized but not started)
        app: Flask application instance

    Note:
        Jobs are added with replace_existing=True to handle restarts gracefully.
        The scheduler should be started AFTER calling this function.
    """
    logger.info("Registering background jobs...")

    # Import services here to avoid circular imports
    from services import HQClient, SyncService, AlertForwarder, ScreenMonitor
    from services.heartbeat_queue import HeartbeatQueueService
    from models.hub_config import HubConfig

    # Job: Content Sync (every 5 minutes)
    def job_content_sync() -> None:
        """Background job to sync content from HQ."""
        with app.app_context():
            try:
                config = app.config['HUB_CONFIG']
                hub_config = HubConfig.get_instance()

                if hub_config is None or not hub_config.is_registered:
                    logger.debug("Hub not registered, skipping content sync")
                    return

                hq_client = HQClient(config.hq_url)
                hq_client.set_token(hub_config.hub_token)

                sync_service = SyncService(hq_client, config)
                result = sync_service.sync_content()

                logger.info(f"Content sync completed: {result}")
            except Exception as e:
                logger.error(f"Content sync failed: {e}")

    # Job: Playlist Sync (every 5 minutes)
    def job_playlist_sync() -> None:
        """Background job to sync playlists from HQ."""
        with app.app_context():
            try:
                config = app.config['HUB_CONFIG']
                hub_config = HubConfig.get_instance()

                if hub_config is None or not hub_config.is_registered:
                    logger.debug("Hub not registered, skipping playlist sync")
                    return

                hq_client = HQClient(config.hq_url)
                hq_client.set_token(hub_config.hub_token)

                sync_service = SyncService(hq_client, config)
                result = sync_service.sync_playlists()

                logger.info(f"Playlist sync completed: {result}")
            except Exception as e:
                logger.error(f"Playlist sync failed: {e}")

    # Job: Alert Forward (every 30 seconds)
    def job_alert_forward() -> None:
        """Background job to forward pending alerts to HQ."""
        with app.app_context():
            try:
                config = app.config['HUB_CONFIG']
                hub_config = HubConfig.get_instance()

                if hub_config is None or not hub_config.is_registered:
                    logger.debug("Hub not registered, skipping alert forward")
                    return

                hq_client = HQClient(config.hq_url)
                hq_client.set_token(hub_config.hub_token)

                forwarder = AlertForwarder(hq_client, config)
                result = forwarder.process_pending_alerts()

                if result.get('processed', 0) > 0:
                    logger.info(f"Alert forwarding completed: {result}")
                else:
                    logger.debug("Alert forwarding: no pending alerts")
            except Exception as e:
                logger.error(f"Alert forwarding failed: {e}")

    # Job: Screen Monitor (every 30 seconds)
    def job_screen_monitor() -> None:
        """Background job to check screen heartbeats."""
        with app.app_context():
            try:
                config = app.config['HUB_CONFIG']
                monitor = ScreenMonitor(config)
                result = monitor.check_screens()

                if result.get('marked_offline', 0) > 0:
                    logger.warning(
                        f"Screen monitor: {result['marked_offline']} screen(s) went offline"
                    )
                else:
                    logger.debug(f"Screen monitor check completed: {result}")
            except Exception as e:
                logger.error(f"Screen monitor check failed: {e}")

    # Job: HQ Heartbeat (every 60 seconds)
    def job_hq_heartbeat() -> None:
        """Background job to send heartbeat to HQ."""
        with app.app_context():
            try:
                config = app.config['HUB_CONFIG']
                hub_config = HubConfig.get_instance()

                if hub_config is None or not hub_config.is_registered:
                    logger.debug("Hub not registered, skipping HQ heartbeat")
                    return

                hq_client = HQClient(config.hq_url)
                hq_client.set_token(hub_config.hub_token)

                # Get screen status list for heartbeat
                from models.screen import Screen
                screens = Screen.query.all()
                screen_list = hq_client.build_screen_status_list(screens)

                # Gather additional hub metrics
                from models.pending_alert import PendingAlert
                from models.sync_status import SyncStatus

                pending_count = PendingAlert.get_pending_count()

                # Get last content sync time
                content_status = SyncStatus.get_content_status()
                last_sync = (
                    content_status.last_sync_at.isoformat()
                    if content_status and content_status.last_sync_at
                    else None
                )

                result = hq_client.send_heartbeat(
                    hub_id=hub_config.hub_id,
                    screens=screen_list,
                    hub_status='online',
                    pending_alerts_count=pending_count,
                    last_sync_at=last_sync,
                )

                logger.debug(f"HQ heartbeat sent: {result}")
            except Exception as e:
                logger.error(f"HQ heartbeat failed: {e}")

    # Job: Heartbeat Batch (every 60 seconds)
    def job_heartbeat_batch() -> None:
        """Background job to forward queued device heartbeats to HQ."""
        with app.app_context():
            try:
                config = app.config['HUB_CONFIG']
                hub_config = HubConfig.get_instance()

                if hub_config is None or not hub_config.is_registered:
                    logger.debug("Hub not registered, skipping heartbeat batch processing")
                    return

                hq_client = HQClient(config.hq_url)
                hq_client.set_token(hub_config.hub_token)

                service = HeartbeatQueueService(hq_client, config)
                result = service.process_pending_heartbeats()

                if result.get('processed', 0) > 0:
                    logger.info(f"Heartbeat batch processing completed: {result}")
                else:
                    logger.debug("Heartbeat batch processing: no pending heartbeats")
            except Exception as e:
                logger.error(f"Heartbeat batch processing failed: {e}")

    # Register all jobs with the scheduler
    add_job(
        scheduler,
        job_content_sync,
        job_id='content_sync',
        trigger='interval',
        minutes=CONTENT_SYNC_INTERVAL_MINUTES,
    )

    add_job(
        scheduler,
        job_playlist_sync,
        job_id='playlist_sync',
        trigger='interval',
        minutes=PLAYLIST_SYNC_INTERVAL_MINUTES,
    )

    add_job(
        scheduler,
        job_alert_forward,
        job_id='alert_forward',
        trigger='interval',
        seconds=ALERT_FORWARD_INTERVAL_SECONDS,
    )

    add_job(
        scheduler,
        job_screen_monitor,
        job_id='screen_monitor',
        trigger='interval',
        seconds=SCREEN_MONITOR_INTERVAL_SECONDS,
    )

    add_job(
        scheduler,
        job_hq_heartbeat,
        job_id='hq_heartbeat',
        trigger='interval',
        seconds=HQ_HEARTBEAT_INTERVAL_SECONDS,
    )

    add_job(
        scheduler,
        job_heartbeat_batch,
        job_id='heartbeat_batch',
        trigger='interval',
        seconds=HEARTBEAT_BATCH_INTERVAL_SECONDS,
    )

    logger.info(
        f"Registered 6 background jobs: "
        f"content_sync ({CONTENT_SYNC_INTERVAL_MINUTES}min), "
        f"playlist_sync ({PLAYLIST_SYNC_INTERVAL_MINUTES}min), "
        f"alert_forward ({ALERT_FORWARD_INTERVAL_SECONDS}s), "
        f"screen_monitor ({SCREEN_MONITOR_INTERVAL_SECONDS}s), "
        f"hq_heartbeat ({HQ_HEARTBEAT_INTERVAL_SECONDS}s), "
        f"heartbeat_batch ({HEARTBEAT_BATCH_INTERVAL_SECONDS}s)"
    )
