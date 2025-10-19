"""
CMS Client - Device pairing with 6-digit code
"""

import requests
import random
import time
from src.common.device_id import get_device_info
from src.common.logger import setup_logger

logger = setup_logger(__name__)


def generate_pairing_code():
    """Generate a random 6-digit pairing code."""
    return str(random.randint(100000, 999999))


class CMSClient:
    """Client for communicating with the CMS."""
    
    def __init__(self, cms_url: str = "http://localhost:5001"):
        self.cms_url = cms_url
        self.device_info = get_device_info()
        self.paired = False
        self.pairing_code = None
    
    def request_pairing(self) -> str:
        """Request pairing with CMS and get a 6-digit code."""
        self.pairing_code = generate_pairing_code()
        
        try:
            response = requests.post(
                f"{self.cms_url}/api/v1/pairing/request",
                json={
                    "device_id": self.device_info['device_id'],
                    "pairing_code": self.pairing_code,
                    "name": self.device_info['hostname'],
                    "mac_address": self.device_info.get('mac_address', 'unknown')
                },
                timeout=5
            )
            
            if response.status_code == 200:
                logger.info(f"Pairing requested. Code: {self.pairing_code}")
                return self.pairing_code
            else:
                logger.error(f"Pairing request failed: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to request pairing: {e}")
            return None
    
    def check_pairing_status(self) -> bool:
        """Check if device has been paired."""
        try:
            response = requests.get(
                f"{self.cms_url}/api/v1/pairing/status/{self.device_info['device_id']}",
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                self.paired = data.get('paired', False)
                return self.paired
            
            return False
                
        except Exception as e:
            logger.error(f"Failed to check pairing status: {e}")
            return False
    
    def wait_for_pairing(self, timeout: int = 300):
        """Wait for admin to approve pairing (default 5 minutes)."""
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
        """Get device configuration from CMS."""
        if not self.paired:
            logger.warning("Device not paired. Cannot get config.")
            return {}
        
        try:
            response = requests.get(
                f"{self.cms_url}/api/v1/device/{self.device_info['device_id']}/config",
                timeout=5
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {}
                
        except Exception as e:
            logger.error(f"Failed to get config: {e}")
            return {}


if __name__ == "__main__":
    print("🎬 Jetson Media Player - Device Pairing")
    print(f"Device ID: {get_device_info()['device_id']}\n")
    
    client = CMSClient()
    
    code = client.request_pairing()
    
    if code:
        if client.wait_for_pairing():
            config = client.get_config()
            print(f"\n📋 Device Config: {config}")
        else:
            print("\n❌ Pairing failed")
    else:
        print("❌ Could not request pairing")
