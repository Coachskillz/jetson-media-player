"""
Service layer for Local Hub.

This module provides services for:
- HQ communication and authentication
- Content and database synchronization
- Alert forwarding with reliable retry
- Screen monitoring

Base exception classes are defined here for consistent error handling
across all services.

Example:
    from services import HQClientError, SyncError
    from services.hq_client import HQClient

    try:
        client = HQClient(config)
        client.heartbeat()
    except HQClientError as e:
        logger.error(f"HQ communication failed: {e}")
"""


class ServiceError(Exception):
    """
    Base exception for all service layer errors.

    All service-specific exceptions should inherit from this class
    to allow catching any service error with a single except clause.
    """

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message}: {self.details}"
        return self.message


class HQClientError(ServiceError):
    """
    Exception raised when HQ API communication fails.

    This includes network errors, authentication failures,
    timeout errors, and unexpected API responses.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: str | None = None,
        details: dict | None = None,
    ):
        super().__init__(message, details)
        self.status_code = status_code
        self.response_body = response_body


class HQAuthenticationError(HQClientError):
    """
    Exception raised when HQ authentication fails.

    This occurs when the hub token is invalid, expired,
    or the hub has not been registered.
    """

    pass


class HQTimeoutError(HQClientError):
    """
    Exception raised when HQ request times out.

    This indicates the HQ server did not respond within
    the configured timeout period.
    """

    pass


class HQConnectionError(HQClientError):
    """
    Exception raised when connection to HQ fails.

    This indicates network-level failures such as
    DNS resolution failures or connection refused.
    """

    pass


class SyncError(ServiceError):
    """
    Exception raised when content or database sync fails.

    This includes failures to download content, hash
    mismatches, and file system errors during sync.
    """

    pass


class AlertForwardError(ServiceError):
    """
    Exception raised when alert forwarding fails.

    Note: Failed alerts should never be lost - they must
    be queued in PendingAlerts for retry.
    """

    pass


class ScreenMonitorError(ServiceError):
    """
    Exception raised by screen monitoring service.
    """

    pass


# Import services as they are created
from services.hq_client import HQClient
from services.sync_service import SyncService
from services.alert_forwarder import AlertForwarder
from services.screen_monitor import ScreenMonitor

__all__ = [
    # Exception classes
    'ServiceError',
    'HQClientError',
    'HQAuthenticationError',
    'HQTimeoutError',
    'HQConnectionError',
    'SyncError',
    'AlertForwardError',
    'ScreenMonitorError',
    # Service classes
    'HQClient',
    'SyncService',
    'AlertForwarder',
    'ScreenMonitor',
]
