"""
Dashboard route for Local Hub.

Provides a web-based dashboard showing hub status, connected screens,
store layout with screen locations, and network connectivity levels.
"""

import os
import socket
import subprocess
from datetime import datetime, timedelta
from flask import Blueprint, render_template, current_app, redirect, url_for

dashboard_bp = Blueprint("dashboard", __name__)

# Store zone definitions - customize for each store
STORE_ZONES = [
    {"id": "entrance", "name": "Entrance", "position": 0},
    {"id": "checkout1", "name": "Checkout 1", "position": 1},
    {"id": "checkout2", "name": "Checkout 2", "position": 2},
    {"id": "checkout3", "name": "Checkout 3", "position": 3},
    {"id": "aisle1", "name": "Aisle 1", "position": 4},
    {"id": "aisle2", "name": "Aisle 2", "position": 5},
    {"id": "aisle3", "name": "Aisle 3", "position": 6},
    {"id": "endcap1", "name": "Endcap 1", "position": 7},
    {"id": "cooler", "name": "Cooler", "position": 8},
    {"id": "backwall", "name": "Back Wall", "position": 9},
    {"id": "office", "name": "Office", "position": 10},
    {"id": "storage", "name": "Storage", "position": 11},
]


def check_internet():
    """Check if internet is accessible."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False


def check_cms_connection(cms_url):
    """Check if CMS is reachable."""
    try:
        import requests
        response = requests.get(f"{cms_url}/health", timeout=5)
        return response.status_code == 200
    except:
        return False


def ping_device(ip_address):
    """Ping a device and return latency in ms."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip_address],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            # Parse ping output for time
            for line in result.stdout.split("\n"):
                if "time=" in line:
                    time_str = line.split("time=")[1].split()[0]
                    return float(time_str.replace("ms", ""))
        return None
    except:
        return None


def get_connectivity_level(latency):
    """Determine connectivity level based on latency."""
    if latency is None:
        return "offline", 0
    elif latency < 5:
        return "excellent", 100
    elif latency < 20:
        return "good", 75
    elif latency < 50:
        return "fair", 50
    else:
        return "poor", 25


def get_uptime():
    """Get system uptime."""
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
            
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        
        if days > 0:
            return f"{days}d {hours}h"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    except:
        return "Unknown"


@dashboard_bp.route("/")
def dashboard():
    """Render the hub dashboard with pairing codes and locations."""
    from models.hub_config import HubConfig
    from models.device import Device

    # Get hub config
    hub_config = HubConfig.get_instance()

    # If hub is not registered, redirect to pairing screen
    if not hub_config.is_registered:
        return redirect('/pairing')

    config = current_app.config.get("HUB_CONFIG", {})

    # Get CMS URL from config
    cms_url = getattr(config, "cms_url", "http://localhost:5002")
    hub_name = getattr(config, "hub_name", "Skillz Hub") or "Skillz Hub"
    hub_id = hub_config.hub_id if hub_config else None
    hub_ip = getattr(config, "hub_ip", "10.10.10.1")
    hub_port = getattr(config, "port", 5000)
    store_name = hub_config.hub_name if hub_config else ""
    network_name = "On The Wave TV" if hub_config and hub_config.network_id else "Unknown"

    # Check CMS connection
    cms_connected = check_cms_connection(cms_url)

    # Get devices
    devices = []
    pending_count = 0
    online_count = 0
    offline_count = 0

    try:
        all_devices = Device.query.all()
        for device in all_devices:
            # Count by status
            if device.status == 'pending':
                pending_count += 1
            elif device.status in ('online', 'active'):
                online_count += 1
            else:
                offline_count += 1

            devices.append({
                "device_id": device.device_id or f"DEV-{device.id}",
                "hardware_id": device.hardware_id,
                "pairing_code": device.pairing_code,
                "location": getattr(device, 'location', None) or device.name,
                "ip_address": device.ip_address,
                "status": device.status,
            })
    except Exception as e:
        current_app.logger.error(f"Error getting devices: {e}")

    device_count = len(devices)

    return render_template(
        "dashboard.html",
        hub_id=hub_id,
        hub_ip=hub_ip,
        hub_port=hub_port,
        store_name=store_name,
        network_name=network_name,
        cms_connected=cms_connected,
        devices=devices,
        device_count=device_count,
        pending_count=pending_count,
        online_count=online_count,
        offline_count=offline_count,
        current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
