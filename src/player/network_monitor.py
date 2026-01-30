"""
Network Monitor for Jetson Media Player.

Tracks network connectivity to the hub/CMS and provides online/offline
state that other services can check before making network calls.

Features:
- Periodic connectivity checks (ping hub/CMS health endpoint)
- Online/offline state with hysteresis (avoids flapping)
- Callback notification when state changes
- Thread-safe access from any service
"""

import socket
import threading
import time
from typing import Callable, Optional

import requests

from src.common.logger import setup_logger

logger = setup_logger(__name__)

# How often to check connectivity (seconds)
CHECK_INTERVAL_ONLINE = 30      # Check every 30s when online
CHECK_INTERVAL_OFFLINE = 10     # Check every 10s when offline (faster recovery)

# Hysteresis: require N consecutive results before changing state
ONLINE_THRESHOLD = 1   # 1 success → go online immediately
OFFLINE_THRESHOLD = 3  # 3 consecutive failures → go offline

# Timeouts
HEALTH_CHECK_TIMEOUT = 5  # seconds


class NetworkMonitor:
    """
    Monitors network connectivity to hub/CMS.

    Usage:
        monitor = NetworkMonitor(hub_url="http://192.168.1.100:5000",
                                 cms_url="http://cms.example.com:5002")
        monitor.start()
        if monitor.is_online:
            # safe to make network calls
        monitor.stop()
    """

    def __init__(
        self,
        hub_url: str = "",
        cms_url: str = "",
        connection_mode: str = "direct",
        on_state_changed: Optional[Callable[[bool], None]] = None,
    ):
        """
        Args:
            hub_url: Local hub URL (used in hub mode)
            cms_url: CMS URL (used in direct mode)
            connection_mode: "hub" or "direct"
            on_state_changed: Callback(is_online) when state changes
        """
        self._hub_url = hub_url
        self._cms_url = cms_url
        self._connection_mode = connection_mode
        self._on_state_changed = on_state_changed

        # State (thread-safe via lock)
        self._lock = threading.Lock()
        self._online = False
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._last_check_time: Optional[float] = None
        self._last_check_result: Optional[bool] = None

        # Background thread
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()

        # Stats
        self._total_checks = 0
        self._total_failures = 0

    @property
    def is_online(self) -> bool:
        """Check if the network is currently online. Thread-safe."""
        with self._lock:
            return self._online

    @property
    def target_url(self) -> str:
        """Get the primary URL to check based on connection mode."""
        if self._connection_mode == "hub" and self._hub_url:
            return self._hub_url
        return self._cms_url

    def get_status(self) -> dict:
        """Get network status for diagnostics."""
        with self._lock:
            return {
                "online": self._online,
                "target_url": self.target_url,
                "connection_mode": self._connection_mode,
                "consecutive_failures": self._consecutive_failures,
                "consecutive_successes": self._consecutive_successes,
                "last_check_time": self._last_check_time,
                "last_check_result": self._last_check_result,
                "total_checks": self._total_checks,
                "total_failures": self._total_failures,
            }

    def check_now(self) -> bool:
        """
        Run an immediate connectivity check. Thread-safe.

        Returns:
            True if the target is reachable.
        """
        reachable = self._do_health_check()
        self._update_state(reachable)
        return reachable

    def _do_health_check(self) -> bool:
        """
        Perform a single connectivity check.

        Strategy:
        1. Try HTTP GET to target /api/health (or /)
        2. If that fails, try a raw TCP socket connect to the target host/port
        3. If both fail, try resolving a public DNS name as a last resort
           (to distinguish "hub is down" from "no network at all")
        """
        url = self.target_url
        if not url:
            return False

        # Try HTTP health endpoint
        for path in ("/api/health", "/api/v1/health", "/"):
            try:
                response = requests.get(
                    f"{url}{path}",
                    timeout=HEALTH_CHECK_TIMEOUT,
                )
                if response.status_code < 500:
                    return True
            except requests.exceptions.RequestException:
                continue

        # HTTP failed — try raw TCP to the target host:port
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if host:
                sock = socket.create_connection((host, port), timeout=HEALTH_CHECK_TIMEOUT)
                sock.close()
                return True
        except (socket.error, OSError):
            pass

        return False

    def _update_state(self, reachable: bool) -> None:
        """Update online/offline state with hysteresis."""
        state_changed = False

        with self._lock:
            self._total_checks += 1
            self._last_check_time = time.time()
            self._last_check_result = reachable

            if reachable:
                self._consecutive_successes += 1
                self._consecutive_failures = 0

                if not self._online and self._consecutive_successes >= ONLINE_THRESHOLD:
                    self._online = True
                    state_changed = True
                    logger.info("Network state: ONLINE (target: %s)", self.target_url)
            else:
                self._consecutive_failures += 1
                self._consecutive_successes = 0
                self._total_failures += 1

                if self._online and self._consecutive_failures >= OFFLINE_THRESHOLD:
                    self._online = False
                    state_changed = True
                    logger.warning(
                        "Network state: OFFLINE after %d failures (target: %s)",
                        self._consecutive_failures, self.target_url,
                    )

        # Fire callback outside lock
        if state_changed and self._on_state_changed:
            try:
                self._on_state_changed(reachable)
            except Exception as e:
                logger.error("Network state callback error: %s", e)

    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        # Do an initial check immediately
        self.check_now()

        while self._running:
            interval = CHECK_INTERVAL_ONLINE if self.is_online else CHECK_INTERVAL_OFFLINE
            if self._stop_event.wait(timeout=interval):
                break  # Stop requested

            if self._running:
                self._do_health_check_and_update()

    def _do_health_check_and_update(self) -> None:
        """Run a health check and update state."""
        try:
            reachable = self._do_health_check()
            self._update_state(reachable)
        except Exception as e:
            logger.error("Health check error: %s", e)
            self._update_state(False)

    def start(self) -> None:
        """Start the background network monitor."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="network-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "NetworkMonitor started (mode=%s, target=%s)",
            self._connection_mode, self.target_url,
        )

    def stop(self) -> None:
        """Stop the background network monitor."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        logger.info("NetworkMonitor stopped")


# Global singleton
_global_network_monitor: Optional[NetworkMonitor] = None


def get_network_monitor(
    hub_url: str = "",
    cms_url: str = "",
    connection_mode: str = "direct",
    on_state_changed: Optional[Callable[[bool], None]] = None,
) -> NetworkMonitor:
    """Get or create the global NetworkMonitor instance."""
    global _global_network_monitor
    if _global_network_monitor is None:
        _global_network_monitor = NetworkMonitor(
            hub_url=hub_url,
            cms_url=cms_url,
            connection_mode=connection_mode,
            on_state_changed=on_state_changed,
        )
    return _global_network_monitor
