"""
Hub Registration Service.

This module provides the RegistrationService class for handling hub registration
with the CMS. It manages:
- Initial registration on first boot
- Storing credentials in the local database
- Re-registration if credentials are invalid

The registration flow:
1. Check if hub is already registered (has valid credentials)
2. If not, call CMS /api/v1/hubs/register with hub details
3. Store returned credentials (hub_id, api_token) in HubConfig
4. Hub is now ready to sync content and send heartbeats

Example:
    from services.registration_service import RegistrationService
    from services.hq_client import HQClient
    from config import load_config

    config = load_config()
    hq_client = HQClient(config.cms_url)
    service = RegistrationService(hq_client, config)

    # Check and register if needed
    result = service.ensure_registered()
    if result['registered']:
        print(f"Hub registered as {result['hub_id']}")
"""

import logging
import socket
import uuid
from typing import Any, Dict, Optional

from services import HQClientError, ServiceError
from services.hq_client import HQClient
from config import HubConfig as FileConfig


logger = logging.getLogger(__name__)


class RegistrationError(ServiceError):
    """Exception raised when hub registration fails."""
    pass


class RegistrationService:
    """
    Service for managing hub registration with CMS.

    This service handles the registration flow for local hubs,
    ensuring they have valid credentials for communicating with
    the CMS for content sync, heartbeats, and alerts.

    Attributes:
        hq_client: HQClient instance for CMS communication
        config: HubConfig instance with registration details
    """

    def __init__(self, hq_client: HQClient, config: FileConfig):
        """
        Initialize the registration service.

        Args:
            hq_client: HQClient instance (does not need to be authenticated)
            config: HubConfig instance with hub_code, hub_name, network_id
        """
        self.hq_client = hq_client
        self.config = config
        logger.info("RegistrationService initialized")

    def is_registered(self) -> bool:
        """
        Check if hub is already registered with valid credentials.

        Returns:
            True if hub has valid hub_id and hub_token in database
        """
        from models.hub_config import HubConfig as DBHubConfig

        hub_config = DBHubConfig.get_instance()
        return hub_config.is_registered

    def get_registration_status(self) -> Dict[str, Any]:
        """
        Get current registration status and details.

        Returns:
            Dictionary with registration status and hub details
        """
        from models.hub_config import HubConfig as DBHubConfig

        hub_config = DBHubConfig.get_instance()

        return {
            'registered': hub_config.is_registered,
            'hub_id': hub_config.hub_id,
            'hub_code': hub_config.hub_code,
            'hub_name': hub_config.hub_name,
            'network_id': hub_config.network_id,
            'status': hub_config.status,
            'registered_at': hub_config.registered_at.isoformat() if hub_config.registered_at else None,
        }

    def _get_machine_info(self) -> Dict[str, str]:
        """
        Gather machine information for registration.

        Returns:
            Dictionary with hostname, ip_address, mac_address
        """
        info = {
            'hostname': socket.gethostname(),
        }

        # Try to get IP address
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            info['ip_address'] = s.getsockname()[0]
            s.close()
        except Exception:
            pass

        # Try to get MAC address
        try:
            mac = uuid.getnode()
            mac_str = ':'.join(f'{(mac >> i) & 0xff:02x}' for i in range(0, 48, 8))[::-1]
            # Reverse and format properly
            mac_bytes = mac.to_bytes(6, 'big')
            mac_str = ':'.join(f'{b:02X}' for b in mac_bytes)
            info['mac_address'] = mac_str
        except Exception:
            pass

        return info

    def register(self) -> Dict[str, Any]:
        """
        Register hub with CMS.

        This method sends registration request to CMS with hub details
        from the config file, and stores the returned credentials.

        Returns:
            Registration result dictionary with:
            - registered: True if registration succeeded
            - hub_id: Hub UUID from CMS
            - hub_code: Hub code
            - status: Hub status (usually 'pending' until approved)

        Raises:
            RegistrationError: If registration fails
        """
        from models.hub_config import HubConfig as DBHubConfig

        # Validate required config values
        if not self.config.hub_code:
            raise RegistrationError(
                "hub_code is required for registration",
                details={'config_key': 'hub_code'}
            )

        if not self.config.hub_name:
            raise RegistrationError(
                "hub_name is required for registration",
                details={'config_key': 'hub_name'}
            )

        if not self.config.network_id:
            raise RegistrationError(
                "network_id is required for registration",
                details={'config_key': 'network_id'}
            )

        # Gather machine info
        machine_info = self._get_machine_info()

        logger.info(
            f"Registering hub '{self.config.hub_code}' ({self.config.hub_name}) "
            f"with network {self.config.network_id}"
        )

        try:
            # Call CMS registration endpoint
            response = self.hq_client.register_hub(
                code=self.config.hub_code,
                name=self.config.hub_name,
                network_id=self.config.network_id,
                ip_address=machine_info.get('ip_address'),
                mac_address=machine_info.get('mac_address'),
                hostname=machine_info.get('hostname'),
            )

            # Store credentials in database
            DBHubConfig.update_registration(
                hub_id=response['hub_id'],
                hub_token=response['hub_token'],
                hub_code=response.get('hub_code'),
                hub_name=response.get('hub_name'),
                network_id=response.get('network_id'),
                status=response.get('status', 'pending'),
            )

            logger.info(
                f"Hub registered successfully: "
                f"hub_id={response['hub_id']}, status={response.get('status')}"
            )

            return {
                'registered': True,
                'hub_id': response['hub_id'],
                'hub_code': response.get('hub_code'),
                'hub_name': response.get('hub_name'),
                'network_id': response.get('network_id'),
                'status': response.get('status', 'pending'),
            }

        except HQClientError as e:
            logger.error(f"Hub registration failed: {e}")
            raise RegistrationError(
                f"Registration failed: {e.message}",
                details={
                    'status_code': e.status_code,
                    'response': e.response_body,
                }
            )

    def ensure_registered(self) -> Dict[str, Any]:
        """
        Ensure hub is registered, registering if needed.

        This is the main entry point for registration. It checks if the
        hub is already registered and only calls register() if needed.

        Returns:
            Registration status dictionary with:
            - registered: True if hub is registered (new or existing)
            - hub_id: Hub UUID
            - newly_registered: True if registration happened in this call

        Raises:
            RegistrationError: If registration is needed but fails
        """
        # Check if already registered
        if self.is_registered():
            status = self.get_registration_status()
            status['newly_registered'] = False
            logger.info(f"Hub already registered as {status['hub_id']}")
            return status

        # Not registered - attempt registration
        logger.info("Hub not registered, attempting registration...")
        result = self.register()
        result['newly_registered'] = True
        return result

    def clear_registration(self) -> None:
        """
        Clear stored registration credentials.

        This forces re-registration on next ensure_registered() call.
        Use with caution - only for debugging/testing.
        """
        from models.hub_config import HubConfig as DBHubConfig

        hub_config = DBHubConfig.get_instance()
        hub_config.hub_id = None
        hub_config.hub_token = None
        hub_config.hub_code = None
        hub_config.hub_name = None
        hub_config.network_id = None
        hub_config.status = 'pending'
        hub_config.registered_at = None

        from models import db
        db.session.commit()

        logger.warning("Hub registration cleared")

    def __repr__(self) -> str:
        """String representation."""
        return f"<RegistrationService hub_code={self.config.hub_code}>"
