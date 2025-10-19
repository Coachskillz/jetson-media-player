"""
Device ID generation and management.
Ensures each Jetson has a unique identifier.
"""

import uuid
import socket
from pathlib import Path


def get_or_create_device_id(config_path: str = "config/device_id.txt") -> str:
    """
    Get existing device ID or create a new one.
    
    Device ID is stored persistently so it survives reboots.
    """
    id_file = Path(config_path)
    
    # Check if ID already exists
    if id_file.exists():
        with open(id_file, 'r') as f:
            device_id = f.read().strip()
            if device_id:
                return device_id
    
    # Generate new unique ID
    device_id = f"jetson-{uuid.uuid4().hex[:12]}"
    
    # Save it
    id_file.parent.mkdir(parents=True, exist_ok=True)
    with open(id_file, 'w') as f:
        f.write(device_id)
    
    return device_id


def get_device_info() -> dict:
    """
    Get device information including ID, hostname, MAC address.
    """
    device_id = get_or_create_device_id()
    hostname = socket.gethostname()
    
    # Try to get MAC address
    try:
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff)
                       for elements in range(0, 2*6, 2)][::-1])
    except:
        mac = "unknown"
    
    return {
        "device_id": device_id,
        "hostname": hostname,
        "mac_address": mac
    }
