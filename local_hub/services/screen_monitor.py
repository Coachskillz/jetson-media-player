"""
Screen Monitor Service - Heartbeat checking and offline detection.

This module provides the ScreenMonitor class for monitoring screen health
and detecting offline screens. It handles:
- Checking screen heartbeats against timeout threshold
- Marking screens as offline when heartbeat timeout expires (2 minutes)
- Providing screen health statistics

The monitor runs periodically (every 30 seconds by default) to check
all screens and update their status accordingly.

Example:
    from services.screen_monitor import ScreenMonitor
    from config import load_config

    config = load_config()
    monitor = ScreenMonitor(config)

    # Check all screens and update statuses
    result = monitor.check_screens()

    # Get monitoring statistics
    stats = monitor.get_monitor_stats()
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from services import ScreenMonitorError
from config import HubConfig


logger = logging.getLogger(__name__)


# Default timeout in seconds (2 minutes as per spec)
DEFAULT_OFFLINE_TIMEOUT_SECONDS = 120

# Default interval for monitoring checks
DEFAULT_CHECK_INTERVAL_SECONDS = 30


class ScreenMonitor:
    """
    Service for monitoring screen heartbeats and detecting offline screens.

    This service periodically checks all registered screens to determine
    if they have missed their heartbeat window (2 minutes by default).
    Screens that have not sent a heartbeat within the timeout period
    are marked as offline.

    Attributes:
        config: HubConfig instance for configuration
        offline_timeout: Seconds without heartbeat before marking offline
        check_interval: Seconds between monitoring checks
    """

    def __init__(
        self,
        config: Optional[HubConfig] = None,
        offline_timeout: int = DEFAULT_OFFLINE_TIMEOUT_SECONDS,
        check_interval: int = DEFAULT_CHECK_INTERVAL_SECONDS,
    ):
        """
        Initialize the screen monitor service.

        Args:
            config: HubConfig instance with configuration (optional)
            offline_timeout: Seconds without heartbeat before marking offline (default 120)
            check_interval: Seconds between monitoring checks (default 30)
        """
        self.config = config
        self.offline_timeout = offline_timeout
        self.check_interval = check_interval

        # Track last check time for statistics
        self._last_check_at: Optional[datetime] = None
        self._last_check_result: Optional[Dict[str, Any]] = None

        logger.info(
            f"ScreenMonitor initialized with offline_timeout={offline_timeout}s, "
            f"check_interval={check_interval}s"
        )

    def check_screens(self) -> Dict[str, Any]:
        """
        Check all screens and update offline status.

        This method queries all screens and marks any screen that has not
        sent a heartbeat within the offline_timeout period as offline.
        Screens that were offline but have recently sent heartbeats are
        not modified (their status should be updated by the heartbeat endpoint).

        Returns:
            Dictionary with check results:
            - checked: Total number of screens checked
            - marked_offline: Number of screens marked offline this check
            - already_offline: Number of screens already marked offline
            - online: Number of screens still online
            - errors: List of error messages

        Note:
            This method should be called periodically by the background
            scheduler (every 30 seconds by default).
        """
        from models.screen import Screen
        from models import db

        result = {
            'checked': 0,
            'marked_offline': 0,
            'already_offline': 0,
            'online': 0,
            'errors': [],
            'started_at': datetime.utcnow().isoformat(),
            'completed_at': None,
        }

        try:
            # Get all screens
            screens = Screen.query.all()

            if not screens:
                logger.debug("No screens registered to monitor")
                result['completed_at'] = datetime.utcnow().isoformat()
                self._update_last_check(result)
                return result

            # Calculate timeout threshold
            timeout_threshold = datetime.utcnow() - timedelta(seconds=self.offline_timeout)

            logger.debug(
                f"Checking {len(screens)} screens with timeout threshold: {timeout_threshold}"
            )

            # Check each screen
            for screen in screens:
                result['checked'] += 1

                try:
                    # Check if screen has missed heartbeat
                    if screen.last_heartbeat is None:
                        # No heartbeat ever received - mark offline
                        if screen.status != 'offline':
                            screen.status = 'offline'
                            result['marked_offline'] += 1
                            logger.info(
                                f"Screen {screen.id} ({screen.hardware_id}) marked offline: "
                                f"no heartbeat received"
                            )
                        else:
                            result['already_offline'] += 1
                    elif screen.last_heartbeat < timeout_threshold:
                        # Heartbeat too old - mark offline if not already
                        if screen.status != 'offline':
                            screen.status = 'offline'
                            result['marked_offline'] += 1
                            logger.info(
                                f"Screen {screen.id} ({screen.hardware_id}) marked offline: "
                                f"last heartbeat {screen.last_heartbeat.isoformat()}"
                            )
                        else:
                            result['already_offline'] += 1
                    else:
                        # Screen is still within heartbeat window
                        result['online'] += 1

                except Exception as e:
                    error_msg = f"Screen {screen.id}: {str(e)}"
                    result['errors'].append(error_msg)
                    logger.error(f"Error checking screen {screen.id}: {e}")

            # Commit all status changes
            db.session.commit()

            result['completed_at'] = datetime.utcnow().isoformat()

            # Log summary
            if result['marked_offline'] > 0:
                logger.info(
                    f"Screen check completed: {result['marked_offline']} newly offline, "
                    f"{result['online']} online, {result['already_offline']} already offline"
                )
            else:
                logger.debug(
                    f"Screen check completed: {result['online']} online, "
                    f"{result['already_offline']} offline"
                )

            self._update_last_check(result)
            return result

        except Exception as e:
            result['completed_at'] = datetime.utcnow().isoformat()
            result['errors'].append(str(e))
            logger.error(f"Error during screen monitoring: {e}")
            self._update_last_check(result)
            raise ScreenMonitorError(
                message="Screen monitoring check failed",
                details={'error': str(e), 'result': result},
            )

    def _update_last_check(self, result: Dict[str, Any]) -> None:
        """Update last check tracking data."""
        self._last_check_at = datetime.utcnow()
        self._last_check_result = result

    def get_screen_status(self, screen_id: int) -> Dict[str, Any]:
        """
        Get detailed status for a specific screen.

        Args:
            screen_id: ID of the screen to check

        Returns:
            Dictionary with screen status details:
            - screen_id: Screen identifier
            - hardware_id: Hardware identifier
            - status: Current status (online/offline)
            - last_heartbeat: Last heartbeat timestamp
            - seconds_since_heartbeat: Seconds since last heartbeat
            - is_within_timeout: Whether still within timeout window

        Raises:
            ScreenMonitorError: If screen is not found
        """
        from models.screen import Screen
        from models import db

        screen = db.session.get(Screen, screen_id)
        if not screen:
            raise ScreenMonitorError(
                message=f"Screen not found: {screen_id}",
                details={'screen_id': screen_id},
            )

        now = datetime.utcnow()
        timeout_threshold = now - timedelta(seconds=self.offline_timeout)

        # Calculate time since last heartbeat
        if screen.last_heartbeat:
            seconds_since_heartbeat = (now - screen.last_heartbeat).total_seconds()
            is_within_timeout = screen.last_heartbeat >= timeout_threshold
        else:
            seconds_since_heartbeat = None
            is_within_timeout = False

        return {
            'screen_id': screen.id,
            'hardware_id': screen.hardware_id,
            'name': screen.name,
            'status': screen.status,
            'last_heartbeat': screen.last_heartbeat.isoformat() if screen.last_heartbeat else None,
            'seconds_since_heartbeat': int(seconds_since_heartbeat) if seconds_since_heartbeat else None,
            'is_within_timeout': is_within_timeout,
            'offline_timeout': self.offline_timeout,
        }

    def get_all_screen_statuses(self) -> List[Dict[str, Any]]:
        """
        Get status for all screens.

        Returns:
            List of screen status dictionaries
        """
        from models.screen import Screen

        screens = Screen.query.all()
        statuses = []

        for screen in screens:
            try:
                status = self.get_screen_status(screen.id)
                statuses.append(status)
            except Exception as e:
                logger.error(f"Error getting status for screen {screen.id}: {e}")

        return statuses

    def get_monitor_stats(self) -> Dict[str, Any]:
        """
        Get monitoring statistics.

        Returns:
            Dictionary with monitoring statistics:
            - total_screens: Total registered screens
            - online_count: Number of online screens
            - offline_count: Number of offline screens
            - last_check_at: Timestamp of last check
            - last_check_result: Result of last check
            - offline_timeout: Current timeout setting
            - check_interval: Current check interval
        """
        from models.screen import Screen

        total = Screen.query.count()
        online = Screen.query.filter_by(status='online').count()
        offline = Screen.query.filter_by(status='offline').count()

        return {
            'total_screens': total,
            'online_count': online,
            'offline_count': offline,
            'last_check_at': self._last_check_at.isoformat() if self._last_check_at else None,
            'last_check_result': self._last_check_result,
            'offline_timeout': self.offline_timeout,
            'check_interval': self.check_interval,
        }

    def get_offline_screens(self) -> List[Dict[str, Any]]:
        """
        Get list of all offline screens with details.

        Returns:
            List of dictionaries with offline screen details
        """
        from models.screen import Screen

        offline_screens = Screen.get_all_offline()

        return [
            {
                'screen_id': screen.id,
                'hardware_id': screen.hardware_id,
                'name': screen.name,
                'last_heartbeat': screen.last_heartbeat.isoformat() if screen.last_heartbeat else None,
                'offline_since': self._calculate_offline_since(screen),
            }
            for screen in offline_screens
        ]

    def _calculate_offline_since(self, screen) -> Optional[str]:
        """
        Calculate when a screen went offline.

        This is approximately the last_heartbeat time plus the timeout period,
        or when the screen was last marked offline.

        Args:
            screen: Screen model instance

        Returns:
            ISO timestamp of when screen went offline, or None
        """
        if screen.last_heartbeat:
            offline_time = screen.last_heartbeat + timedelta(seconds=self.offline_timeout)
            return offline_time.isoformat()
        return None

    def get_online_screens(self) -> List[Dict[str, Any]]:
        """
        Get list of all online screens with details.

        Returns:
            List of dictionaries with online screen details
        """
        from models.screen import Screen

        online_screens = Screen.get_all_online()

        now = datetime.utcnow()

        return [
            {
                'screen_id': screen.id,
                'hardware_id': screen.hardware_id,
                'name': screen.name,
                'last_heartbeat': screen.last_heartbeat.isoformat() if screen.last_heartbeat else None,
                'seconds_until_timeout': self._calculate_seconds_until_timeout(screen, now),
            }
            for screen in online_screens
        ]

    def _calculate_seconds_until_timeout(self, screen, now: datetime) -> Optional[int]:
        """
        Calculate seconds until a screen will be marked offline.

        Args:
            screen: Screen model instance
            now: Current datetime

        Returns:
            Seconds until timeout, or None if already expired
        """
        if screen.last_heartbeat:
            timeout_time = screen.last_heartbeat + timedelta(seconds=self.offline_timeout)
            remaining = (timeout_time - now).total_seconds()
            return max(0, int(remaining))
        return None

    def force_check(self) -> Dict[str, Any]:
        """
        Force an immediate screen check.

        This bypasses the normal scheduling and performs a check immediately.
        Useful for manual intervention or testing.

        Returns:
            Result of the check operation
        """
        logger.info("Forcing immediate screen check")
        return self.check_screens()

    def mark_screen_online(self, screen_id: int) -> bool:
        """
        Manually mark a screen as online.

        This method is primarily for testing or manual intervention.
        Normal operation should use the heartbeat endpoint.

        Args:
            screen_id: ID of the screen to mark online

        Returns:
            True if successful

        Raises:
            ScreenMonitorError: If screen is not found
        """
        from models.screen import Screen
        from models import db

        screen = db.session.get(Screen, screen_id)
        if not screen:
            raise ScreenMonitorError(
                message=f"Screen not found: {screen_id}",
                details={'screen_id': screen_id},
            )

        screen.status = 'online'
        screen.last_heartbeat = datetime.utcnow()
        db.session.commit()

        logger.info(f"Screen {screen_id} manually marked online")
        return True

    def mark_screen_offline(self, screen_id: int) -> bool:
        """
        Manually mark a screen as offline.

        This method is primarily for testing or manual intervention.

        Args:
            screen_id: ID of the screen to mark offline

        Returns:
            True if successful

        Raises:
            ScreenMonitorError: If screen is not found
        """
        from models.screen import Screen
        from models import db

        screen = db.session.get(Screen, screen_id)
        if not screen:
            raise ScreenMonitorError(
                message=f"Screen not found: {screen_id}",
                details={'screen_id': screen_id},
            )

        screen.status = 'offline'
        db.session.commit()

        logger.info(f"Screen {screen_id} manually marked offline")
        return True

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<ScreenMonitor offline_timeout={self.offline_timeout}s "
            f"check_interval={self.check_interval}s>"
        )
