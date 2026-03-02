"""
CMS Client - Device pairing with 6-digit code
"""

import requests
import random
import time
from typing import Optional, Any, Callable
from src.common.device_id import get_device_info
from src.common.logger import setup_logger

logger = setup_logger(__name__)

# Retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_TIMEOUT = 5  # seconds


def retry_with_backoff(
    func: Callable,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
) -> Any:
    """
    Execute a function with exponential backoff retry logic.

    Args:
        func: The function to execute (should raise on failure)
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds

    Returns:
        The result of the successful function call

    Raises:
        The last exception if all retries fail
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return func()
        except requests.exceptions.ConnectionError as e:
            last_exception = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    f"Connection error (attempt {attempt + 1}/{max_retries + 1}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)
        except requests.exceptions.Timeout as e:
            last_exception = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    f"Request timeout (attempt {attempt + 1}/{max_retries + 1}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)
        except requests.exceptions.RequestException as e:
            last_exception = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    f"Request failed (attempt {attempt + 1}/{max_retries + 1}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)

    raise last_exception


def generate_pairing_code():
    """Generate a random 6-digit pairing code."""
    return str(random.randint(100000, 999999))


class CMSClient:
    """Client for communicating with the CMS or Hub."""

    def __init__(
        self,
        cms_url: str = "https://keen-ambition-production.up.railway.app",
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: int = DEFAULT_TIMEOUT,
        is_hub: bool = False,
    ):
        self.cms_url = cms_url
        self.device_info = get_device_info()
        self.paired = False
        self.pairing_code = None
        self.max_retries = max_retries
        self.timeout = timeout
        self.is_hub = is_hub  # True if connecting to local Hub, False for CMS

    def _get_hardware_id(self) -> str:
        """Get the hardware_id for API requests (uses device_id from device_info)."""
        return self.device_info['device_id']

    def request_pairing(self) -> Optional[str]:
        """Request pairing - works with both Hub and CMS.

        Hub mode: Jetson generates code, sends to Hub, Hub forwards to CMS.
        Direct mode: CMS generates the code server-side.

        Returns:
            The 6-digit pairing code if successful, None otherwise.
        """
        hardware_id = self._get_hardware_id()

        if self.is_hub:
            # Hub mode: generate code locally, send to Hub
            code = generate_pairing_code()
            ip_address = self.device_info.get('ip_address')

            def make_request():
                return requests.post(
                    f"{self.cms_url}/api/v1/pairing/request",
                    json={
                        "hardware_id": hardware_id,
                        "pairing_code": code,
                        "name": self.device_info.get('hostname', 'Jetson Device'),
                        "ip_address": ip_address,
                    },
                    timeout=self.timeout
                )
        else:
            # Direct mode: CMS generates the code
            def make_request():
                return requests.post(
                    f"{self.cms_url}/api/v1/devices/pairing/request",
                    json={
                        "hardware_id": hardware_id,
                    },
                    timeout=self.timeout
                )

        try:
            response = retry_with_backoff(make_request, max_retries=self.max_retries)

            if response.status_code == 200:
                data = response.json()
                self.pairing_code = data.get('pairing_code') or code if self.is_hub else data.get('pairing_code')
                if self.pairing_code:
                    logger.info(f"Pairing requested. Code: {self.pairing_code}")
                    return self.pairing_code
                else:
                    logger.error("No pairing code received")
                    return None
            elif response.status_code == 404:
                logger.error(f"Pairing endpoint not found at {self.cms_url}")
                return None
            else:
                logger.error(f"Pairing request failed: {response.status_code}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to request pairing after retries: {e}")
            return None

    def check_pairing_status(self) -> bool:
        """Check if device has been paired.

        Uses exponential backoff retry logic for connection errors.
        Uses different endpoints for Hub vs CMS:
        - Hub: /api/v1/pairing/status/{hardware_id}
        - CMS: /api/v1/devices/pairing/status/{hardware_id}

        Returns:
            True if device is paired, False otherwise.
        """
        hardware_id = self._get_hardware_id()

        # Hub uses /api/v1/pairing/status, CMS uses /api/v1/devices/pairing/status
        if self.is_hub:
            endpoint = f"{self.cms_url}/api/v1/pairing/status/{hardware_id}"
        else:
            endpoint = f"{self.cms_url}/api/v1/devices/pairing/status/{hardware_id}"

        def make_request():
            return requests.get(endpoint, timeout=self.timeout)

        try:
            response = retry_with_backoff(make_request, max_retries=self.max_retries)

            if response.status_code == 200:
                data = response.json()
                self.paired = data.get('paired', False)
                return self.paired

            return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to check pairing status: {e}")
            return False

    def wait_for_pairing(self, timeout: int = 300) -> bool:
        """Wait for admin to approve pairing (default 5 minutes).

        Args:
            timeout: Maximum time to wait in seconds.

        Returns:
            True if paired successfully, False if timeout.
        """
        print("\n" + "=" * 50)
        print("DEVICE PAIRING")
        print("=" * 50)
        print(f"\nYour pairing code: {self.pairing_code}")
        print("\nEnter this code in the CMS to pair this device")
        print(f"CMS URL: {self.cms_url}/devices")
        print("\nWaiting for approval...")
        print("=" * 50 + "\n")

        start_time = time.time()

        while time.time() - start_time < timeout:
            if self.check_pairing_status():
                print("\n✅ Device successfully paired!")
                return True

            time.sleep(5)
            remaining = int(timeout - (time.time() - start_time))
            print(f"⏳ Waiting... ({remaining}s remaining)", end='\r')

        print("\n\n❌ Pairing timeout. Please try again.")
        return False

    def get_config(self) -> dict:
        """Get device configuration from CMS.

        Uses exponential backoff retry logic for connection errors.

        Returns:
            Device configuration dict, or empty dict on failure.
        """
        if not self.paired:
            logger.warning("Device not paired. Cannot get config.")
            return {}

        hardware_id = self._get_hardware_id()

        def make_request():
            return requests.get(
                f"{self.cms_url}/api/v1/devices/{hardware_id}/config",
                timeout=self.timeout
            )

        try:
            response = retry_with_backoff(make_request, max_retries=self.max_retries)

            if response.status_code == 200:
                return response.json()
            else:
                return {}

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get config: {e}")
            return {}

    def register_device(self, mode: str = "direct") -> Optional[dict]:
        """Register device with CMS.

        This should be called before requesting pairing if the device
        is not yet registered.

        Args:
            mode: Connection mode, either "direct" or "hub".

        Returns:
            Device data dict if successful, None otherwise.
        """
        hardware_id = self._get_hardware_id()
        name = self.device_info.get('hostname', 'Unknown Device')
        ip_address = self.device_info.get('ip_address')

        def make_request():
            payload = {
                "hardware_id": hardware_id,
                "mode": mode,
                "name": name,
            }
            if ip_address:
                payload["ip_address"] = ip_address
            return requests.post(
                f"{self.cms_url}/api/v1/devices/register",
                json=payload,
                timeout=self.timeout
            )

        try:
            response = retry_with_backoff(make_request, max_retries=self.max_retries)

            if response.status_code in (200, 201):
                data = response.json()
                logger.info(f"Device registered: {data.get('device_id', 'unknown')}")
                return data
            else:
                logger.error(f"Device registration failed: {response.status_code}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to register device: {e}")
            return None

    def get_connection_config(self) -> dict:
        """Get connection configuration from CMS.

        Returns connection mode and URLs for hub/CMS connections.

        Returns:
            Connection config dict, or empty dict on failure.
        """
        hardware_id = self._get_hardware_id()

        def make_request():
            return requests.get(
                f"{self.cms_url}/api/v1/devices/{hardware_id}/connection-config",
                timeout=self.timeout
            )

        try:
            response = retry_with_backoff(make_request, max_retries=self.max_retries)

            if response.status_code == 200:
                return response.json()
            else:
                return {}

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get connection config: {e}")
            return {}


if __name__ == "__main__":
    print("🎬 Jetson Media Player - Device Pairing")
    print(f"Device ID: {get_device_info()['device_id']}\n")

    client = CMSClient()

    # First register the device
    print("Registering device with CMS...")
    device = client.register_device()

    if device:
        print(f"Device registered: {device.get('device_id')}")

        code = client.request_pairing()

        if code:
            if client.wait_for_pairing():
                config = client.get_config()
                print(f"\n📋 Device Config: {config}")
            else:
                print("\n❌ Pairing failed")
        else:
            print("❌ Could not request pairing")
    else:
        print("❌ Could not register device")
