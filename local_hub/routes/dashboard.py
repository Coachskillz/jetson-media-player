"""
Dashboard route for Local Hub.

Provides a web-based dashboard showing hub status, connected screens,
store layout with screen locations, and network connectivity levels.
"""

import os
import socket
import subprocess
from datetime import datetime, timedelta
from flask import Blueprint, render_template, current_app

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
    """Render the hub dashboard with store layout and connectivity."""
    from models.hub_config import HubConfig
    from models.device import Device
    from models.content import Content
    from models.sync_status import SyncStatus
    
    # Get hub config
    hub_config = HubConfig.get_instance()
    config = current_app.config.get("HUB_CONFIG", {})
    
    # Get CMS URL from config
    cms_url = getattr(config, "cms_url", "http://localhost:5002")
    hub_name = getattr(config, "hub_name", "Skillz Hub") or "Skillz Hub"
    hub_id = getattr(config, "hub_id", "HUB-001") or hub_config.hub_id or "HUB-001"
    hub_ip = "10.10.10.1"
    hub_port = getattr(config, "port", 5000)
    store_name = getattr(config, "store_name", "") or ""
    store_number = getattr(config, "store_number", "") or ""
    
    # Check statuses
    hub_status = True
    cms_connected = check_cms_connection(cms_url)
    internet_connected = check_internet()
    
    # Get devices and build screen list with connectivity
    screens = []
    screens_online = 0
    screens_offline = 0
    total_latency = 0
    latency_count = 0
    
    try:
        devices = Device.query.all()
        for device in devices:
            ip = device.ip_address or "Unknown"
            
            # Ping device to check connectivity
            latency = ping_device(ip) if ip != "Unknown" else None
            connectivity, signal_strength = get_connectivity_level(latency)
            
            # Determine status
            if latency is not None:
                status = "online"
                screens_online += 1
                total_latency += latency
                latency_count += 1
            else:
                status = "offline"
                screens_offline += 1
            
            # Get location from device name or use default
            location = device.name or "Unassigned"
            zone_id = getattr(device, "zone_id", None) or "unassigned"
            
            # Create short ID from device ID
            device_id = device.device_id or device.hardware_id or f"DEV-{device.id}"
            short_id = device_id[-4:] if len(device_id) > 4 else device_id
            
            screens.append({
                "id": device_id,
                "short_id": short_id,
                "name": device.name,
                "ip": ip,
                "location": location,
                "zone_id": zone_id,
                "status": status,
                "connectivity": connectivity,
                "signal_strength": signal_strength,
                "latency": int(latency) if latency else "-",
                "current_content": getattr(device, "current_content", None),
                "last_seen": device.last_heartbeat.strftime("%H:%M:%S") if device.last_heartbeat else None
            })
    except Exception as e:
        current_app.logger.error(f"Error getting devices: {e}")
    
    # Calculate average latency
    avg_latency = int(total_latency / latency_count) if latency_count > 0 else 0
    
    # Build store zones with assigned screens
    store_zones = []
    for zone in STORE_ZONES:
        zone_data = {
            "name": zone["name"],
            "id": zone["id"],
            "screen": None
        }
        
        # Find screen assigned to this zone
        for screen in screens:
            if screen.get("zone_id") == zone["id"] or screen.get("location", "").lower() == zone["name"].lower():
                zone_data["screen"] = screen
                break
        
        store_zones.append(zone_data)
    
    # Get content count
    content_count = 0
    try:
        content_count = Content.query.filter_by(is_cached=True).count()
    except:
        pass
    
    # Get last sync time
    last_sync = None
    try:
        sync_status = SyncStatus.get_content_status()
        if sync_status and sync_status.last_sync_at:
            last_sync = sync_status.last_sync_at.strftime("%Y-%m-%d %H:%M")
    except:
        pass
    
    return render_template(
        "dashboard.html",
        hub_name=hub_name,
        hub_id=hub_id,
        hub_ip=hub_ip,
        hub_port=hub_port,
        hub_status=hub_status,
        cms_connected=cms_connected,
        internet_connected=internet_connected,
        screens=screens,
        screens_online=screens_online,
        screens_offline=screens_offline,
        store_zones=store_zones,
        content_count=content_count,
        last_sync=last_sync,
        avg_latency=avg_latency,
        uptime=get_uptime(),
        store_name=store_name,
        store_number=store_number,
        current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
