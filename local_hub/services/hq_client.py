"""
HQ Client - Communication with cloud HQ service.

This module provides the HQClient class for all communication with the
cloud HQ (headquarters) service. It handles:
- Session pooling for efficient connection reuse
- Bearer token authentication
- Timeout handling with proper error types
- Automatic retry for transient failures

The client uses the hub_token stored in HubConfig for authentication
after initial registration.

Example:
    from services.hq_client import HQClient
    from config import load_config

    config = load_config()
    client = HQClient(config.hq_url)

    # After registration, use token from HubConfig
    client.set_token(hub_config.hub_token)

    # Make authenticated requests
    manifest = client.get_content_manifest()
"""

import logging
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    RequestException,
    Timeout,
)
from urllib3.util.retry import Retry

from services import (
    HQAuthenticationError,
    HQClientError,
    HQConnectionError,
    HQTimeoutError,
)


logger = logging.getLogger(__name__)


# Default configuration
DEFAULT_TIMEOUT = 30  # seconds
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.5


class HQClient:
    """
    Client for communicating with the cloud HQ service.

    This client handles all HTTP communication with HQ, including:
    - Hub registration and authentication
    - Content manifest retrieval
    - Database version checks and downloads
    - Alert forwarding
    - Heartbeat reporting

    Attributes:
        base_url: HQ API base URL
        timeout: Request timeout in seconds
        session: Requests session for connection pooling
    """

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    ):
        """
        Initialize the HQ client.

        Args:
            base_url: HQ API base URL (e.g., 'https://hub.skillzmedia.com')
            token: Optional authentication token (can be set later)
            timeout: Request timeout in seconds (default: 30)
            max_retries: Maximum retry attempts for transient failures (default: 3)
            backoff_factor: Exponential backoff factor for retries (default: 0.5)
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self._token: Optional[str] = token

        # Create session with connection pooling
        self.session = requests.Session()

        # Configure retry strategy for transient failures
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=['HEAD', 'GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'TRACE'],
        )

        # Mount retry adapter for both HTTP and HTTPS
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10,
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        # Set default headers
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'SkillzHub/1.0',
        })

        # Set auth token if provided
        if token:
            self.set_token(token)

        logger.info(f"HQ client initialized with base URL: {self.base_url}")

    def set_token(self, token: str) -> None:
        """
        Set or update the authentication token.

        Args:
            token: Bearer token for HQ API authentication
        """
        self._token = token
        self.session.headers['Authorization'] = f'Bearer {token}'
        logger.debug("HQ client authentication token updated")

    def clear_token(self) -> None:
        """Remove authentication token from session."""
        self._token = None
        self.session.headers.pop('Authorization', None)
        logger.debug("HQ client authentication token cleared")

    @property
    def is_authenticated(self) -> bool:
        """Check if client has an authentication token set."""
        return self._token is not None

    def _build_url(self, endpoint: str) -> str:
        """
        Build full URL from endpoint.

        Args:
            endpoint: API endpoint path (e.g., '/api/v1/content')

        Returns:
            Full URL string
        """
        endpoint = endpoint.lstrip('/')
        return f"{self.base_url}/{endpoint}"

    def _handle_response(self, response: requests.Response, endpoint: str) -> Dict[str, Any]:
        """
        Handle HTTP response and convert errors to exceptions.

        Args:
            response: HTTP response object
            endpoint: Original endpoint for error context

        Returns:
            Parsed JSON response data

        Raises:
            HQAuthenticationError: When authentication fails (401/403)
            HQClientError: For other HTTP errors
        """
        # Check for authentication errors
        if response.status_code in (401, 403):
            logger.error(f"HQ authentication failed for {endpoint}: {response.status_code}")
            raise HQAuthenticationError(
                message=f"Authentication failed for {endpoint}",
                status_code=response.status_code,
                response_body=response.text,
            )

        # Check for other HTTP errors
        if not response.ok:
            logger.error(f"HQ request failed for {endpoint}: {response.status_code}")
            raise HQClientError(
                message=f"Request failed for {endpoint}",
                status_code=response.status_code,
                response_body=response.text,
            )

        # Parse JSON response
        try:
            return response.json()
        except ValueError:
            # Response was successful but not JSON
            return {'status': 'ok', 'raw': response.text}

    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Make authenticated GET request to HQ.

        Args:
            endpoint: API endpoint path
            params: Optional query parameters

        Returns:
            Parsed JSON response

        Raises:
            HQConnectionError: When connection fails
            HQTimeoutError: When request times out
            HQAuthenticationError: When authentication fails
            HQClientError: For other request errors
        """
        url = self._build_url(endpoint)

        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.timeout,
            )
            return self._handle_response(response, endpoint)

        except Timeout as e:
            logger.error(f"HQ request timeout for {endpoint}: {e}")
            raise HQTimeoutError(
                message=f"Request timed out for {endpoint}",
                details={'timeout': self.timeout},
            )

        except RequestsConnectionError as e:
            logger.error(f"HQ connection failed for {endpoint}: {e}")
            raise HQConnectionError(
                message=f"Connection failed for {endpoint}",
                details={'error': str(e)},
            )

        except RequestException as e:
            logger.error(f"HQ request error for {endpoint}: {e}")
            raise HQClientError(
                message=f"Request error for {endpoint}",
                details={'error': str(e)},
            )

    def post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make authenticated POST request to HQ.

        Args:
            endpoint: API endpoint path
            data: JSON request body
            params: Optional query parameters

        Returns:
            Parsed JSON response

        Raises:
            HQConnectionError: When connection fails
            HQTimeoutError: When request times out
            HQAuthenticationError: When authentication fails
            HQClientError: For other request errors
        """
        url = self._build_url(endpoint)

        try:
            response = self.session.post(
                url,
                json=data,
                params=params,
                timeout=self.timeout,
            )
            return self._handle_response(response, endpoint)

        except Timeout as e:
            logger.error(f"HQ request timeout for {endpoint}: {e}")
            raise HQTimeoutError(
                message=f"Request timed out for {endpoint}",
                details={'timeout': self.timeout},
            )

        except RequestsConnectionError as e:
            logger.error(f"HQ connection failed for {endpoint}: {e}")
            raise HQConnectionError(
                message=f"Connection failed for {endpoint}",
                details={'error': str(e)},
            )

        except RequestException as e:
            logger.error(f"HQ request error for {endpoint}: {e}")
            raise HQClientError(
                message=f"Request error for {endpoint}",
                details={'error': str(e)},
            )

    def download_file(
        self,
        endpoint: str,
        destination: str,
        chunk_size: int = 8192,
    ) -> str:
        """
        Download file from HQ to local path.

        Args:
            endpoint: API endpoint path for file download
            destination: Local file path to save download
            chunk_size: Download chunk size in bytes

        Returns:
            Path to downloaded file

        Raises:
            HQConnectionError: When connection fails
            HQTimeoutError: When request times out
            HQAuthenticationError: When authentication fails
            HQClientError: For other request errors
        """
        url = self._build_url(endpoint)

        try:
            # Use streaming download for large files
            with self.session.get(url, stream=True, timeout=self.timeout) as response:
                # Check for errors before downloading
                if response.status_code in (401, 403):
                    raise HQAuthenticationError(
                        message=f"Authentication failed for {endpoint}",
                        status_code=response.status_code,
                    )

                if not response.ok:
                    raise HQClientError(
                        message=f"Download failed for {endpoint}",
                        status_code=response.status_code,
                    )

                # Download file in chunks
                with open(destination, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)

            logger.info(f"Downloaded {endpoint} to {destination}")
            return destination

        except Timeout as e:
            logger.error(f"HQ download timeout for {endpoint}: {e}")
            raise HQTimeoutError(
                message=f"Download timed out for {endpoint}",
                details={'timeout': self.timeout},
            )

        except RequestsConnectionError as e:
            logger.error(f"HQ connection failed for {endpoint}: {e}")
            raise HQConnectionError(
                message=f"Connection failed for {endpoint}",
                details={'error': str(e)},
            )

        except RequestException as e:
            logger.error(f"HQ download error for {endpoint}: {e}")
            raise HQClientError(
                message=f"Download error for {endpoint}",
                details={'error': str(e)},
            )

    def close(self) -> None:
        """Close the session and release resources."""
        self.session.close()
        logger.info("HQ client session closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close session."""
        self.close()
        return False

    # -------------------------------------------------------------------------
    # Hub Registration
    # -------------------------------------------------------------------------

    def register_hub(
        self,
        network_slug: str,
        machine_id: Optional[str] = None,
        hostname: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Register hub with HQ on first boot.

        This method is called when the hub starts without credentials.
        It sends the network_slug to HQ and receives hub_id and hub_token
        for future authenticated requests.

        Args:
            network_slug: Network identifier (e.g., 'high-octane')
            machine_id: Optional unique machine identifier (e.g., MAC address)
            hostname: Optional hostname for identification

        Returns:
            Registration response containing:
            - hub_id: Unique identifier for this hub
            - hub_token: Authentication token for HQ API
            - network_id: Network identifier
            - store_id: Store location identifier (if assigned)

        Raises:
            HQConnectionError: When HQ is unreachable
            HQTimeoutError: When registration times out
            HQClientError: For registration failures (invalid network_slug, etc.)

        Example:
            client = HQClient('https://hub.skillzmedia.com')
            result = client.register_hub('high-octane', machine_id='ab:cd:ef:12:34:56')
            # result = {'hub_id': 'hub_123', 'hub_token': 'secret', ...}
            # Token is automatically set for future requests
        """
        endpoint = '/api/v1/hubs/register'
        url = self._build_url(endpoint)

        # Build registration payload
        payload: Dict[str, Any] = {
            'network_slug': network_slug,
        }

        if machine_id:
            payload['machine_id'] = machine_id

        if hostname:
            payload['hostname'] = hostname

        logger.info(f"Registering hub with HQ for network: {network_slug}")

        try:
            # Registration does not require authentication
            # Temporarily remove auth header if present
            auth_header = self.session.headers.pop('Authorization', None)

            try:
                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.timeout,
                )
            finally:
                # Restore auth header if it was present
                if auth_header:
                    self.session.headers['Authorization'] = auth_header

            # Check for specific registration errors
            if response.status_code == 400:
                logger.error(f"Invalid registration request: {response.text}")
                raise HQClientError(
                    message="Invalid registration request",
                    status_code=400,
                    response_body=response.text,
                )

            if response.status_code == 404:
                logger.error(f"Network not found: {network_slug}")
                raise HQClientError(
                    message=f"Network not found: {network_slug}",
                    status_code=404,
                    response_body=response.text,
                )

            if response.status_code == 409:
                logger.error(f"Hub already registered with this machine_id")
                raise HQClientError(
                    message="Hub already registered with this machine_id",
                    status_code=409,
                    response_body=response.text,
                )

            # Handle general errors
            if not response.ok:
                logger.error(f"Registration failed: {response.status_code}")
                raise HQClientError(
                    message=f"Registration failed for network {network_slug}",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            # Parse successful response
            data = response.json()

            # Validate required fields in response
            if 'hub_id' not in data or 'hub_token' not in data:
                logger.error(f"Invalid registration response: missing hub_id or hub_token")
                raise HQClientError(
                    message="Invalid registration response from HQ",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            # Automatically set the token for future requests
            self.set_token(data['hub_token'])

            logger.info(f"Hub registered successfully with hub_id: {data['hub_id']}")

            return data

        except Timeout as e:
            logger.error(f"Registration timeout: {e}")
            raise HQTimeoutError(
                message="Registration request timed out",
                details={'timeout': self.timeout, 'network_slug': network_slug},
            )

        except RequestsConnectionError as e:
            logger.error(f"Registration connection failed: {e}")
            raise HQConnectionError(
                message="Cannot connect to HQ for registration",
                details={'error': str(e), 'network_slug': network_slug},
            )

        except RequestException as e:
            logger.error(f"Registration request error: {e}")
            raise HQClientError(
                message="Registration request failed",
                details={'error': str(e), 'network_slug': network_slug},
            )

    # -------------------------------------------------------------------------
    # Heartbeat Reporting
    # -------------------------------------------------------------------------

    def send_heartbeat(
        self,
        hub_id: str,
        screens: Optional[List[Dict[str, Any]]] = None,
        hub_status: str = 'online',
        uptime_seconds: Optional[int] = None,
        disk_usage_percent: Optional[float] = None,
        pending_alerts_count: Optional[int] = None,
        last_sync_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send heartbeat to HQ reporting hub status and screen statuses.

        This method is called periodically (default: every 60 seconds) by the
        background scheduler to report the hub's health and the status of all
        connected screens to HQ.

        Args:
            hub_id: The hub's unique identifier from registration
            screens: List of screen status dictionaries, each containing:
                - screen_id: Screen's ID
                - hardware_id: Hardware identifier
                - status: 'online' or 'offline'
                - last_heartbeat: ISO timestamp of last heartbeat
            hub_status: Hub's current status ('online', 'degraded', 'error')
            uptime_seconds: Hub's uptime in seconds (optional)
            disk_usage_percent: Percentage of disk space used (optional)
            pending_alerts_count: Number of alerts waiting to be sent (optional)
            last_sync_at: ISO timestamp of last successful sync (optional)

        Returns:
            Response from HQ, may contain:
            - ack: Acknowledgement status
            - commands: Optional list of commands for hub to execute
            - config_update: Optional configuration updates

        Raises:
            HQConnectionError: When HQ is unreachable
            HQTimeoutError: When request times out
            HQAuthenticationError: When authentication fails
            HQClientError: For other request errors

        Example:
            client = HQClient('https://hub.skillzmedia.com', token='...')
            screens = [
                {'screen_id': 1, 'hardware_id': 'abc123', 'status': 'online'},
                {'screen_id': 2, 'hardware_id': 'def456', 'status': 'offline'},
            ]
            result = client.send_heartbeat(
                hub_id='hub_123',
                screens=screens,
                hub_status='online',
                uptime_seconds=3600,
            )
        """
        if not self.is_authenticated:
            logger.error("Cannot send heartbeat: client not authenticated")
            raise HQAuthenticationError(
                message="Client not authenticated for heartbeat",
                status_code=401,
            )

        endpoint = '/api/v1/hubs/heartbeat'
        url = self._build_url(endpoint)

        # Build heartbeat payload
        payload: Dict[str, Any] = {
            'hub_id': hub_id,
            'hub_status': hub_status,
            'screens': screens or [],
        }

        # Add optional metrics
        if uptime_seconds is not None:
            payload['uptime_seconds'] = uptime_seconds

        if disk_usage_percent is not None:
            payload['disk_usage_percent'] = disk_usage_percent

        if pending_alerts_count is not None:
            payload['pending_alerts_count'] = pending_alerts_count

        if last_sync_at is not None:
            payload['last_sync_at'] = last_sync_at

        logger.debug(f"Sending heartbeat for hub {hub_id} with {len(screens or [])} screens")

        try:
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout,
            )
            return self._handle_response(response, endpoint)

        except Timeout as e:
            logger.warning(f"Heartbeat timeout: {e}")
            raise HQTimeoutError(
                message="Heartbeat request timed out",
                details={'timeout': self.timeout, 'hub_id': hub_id},
            )

        except RequestsConnectionError as e:
            logger.warning(f"Heartbeat connection failed: {e}")
            raise HQConnectionError(
                message="Cannot connect to HQ for heartbeat",
                details={'error': str(e), 'hub_id': hub_id},
            )

        except RequestException as e:
            logger.error(f"Heartbeat request error: {e}")
            raise HQClientError(
                message="Heartbeat request failed",
                details={'error': str(e), 'hub_id': hub_id},
            )

    def build_screen_status_list(
        self,
        screens: List[Any],
    ) -> List[Dict[str, Any]]:
        """
        Build screen status list for heartbeat payload.

        This is a helper method to convert Screen model instances
        into the dictionary format expected by send_heartbeat().

        Args:
            screens: List of Screen model instances (or objects with to_dict())

        Returns:
            List of screen status dictionaries suitable for heartbeat

        Example:
            from models import Screen
            screens = Screen.query.all()
            screen_statuses = client.build_screen_status_list(screens)
            client.send_heartbeat(hub_id, screens=screen_statuses)
        """
        screen_list = []
        for screen in screens:
            # Support both dict and objects with to_dict()
            if hasattr(screen, 'to_dict'):
                screen_data = screen.to_dict()
            elif isinstance(screen, dict):
                screen_data = screen
            else:
                continue

            # Extract only the fields needed for heartbeat
            screen_list.append({
                'screen_id': screen_data.get('id'),
                'hardware_id': screen_data.get('hardware_id'),
                'status': screen_data.get('status', 'unknown'),
                'last_heartbeat': screen_data.get('last_heartbeat'),
                'name': screen_data.get('name'),
            })

        return screen_list

    def __repr__(self) -> str:
        """String representation."""
        auth_status = 'authenticated' if self.is_authenticated else 'unauthenticated'
        return f"<HQClient url={self.base_url} {auth_status}>"
