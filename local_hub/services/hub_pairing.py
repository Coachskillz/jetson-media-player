"""
Hub Pairing Service - Handles hub registration with CMS.

This module provides the pairing flow for local hubs to register with the CMS:
1. Generate a unique hardware ID and pairing code
2. Call /api/v1/hubs/announce to register with CMS
3. Display pairing code for admin to enter in CMS
4. Poll /api/v1/hubs/pairing-status until paired
5. Store credentials and start normal operation

Usage:
    from services.hub_pairing import HubPairingService

    service = HubPairingService(cms_url='http://localhost:5002')
    result = service.start_pairing()

    if result['status'] == 'paired':
        print(f"Paired as {result['store_name']}")
"""

import logging
import random
import string
import socket
import time
import uuid
from typing import Any, Dict, Optional

import requests


logger = logging.getLogger(__name__)


def get_hardware_id() -> str:
    """Generate a unique hardware ID for this hub."""
    # Try to get MAC address first
    try:
        mac = uuid.getnode()
        mac_str = ':'.join(f'{(mac >> i) & 0xff:02x}' for i in range(0, 48, 8))
        return f'HUB-{mac_str.replace(":", "").upper()[-8:]}'
    except Exception:
        pass

    # Fallback to random ID
    chars = ''.join(random.choices(string.hexdigits.upper(), k=8))
    return f'HUB-{chars}'


def generate_pairing_code() -> str:
    """Generate a pairing code to display on hub screen."""
    part1 = ''.join(random.choices(string.ascii_uppercase, k=3))
    part2 = ''.join(random.choices(string.digits, k=3))
    return f'{part1}-{part2}'


def get_local_ip() -> str:
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


class HubPairingService:
    """
    Service for pairing local hub with CMS.

    This service handles the full pairing lifecycle:
    1. Announce hub to CMS with pairing code
    2. Poll for pairing completion
    3. Store credentials for future use
    """

    def __init__(
        self,
        cms_url: str,
        hardware_id: Optional[str] = None,
        timeout: int = 10,
    ):
        """
        Initialize pairing service.

        Args:
            cms_url: CMS base URL
            hardware_id: Optional hardware ID (generated if not provided)
            timeout: Request timeout in seconds
        """
        self.cms_url = cms_url.rstrip('/')
        self.hardware_id = hardware_id or get_hardware_id()
        self.timeout = timeout
        self.pairing_code: Optional[str] = None

    def announce(self, version: str = '1.0.0') -> Dict[str, Any]:
        """
        Announce hub to CMS and get pairing code.

        Args:
            version: Hub software version

        Returns:
            Response from CMS
        """
        self.pairing_code = generate_pairing_code()

        url = f'{self.cms_url}/api/v1/hubs/announce'
        payload = {
            'hardware_id': self.hardware_id,
            'pairing_code': self.pairing_code,
            'wan_ip': get_local_ip(),
            'lan_ip': '10.10.10.1',
            'tunnel_url': f'{self.hardware_id.lower()}.skillzmedia.local',
            'version': version,
        }

        logger.info(f'Announcing hub to CMS: {self.hardware_id}')

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            data = response.json()

            if data.get('status') == 'already_paired':
                logger.info(f'Hub already paired as: {data.get("store_name")}')
                return data

            logger.info(f'Hub announced with pairing code: {self.pairing_code}')
            return data

        except Exception as e:
            logger.error(f'Failed to announce hub: {e}')
            return {'status': 'error', 'error': str(e)}

    def check_pairing_status(self) -> Dict[str, Any]:
        """
        Check if pairing has been completed.

        Returns:
            Pairing status from CMS
        """
        url = f'{self.cms_url}/api/v1/hubs/pairing-status'
        params = {'hardware_id': self.hardware_id}

        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            return response.json()
        except Exception as e:
            logger.error(f'Failed to check pairing status: {e}')
            return {'status': 'error', 'error': str(e)}

    def wait_for_pairing(
        self,
        poll_interval: int = 5,
        max_wait: int = 900,  # 15 minutes
        on_status: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Wait for admin to complete pairing in CMS.

        Args:
            poll_interval: Seconds between status checks
            max_wait: Maximum seconds to wait
            on_status: Optional callback for status updates

        Returns:
            Final pairing result
        """
        start_time = time.time()

        while time.time() - start_time < max_wait:
            status = self.check_pairing_status()

            if on_status:
                on_status(status)

            if status.get('status') == 'paired':
                logger.info(f'Hub paired successfully as: {status.get("store_name")}')
                return status

            if status.get('status') == 'expired':
                logger.warning('Pairing code expired, regenerating...')
                self.announce()

            elif status.get('status') == 'error':
                logger.error(f'Pairing error: {status.get("error")}')
                return status

            time.sleep(poll_interval)

        logger.error('Pairing timeout')
        return {'status': 'timeout', 'error': 'Pairing wait timeout'}

    def start_pairing(
        self,
        version: str = '1.0.0',
        poll_interval: int = 5,
        max_wait: int = 900,
        on_status: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Start the full pairing process.

        Args:
            version: Hub software version
            poll_interval: Seconds between status checks
            max_wait: Maximum seconds to wait for pairing
            on_status: Optional callback for status updates

        Returns:
            Pairing result with credentials if successful
        """
        # First announce
        announce_result = self.announce(version)

        if announce_result.get('status') == 'already_paired':
            return announce_result

        if announce_result.get('status') == 'error':
            return announce_result

        # Wait for pairing
        return self.wait_for_pairing(
            poll_interval=poll_interval,
            max_wait=max_wait,
            on_status=on_status,
        )


def check_and_pair_hub(app) -> Optional[Dict[str, Any]]:
    """
    Check if hub is registered, if not start pairing flow.

    This function is called during hub startup to ensure the hub
    is properly paired with the CMS.

    Args:
        app: Flask application instance

    Returns:
        Pairing result if pairing was needed, None if already registered
    """
    from models.hub_config import HubConfig

    with app.app_context():
        config = app.config['HUB_CONFIG']
        hub_config = HubConfig.get_instance()

        if hub_config.is_registered:
            logger.info(f'Hub already registered: {hub_config.hub_id}')
            return None

        logger.info('Hub not registered, starting pairing flow...')

        service = HubPairingService(cms_url=config.cms_url)

        def status_callback(status):
            if status.get('status') == 'pending':
                logger.info(f'Waiting for pairing... Code: {service.pairing_code}')
            elif status.get('status') == 'expired':
                logger.info(f'New pairing code: {service.pairing_code}')

        result = service.start_pairing(on_status=status_callback)

        if result.get('status') == 'paired':
            # Store credentials
            HubConfig.update_registration(
                hub_id=result.get('hub_id'),
                hub_token=result.get('api_token'),
                hub_code=result.get('hub_code'),
                hub_name=result.get('store_name'),
                network_id=result.get('network_id'),
                status='active',
            )
            logger.info(f'Hub paired and credentials stored')

        return result
