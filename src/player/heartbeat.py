"""
Heartbeat Reporter - Reports device status to hub at regular intervals.
Sends health metrics and playback state every 60 seconds.
"""

import os
import time
import threading
import requests
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.common.logger import setup_logger

logger = setup_logger(__name__)


class HeartbeatReporter:
    """Reports device status to hub at regular intervals."""

    DEFAULT_INTERVAL = 60  # 60 seconds between heartbeats

    def __init__(
        self,
        hub_url: str = "http://192.168.1.100:5000",
        screen_id: str = "",
        interval: int = DEFAULT_INTERVAL,
        connection_mode: str = "hub",
        hardware_id: str = ""
    ):
        """
        Initialize heartbeat reporter.

        Args:
            hub_url: URL of the local hub or CMS (in direct mode)
            screen_id: Unique screen identifier (used in hub mode)
            interval: Seconds between heartbeats (default: 60)
            connection_mode: 'hub' or 'direct' - determines URL format
            hardware_id: Device hardware ID (used in direct mode)
        """
        self.hub_url = hub_url
        self.screen_id = screen_id
        self.interval = interval
        self.connection_mode = connection_mode
        self.hardware_id = hardware_id

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._status_callback: Optional[Callable[[], Dict[str, Any]]] = None

        # Track last heartbeat
        self._last_heartbeat_time: Optional[float] = None
        self._last_heartbeat_success: bool = False
        self._consecutive_failures = 0

        # Startup time for uptime calculation
        self._start_time = time.time()

    def set_status_callback(self, callback: Callable[[], Dict[str, Any]]) -> None:
        """
        Set callback function for getting current playback status.

        The callback should return a dict with keys:
        - status: str (playing, paused, stopped, error)
        - current_content: str (filename of current video)

        Args:
            callback: Function that returns current status dict
        """
        self._status_callback = callback

    def _get_cpu_temp(self) -> int:
        """
        Get CPU temperature in Celsius.

        Returns:
            CPU temperature or 0 if unavailable
        """
        try:
            # Try Jetson thermal zones
            thermal_paths = [
                "/sys/class/thermal/thermal_zone0/temp",
                "/sys/class/thermal/thermal_zone1/temp",
            ]

            for path in thermal_paths:
                if Path(path).exists():
                    with open(path, 'r') as f:
                        temp = int(f.read().strip())
                        # Convert millidegrees to degrees
                        return temp // 1000

            return 0
        except Exception:
            return 0

    def _get_memory_usage(self) -> int:
        """
        Get memory usage percentage.

        Returns:
            Memory usage percent (0-100) or 0 if unavailable
        """
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()

            mem_total = 0
            mem_available = 0

            for line in meminfo.split('\n'):
                if line.startswith('MemTotal:'):
                    mem_total = int(line.split()[1])
                elif line.startswith('MemAvailable:'):
                    mem_available = int(line.split()[1])

            if mem_total > 0:
                mem_used = mem_total - mem_available
                return int((mem_used / mem_total) * 100)

            return 0
        except Exception:
            return 0

    def _get_disk_free(self) -> float:
        """
        Get free disk space in gigabytes.

        Returns:
            Free disk space in GB or 0.0 if unavailable
        """
        try:
            # Check media directory or home directory
            check_paths = ['/home/skillz/media', '/home/skillz', '/']

            for path in check_paths:
                if Path(path).exists():
                    stat = os.statvfs(path)
                    free_bytes = stat.f_bavail * stat.f_frsize
                    return round(free_bytes / (1024 ** 3), 1)

            return 0.0
        except Exception:
            return 0.0

    def _get_uptime(self) -> int:
        """
        Get process uptime in seconds.

        Returns:
            Uptime in seconds
        """
        return int(time.time() - self._start_time)

    def collect_metrics(self) -> Dict[str, Any]:
        """
        Collect all system metrics for heartbeat.

        Returns:
            Dictionary with system metrics and playback status
        """
        # Get playback status from callback
        playback_status = {"status": "unknown", "current_content": ""}
        if self._status_callback:
            try:
                playback_status = self._status_callback()
            except Exception as e:
                logger.error(f"Error getting playback status: {e}")

        return {
            "status": playback_status.get("status", "unknown"),
            "current_content": playback_status.get("current_content", ""),
            "cpu_temp": self._get_cpu_temp(),
            "memory_usage_percent": self._get_memory_usage(),
            "disk_free_gb": self._get_disk_free(),
            "uptime_seconds": self._get_uptime()
        }

    def send_heartbeat(self) -> bool:
        """
        Send heartbeat to hub or CMS.

        In hub mode: POST {hub_url}/api/v1/screens/{screen_id}/heartbeat
        In direct mode: POST {cms_url}/api/v1/devices/{hardware_id}/heartbeat

        Returns:
            True if heartbeat was sent successfully, False otherwise
        """
        if self.connection_mode == 'direct':
            if not self.hardware_id:
                logger.warning("Cannot send heartbeat: no hardware_id configured")
                return False
            url = f"{self.hub_url}/api/v1/devices/{self.hardware_id}/heartbeat"
        else:
            if not self.screen_id:
                logger.warning("Cannot send heartbeat: no screen_id configured")
                return False
            url = f"{self.hub_url}/api/v1/screens/{self.screen_id}/heartbeat"

        metrics = self.collect_metrics()

        try:
            response = requests.post(
                url,
                json=metrics,
                timeout=10
            )

            if response.status_code == 200:
                self._last_heartbeat_time = time.time()
                self._last_heartbeat_success = True
                self._consecutive_failures = 0
                logger.debug(f"Heartbeat sent: {metrics['status']}")
                return True
            else:
                logger.warning(f"Heartbeat failed: HTTP {response.status_code}")
                self._last_heartbeat_success = False
                self._consecutive_failures += 1
                return False

        except requests.Timeout:
            logger.warning("Heartbeat timeout - hub unreachable")
            self._last_heartbeat_success = False
            self._consecutive_failures += 1
            return False
        except requests.RequestException as e:
            logger.warning(f"Heartbeat error: {e}")
            self._last_heartbeat_success = False
            self._consecutive_failures += 1
            return False

    def _heartbeat_loop(self) -> None:
        """Background thread loop for sending heartbeats."""
        logger.info(f"Heartbeat reporter started (interval: {self.interval}s)")

        while self._running:
            self.send_heartbeat()

            # Sleep in small increments for responsive shutdown
            for _ in range(self.interval):
                if not self._running:
                    break
                time.sleep(1)

        logger.info("Heartbeat reporter stopped")

    def start(self) -> None:
        """Start the heartbeat reporter background thread."""
        if self._running:
            logger.warning("Heartbeat reporter already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()
        logger.info("Heartbeat reporter started")

    def stop(self) -> None:
        """Stop the heartbeat reporter."""
        if not self._running:
            return

        self._running = False

        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

        logger.info("Heartbeat reporter stopped")

    def is_running(self) -> bool:
        """Check if heartbeat reporter is running."""
        return self._running

    def get_last_heartbeat_info(self) -> Dict[str, Any]:
        """
        Get information about the last heartbeat.

        Returns:
            Dictionary with last heartbeat details
        """
        return {
            "last_time": self._last_heartbeat_time,
            "last_success": self._last_heartbeat_success,
            "consecutive_failures": self._consecutive_failures
        }


if __name__ == "__main__":
    print("Heartbeat Reporter Test")
    print("=" * 50)

    # Create reporter with test config
    reporter = HeartbeatReporter(
        hub_url="http://localhost:5000",
        screen_id="test-screen-001",
        interval=10
    )

    # Set a test status callback
    def test_status():
        return {
            "status": "playing",
            "current_content": "test_video.mp4"
        }

    reporter.set_status_callback(test_status)

    # Collect and display metrics
    metrics = reporter.collect_metrics()
    print("\nCollected Metrics:")
    for key, value in metrics.items():
        print(f"  {key}: {value}")

    # Send a test heartbeat
    print("\nSending test heartbeat...")
    result = reporter.send_heartbeat()
    print(f"Result: {'Success' if result else 'Failed (expected if no hub)'}")
